import frappe
from frappe.tests.utils import FrappeTestCase
from datetime import datetime, timedelta, timezone
from hotel_engine.api import (
    get_availability,
    create_booking,
    cancel_booking,
    get_booking
)


def make_hotel(name="Test Hotel"):
    if not frappe.db.exists("Hotel", name):
        doc = frappe.new_doc("Hotel")
        doc.name = name
        doc.city = "Cairo"
        doc.timezone = "Asia/Cairo"
        doc.insert(ignore_permissions=True)
    return name


def make_room_type(hotel, room_name="Test Room", inventory=2):
    existing = frappe.db.get_value("Room Type", {"room_name": room_name, "hotel": hotel}, "name")
    if existing:
        return existing
    doc = frappe.new_doc("Room Type")
    doc.hotel = hotel
    doc.room_name = room_name
    doc.total_inventory = inventory
    doc.insert(ignore_permissions=True)
    return doc.name


def make_rate_plan(room_type, plan_name="Test Plan", price=100, refundable=1, deadline=48):
    existing = frappe.db.get_value("Rate Plan", {"plan_name": plan_name, "room_type": room_type}, "name")
    if existing:
        return existing
    doc = frappe.new_doc("Rate Plan")
    doc.room_type = room_type
    doc.plan_name = plan_name
    doc.price_per_night = price
    doc.is_refundable = refundable
    doc.cancellation_deadline_hours = deadline
    doc.insert(ignore_permissions=True)
    return doc.name


def future_dates(days_from_now=30, nights=3):
    check_in = (datetime.now(timezone.utc) + timedelta(days=days_from_now)).strftime("%Y-%m-%d")
    check_out = (datetime.now(timezone.utc) + timedelta(days=days_from_now + nights)).strftime("%Y-%m-%d")
    return check_in, check_out


def cleanup_bookings():
    bookings = frappe.get_all("Hotel Booking", pluck="name")
    for b in bookings:
        frappe.delete_doc("Hotel Booking", b, ignore_permissions=True, force=True)
    frappe.db.commit()


class TestBookingEngine(FrappeTestCase):

    def setUp(self):
        cleanup_bookings()
        self.hotel = make_hotel("Test Hotel")
        self.room_type = make_room_type(self.hotel, "Deluxe Test Room", inventory=2)
        self.rate_plan = make_rate_plan(self.room_type, "Flexible Test", price=200, refundable=1, deadline=48)
        self.non_refundable_plan = make_rate_plan(self.room_type, "Non-refundable Test", price=150, refundable=0, deadline=0)
        frappe.db.commit()

    # Test 1 - Successful booking
    def test_successful_booking(self):
        check_in, check_out = future_dates(30, 3)
        result = create_booking(self.rate_plan, "Test Guest", check_in, check_out)
        self.assertIn("data", result)
        self.assertEqual(result["data"]["status"], "confirmed")
        self.assertEqual(result["data"]["total_price"], 600.0)

    # Test 2 - Overbooking rejection
    def test_overbooking_rejection(self):
        check_in, check_out = future_dates(30, 3)
        # Fill all 2 rooms
        create_booking(self.rate_plan, "Guest One", check_in, check_out)
        create_booking(self.rate_plan, "Guest Two", check_in, check_out)
        # Third booking must fail
        result = create_booking(self.rate_plan, "Guest Three", check_in, check_out)
        self.assertIn("error", result)
        self.assertEqual(result["code"], "NO_AVAILABILITY")

    # Test 3 - Availability accuracy
    def test_availability_excludes_fully_booked(self):
        check_in, check_out = future_dates(30, 3)
        # Fill all rooms
        create_booking(self.rate_plan, "Guest One", check_in, check_out)
        create_booking(self.rate_plan, "Guest Two", check_in, check_out)
        frappe.db.commit()
        # Check availability
        result = get_availability(self.hotel, check_in, check_out)
        self.assertIn("data", result)
        room_names = [r["room_type"] for r in result["data"]]
        self.assertNotIn("Deluxe Test Room", room_names)

    # Test 4 - Cancellation past deadline
    def test_cancellation_past_deadline(self):
        # Book with only 24 hours until check-in but deadline is 48 hours
        check_in = (datetime.now(timezone.utc) + timedelta(hours=24)).strftime("%Y-%m-%d")
        check_out = (datetime.now(timezone.utc) + timedelta(hours=48)).strftime("%Y-%m-%d")
        result = create_booking(self.rate_plan, "Test Guest", check_in, check_out)
        if "data" not in result:
            self.skipTest("Could not create booking with near dates")
        booking_id = result["data"]["booking_id"]
        cancel_result = cancel_booking(booking_id)
        self.assertEqual(cancel_result["data"]["status"], "cancelled_no_refund")

    # Test 5 - Cancellation within window
    def test_cancellation_within_window(self):
        check_in, check_out = future_dates(60, 3)
        result = create_booking(self.rate_plan, "Test Guest", check_in, check_out)
        booking_id = result["data"]["booking_id"]
        cancel_result = cancel_booking(booking_id)
        self.assertEqual(cancel_result["data"]["status"], "cancelled_refunded")

    # Test 6 - Non-refundable cancellation
    def test_non_refundable_cancellation(self):
        check_in, check_out = future_dates(60, 3)
        result = create_booking(self.non_refundable_plan, "Test Guest", check_in, check_out)
        booking_id = result["data"]["booking_id"]
        cancel_result = cancel_booking(booking_id)
        self.assertEqual(cancel_result["data"]["status"], "cancelled_no_refund")

    # Test 7 - Already cancelled
    def test_already_cancelled(self):
        check_in, check_out = future_dates(60, 3)
        result = create_booking(self.rate_plan, "Test Guest", check_in, check_out)
        booking_id = result["data"]["booking_id"]
        cancel_booking(booking_id)
        result2 = cancel_booking(booking_id)
        self.assertIn("error", result2)
        self.assertEqual(result2["code"], "ALREADY_CANCELLED")

    # Test 8 - Invalid dates
    def test_invalid_dates(self):
        result = create_booking(self.rate_plan, "Test Guest", "2026-07-10", "2026-07-05")
        self.assertIn("error", result)
        self.assertEqual(result["code"], "INVALID_DATES")

