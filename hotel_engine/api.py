import frappe
from datetime import datetime, timezone
import time


def success(data, http_status_code=200):
    frappe.response["http_status_code"] = http_status_code
    return {"data": data}


def error(message, code, http_status_code=400):
    frappe.response["http_status_code"] = http_status_code
    return {"error": message, "code": code}


def validate_dates(check_in, check_out):
    today = datetime.now(timezone.utc).date()
    ci = datetime.strptime(check_in, "%Y-%m-%d").date()
    co = datetime.strptime(check_out, "%Y-%m-%d").date()
    if co <= ci:
        return False, "check_out must be after check_in"
    if ci < today:
        return False, "check_in cannot be in the past"
    return True, None


def get_confirmed_bookings_count(room_type_id, check_in, check_out):
    rate_plans = frappe.db.get_all("Rate Plan",
        filters={"room_type": room_type_id},
        pluck="name"
    )
    if not rate_plans:
        return 0
    plan_list = ", ".join(["%s"] * len(rate_plans))
    result = frappe.db.sql(f"""
        SELECT COUNT(*) as cnt
        FROM `tabHotel Booking`
        WHERE status = 'confirmed'
        AND rate_plan IN ({plan_list})
        AND check_in < %s
        AND check_out > %s
    """, rate_plans + [check_out, check_in], as_dict=True)
    return result[0].cnt if result else 0


@frappe.whitelist(allow_guest=True)
def get_availability(hotel, check_in, check_out):
    valid, msg = validate_dates(check_in, check_out)
    if not valid:
        return error(msg, "INVALID_DATES", 400)

    nights = (datetime.strptime(check_out, "%Y-%m-%d") - datetime.strptime(check_in, "%Y-%m-%d")).days

    room_types = frappe.get_all("Room Type",
        filters={"hotel": hotel},
        fields=["name", "room_name", "total_inventory"]
    )

    result = []
    for rt in room_types:
        booked = get_confirmed_bookings_count(rt["name"], check_in, check_out)
        remaining = rt["total_inventory"] - booked

        if remaining <= 0:
            continue

        rate_plans = frappe.get_all("Rate Plan",
            filters={"room_type": rt["name"]},
            fields=["name", "plan_name", "price_per_night", "is_refundable", "cancellation_deadline_hours"]
        )

        result.append({
            "room_type": rt["room_name"],
            "remaining_rooms": remaining,
            "rate_plans": [
                {
                    "name": rp["name"],
                    "plan_name": rp["plan_name"],
                    "price_per_night": rp["price_per_night"],
                    "total_price": rp["price_per_night"] * nights,
                    "is_refundable": bool(rp["is_refundable"]),
                    "cancellation_deadline_hours": rp["cancellation_deadline_hours"]
                }
                for rp in rate_plans
            ]
        })

    return success(result)


@frappe.whitelist(allow_guest=True)
def create_booking(rate_plan, guest_name, check_in, check_out):
    valid, msg = validate_dates(check_in, check_out)
    if not valid:
        return error(msg, "INVALID_DATES", 400)

    nights = (datetime.strptime(check_out, "%Y-%m-%d") - datetime.strptime(check_in, "%Y-%m-%d")).days

    try:
        rp = frappe.get_doc("Rate Plan", rate_plan)
    except frappe.DoesNotExistError:
        return error("Rate plan not found", "NOT_FOUND", 404)

    # Lock key per room type — only one booking at a time per room type
    lock_key = f"hotel:booking:lock:{rp.room_type}"
    cache = frappe.cache()

    # Spin-wait to acquire lock — max 10 retries x 0.3s = 3s
    acquired = False
    for _ in range(10):
        acquired = bool(cache.set(lock_key, "1", nx=True, ex=30))
        if acquired:
            break
        time.sleep(0.3)

    if not acquired:
        return error("No rooms available for the selected dates", "NO_AVAILABILITY", 409)

    try:
        # AFTER lock — recount from DB with fresh read
        frappe.db.commit()  # flush any pending state
        booked = get_confirmed_bookings_count(rp.room_type, check_in, check_out)
        total_inventory = frappe.db.get_value(
            "Room Type", rp.room_type, "total_inventory",
            cache=False  # force fresh DB read
        )
        remaining = total_inventory - booked

        if remaining <= 0:
            return error("No rooms available for the selected dates", "NO_AVAILABILITY", 409)

        booking = frappe.new_doc("Hotel Booking")
        booking.rate_plan = rate_plan
        booking.guest_name = guest_name
        booking.check_in = check_in
        booking.check_out = check_out
        booking.total_price = rp.price_per_night * nights
        booking.status = "confirmed"
        booking.insert(ignore_permissions=True)
        frappe.db.commit()  # commit BEFORE releasing lock

        return success({
            "booking_id": booking.name,
            "status": booking.status,
            "total_price": booking.total_price
        }, 201)

    finally:
        cache.delete(lock_key)


@frappe.whitelist(allow_guest=True)
def cancel_booking(booking_id):
    booking = frappe.db.get_value(
        "Hotel Booking", booking_id,
        ["name", "status", "rate_plan", "check_in"],
        as_dict=True
    )

    if not booking:
        return error("Booking not found", "BOOKING_NOT_FOUND", 404)

    if booking.status in ("cancelled_refunded", "cancelled_no_refund"):
        return error("Booking is already cancelled", "ALREADY_CANCELLED", 409)

    rp = frappe.get_doc("Rate Plan", booking.rate_plan)

    if not rp.is_refundable:
        new_status = "cancelled_no_refund"
    else:
        now = datetime.now(timezone.utc)
        check_in_dt = datetime.strptime(str(booking.check_in), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        hours_until = (check_in_dt - now).total_seconds() / 3600

        if hours_until < rp.cancellation_deadline_hours:
            new_status = "cancelled_no_refund"
        else:
            new_status = "cancelled_refunded"

    frappe.db.set_value("Hotel Booking", booking_id, "status", new_status)
    frappe.db.commit()

    return success({"booking_id": booking_id, "status": new_status})


@frappe.whitelist(allow_guest=True)
def get_booking(booking_id):
    booking = frappe.db.get_value(
        "Hotel Booking", booking_id,
        ["name", "guest_name", "check_in", "check_out", "total_price", "status", "rate_plan"],
        as_dict=True
    )

    if not booking:
        return error("Booking not found", "BOOKING_NOT_FOUND", 404)

    rp = frappe.db.get_value(
        "Rate Plan", booking.rate_plan,
        ["plan_name", "price_per_night", "is_refundable", "cancellation_deadline_hours"],
        as_dict=True
    )

    return success({
        "booking_id": booking.name,
        "guest_name": booking.guest_name,
        "check_in": str(booking.check_in),
        "check_out": str(booking.check_out),
        "total_price": booking.total_price,
        "status": booking.status,
        "rate_plan": {
            "name": booking.rate_plan,
            "plan_name": rp.plan_name,
            "price_per_night": rp.price_per_night,
            "is_refundable": bool(rp.is_refundable),
            "cancellation_deadline_hours": rp.cancellation_deadline_hours
        }
    })
