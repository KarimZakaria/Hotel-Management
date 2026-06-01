import frappe

def setup_demo_data():
    # Hotels
    hotels = [
        {"name": "Grand Cairo Hotel", "city": "Cairo", "timezone": "Asia/Cairo"},
        {"name": "Riyadh Palace Hotel", "city": "Riyadh", "timezone": "Asia/Riyadh"},
    ]

    for h in hotels:
        if not frappe.db.exists("Hotel", h["name"]):
            doc = frappe.new_doc("Hotel")
            doc.update(h)
            doc.insert(ignore_permissions=True)

    # Room Types
    room_types = [
        {"hotel": "Grand Cairo Hotel", "room_name": "Deluxe King", "total_inventory": 5},
        {"hotel": "Grand Cairo Hotel", "room_name": "Standard Twin", "total_inventory": 3},
        {"hotel": "Grand Cairo Hotel", "room_name": "Suite", "total_inventory": 2},
        {"hotel": "Riyadh Palace Hotel", "room_name": "Executive King", "total_inventory": 4},
        {"hotel": "Riyadh Palace Hotel", "room_name": "Standard Single", "total_inventory": 6},
        {"hotel": "Riyadh Palace Hotel", "room_name": "Presidential Suite", "total_inventory": 1},
    ]

    for rt in room_types:
        if not frappe.db.exists("Room Type", {"room_name": rt["room_name"], "hotel": rt["hotel"]}):
            doc = frappe.new_doc("Room Type")
            doc.update(rt)
            doc.insert(ignore_permissions=True)

    # Rate Plans
    rate_plans = [
        {"room_type": "Deluxe King", "plan_name": "Flexible", "price_per_night": 250, "is_refundable": 1, "cancellation_deadline_hours": 48},
        {"room_type": "Deluxe King", "plan_name": "Non-refundable", "price_per_night": 180, "is_refundable": 0, "cancellation_deadline_hours": 0},
        {"room_type": "Standard Twin", "plan_name": "Flexible", "price_per_night": 150, "is_refundable": 1, "cancellation_deadline_hours": 24},
        {"room_type": "Standard Twin", "plan_name": "Breakfast Included", "price_per_night": 180, "is_refundable": 1, "cancellation_deadline_hours": 48},
        {"room_type": "Suite", "plan_name": "Flexible", "price_per_night": 500, "is_refundable": 1, "cancellation_deadline_hours": 72},
        {"room_type": "Suite", "plan_name": "Non-refundable", "price_per_night": 400, "is_refundable": 0, "cancellation_deadline_hours": 0},
        {"room_type": "Executive King", "plan_name": "Flexible", "price_per_night": 300, "is_refundable": 1, "cancellation_deadline_hours": 48},
        {"room_type": "Executive King", "plan_name": "Non-refundable", "price_per_night": 220, "is_refundable": 0, "cancellation_deadline_hours": 0},
        {"room_type": "Standard Single", "plan_name": "Flexible", "price_per_night": 120, "is_refundable": 1, "cancellation_deadline_hours": 24},
        {"room_type": "Presidential Suite", "plan_name": "Flexible", "price_per_night": 1000, "is_refundable": 1, "cancellation_deadline_hours": 96},
        {"room_type": "Presidential Suite", "plan_name": "Non-refundable", "price_per_night": 800, "is_refundable": 0, "cancellation_deadline_hours": 0},
    ]

    for rp in rate_plans:
        rt_name = frappe.db.get_value("Room Type", {"room_name": rp["room_type"]}, "name")
        if rt_name and not frappe.db.exists("Rate Plan", {"plan_name": rp["plan_name"], "room_type": rt_name}):
            doc = frappe.new_doc("Rate Plan")
            doc.room_type = rt_name
            doc.plan_name = rp["plan_name"]
            doc.price_per_night = rp["price_per_night"]
            doc.is_refundable = rp["is_refundable"]
            doc.cancellation_deadline_hours = rp["cancellation_deadline_hours"]
            doc.insert(ignore_permissions=True)

    frappe.db.commit()
    print("Demo data created successfully!")
