#
#
#
# from flask import Flask, request, jsonify
# from flask_pymongo import PyMongo
# from datetime import datetime, date
# from bson import ObjectId
# from flask_cors import CORS
#
# app = Flask(__name__)
# CORS(app)  # Allow requests from Flutter app
#
# # MongoDB configuration
# app.config["MONGO_URI"] = "mongodb://localhost:27017/attendance_db"
# mongo = PyMongo(app)
# attendance_collection = mongo.db.attendance
#
#
# # Helper to convert ObjectId to string
# def to_json(data):
#     if isinstance(data, list):
#         for d in data:
#             d["_id"] = str(d["_id"])
#     else:
#         data["_id"] = str(data["_id"])
#     return data
#
#
# @app.route("/attendance", methods=["POST"])
# def mark_attendance():
#     data = request.json
#     employee_id = data.get("employee_id")
#     latitude = data.get("latitude")
#     longitude = data.get("longitude")
#
#     if not employee_id or latitude is None or longitude is None:
#         return jsonify({"error": "Missing required fields"}), 400
#
#     today = date.today().isoformat()
#     now_time = datetime.utcnow().strftime("%H:%M:%S")
#
#     # Check if record exists for this employee today
#     record = attendance_collection.find_one({"employee_id": employee_id, "date": today})
#
#     if not record:
#         # First hit of the day -> set in_time
#         new_record = {
#             "employee_id": employee_id,
#             "date": today,
#             "in_time": now_time,
#             "out_time": None,
#             "latitude": latitude,
#             "longitude": longitude,
#             "created_at": datetime.utcnow()
#         }
#         attendance_collection.insert_one(new_record)
#         return jsonify({"message": "In-time recorded", "data": to_json(new_record)}), 201
#     else:
#         # Already exists -> update out_time with latest
#         attendance_collection.update_one(
#             {"_id": record["_id"]},
#             {"$set": {
#                 "out_time": now_time,
#                 "latitude": latitude,
#                 "longitude": longitude
#             }}
#         )
#         record = attendance_collection.find_one({"_id": record["_id"]})
#         return jsonify({"message": "Out-time updated", "data": to_json(record)}), 200
#
#
# @app.route("/attendance", methods=["GET"])
# def get_attendance():
#     employee_id = request.args.get("employee_id")
#     start_date = request.args.get("start_date")
#     end_date = request.args.get("end_date")
#
#     query = {}
#     if employee_id:
#         query["employee_id"] = employee_id
#     if start_date and end_date:
#         query["date"] = {"$gte": start_date, "$lte": end_date}
#     elif start_date:
#         query["date"] = {"$gte": start_date}
#     elif end_date:
#         query["date"] = {"$lte": end_date}
#
#     records = list(attendance_collection.find(query))
#     return jsonify(to_json(records)), 200
#
#
# @app.route("/health", methods=["GET"])
# def health():
#     return jsonify({"status": "OK"}), 200
#
#
# if __name__ == "__main__":
#     app.run(host="0.0.0.0", port=8080, debug=True)
#


from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from datetime import datetime, date
from bson import ObjectId
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow requests from Flutter app

# MongoDB configuration
app.config["MONGO_URI"] = "mongodb://localhost:27017/attendance_db"
mongo = PyMongo(app)
attendance_collection = mongo.db.attendance


# Helper to convert ObjectId to string
def to_json(data):
    if isinstance(data, list):
        for d in data:
            d["_id"] = str(d["_id"])
    else:
        data["_id"] = str(data["_id"])
    return data


@app.route("/attendance", methods=["POST"])
def mark_attendance():
    data = request.json
    employee_id = data.get("employee_id")
    latitude = data.get("latitude")
    longitude = data.get("longitude")

    if not employee_id or latitude is None or longitude is None:
        return jsonify({"error": "Missing required fields"}), 400

    today = date.today().isoformat()
    now_time = datetime.utcnow().strftime("%H:%M:%S")

    # Check if record exists for this employee today
    record = attendance_collection.find_one({"employee_id": employee_id, "date": today})

    if not record:
        # First hit of the day -> set in_time
        new_record = {
            "employee_id": employee_id,
            "date": today,
            "in_time": now_time,
            "out_times": [],  # keep list of out times
            "out_time": None,  # latest out time of the day
            "latitude": latitude,
            "longitude": longitude,
            "created_at": datetime.utcnow()
        }
        attendance_collection.insert_one(new_record)
        return jsonify({"message": "In-time recorded", "data": to_json(new_record)}), 201
    else:
        # Add to out_times list and update latest out_time
        attendance_collection.update_one(
            {"_id": record["_id"]},
            {
                "$push": {"out_times": now_time},
                "$set": {
                    "out_time": now_time,  # latest out-time always updated
                    "latitude": latitude,
                    "longitude": longitude
                }
            }
        )
        record = attendance_collection.find_one({"_id": record["_id"]})
        return jsonify({"message": "Out-time added", "data": to_json(record)}), 200


@app.route("/attendance", methods=["GET"])
def get_attendance():
    employee_id = request.args.get("employee_id")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    query = {}
    if employee_id:
        query["employee_id"] = employee_id
    if start_date and end_date:
        query["date"] = {"$gte": start_date, "$lte": end_date}
    elif start_date:
        query["date"] = {"$gte": start_date}
    elif end_date:
        query["date"] = {"$lte": end_date}

    records = list(attendance_collection.find(query))
    return jsonify(to_json(records)), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "OK"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
