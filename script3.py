
import os
from datetime import datetime, timezone
from pymongo import MongoClient
from bson.objectid import ObjectId
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, session, g

# Load .env if present
load_dotenv()

# Configuration via env vars
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "video_app_db")
UPLOAD_FOLDER = os.path.abspath(os.getenv("UPLOAD_FOLDER", "./uploads"))  # absolute path
ALLOWED_EXTENSIONS = set(["mp4", "mov", "mkv", "webm", "ogg"])

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Flask app
app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
CORS(app)

app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024 * 1024  # 10 GB পর্যন্ত


# Mongo client
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
videos_col = db.videos

# Helpers
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def get_client_ip():
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        ip = xff.split(",")[0].strip()
        if ip:
            return ip
    return request.remote_addr or "unknown"

# ────────────── Serve uploaded files ──────────────
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# ────────────── Admin Edit Video ──────────────

@app.route("/admin/video/<video_id>", methods=["PATCH"])
def edit_video(video_id):
    """
    আপডেট করা যাবে:
      - title (text)
      - video_link (text)
      - subtitle (text)
      - image (file)
      - file (video file)
    সবগুলো ফিল্ড optional; যেটা দিবে সেটাই আপডেট হবে।
    """
    try:
        oid = ObjectId(video_id)
    except Exception:
        return jsonify({"error": "invalid video id"}), 400

    v = videos_col.find_one({"_id": oid})
    if not v:
        return jsonify({"error": "video not found"}), 404

    # -------- ইনপুট ফিল্ডগুলো নাও --------
    new_title = (request.form.get("title") or "").strip() if request.form else None
    new_video_link = (request.form.get("video_link") or "").strip() if request.form else None
    new_subtitle_text = (request.form.get("subtitle") or "").strip() if request.form else None

    update_fields = {}

    # -------- টেক্সট ফিল্ড আপডেট --------
    if new_title:
        update_fields["title"] = new_title
    if new_video_link is not None and new_video_link != "":
        update_fields["video_link"] = new_video_link
    if new_subtitle_text is not None:
        update_fields["subtitle_text"] = new_subtitle_text

    # -------- ইমেজ ফাইল আপডেট --------
    if "image" in request.files and request.files["image"].filename:
        img = request.files["image"]
        safe_img = secure_filename(img.filename)
        img_name = f"img_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{safe_img}"
        img_path = os.path.join(app.config["UPLOAD_FOLDER"], img_name)
        img.save(img_path)

        # পুরনো ইমেজ থাকলে মুছে দাও
        if v.get("image_filename"):
            old_img_path = os.path.join(app.config["UPLOAD_FOLDER"], v.get("image_filename"))
            try:
                os.remove(old_img_path)
            except FileNotFoundError:
                pass

        update_fields["image_filename"] = img_name

    # -------- ভিডিও ফাইল আপডেট --------
    if "file" in request.files and request.files["file"].filename:
        f = request.files["file"]
        if not allowed_file(f.filename):
            return jsonify({"error": f"filetype not allowed. allowed: {ALLOWED_EXTENSIONS}"}), 400

        # পুরনো ভিডিও থাকলে মুছে দাও
        if v.get("filename"):
            old_video_path = os.path.join(app.config["UPLOAD_FOLDER"], v.get("filename"))
            try:
                os.remove(old_video_path)
            except FileNotFoundError:
                pass

        safe_name = secure_filename(f.filename)
        unique_prefix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        saved_name = f"{unique_prefix}_{safe_name}"
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], saved_name)
        f.save(save_path)

        update_fields["filename"] = saved_name
        update_fields["original_filename"] = safe_name

    if not update_fields:
        return jsonify({"error": "no new data provided"}), 400

    # -------- MongoDB তে আপডেট --------
    result = videos_col.update_one({"_id": oid}, {"$set": update_fields})
    if result.matched_count == 0:
        return jsonify({"error": "video not found during update"}), 404

    updated_doc = videos_col.find_one({"_id": oid})

    # -------- রেসপন্স বানানো --------
    image_url = None
    if updated_doc.get("image_filename"):
        image_url = f"{request.host_url}uploads/{updated_doc.get('image_filename')}"

    video_url = None
    if updated_doc.get("filename"):
        video_url = f"{request.host_url}video/{updated_doc['_id']}/stream"

    return jsonify({
        "message": "video updated",
        "video": {
            "id": str(updated_doc["_id"]),
            "title": updated_doc.get("title"),
            "video_link": updated_doc.get("video_link"),
            "subtitle_text": updated_doc.get("subtitle_text"),
            "image_url": image_url,
            "video_url": video_url,
            "original_filename": updated_doc.get("original_filename"),
            "uploaded_at": updated_doc.get("uploaded_at"),
            "unique_views": updated_doc.get("unique_views", 0),
            "total_clicks": updated_doc.get("total_clicks", 0)
        }
    })



# ────────────── Admin Upload Video ──────────────

@app.route("/admin/upload_chunk", methods=["POST"])
def upload_chunk():
    """
    বড় ফাইল টুকরো টুকরো (chunk) করে আপলোড করতে।
    ফ্রন্টএন্ড থেকে multipart/form-data পাঠাতে হবে:
      - chunk=<file part>
      - chunk_number=<int> (যেমন 1,2,3…)
      - total_chunks=<int> (যেমন মোট 10 chunk)
      - original_filename=<filename>
    """
    chunk_file = request.files.get("chunk")
    chunk_number = int(request.form.get("chunk_number", 0))
    total_chunks = int(request.form.get("total_chunks", 0))
    original_filename = secure_filename(request.form.get("original_filename", "file"))

    if not chunk_file or chunk_number == 0 or total_chunks == 0:
        return jsonify({"error": "invalid chunk data"}), 400

    temp_dir = os.path.join(app.config["UPLOAD_FOLDER"], f"chunks_{original_filename}")
    os.makedirs(temp_dir, exist_ok=True)

    chunk_path = os.path.join(temp_dir, f"chunk_{chunk_number:05d}")
    chunk_file.save(chunk_path)

    # সব chunk এলে ফাইল কম্বাইন করি
    if len(os.listdir(temp_dir)) == total_chunks:
        combined_name = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "_" + original_filename
        final_path = os.path.join(app.config["UPLOAD_FOLDER"], combined_name)
        with open(final_path, "wb") as outfile:
            for i in range(1, total_chunks + 1):
                part_path = os.path.join(temp_dir, f"chunk_{i:05d}")
                with open(part_path, "rb") as infile:
                    outfile.write(infile.read())
        # অস্থায়ী chunk ফোল্ডার মুছে দিই
        import shutil
        shutil.rmtree(temp_dir)

        # MongoDB তে রেকর্ড যোগ করা
        doc = {
            "title": original_filename,
            "filename": combined_name,
            "original_filename": original_filename,
            "video_link": "",
            "subtitle_text": "",
            "image_filename": None,
            "uploaded_at": now_iso(),
            "viewers": [],
            "unique_views": 0,
            "total_clicks": 0
        }
        res = videos_col.insert_one(doc)
        return jsonify({"message": "upload complete", "video_id": str(res.inserted_id)})

    return jsonify({"message": f"chunk {chunk_number}/{total_chunks} uploaded"})


@app.route("/admin/upload", methods=["POST"])
def upload_video():
    title = (request.form.get("title") or "").strip()
    video_link = (request.form.get("video_link") or "").strip()
    subtitle_text = (request.form.get("subtitle") or "").strip()

    filename_for_db = None
    original_filename = None
    image_filename = None

    if "file" in request.files and request.files["file"].filename:
        f = request.files["file"]
        if not allowed_file(f.filename):
            return jsonify({"error": f"filetype not allowed. allowed: {ALLOWED_EXTENSIONS}"}), 400

        safe_name = secure_filename(f.filename)
        unique_prefix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        saved_name = f"{unique_prefix}_{safe_name}"
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], saved_name)
        f.save(save_path)

        filename_for_db = saved_name
        original_filename = safe_name
        title = title or f.filename

    elif video_link:
        title = title or "External Video"
    else:
        return jsonify({"error": "no file or video_link provided"}), 400

    if "image" in request.files and request.files["image"].filename:
        img = request.files["image"]
        safe_img = secure_filename(img.filename)
        img_name = f"img_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{safe_img}"
        img_path = os.path.join(app.config["UPLOAD_FOLDER"], img_name)
        img.save(img_path)
        image_filename = img_name

    doc = {
        "title": title,
        "filename": filename_for_db,
        "original_filename": original_filename,
        "video_link": video_link,
        "subtitle_text": subtitle_text,
        "image_filename": image_filename,
        "uploaded_at": now_iso(),
        "viewers": [],
        "unique_views": 0,
        "total_clicks": 0
    }

    res = videos_col.insert_one(doc)

    return jsonify({
        "message": "uploaded",
        "video": {
            "id": str(res.inserted_id),
            "title": title
        }
    }), 201

# ────────────── Videos list ──────────────

@app.route("/videos", methods=["GET"])
def list_videos():
    """
    সব ভিডিও রিটার্ন করবে, কিন্তু viewers / timestamps ইত্যাদি date বা date range অনুযায়ী ফিল্টার হবে।
    Query params:
      ?date=YYYY-MM-DD  অথবা
      ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
    """
    single_date = request.args.get("date")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    date_filter_start = None
    date_filter_end = None

    if single_date:
        try:
            day_start = datetime.fromisoformat(single_date).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start.replace(hour=23, minute=59, second=59, microsecond=999999)
            date_filter_start, date_filter_end = day_start, day_end
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

    elif start_date and end_date:
        try:
            start = datetime.fromisoformat(start_date).replace(hour=0, minute=0, second=0, microsecond=0)
            end = datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59, microsecond=999999)
            date_filter_start, date_filter_end = start, end
        except ValueError:
            return jsonify({"error": "Invalid start_date or end_date format. Use YYYY-MM-DD"}), 400

    vids = []
    all_unique_ips = set()   # 🔹 নতুন যোগ করা হয়েছে

    for v in videos_col.find().sort("uploaded_at", -1):
        video_id = str(v["_id"])
        video_url = f"{request.host_url}video/{video_id}/stream" if v.get("filename") else None
        image_url = f"{request.host_url}uploads/{v.get('image_filename')}" if v.get("image_filename") else None

        # ---- viewers ফিল্টার ----
        viewers = v.get("viewers", [])
        if date_filter_start and date_filter_end:
            filtered_viewers = []
            for viewer in viewers:
                timestamps = viewer.get("timestamps", [])
                filtered_ts = [ts for ts in timestamps if
                               date_filter_start.isoformat() <= ts <= date_filter_end.isoformat()]
                if filtered_ts:
                    filtered_viewers.append({"ip": viewer.get("ip"), "timestamps": filtered_ts})
            viewers = filtered_viewers

        # 🔹 এখানে সব ফিল্টারকৃত viewers এর unique ip সংগ্রহ করা হবে
        for viewer in viewers:
            if viewer.get("ip"):
                all_unique_ips.add(viewer["ip"])

        vids.append({
            "id": video_id,
            "title": v.get("title"),
            "original_filename": v.get("original_filename"),
            "uploaded_at": v.get("uploaded_at"),
            "unique_views": v.get("unique_views", 0),
            "total_clicks": v.get("total_clicks", 0),
            "video_url": video_url,
            "video_link": v.get("video_link"),
            "subtitle_text": v.get("subtitle_text"),
            "image_url": image_url,
            "viewers": viewers
        })

    # 🔹 নতুন parameter response এ যোগ করা হল
    return jsonify({
        "videos": vids,
        "total_unique_ips": len(all_unique_ips)
    })

# ────────────── Delete Image ──────────────
@app.route("/admin/image/<image_id>", methods=["DELETE"])
def delete_image(image_id):
    try:
        oid = ObjectId(image_id)
    except Exception:
        return jsonify({"error": "invalid image id"}), 400

    img = images_col.find_one_and_delete({"_id": oid})
    if not img:
        return jsonify({"error": "image not found"}), 404

    filename = img.get("filename")
    if filename:
        try:
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"], filename))
        except FileNotFoundError:
            pass

    return jsonify({"message": "image deleted", "id": image_id})



# ────────────── Images Collection ──────────────
images_col = db.images


# ────────────── Admin Upload Image ──────────────









# @app.route("/admin/upload_image", methods=["POST"])
# def upload_image():
#     """
#     শুধু ইমেজ আপলোড করতে।
#     form-data:
#       - image (file)
#       - title (optional)
#     """
#     if "image" not in request.files or not request.files["image"].filename:
#         return jsonify({"error": "no image file provided"}), 400
#
#     img = request.files["image"]
#     safe_img = secure_filename(img.filename)
#     img_name = f"img_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{safe_img}"
#     img_path = os.path.join(app.config["UPLOAD_FOLDER"], img_name)
#     img.save(img_path)
#
#     title = (request.form.get("title") or "").strip() or safe_img
#
#     doc = {
#         "title": title,
#         "filename": img_name,
#         "uploaded_at": now_iso()
#     }
#     res = images_col.insert_one(doc)
#
#     return jsonify({
#         "message": "image uploaded",
#         "image": {
#             "id": str(res.inserted_id),
#             "title": title,
#             "url": f"{request.host_url}uploads/{img_name}"
#         }
#     }), 201




















# ────────────── Images List ──────────────
# @app.route("/images", methods=["GET"])
# def list_images():
#     """
#     সব ইমেজ লিস্ট করবে
#     """
#     imgs = []
#     for img in images_col.find().sort("uploaded_at", -1):
#         imgs.append({
#             "id": str(img["_id"]),
#             "title": img.get("title"),
#             "uploaded_at": img.get("uploaded_at"),
#             "url": f"{request.host_url}uploads/{img.get('filename')}"
#         })
#     return jsonify({"images": imgs})








@app.route("/images", methods=["GET"])
def list_images():
    """
    সব ইমেজ লিস্ট করবে — প্রতিটা রেকর্ডে থাকবে:
    id, title, original_filename, index_number,
    site_name, site_url, registration_information,
    domain_name, copyright
    """
    imgs = []
    for img in images_col.find().sort("uploaded_at", -1):
        imgs.append({
            "id": str(img["_id"]),
            "title": img.get("title"),
            "original_filename": img.get("original_filename"),
            "index_number": img.get("index_number"),
            "uploaded_at": img.get("uploaded_at"),
            "url": f"{request.host_url}uploads/{img.get('filename')}",
            "site_name": img.get("site_name"),
            "site_url": img.get("site_url"),
            "registration_information": img.get("registration_information"),
            "domain_name": img.get("domain_name"),
            "copyright_info": img.get("copyright_info")
        })
    return jsonify({"images": imgs})














@app.route("/admin/upload_image", methods=["POST"])
def upload_image():
    """
    শুধু ইমেজ আপলোড করতে।
    form-data:
      - image (file)
      - title (optional)
      - index_number (optional integer/string)
      - site_name (string)
      - site_url (string)
      - registration_information (string)
      - domain_name (string)
      - copyright_info (string)
    """
    if "image" not in request.files or not request.files["image"].filename:
        return jsonify({"error": "no image file provided"}), 400

    img = request.files["image"]
    safe_img = secure_filename(img.filename)
    img_name = f"img_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{safe_img}"
    img_path = os.path.join(app.config["UPLOAD_FOLDER"], img_name)
    img.save(img_path)

    # ---------- মূল ফিল্ডগুলো ----------
    title = (request.form.get("title") or "").strip() or safe_img
    index_number = (request.form.get("index_number") or "").strip()
    original_filename = safe_img

    # ---------- নতুন ফিল্ডগুলো ----------
    site_name = (request.form.get("site_name") or "").strip()
    site_url = (request.form.get("site_url") or "").strip()
    registration_information = (request.form.get("registration_information") or "").strip()
    domain_name = (request.form.get("domain_name") or "").strip()
    copyright_info = (request.form.get("copyright_info") or "").strip()

    # ---------- MongoDB তে সেভ ----------
    doc = {
        "title": title,
        "filename": img_name,
        "original_filename": original_filename,
        "index_number": index_number,
        "uploaded_at": now_iso(),
        # নতুন ফিল্ড যোগ
        "site_name": site_name,
        "site_url": site_url,
        "registration_information": registration_information,
        "domain_name": domain_name,
        "copyright_info": copyright_info
    }
    res = images_col.insert_one(doc)

    # ---------- Response ----------
    return jsonify({
        "message": "image uploaded",
        "image": {
            "id": str(res.inserted_id),
            "title": title,
            "original_filename": original_filename,
            "index_number": index_number,
            "url": f"{request.host_url}uploads/{img_name}",
            "site_name": site_name,
            "site_url": site_url,
            "registration_information": registration_information,
            "domain_name": domain_name,
            "copyright_info": copyright_info
        }
    }), 201








# ────────────── Keywords Collection ──────────────
keywords_col = db.keywords


# ────────────── Create Keyword ──────────────
@app.route("/admin/keyword", methods=["POST"])
def create_keyword():
    """
    form-data/json:
      - keyword (string)
    """
    keyword = (request.form.get("keyword") or request.json.get("keyword") or "").strip()
    if not keyword:
        return jsonify({"error": "keyword required"}), 400

    doc = {
        "keyword": keyword,
        "created_at": now_iso()
    }
    res = keywords_col.insert_one(doc)

    return jsonify({
        "message": "keyword created",
        "keyword": {
            "id": str(res.inserted_id),
            "keyword": keyword
        }
    }), 201


# ────────────── Get All Keywords ──────────────
@app.route("/keywords", methods=["GET"])
def list_keywords():
    keywords = []
    for k in keywords_col.find().sort("created_at", -1):
        keywords.append({
            "id": str(k["_id"]),
            "keyword": k.get("keyword"),
            "created_at": k.get("created_at")
        })
    return jsonify({"keywords": keywords})


# ────────────── Get Single Keyword ──────────────
@app.route("/keyword/<keyword_id>", methods=["GET"])
def get_keyword(keyword_id):
    try:
        oid = ObjectId(keyword_id)
    except Exception:
        return jsonify({"error": "invalid keyword id"}), 400

    k = keywords_col.find_one({"_id": oid})
    if not k:
        return jsonify({"error": "keyword not found"}), 404

    return jsonify({
        "id": str(k["_id"]),
        "keyword": k.get("keyword"),
        "created_at": k.get("created_at")
    })


# ────────────── Update Keyword ──────────────
@app.route("/admin/keyword/<keyword_id>", methods=["PATCH"])
def update_keyword(keyword_id):
    try:
        oid = ObjectId(keyword_id)
    except Exception:
        return jsonify({"error": "invalid keyword id"}), 400

    new_keyword = (request.form.get("keyword") or request.json.get("keyword") or "").strip()
    if not new_keyword:
        return jsonify({"error": "keyword required"}), 400

    res = keywords_col.update_one({"_id": oid}, {"$set": {"keyword": new_keyword}})
    if res.matched_count == 0:
        return jsonify({"error": "keyword not found"}), 404

    updated_doc = keywords_col.find_one({"_id": oid})
    return jsonify({
        "message": "keyword updated",
        "keyword": {
            "id": str(updated_doc["_id"]),
            "keyword": updated_doc.get("keyword")
        }
    })


# ────────────── Delete Keyword ──────────────
@app.route("/admin/keyword/<keyword_id>", methods=["DELETE"])
def delete_keyword(keyword_id):
    try:
        oid = ObjectId(keyword_id)
    except Exception:
        return jsonify({"error": "invalid keyword id"}), 400

    k = keywords_col.find_one_and_delete({"_id": oid})
    if not k:
        return jsonify({"error": "keyword not found"}), 404

    return jsonify({"message": "keyword deleted", "id": keyword_id})












# ────────────── Admin Update Uploaded Image ──────────────
@app.route("/admin/upload_image/<image_id>", methods=["PATCH"])
def update_uploaded_image(image_id):
    """
    আগে আপলোড করা image (images collection এ) আপডেট করবে।
    আপডেট করা যাবে:
      - title (text)
      - image (file)
    সবগুলো ফিল্ড optional; যেটা দিবে সেটাই আপডেট হবে।
    """
    try:
        oid = ObjectId(image_id)
    except Exception:
        return jsonify({"error": "invalid image id"}), 400

    img_doc = images_col.find_one({"_id": oid})
    if not img_doc:
        return jsonify({"error": "image not found"}), 404

    update_fields = {}

    # ---- টাইটেল আপডেট ----
    new_title = (request.form.get("title") or "").strip() if request.form else None
    if new_title:
        update_fields["title"] = new_title

    # ---- ইমেজ ফাইল আপডেট ----
    if "image" in request.files and request.files["image"].filename:
        img = request.files["image"]
        safe_img = secure_filename(img.filename)
        img_name = f"img_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{safe_img}"
        img_path = os.path.join(app.config["UPLOAD_FOLDER"], img_name)
        img.save(img_path)

        # পুরনো ইমেজ থাকলে ফাইল সিস্টেম থেকে মুছে দাও
        if img_doc.get("filename"):
            old_img_path = os.path.join(app.config["UPLOAD_FOLDER"], img_doc.get("filename"))
            try:
                os.remove(old_img_path)
            except FileNotFoundError:
                pass

        update_fields["filename"] = img_name

    if not update_fields:
        return jsonify({"error": "no new data provided"}), 400

    images_col.update_one({"_id": oid}, {"$set": update_fields})
    updated_doc = images_col.find_one({"_id": oid})

    return jsonify({
        "message": "image updated",
        "image": {
            "id": str(updated_doc["_id"]),
            "title": updated_doc.get("title"),
            "url": f"{request.host_url}uploads/{updated_doc.get('filename')}",
            "uploaded_at": updated_doc.get("uploaded_at")
        }
    })


#########################################################################

users_col = db.users


@app.route("/auth/register", methods=["POST"])
def register():
    """
    JSON form:
      {
        "username": "testuser",
        "email": "test@example.com",
        "password": "123456",
        "role": "admin" | "user" (optional)
      }
    """
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()
    role = (data.get("role") or "user").strip().lower()

    if not username or not email or not password:
        return jsonify({"error": "username, email, password required"}), 400

    if users_col.find_one({"$or": [{"username": username}, {"email": email}]}):
        return jsonify({"error": "username or email already exists"}), 409

    user_doc = {
        "username": username,
        "email": email,
        "password": password,  # plain text (simple)
        "role": role,
        "created_at": now_iso(),
        "last_login_at": None
    }
    res = users_col.insert_one(user_doc)

    session["user_id"] = str(res.inserted_id)
    session["username"] = username
    session["role"] = role

    return jsonify({
        "message": "registered successfully",
        "user": {
            "id": str(res.inserted_id),
            "username": username,
            "email": email,
            "role": role
        }
    }), 201





@app.route("/auth/login", methods=["POST"])
def login():
    """
    JSON form:
      {
        "username": "testuser",
        "password": "123456"
      }
    """
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"error": "username and password required"}), 400

    user = users_col.find_one({"username": username})
    if not user or user.get("password") != password:
        return jsonify({"error": "invalid username or password"}), 401

    session["user_id"] = str(user["_id"])
    session["username"] = user.get("username")
    session["role"] = user.get("role", "user")

    users_col.update_one({"_id": user["_id"]}, {"$set": {"last_login_at": now_iso()}})

    return jsonify({
        "message": "login successful",
        "user": {
            "id": str(user["_id"]),
            "username": user.get("username"),
            "email": user.get("email"),
            "role": user.get("role")
        }
    })







@app.route("/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "logged out successfully"})





@app.route("/auth/me", methods=["GET"])
def me():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"authenticated": False})

    u = users_col.find_one({"_id": ObjectId(user_id)})
    if not u:
        return jsonify({"authenticated": False})

    return jsonify({
        "authenticated": True,
        "user": {
            "id": str(u["_id"]),
            "username": u.get("username"),
            "email": u.get("email"),
            "role": u.get("role"),
            "created_at": u.get("created_at"),
            "last_login_at": u.get("last_login_at")
        }
    })






@app.route("/admin/user/<user_id>/role", methods=["PATCH"])
def update_user_role(user_id):
    """
    কেবল admin ইউজাররা অন্য ইউজারের role পরিবর্তন করতে পারবে।
    form-data বা JSON:
      {
        "new_role": "admin" | "user"
      }
    """
    # --- প্রথমে লগইন আছে কিনা চেক করো ---
    current_role = session.get("role")
    if not current_role:
        return jsonify({"error": "login required"}), 401

    # --- admin না হলে অনুমতি নাই ---
    if current_role != "admin":
        return jsonify({"error": "only admin can update roles"}), 403

    # --- ইনপুট নাও ---
    data = request.get_json(silent=True) or request.form
    new_role = (data.get("new_role") or "").strip().lower()

    if new_role not in ("admin", "user"):
        return jsonify({"error": "invalid role, must be 'admin' or 'user'"}), 400

    try:
        oid = ObjectId(user_id)
    except Exception:
        return jsonify({"error": "invalid user id"}), 400

    user = users_col.find_one({"_id": oid})
    if not user:
        return jsonify({"error": "user not found"}), 404

    # --- নিজের role নিজে পরিবর্তন করতে না পারে ---
    if str(user["_id"]) == session.get("user_id"):
        return jsonify({"error": "cannot change your own role"}), 400

    # --- MongoDB তে আপডেট ---
    users_col.update_one({"_id": oid}, {"$set": {"role": new_role}})

    return jsonify({
        "message": "user role updated",
        "user": {
            "id": str(user["_id"]),
            "username": user.get("username"),
            "email": user.get("email"),
            "new_role": new_role
        }
    })






########################################################################

# ────────────── Video detail ──────────────
@app.route("/video/<video_id>", methods=["GET"])
def video_detail(video_id):
    try:
        oid = ObjectId(video_id)
    except Exception:
        return jsonify({"error": "invalid video id"}), 400

    v = videos_col.find_one({"_id": oid})
    if not v:
        return jsonify({"error": "video not found"}), 404

    image_url = None
    if v.get("image_filename"):
        image_url = f"{request.host_url}uploads/{v.get('image_filename')}"

    return jsonify({
        "id": str(v["_id"]),
        "title": v.get("title"),
        "original_filename": v.get("original_filename"),
        "uploaded_at": v.get("uploaded_at"),
        "unique_views": v.get("unique_views", 0),
        "total_clicks": v.get("total_clicks", 0),
        "video_url": f"{request.host_url}video/{v['_id']}/stream",
        "video_link": v.get("video_link"),
        "subtitle_text": v.get("subtitle_text"),
        "image_url": image_url,
        "viewers": v.get("viewers", [])
    })

# ────────────── Stream Video ──────────────
@app.route("/video/<video_id>/stream", methods=["GET"])
def stream_video(video_id):
    try:
        oid = ObjectId(video_id)
    except Exception:
        return jsonify({"error": "invalid video id"}), 400
    v = videos_col.find_one({"_id": oid})
    if not v:
        return jsonify({"error": "video not found"}), 404
    filename = v.get("filename")
    if not filename:
        return jsonify({"error": "file missing"}), 404
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=False)

# ────────────── Record Click ──────────────
@app.route("/video/<video_id>/click", methods=["POST"])
def video_click(video_id):
    try:
        oid = ObjectId(video_id)
    except Exception:
        return jsonify({"error": "invalid video id"}), 400

    client_ip = get_client_ip()
    timestamp = now_iso()

    update_result = videos_col.update_one(
        {"_id": oid, "viewers.ip": client_ip},
        {
            "$push": {"viewers.$.timestamps": timestamp},
            "$inc": {"total_clicks": 1}
        }
    )

    if update_result.matched_count == 0:
        new_viewer = {"ip": client_ip, "timestamps": [timestamp]}
        update_result2 = videos_col.update_one(
            {"_id": oid},
            {
                "$push": {"viewers": new_viewer},
                "$inc": {"unique_views": 1, "total_clicks": 1}
            }
        )
        if update_result2.matched_count == 0:
            return jsonify({"error": "video not found"}), 404
        first_time = True
    else:
        first_time = False

    v = videos_col.find_one({"_id": oid}, {"viewers": 1, "unique_views": 1, "total_clicks":1})
    if not v:
        return jsonify({"error": "video not found after update"}), 404

    return jsonify({
        "message": "click recorded",
        "first_time_for_ip": first_time,
        "unique_views": v.get("unique_views", 0),
        "total_clicks": v.get("total_clicks", 0),
        "viewer_preview": v.get("viewers", [])[:50]
    })

# ────────────── Delete Video ──────────────
@app.route("/admin/video/<video_id>", methods=["DELETE"])
def delete_video(video_id):
    try:

        oid = ObjectId(video_id)
    except Exception:
        return jsonify({"error": "invalid video id"}), 400
    v = videos_col.find_one_and_delete({"_id": oid})
    if not v:
        return jsonify({"error": "video not found"}), 404
    filename = v.get("filename")
    if filename:
        try:
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"], filename))
        except FileNotFoundError:
            pass
    return jsonify({"message": "deleted", "id": video_id})

# ────────────── Admin list full viewers ──────────────
@app.route("/admin/videos_with_viewers", methods=["GET"])
def admin_videos_with_viewers():
    vids = []
    for v in videos_col.find().sort("uploaded_at", -1):
        vids.append({
            "id": str(v["_id"]),
            "title": v.get("title"),
            "uploaded_at": v.get("uploaded_at"),
            "unique_views": v.get("unique_views", 0),
            "total_clicks": v.get("total_clicks", 0),
            "viewers": v.get("viewers", [])
        })
    return jsonify({"videos": vids})

# ────────────── Healthcheck ──────────────
@app.route("/health", methods=["GET"])
def health():
    try:
        client.admin.command("ping")
        return jsonify({"status": "ok", "db": DB_NAME})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500













    # =====================================================
    # 📂 BANNER IMAGE (Header & Footer)
    # =====================================================

    banner_images_col = db.banner_images  # নতুন collection

    # ────────────── Upload Banner ──────────────
    @app.route("/admin/upload_banner", methods=["POST"])
    def upload_banner():
        """
        form-data:
          - image (file)
          - title (optional)
          - banner_type (header/footer)
          - index_number (optional)
        """
        if "image" not in request.files or not request.files["image"].filename:
            return jsonify({"error": "no image file provided"}), 400

        banner_type = (request.form.get("banner_type") or "").strip().lower()
        if banner_type not in ["header", "footer"]:
            return jsonify({"error": "invalid banner_type, must be 'header' or 'footer'"}), 400

        img = request.files["image"]
        safe_img = secure_filename(img.filename)
        img_name = f"banner_{banner_type}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{safe_img}"
        img_path = os.path.join(app.config["UPLOAD_FOLDER"], img_name)
        img.save(img_path)

        title = (request.form.get("title") or "").strip() or safe_img
        index_number = (request.form.get("index_number") or "").strip()
        original_filename = safe_img

        doc = {
            "title": title,
            "filename": img_name,
            "original_filename": original_filename,
            "banner_type": banner_type,
            "index_number": index_number,
            "uploaded_at": now_iso()
        }
        res = banner_images_col.insert_one(doc)

        return jsonify({
            "message": f"{banner_type} banner uploaded",
            "banner": {
                "id": str(res.inserted_id),
                "title": title,
                "banner_type": banner_type,
                "original_filename": original_filename,
                "index_number": index_number,
                "url": f"{request.host_url}uploads/{img_name}"
            }
        }), 201

    # ────────────── Get All Banners ──────────────
    @app.route("/banners", methods=["GET"])
    def list_banners():
        """
        সব header এবং footer banner রিটার্ন করবে
        optional query param: ?type=header OR ?type=footer
        """
        banner_type = request.args.get("type")
        q = {}
        if banner_type:
            q["banner_type"] = banner_type.lower()

        banners = []
        for b in banner_images_col.find(q).sort("uploaded_at", -1):
            banners.append({
                "id": str(b["_id"]),
                "title": b.get("title"),
                "banner_type": b.get("banner_type"),
                "original_filename": b.get("original_filename"),
                "index_number": b.get("index_number"),
                "uploaded_at": b.get("uploaded_at"),
                "url": f"{request.host_url}uploads/{b.get('filename')}"
            })

        return jsonify({"banners": banners})

    # ────────────── Delete Banner ──────────────
    @app.route("/admin/banner/<banner_id>", methods=["DELETE"])
    def delete_banner(banner_id):
        try:
            oid = ObjectId(banner_id)
        except Exception:
            return jsonify({"error": "invalid banner id"}), 400

        b = banner_images_col.find_one_and_delete({"_id": oid})
        if not b:
            return jsonify({"error": "banner not found"}), 404

        filename = b.get("filename")
        if filename:
            try:
                os.remove(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            except FileNotFoundError:
                pass

        return jsonify({
            "message": f"{b.get('banner_type', 'banner')} deleted",
            "id": banner_id
        })























if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=8080, debug=debug)
