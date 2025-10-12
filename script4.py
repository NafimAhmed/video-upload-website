

import os
import asyncio
from flask import Flask, request, jsonify, redirect, send_file
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
    PhoneNumberInvalidError,
)
from pymongo import MongoClient
from datetime import datetime, timezone
from io import BytesIO

# ==================================
# ⚙️ CONFIGURATION
# ==================================
API_ID = int(os.getenv("TG_API_ID", "20767444"))
API_HASH = os.getenv("TG_API_HASH", "2ca0cb711803e1aae9e45d34eb81e57a")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "telegram_api")

mongo_client = MongoClient(MONGO_URI)
db = mongo_client[MONGO_DB]

# ✅ Flask Init
app = Flask(__name__)

# ✅ Windows fix
try:
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
except Exception:
    pass


# ==================================
# 🧩 MongoDB-based session helper
# ==================================
async def get_client(phone: str):
    safe_phone = phone.strip().replace("+", "").replace(" ", "")
    doc = db.sessions.find_one({"phone": safe_phone})
    if doc and "session_string" in doc and doc["session_string"]:
        session_str = doc["session_string"]
        print(f"🔹 Restoring existing session for {phone}")
    else:
        session_str = ""
        print(f"⚠️ No session found for {phone}, creating new one.")
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    return client


async def save_session(phone: str, client: TelegramClient):
    """Save authorized session string to MongoDB"""
    session_str = client.session.save()
    safe_phone = phone.strip().replace("+", "").replace(" ", "")
    db.sessions.update_one(
        {"phone": safe_phone},
        {"$set": {"session_string": session_str, "updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    print(f"💾 Session saved for {phone}")


# ==================================
# 📱 LOGIN (Send OTP)
# ==================================
@app.route("/login", methods=["POST"])
def login():
    phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
    if not phone:
        return jsonify({"status": "error", "detail": "phone missing"}), 400

    async def send_code():
        client = await get_client(phone)
        await client.connect()
        try:
            if await client.is_user_authorized():
                await client.disconnect()
                return {"status": "already_authorized"}

            sent = await client.send_code_request(phone)
            await save_session(phone, client)
            await client.disconnect()
            return {"status": "code_sent", "phone_code_hash": sent.phone_code_hash}
        except PhoneNumberInvalidError:
            return {"status": "error", "detail": "Invalid phone number"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    result = asyncio.run(send_code())
    print("✅ Login result:", result)
    return jsonify(result)


# ==================================
# 🔑 VERIFY OTP
# ==================================
# @app.route("/verify", methods=["POST"])
# def verify():
#     phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
#     code = request.form.get("code") or (request.json.get("code") if request.is_json else None)
#     phone_code_hash = request.form.get("phone_code_hash") or (
#         request.json.get("phone_code_hash") if request.is_json else None
#     )
#
#     if not all([phone, code, phone_code_hash]):
#         return jsonify({"status": "error", "detail": "phone/code/phone_code_hash missing"}), 400
#
#     async def do_verify():
#         client = await get_client(phone)
#         await client.connect()
#         try:
#             if await client.is_user_authorized():
#                 await client.disconnect()
#                 return {"status": "already_authorized"}
#
#             user = await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
#             await client.send_message("me", "✅ Flask API login successful!")
#             await save_session(phone, client)
#             await client.disconnect()
#             return {"status": "authorized", "user": str(user)}
#         except PhoneCodeInvalidError:
#             return {"status": "error", "detail": "Invalid OTP code"}
#         except SessionPasswordNeededError:
#             return {"status": "error", "detail": "Two-step verification enabled"}
#         except Exception as e:
#             return {"status": "error", "detail": str(e)}
#
#     result = asyncio.run(do_verify())
#     print("✅ Verify result:", result)
#     return jsonify(result)









# ==================================
# 🔑 VERIFY OTP (with Two-Step support)
# ==================================
# @app.route("/verify", methods=["POST"])
# def verify():
#     """
#     Telegram OTP ভেরিফিকেশন API
#     - যদি normal OTP হয় -> সরাসরি authorized হবে
#     - যদি 2FA password লাগে -> '2fa_required' status ফেরত দেবে
#     Example:
#         {
#           "phone": "+8801606xxxxxx",
#           "code": "12345",
#           "phone_code_hash": "xxxxx"
#         }
#     """
#     phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
#     code = request.form.get("code") or (request.json.get("code") if request.is_json else None)
#     phone_code_hash = request.form.get("phone_code_hash") or (
#         request.json.get("phone_code_hash") if request.is_json else None
#     )
#
#     if not all([phone, code, phone_code_hash]):
#         return jsonify({"status": "error", "detail": "phone/code/phone_code_hash missing"}), 400
#
#     async def do_verify():
#         client = await get_client(phone)
#         await client.connect()
#         try:
#             # যদি আগেই লগইন করা থাকে
#             if await client.is_user_authorized():
#                 me = await client.get_me()
#                 await client.disconnect()
#                 return {
#                     "status": "already_authorized",
#                     "user": {"id": me.id, "username": me.username, "first_name": me.first_name},
#                 }
#
#             # OTP verify করার চেষ্টা
#             user = await client.sign_in(
#                 phone=phone, code=code, phone_code_hash=phone_code_hash
#             )
#
#             # সফল হলে
#             await client.send_message("me", "✅ Flask API login successful!")
#             await save_session(phone, client)
#             me = await client.get_me()
#             await client.disconnect()
#             return {
#                 "status": "authorized",
#                 "user": {
#                     "id": me.id,
#                     "username": me.username,
#                     "first_name": me.first_name,
#                     "phone": me.phone,
#                 },
#             }
#
#         # ⚠️ যদি 2FA enabled থাকে
#         except SessionPasswordNeededError:
#             await client.disconnect()
#             return {
#                 "status": "2fa_required",
#                 "detail": "Two-step verification password needed for this account",
#             }
#
#         # ⚠️ ভুল OTP
#         except PhoneCodeInvalidError:
#             await client.disconnect()
#             return {"status": "error", "detail": "Invalid OTP code"}
#
#         # ⚠️ অন্য error
#         except Exception as e:
#             await client.disconnect()
#             return {"status": "error", "detail": str(e)}
#
#     # Run async function
#     result = asyncio.run(do_verify())
#     print("✅ Verify result:", result)
#     return jsonify(result)








# ==================================
# 🔑 VERIFY OTP (Full User Info + 2FA Support + Safe JSON)
# ==================================
# @app.route("/verify", methods=["POST"])
# def verify():
#     """
#     Telegram OTP verification endpoint.
#     Handles:
#     - Normal OTP login
#     - Two-step verification (2FA)
#     - Returns full Telegram user data in JSON
#     Example:
#         POST /verify
#         {
#           "phone": "+8801606xxxxxx",
#           "code": "12345",
#           "phone_code_hash": "xxxxxxxx"
#         }
#     """
#     phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
#     code = request.form.get("code") or (request.json.get("code") if request.is_json else None)
#     phone_code_hash = request.form.get("phone_code_hash") or (
#         request.json.get("phone_code_hash") if request.is_json else None
#     )
#
#     if not all([phone, code, phone_code_hash]):
#         return jsonify({"status": "error", "detail": "phone/code/phone_code_hash missing"}), 400
#
#     async def do_verify():
#         from datetime import datetime
#         client = await get_client(phone)
#         await client.connect()
#         try:
#             # ✅ already authorized
#             if await client.is_user_authorized():
#                 me = await client.get_me()
#                 await client.disconnect()
#                 return {"status": "already_authorized", "user": user_to_dict(me)}
#
#             # ✅ try OTP sign in
#             user = await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
#             if not user:
#                 await client.disconnect()
#                 return {"status": "error", "detail": "sign_in returned None (invalid code or hash)"}
#
#             await client.send_message("me", "✅ Flask API login successful!")
#             await save_session(phone, client)
#
#             me = await client.get_me()
#             await client.disconnect()
#             return {"status": "authorized", "user": user_to_dict(me)}
#
#         except SessionPasswordNeededError:
#             # 🔐 2FA required
#             await client.disconnect()
#             return {
#                 "status": "2fa_required",
#                 "detail": "Two-step verification password needed for this account"
#             }
#
#         except PhoneCodeInvalidError:
#             await client.disconnect()
#             return {"status": "error", "detail": "Invalid OTP code"}
#
#         except Exception as e:
#             import traceback
#             print("❌ Exception:\n", traceback.format_exc())
#             await client.disconnect()
#             return {"status": "error", "detail": str(e)}
#
#     result = asyncio.run(do_verify())
#     print("✅ Verify result:", result)
#     return jsonify(result)












# ==================================
# 🔑 VERIFY OTP (RAW USER STRING)
# ==================================
@app.route("/verify", methods=["POST"])
def verify():
    """
    Telegram OTP verification endpoint.
    Handles:
    - Normal OTP login
    - Two-step verification (2FA)
    - Returns raw Telethon User(...) string exactly like Telegram object repr
    Example:
        POST /verify
        {
          "phone": "+8801606xxxxxx",
          "code": "12345",
          "phone_code_hash": "xxxxxxxx"
        }
    """
    phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
    code = request.form.get("code") or (request.json.get("code") if request.is_json else None)
    phone_code_hash = request.form.get("phone_code_hash") or (
        request.json.get("phone_code_hash") if request.is_json else None
    )

    if not all([phone, code, phone_code_hash]):
        return jsonify({"status": "error", "detail": "phone/code/phone_code_hash missing"}), 400

    async def do_verify():
        client = await get_client(phone)
        await client.connect()
        try:
            # ✅ already authorized
            if await client.is_user_authorized():
                me = await client.get_me()
                user_str = str(me)
                await client.disconnect()
                return {"status": "already_authorized", "user": user_str}

            # ✅ try OTP sign in
            user = await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            if not user:
                await client.disconnect()
                return {"status": "error", "detail": "sign_in returned None (invalid code or hash)"}

            await client.send_message("me", "✅ Flask API login successful!")
            await save_session(phone, client)

            me = await client.get_me()
            user_str = str(me)

            await client.disconnect()
            return {"status": "authorized", "user": user_str}

        except SessionPasswordNeededError:
            # 🔐 2FA required
            await client.disconnect()
            return {
                "status": "2fa_required",
                "detail": "Two-step verification password needed for this account"
            }

        except PhoneCodeInvalidError:
            await client.disconnect()
            return {"status": "error", "detail": "Invalid OTP code"}

        except Exception as e:
            import traceback
            print("❌ Exception in /verify:\n", traceback.format_exc())
            await client.disconnect()
            return {"status": "error", "detail": str(e)}

    result = asyncio.run(do_verify())
    print("✅ Verify result:", result)
    return jsonify(result)










# ==================================
# 🔐 VERIFY 2FA PASSWORD
# ==================================
# @app.route("/verify_password", methods=["POST"])
# def verify_password():
#     phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
#     password = request.form.get("password") or (request.json.get("password") if request.is_json else None)
#     if not all([phone, password]):
#         return jsonify({"status": "error", "detail": "phone/password missing"}), 400
#
#     async def do_verify_password():
#         client = await get_client(phone)
#         await client.connect()
#         try:
#             if await client.is_user_authorized():
#                 await client.disconnect()
#                 return {"status": "already_authorized"}
#
#             await client.sign_in(password=password)
#             await client.send_message("me", "✅ 2FA password verified successfully!")
#             await save_session(phone, client)
#             await client.disconnect()
#             return {"status": "authorized_by_password"}
#         except Exception as e:
#             await client.disconnect()
#             return {"status": "error", "detail": str(e)}
#
#     result = asyncio.run(do_verify_password())
#     print("✅ Verify password result:", result)
#     return jsonify(result)












# ==================================
# 🔐 VERIFY 2FA PASSWORD (FULL USER INFO)
# ==================================
# @app.route("/verify_password", methods=["POST"])
# def verify_password():
#     """
#     Verify Telegram 2-Step Verification password.
#     Returns full user info if successful.
#     """
#     phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
#     password = request.form.get("password") or (request.json.get("password") if request.is_json else None)
#     if not all([phone, password]):
#         return jsonify({"status": "error", "detail": "phone/password missing"}), 400
#
#     async def do_verify_password():
#         client = await get_client(phone)
#         await client.connect()
#         try:
#             # যদি আগে থেকেই লগইন করা থাকে
#             if await client.is_user_authorized():
#                 me = await client.get_me()
#                 await client.disconnect()
#                 return {
#                     "status": "already_authorized",
#                     "user": str(me)
#                 }
#
#             # 🔐 password দিয়ে sign in
#             await client.sign_in(password=password)
#
#             await client.send_message("me", "✅ 2FA password verified successfully!")
#             await save_session(phone, client)
#
#             # ✅ full user info
#             me = await client.get_me()
#             await client.disconnect()
#
#             return {
#                 "status": "authorized_by_password",
#                 "user": str(me)
#             }
#
#         except Exception as e:
#             import traceback
#             print("❌ Exception in /verify_password:\n", traceback.format_exc())
#             await client.disconnect()
#             return {"status": "error", "detail": str(e)}
#
#     result = asyncio.run(do_verify_password())
#     print("✅ Verify password result:", result)
#     return jsonify(result)



















# ==================================
# 🔐 VERIFY 2FA PASSWORD (RAW USER STRING)
# ==================================
@app.route("/verify_password", methods=["POST"])
def verify_password():
    """
    Verify Telegram 2FA password and return the raw Telethon User(...) string.
    """
    phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
    password = request.form.get("password") or (request.json.get("password") if request.is_json else None)
    if not all([phone, password]):
        return jsonify({"status": "error", "detail": "phone/password missing"}), 400

    async def do_verify_password():
        client = await get_client(phone)
        await client.connect()
        try:
            # 🔹 Already authorized
            if await client.is_user_authorized():
                me = await client.get_me()
                user_str = str(me)
                await client.disconnect()
                return {
                    "status": "already_authorized",
                    "user": user_str
                }

            # 🔹 Sign in with password
            await client.sign_in(password=password)
            await client.send_message("me", "✅ 2FA password verified successfully!")
            await save_session(phone, client)

            me = await client.get_me()
            user_str = str(me)

            await client.disconnect()
            return {
                "status": "authorized_by_password",
                "user": user_str
            }

        except Exception as e:
            import traceback
            print("❌ Exception in /verify_password:\n", traceback.format_exc())
            await client.disconnect()
            return {"status": "error", "detail": str(e)}

    result = asyncio.run(do_verify_password())
    print("✅ Verify password result:", result)
    return jsonify(result)







# ==================================
# 🧩 Helper: Convert Telegram User → JSON safe
# ==================================
def user_to_dict(user):
    """Convert Telethon User object safely to JSON-serializable dict"""
    if not user:
        return {}

    from datetime import datetime
    data = {}
    for k, v in vars(user).items():
        try:
            if isinstance(v, datetime):
                data[k] = v.isoformat()
            elif isinstance(v, (list, tuple, set)):
                data[k] = [str(x) for x in v]
            elif isinstance(v, dict):
                data[k] = {str(key): str(val) for key, val in v.items()}
            else:
                data[k] = str(v)
        except Exception as e:
            data[k] = f"<unserializable: {e}>"
    return data



















# ==================================
# 💬 GET DIALOGS (Optimized + Lazy Load Ready)
# ==================================
@app.route("/dialogs", methods=["GET"])
def get_dialogs():
    """
    Telegram থেকে সমস্ত dialogs (chats, groups, channels)
    দ্রুত ও lazy-load ready format-এ ফেরত দেয়।
    Example:
      /dialogs?phone=+8801606100833
    """
    phone = request.args.get("phone")
    if not phone:
        return jsonify({"status": "error", "detail": "phone missing"}), 400

    async def do_get_dialogs():
        # 🧠 Cached client load
        client = await get_client(phone)
        if not client.is_connected():
            await client.connect()

        # ✅ Authorized check
        if not await client.is_user_authorized():
            await client.disconnect()
            return {"status": "error", "detail": "not authorized"}

        dialogs = []

        # ⚙️ Limit কমানো হয়েছে (speed boost)
        async for d in client.iter_dialogs(limit=50):
            e = d.entity

            # 🖼️ Future-ready lazy load (photo download এখন বন্ধ)
            # ⚡ ভবিষ্যতে চাইলে নিচের তিনটা লাইন uncomment করে দিও
            photo = None
            # try:
            #     if e.photo:
            #         photo = await client.download_profile_photo(e, file=bytes)
            # except Exception:
            #     pass

            # 🧩 Last message info
            msg = d.message
            last_msg = {
                "id": getattr(msg, "id", None),
                "text": getattr(msg, "message", None),
                "date": getattr(msg, "date", None).isoformat() if getattr(msg, "date", None) else None,
                "sender_id": getattr(getattr(msg, "from_id", None), "user_id", None),
                "reply_to": getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None),
                "media": str(type(getattr(msg, "media", None)).__name__) if getattr(msg, "media", None) else None,
            } if msg else None

            # 📦 Dialog summary data
            dialog_info = {
                # 🆔 Basic
                "id": d.id,
                "name": getattr(e, "title", getattr(e, "username", str(e))),
                "username": getattr(e, "username", None),
                "first_name": getattr(e, "first_name", None),
                "last_name": getattr(e, "last_name", None),
                "phone": getattr(e, "phone", None),

                # 🔍 Type
                "is_user": d.is_user,
                "is_group": d.is_group,
                "is_channel": d.is_channel,

                # 🕐 Meta
                "unread_count": d.unread_count,
                "pinned": getattr(d, "pinned", False),

                # ⚡ Optional flags
                "verified": getattr(e, "verified", False),
                "bot": getattr(e, "bot", False),
                "premium": getattr(e, "premium", False),
                "fake": getattr(e, "fake", False),
                "scam": getattr(e, "scam", False),

                # 💬 Last message info
                "last_message": last_msg,

                # 🖼️ Lazy photo indicator
                "has_photo": bool(getattr(e, "photo", None)),
            }

            dialogs.append(dialog_info)

        # ✅ Disconnect কোরো না যদি client cache ব্যবহার করো
        # await client.disconnect()

        return {"status": "ok", "count": len(dialogs), "dialogs": dialogs}

    # 🚀 Run async task
    result = asyncio.run(do_get_dialogs())
    print(f"✅ Dialogs result: {result['count']} chats fetched")
    return jsonify(result)









#
# @app.route("/dialogs", methods=["GET"])
# def get_dialogs():
#     """
#     Telegram থেকে সমস্ত dialogs (chats, groups, channels)
#     full detailed info সহ ফেরত দেয়।
#     Example:
#       /dialogs?phone=+8801606100833
#     """
#     phone = request.args.get("phone")
#     if not phone:
#         return jsonify({"status": "error", "detail": "phone missing"}), 400
#
#     async def do_get_dialogs():
#         client = await get_client(phone)
#         await client.connect()
#
#         if not await client.is_user_authorized():
#             await client.disconnect()
#             return {"status": "error", "detail": "not authorized"}
#
#         dialogs = []
#         async for d in client.iter_dialogs(limit=100):  # চাইলে limit বাড়াতে পারো
#             e = d.entity
#
#             # 🧩 Try to get profile photo URL (optional)
#             photo = None
#             try:
#                 if e.photo:
#                     photo = await client.download_profile_photo(e, file=bytes)
#             except Exception:
#                 pass
#
#             # 🧩 Last message info
#             msg = d.message
#             last_msg = {
#                 "id": getattr(msg, "id", None),
#                 "text": getattr(msg, "message", None),
#                 "date": getattr(msg, "date", None).isoformat() if getattr(msg, "date", None) else None,
#                 "sender_id": getattr(getattr(msg, "from_id", None), "user_id", None),
#                 "reply_to": getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None),
#                 "media": str(type(getattr(msg, "media", None)).__name__) if getattr(msg, "media", None) else None,
#             } if msg else None
#
#             dialog_info = {
#                 # 🆔 Basic identifiers
#                 "id": d.id,
#                 "name": getattr(e, "title", getattr(e, "username", str(e))),
#                 "username": getattr(e, "username", None),
#                 "first_name": getattr(e, "first_name", None),
#                 "last_name": getattr(e, "last_name", None),
#                 "phone": getattr(e, "phone", None),
#
#                 # 🔍 Chat Type
#                 "is_user": d.is_user,
#                 "is_group": d.is_group,
#                 "is_channel": d.is_channel,
#
#                 # 🕐 Message + Meta
#                 "unread_count": d.unread_count,
#                 "pinned": getattr(d, "pinned", False),
#                 "verified": getattr(e, "verified", False),
#                 "restricted": getattr(e, "restricted", False),
#                 "bot": getattr(e, "bot", False),
#                 "scam": getattr(e, "scam", False),
#                 "fake": getattr(e, "fake", False),
#                 "premium": getattr(e, "premium", False),
#
#                 # 🧠 Extended fields
#                 "title": getattr(e, "title", None),
#                 "about": getattr(e, "about", None),
#                 "participants_count": getattr(e, "participants_count", None),
#                 "access_hash": getattr(e, "access_hash", None),
#                 "dc_id": getattr(getattr(e, "photo", None), "dc_id", None),
#
#                 # 💬 Last Message Info
#                 "last_message": last_msg,
#
#                 # 🖼️ Optional: photo bytes base64
#                 "has_photo": bool(photo),
#             }
#
#             dialogs.append(dialog_info)
#
#         await client.disconnect()
#         return {"status": "ok", "count": len(dialogs), "dialogs": dialogs}
#
#     result = asyncio.run(do_get_dialogs())
#     print(f"✅ Dialogs result: {result['count']} chats fetched")
#     return jsonify(result)



# ==================================
# 🧍 AVATAR REDIRECT
# ==================================
@app.route("/avatar_redirect", methods=["GET"])
def avatar_redirect():
    phone = request.args.get("phone")
    username = request.args.get("username")
    if not phone or not username:
        return jsonify({"error": "phone or username missing"}), 400

    async def get_avatar_bytes():
        client = await get_client(phone)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return None

        try:
            entity = await client.get_entity(username)
            avatar_bytes = await client.download_profile_photo(entity, file=bytes)
            await client.disconnect()
            return avatar_bytes
        except Exception as e:
            print(f"⚠️ avatar error: {e}")
            await client.disconnect()
            return None

    img_bytes = asyncio.run(get_avatar_bytes())
    if img_bytes is None:
        return redirect("https://telegram.org/img/t_logo.png")

    return send_file(BytesIO(img_bytes), mimetype="image/jpeg")


# ==================================
# 🔒 LOGOUT
# ==================================
@app.route("/logout", methods=["POST"])
def logout():
    phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
    if not phone:
        return jsonify({"status": "error", "detail": "phone missing"}), 400

    async def do_logout():
        client = await get_client(phone)
        await client.connect()
        try:
            if await client.is_user_authorized():
                await client.log_out()
            await client.disconnect()
            db.sessions.delete_one({"phone": phone.strip().replace("+", "").replace(" ", "")})
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    result = asyncio.run(do_logout())
    print("✅ Logout result:", result)
    return jsonify(result)












@app.route("/send", methods=["POST"])
def send_message():
    phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
    to = request.form.get("to") or (request.json.get("to") if request.is_json else None)
    text = request.form.get("text") or (request.json.get("text") if request.is_json else None)

    if not all([phone, to, text]):
        return jsonify({"status": "error", "detail": "phone/to/text missing"}), 400

    async def do_send():
        client = await get_client(phone)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                await client.disconnect()
                return {"status": "error", "detail": "not authorized"}

            await client.send_message(to, text)
            await save_session(phone, client)
            await client.disconnect()
            return {"status": "sent", "to": to, "text": text}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    result = asyncio.run(do_send())
    print("✅ Send result:", result)
    return jsonify(result)























# ==================================
# 💌 GET CHAT MESSAGES (NEW)
# ==================================






@app.route("/messages", methods=["GET"])
def get_messages():
    phone = request.args.get("phone")
    chat_id = request.args.get("chat_id")
    limit = int(request.args.get("limit", 30))

    if not phone or not chat_id:
        return jsonify({"status": "error", "detail": "phone/chat_id missing"}), 400

    async def do_get_messages():
        client = await get_client(phone)
        await client.connect()

        if not await client.is_user_authorized():
            await client.disconnect()
            return {"status": "error", "detail": "not authorized"}

        try:
            # ✅ আগে entity resolve করো
            entity = await client.get_entity(int(chat_id))

            messages = []
            async for msg in client.iter_messages(entity, limit=limit):
                messages.append({
                    "id": msg.id,
                    "text": msg.message,
                    "sender_id": getattr(msg.from_id, "user_id", None),
                    "date": msg.date.isoformat() if msg.date else None,
                    "is_out": msg.out,
                })
            await client.disconnect()
            return {"status": "ok", "messages": list(reversed(messages))}

        except Exception as e:
            await client.disconnect()
            return {"status": "error", "detail": str(e)}

    result = asyncio.run(do_get_messages())
    print("✅ Messages result:", result)
    return jsonify(result)




# ==================================
# 🏁 RUN SERVER
# ==================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
