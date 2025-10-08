#
#
#
# import os
# import asyncio
# from flask import Flask, request, jsonify
# from telethon import TelegramClient
# from telethon.errors import (
#     PhoneCodeInvalidError,
#     SessionPasswordNeededError,
#     PhoneNumberInvalidError,
# )
#
# # =============================
# # 🔧 CONFIGURATION
# # =============================
#
# API_ID = int(os.getenv("TG_API_ID", "20767444"))        # ← তোমার Telegram App ID বসাও
# API_HASH = os.getenv("TG_API_HASH", "2ca0cb711803e1aae9e45d34eb81e57a")  # ← তোমার App Hash বসাও
# SESS_DIR = "./sessions"
# os.makedirs(SESS_DIR, exist_ok=True)
#
# # =============================
# # 🚀 Flask App Init
# # =============================
# app = Flask(__name__)
#
# def get_client(phone: str):
#     """Session per phone number"""
#     session_path = os.path.join(SESS_DIR, f"{phone}.session")
#     return TelegramClient(session_path, API_ID, API_HASH)
#
#
# # =============================
# # 📱 1️⃣ Login Endpoint (send OTP)
# # =============================
# @app.route("/login", methods=["POST"])
# def login():
#     phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
#     if not phone:
#         return jsonify({"status": "error", "detail": "phone missing"}), 400
#
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#
#     async def send_code():
#         client = get_client(phone)
#         await client.connect()
#         try:
#             if await client.is_user_authorized():
#                 return {"status": "already_authorized"}
#             sent = await client.send_code_request(phone)
#             print(f"📨 Sent code to {phone} | hash={sent.phone_code_hash}")
#             return {
#                 "status": "code_sent",
#                 "phone_code_hash": sent.phone_code_hash
#             }
#         except PhoneNumberInvalidError:
#             return {"status": "error", "detail": "Invalid phone number"}
#         except Exception as e:
#             return {"status": "error", "detail": str(e)}
#         finally:
#             await client.disconnect()
#
#     result = loop.run_until_complete(send_code())
#     print("✅ Login result:", result)
#     return jsonify(result)
#
#
# # =============================
# # 🔑 2️⃣ Verify Endpoint (verify OTP)
# # =============================
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
# # @app.route("/verify", methods=["POST"])
# # def verify():
# #     phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
# #     code = request.form.get("code") or (request.json.get("code") if request.is_json else None)
# #     phone_code_hash = request.form.get("phone_code_hash") or (request.json.get("phone_code_hash") if request.is_json else None)
# #
# #     if not phone or not code or not phone_code_hash:
# #         return jsonify({"status": "error", "detail": "phone/code/phone_code_hash missing"}), 400
# #
# #     loop = asyncio.new_event_loop()
# #     asyncio.set_event_loop(loop)
# #
# #     async def do_verify():
# #         client = get_client(phone)
# #         await client.connect()
# #         try:
# #             if await client.is_user_authorized():
# #                 return {"status": "already_authorized"}
# #             await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
# #             return {"status": "authorized"}
# #         except PhoneCodeInvalidError:
# #             return {"status": "error", "detail": "Invalid OTP code"}
# #         except SessionPasswordNeededError:
# #             return {"status": "error", "detail": "Two-step verification enabled"}
# #         except Exception as e:
# #             return {"status": "error", "detail": str(e)}
# #         finally:
# #             await client.disconnect()
# #
# #     result = loop.run_until_complete(do_verify())
# #     print("✅ Verify result:", result)
# #     return jsonify(result)
#
#
#
#
#
#
#
#
#
#
#
# @app.route("/verify", methods=["POST"])
# def verify():
#     phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
#     code = request.form.get("code") or (request.json.get("code") if request.is_json else None)
#     phone_code_hash = request.form.get("phone_code_hash") or (request.json.get("phone_code_hash") if request.is_json else None)
#
#     if not phone or not code or not phone_code_hash:
#         return jsonify({"status": "error", "detail": "phone/code/phone_code_hash missing"}), 400
#
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#
#     async def do_verify():
#         client = get_client(phone)
#         await client.connect()
#         try:
#             if await client.is_user_authorized():
#                 return {"status": "already_authorized"}
#             user = await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
#             await client.send_message("me", "✅ Flask API login successful!")
#             await client.disconnect()
#             return {"status": "authorized", "user": str(user)}
#         except Exception as e:
#             return {"status": "error", "detail": str(e)}
#
#     result = loop.run_until_complete(do_verify())
#     print("✅ Verify result:", result)
#     return jsonify(result)
#
#
#
#
#
#
# # =============================
# # ✉️ 3️⃣ Send Message
# # =============================
# @app.route("/send", methods=["POST"])
# def send_message():
#     phone = request.form.get("phone")
#     to = request.form.get("to")
#     text = request.form.get("text")
#
#     if not phone or not to or not text:
#         return jsonify({"status": "error", "detail": "phone/to/text missing"}), 400
#
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#
#     async def do_send():
#         client = get_client(phone)
#         await client.connect()
#         try:
#             if not await client.is_user_authorized():
#                 return {"status": "error", "detail": "not authorized"}
#             await client.send_message(to, text)
#             return {"status": "sent"}
#         except Exception as e:
#             return {"status": "error", "detail": str(e)}
#         finally:
#             await client.disconnect()
#
#     result = loop.run_until_complete(do_send())
#     print("✅ Send result:", result)
#     return jsonify(result)
#
#
# # =============================
# # 💬 4️⃣ Get Dialogs (chat list)
# # =============================
# @app.route("/dialogs", methods=["GET"])
# def get_dialogs():
#     phone = request.args.get("phone")
#     if not phone:
#         return jsonify({"status": "error", "detail": "phone missing"}), 400
#
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#
#     async def do_get_dialogs():
#         client = get_client(phone)
#         await client.connect()
#         try:
#             if not await client.is_user_authorized():
#                 return {"status": "error", "detail": "not authorized"}
#             dialogs = []
#             async for d in client.iter_dialogs(limit=50):
#                 dialogs.append({
#                     "id": d.id,
#                     "name": getattr(d.entity, 'title', getattr(d.entity, 'username', str(d.entity)))
#                 })
#             return {"status": "ok", "dialogs": dialogs}
#         except Exception as e:
#             return {"status": "error", "detail": str(e)}
#         finally:
#             await client.disconnect()
#
#     result = loop.run_until_complete(do_get_dialogs())
#     print("✅ Dialogs result:", result)
#     return jsonify(result)
#
#
# # =============================
# # 🏁 RUN APP
# # =============================
# if __name__ == "__main__":
#     app.run(host="0.0.0.0", port=8080, debug=True)




















import os
import shutil
import asyncio
import time
import sqlite3
from flask import Flask, request, jsonify
from telethon import TelegramClient
from telethon.errors import (
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
    PhoneNumberInvalidError,
)

# ==================================
# ⚙️ CONFIGURATION
# ==================================
API_ID = int(os.getenv("TG_API_ID", "20767444"))  # ← তোমার Telegram API_ID বসাও
API_HASH = os.getenv("TG_API_HASH", "2ca0cb711803e1aae9e45d34eb81e57a")  # ← তোমার API_HASH বসাও

SESS_DIR = "./sessions"
os.makedirs(SESS_DIR, exist_ok=True)

# ✅ Windows async loop fix (Python 3.12 safety)
try:
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
except Exception:
    pass

# ==================================
# 🚀 Flask Init
# ==================================
app = Flask(__name__)

# ==================================
# 🧩 Helper: Safe Client Loader
# ==================================
def get_client(phone: str):
    """
    প্রতিবার client connect করার আগে .session ফাইলের একটা .tmp কপি নেয়,
    যাতে sqlite database locked না হয়।
    """
    safe_phone = phone.replace("+", "").replace(" ", "").strip()
    base_path = os.path.join(SESS_DIR, f"{safe_phone}.session")
    tmp_path = base_path + ".tmp"

    if os.path.exists(base_path):
        try:
            shutil.copy(base_path, tmp_path)
        except Exception as e:
            print(f"⚠️ Could not copy session file: {e}")

    session_path = tmp_path if os.path.exists(tmp_path) else base_path
    print(f"📂 Using session file: {session_path}")
    return TelegramClient(session_path, API_ID, API_HASH)

# ==================================
# 📱 1️⃣ LOGIN (Send OTP)
# ==================================
# @app.route("/login", methods=["POST"])
# def login():
#     phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
#     if not phone:
#         return jsonify({"status": "error", "detail": "phone missing"}), 400
#
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#
#     async def send_code():
#         client = get_client(phone)
#         await client.connect()
#         try:
#             if await client.is_user_authorized():
#                 await client.disconnect()
#                 return {"status": "already_authorized"}
#
#             sent = await client.send_code_request(phone)
#             await client.session.save()
#             await client.disconnect()
#             return {"status": "code_sent", "phone_code_hash": sent.phone_code_hash}
#         except PhoneNumberInvalidError:
#             return {"status": "error", "detail": "Invalid phone number"}
#         except Exception as e:
#             return {"status": "error", "detail": str(e)}
#
#     result = loop.run_until_complete(send_code())
#     print("✅ Login result:", result)
#     return jsonify(result)














@app.route("/login", methods=["POST"])
def login():
    phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
    if not phone:
        return jsonify({"status": "error", "detail": "phone missing"}), 400

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def send_code():
        client = get_client(phone)
        await client.connect()
        try:
            if await client.is_user_authorized():
                try:
                    await client.disconnect()
                except Exception:
                    client.disconnect()
                return {"status": "already_authorized"}

            sent = await client.send_code_request(phone)
            # ✅ safer session save
            try:
                client.session.save()
            except Exception as e:
                print(f"⚠️ session save error: {e}")

            try:
                await client.disconnect()
            except Exception:
                client.disconnect()

            return {"status": "code_sent", "phone_code_hash": sent.phone_code_hash}

        except PhoneNumberInvalidError:
            return {"status": "error", "detail": "Invalid phone number"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    result = loop.run_until_complete(send_code())
    print("✅ Login result:", result)
    return jsonify(result)









# ==================================
# 🔑 2️⃣ VERIFY OTP
# ==================================
# @app.route("/verify", methods=["POST"])
# def verify():
#     phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
#     code = request.form.get("code") or (request.json.get("code") if request.is_json else None)
#     phone_code_hash = request.form.get("phone_code_hash") or (request.json.get("phone_code_hash") if request.is_json else None)
#
#     if not phone or not code or not phone_code_hash:
#         return jsonify({"status": "error", "detail": "phone/code/phone_code_hash missing"}), 400
#
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#
#     async def do_verify():
#         client = get_client(phone)
#         await client.connect()
#         try:
#             if await client.is_user_authorized():
#                 return {"status": "already_authorized"}
#
#             user = await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
#             await client.send_message("me", "✅ Flask API login successful!")
#             await client.session.save()
#             await client.disconnect()
#             return {"status": "authorized", "user": str(user)}
#         except PhoneCodeInvalidError:
#             return {"status": "error", "detail": "Invalid OTP code"}
#         except SessionPasswordNeededError:
#             return {"status": "error", "detail": "Two-step verification enabled"}
#         except Exception as e:
#             return {"status": "error", "detail": str(e)}
#
#     result = loop.run_until_complete(do_verify())
#     print("✅ Verify result:", result)
#     return jsonify(result)



















@app.route("/verify", methods=["POST"])
def verify():
    phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
    code = request.form.get("code") or (request.json.get("code") if request.is_json else None)
    phone_code_hash = request.form.get("phone_code_hash") or (request.json.get("phone_code_hash") if request.is_json else None)

    if not phone or not code or not phone_code_hash:
        return jsonify({"status": "error", "detail": "phone/code/phone_code_hash missing"}), 400

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def do_verify():
        client = get_client(phone)
        await client.connect()
        try:
            if await client.is_user_authorized():
                # ✅ যদি আগেই লগইন থাকে, তাহলে শুধু disconnect করো
                try:
                    await client.disconnect()
                except Exception:
                    client.disconnect()
                return {"status": "already_authorized"}

            # ✅ Telegram login
            user = await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            await client.send_message("me", "✅ Flask API login successful!")

            # ⚠️ FIX #1: 'await' বাদ দাও — session.save() async নয়
            try:
                client.session.save()
            except Exception as e:
                print(f"⚠️ session save error: {e}")

            # ⚠️ FIX #2: safe disconnect — async বা non-async দুইভাবেই চলবে
            try:
                await client.disconnect()
            except Exception:
                client.disconnect()

            return {"status": "authorized", "user": str(user)}

        except PhoneCodeInvalidError:
            return {"status": "error", "detail": "Invalid OTP code"}
        except SessionPasswordNeededError:
            return {"status": "error", "detail": "Two-step verification enabled"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    result = loop.run_until_complete(do_verify())
    print("✅ Verify result:", result)
    return jsonify(result)





# ==================================
# ✉️ 3️⃣ SEND MESSAGE
# ==================================
@app.route("/send", methods=["POST"])
def send_message():
    phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
    to = request.form.get("to") or (request.json.get("to") if request.is_json else None)
    text = request.form.get("text") or (request.json.get("text") if request.is_json else None)

    if not phone or not to or not text:
        return jsonify({"status": "error", "detail": "phone/to/text missing"}), 400

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def do_send():
        client = get_client(phone)
        await client.connect()
        await client.start()
        try:
            if not await client.is_user_authorized():
                return {"status": "error", "detail": "not authorized"}
            await client.send_message(to, text)
            await client.session.save()
            return {"status": "sent"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}
        finally:
            await client.disconnect()
            await client.disconnected

    result = loop.run_until_complete(do_send())
    print("✅ Send result:", result)
    return jsonify(result)





















# ==================================
# 🔒 5️⃣ LOGOUT (Remove session)
# ==================================
@app.route("/logout", methods=["POST"])
def logout():
    phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)

    if not phone:
        return jsonify({"status": "error", "detail": "phone missing"}), 400

    # make consistent filename (same as get_client)
    safe_phone = phone.replace("+", "").replace(" ", "").strip()
    session_path = os.path.join(SESS_DIR, f"{safe_phone}.session")
    tmp_path = session_path + ".tmp"

    # async disconnect before delete
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def do_logout():
        client = get_client(phone)
        try:
            await client.connect()
            if await client.is_user_authorized():
                await client.log_out()  # proper Telegram logout
                print(f"👋 Logged out Telegram session for {phone}")
            await client.disconnect()
        except Exception as e:
            print(f"⚠️ Logout error: {e}")

    # run async part
    loop.run_until_complete(do_logout())

    # delete session files
    deleted = []
    for path in [session_path, tmp_path]:
        if os.path.exists(path):
            try:
                os.remove(path)
                deleted.append(os.path.basename(path))
            except Exception as e:
                print(f"⚠️ Could not delete {path}: {e}")

    if deleted:
        return jsonify({"status": "ok", "deleted": deleted})
    else:
        return jsonify({"status": "ok", "detail": "no session file found"})

# ==================================
# 💬 4️⃣ GET DIALOGS (Chat list)
# ==================================
@app.route("/dialogs", methods=["GET"])
def get_dialogs():
    phone = request.args.get("phone")
    if not phone:
        return jsonify({"status": "error", "detail": "phone missing"}), 400

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def do_get_dialogs(retry=0):
        client = get_client(phone)
        try:
            await client.connect()
            await client.start()

            if not await client.is_user_authorized():
                await client.disconnect()
                return {"status": "error", "detail": "not authorized"}

            dialogs = []
            async for d in client.iter_dialogs(limit=50):
                dialogs.append({
                    "id": d.id,
                    "name": getattr(d.entity, 'title', getattr(d.entity, 'username', str(d.entity))),
                    "unread_count": d.unread_count,
                    "is_user": d.is_user,
                    "is_group": d.is_group,
                    "is_channel": d.is_channel
                })
            await client.disconnect()
            await client.disconnected
            return {"status": "ok", "dialogs": dialogs}

        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and retry < 3:
                print(f"⏳ Database locked, retrying ({retry+1}) ...")
                time.sleep(0.5)
                return await do_get_dialogs(retry + 1)
            return {"status": "error", "detail": f"SQLite lock error: {str(e)}"}

        except Exception as e:
            return {"status": "error", "detail": str(e)}
        finally:
            try:
                await client.disconnect()
                await client.disconnected
            except Exception:
                pass

    result = loop.run_until_complete(do_get_dialogs())
    print("✅ Dialogs result:", result)
    return jsonify(result)

# ==================================
# 🏁 RUN SERVER
# ==================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
