# Hotel Engine

> A hotel booking engine built on the [Frappe Framework](https://frappeframework.com). Supports room availability checking, booking creation with concurrency safety, and cancellation with refund policy enforcement.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Seed Demo Data](#seed-demo-data)
- [Running Tests](#running-tests)
- [Concurrency Test](#concurrency-test)
- [API Reference](#api-reference)
- [Error Codes](#error-codes)
- [Design Decisions](#design-decisions)

---

## Quick Start

### 1. Initialize bench and install app

```bash
bench init hotel-engine-bench --frappe-branch version-15
cd hotel-engine-bench
bench new-site hotel.local
bench --site hotel.local set-config developer_mode 1
bench get-app hotel_engine https://github.com/YOURUSERNAME/hotel_engine.git
bench --site hotel.local install-app hotel_engine
bench --site hotel.local add-to-hosts
bench start
```

---

## Seed Demo Data

```bash
bench --site hotel.local console
```

```python
from hotel_engine.setup_demo_data import setup_demo_data
setup_demo_data()
```

This creates:

- **2 hotels** — Grand Cairo Hotel, Riyadh Palace Hotel
- **3 room types** per hotel with varying inventory
- **2–3 rate plans** per room type (mix of refundable and non-refundable)

> Running it multiple times is safe — it is fully idempotent.

---

## Running Tests

```bash
bench --site hotel.local set-config allow_tests true
bench --site hotel.local run-tests --app hotel_engine
```

**Expected output:**

```
........
----------------------------------------------------------------------
Ran 8 tests in 1.5s
OK
```

### Test Coverage

| Test | Description |
|------|-------------|
| `test_successful_booking` | Creates a booking and verifies confirmed status and correct total price |
| `test_overbooking_rejection` | Fills all rooms then attempts a third — expects `NO_AVAILABILITY` |
| `test_availability_excludes_fully_booked` | Fully booked room type must not appear in availability response |
| `test_cancellation_past_deadline` | Cancels within 24h of check-in with 48h deadline — expects `cancelled_no_refund` |
| `test_cancellation_within_window` | Cancels 60 days before check-in — expects `cancelled_refunded` |
| `test_non_refundable_cancellation` | Non-refundable plan always returns `cancelled_no_refund` regardless of timing |
| `test_already_cancelled` | Cancelling an already cancelled booking returns `ALREADY_CANCELLED` |
| `test_invalid_dates` | `check_out` before `check_in` returns `INVALID_DATES` |

---

## Concurrency Test

To verify overbooking prevention under concurrent load:

```python
# test_concurrency.py
import requests
import threading

URL = "http://hotel.local:8000/api/method/hotel_engine.api.create_booking"
PAYLOAD = {
    "rate_plan": "1",
    "guest_name": "Concurrent Guest",
    "check_in": "2026-11-01",
    "check_out": "2026-11-03"
}

results = []
lock = threading.Lock()

def make_booking():
    r = requests.post(URL, json=PAYLOAD)
    data = r.json()
    with lock:
        results.append(data.get("message", data))

threads = [threading.Thread(target=make_booking) for _ in range(5)]
for t in threads:
    t.start()
for t in threads:
    t.join()

confirmed = [r for r in results if "data" in r]
failed = [r for r in results if "error" in r]
print(f"Confirmed: {len(confirmed)} (should be 1)")
print(f"Rejected: {len(failed)} (should be 4)")
```

**Result with 1-room inventory:**

```
Confirmed: 1 (should be 1)
Rejected: 4 (should be 4)
```

---

## API Reference

**Base URL:** `http://hotel.local:8000`

All responses follow a consistent envelope:

```json
{ "data": { ... } }
```

Errors follow:

```json
{ "error": "Human-readable message", "code": "MACHINE_READABLE_CODE" }
```

---

### 1. Get Availability

```
GET /api/method/hotel_engine.api.get_availability
    ?hotel=Grand Cairo Hotel
    &check_in=2026-07-01
    &check_out=2026-07-04
```

**Response:**

```json
{
  "data": [
    {
      "room_type": "Deluxe King",
      "remaining_rooms": 5,
      "rate_plans": [
        {
          "name": "1",
          "plan_name": "Flexible",
          "price_per_night": 250.0,
          "total_price": 750.0,
          "is_refundable": true,
          "cancellation_deadline_hours": 48
        }
      ]
    }
  ]
}
```

---

### 2. Create Booking

```
POST /api/method/hotel_engine.api.create_booking
Content-Type: application/json
```

**Request:**

```json
{
  "rate_plan": "1",
  "guest_name": "Sara Ahmed",
  "check_in": "2026-07-01",
  "check_out": "2026-07-04"
}
```

**Response (HTTP 201):**

```json
{
  "data": {
    "booking_id": "HTL-BOOK-00001",
    "status": "confirmed",
    "total_price": 750.0
  }
}
```

---

### 3. Cancel Booking

```
DELETE /api/method/hotel_engine.api.cancel_booking
Content-Type: application/json
```

**Request:**

```json
{ "booking_id": "HTL-BOOK-00001" }
```

**Response:**

```json
{
  "data": {
    "booking_id": "HTL-BOOK-00001",
    "status": "cancelled_refunded"
  }
}
```

---

### 4. Get Booking

```
GET /api/method/hotel_engine.api.get_booking?booking_id=HTL-BOOK-00001
```

**Response:**

```json
{
  "data": {
    "booking_id": "HTL-BOOK-00001",
    "guest_name": "Sara Ahmed",
    "check_in": "2026-07-01",
    "check_out": "2026-07-04",
    "total_price": 750.0,
    "status": "confirmed",
    "rate_plan": {
      "name": "1",
      "plan_name": "Flexible",
      "price_per_night": 250.0,
      "is_refundable": true,
      "cancellation_deadline_hours": 48
    }
  }
}
```

---

## Error Codes

| Code | HTTP | Meaning |
|------|------|---------|
| `NO_AVAILABILITY` | 409 | No rooms left for the requested date range |
| `BOOKING_NOT_FOUND` | 404 | Booking ID does not exist |
| `ALREADY_CANCELLED` | 409 | Booking is already cancelled |
| `INVALID_DATES` | 400 | `check_out` is before or equal to `check_in`, or dates are in the past |

---

## Design Decisions

### Concurrency — Redis Distributed Lock

The core challenge is preventing two simultaneous requests from both claiming the last available room.

`SELECT ... FOR UPDATE` does not work in Frappe because Frappe operates in auto-commit mode by default — each query runs in its own transaction, so the lock is released immediately and does not protect the check-then-insert window.

Instead, `create_booking` uses a Redis distributed lock via `frappe.cache()`:

```python
lock_key = f"hotel:booking:lock:{room_type_id}"
acquired = cache.set(lock_key, "1", nx=True, ex=30)
```

- `nx=True` means the key is only set if it does not already exist — this is atomic at the Redis level.
- Only one request acquires the lock at a time. All others spin-wait up to 3 seconds then return `NO_AVAILABILITY`.
- The lock is always released in a `finally` block so it cannot be held indefinitely.
- The availability count is re-read from the database **after** the lock is acquired to ensure no booking slipped through between the check and the insert.

### `total_price` as a Snapshot

`total_price` is computed once at booking time (`nights × price_per_night`) and stored on the Hotel Booking document. It is never recalculated on read. This means a rate plan price change after booking does not affect existing bookings — which is the correct behavior for any real booking system.

### Cancellation Logic

Refund status is determined by three rules applied in order:

1. If the rate plan is **non-refundable** → `cancelled_no_refund` always.
2. If **now** is within `cancellation_deadline_hours` of check-in → `cancelled_no_refund`.
3. Otherwise → `cancelled_refunded`.

### Seed Data is Idempotent

`setup_demo_data()` checks for existence before inserting every record. Running it multiple times produces the same state with no duplicates.