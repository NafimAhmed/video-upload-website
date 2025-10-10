
import os
import shutil
import asyncio
import time
import sqlite3
from flask import Flask, request, jsonify, redirect, send_file
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




# def get_client(phone: str):
#     safe_phone = phone.replace("+", "").replace(" ", "").strip()
#     base_path = os.path.join(SESS_DIR, f"{safe_phone}.session")
#
#     # 🔹 প্রতিবার নতুন temp copy তৈরি করো
#     tmp_path = os.path.join(SESS_DIR, f"{safe_phone}_{int(time.time()*1000)}.tmp.session")
#
#     if os.path.exists(base_path):
#         try:
#             shutil.copy(base_path, tmp_path)
#         except Exception as e:
#             print(f"⚠️ Could not copy session file: {e}")
#             tmp_path = base_path  # fallback
#
#     print(f"📂 Using isolated session file: {tmp_path}")
#     return TelegramClient(tmp_path, API_ID, API_HASH)















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



















# @app.route("/send", methods=["POST"])
# def send_message():
#     phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
#     to = request.form.get("to") or (request.json.get("to") if request.is_json else None)
#     text = request.form.get("text") or (request.json.get("text") if request.is_json else None)
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
#         await client.start()
#         try:
#             if not await client.is_user_authorized():
#                 return {"status": "error", "detail": "not authorized"}
#             await client.send_message(to, text)
#             await client.session.save()
#             return {"status": "sent"}
#         except Exception as e:
#             return {"status": "error", "detail": str(e)}
#         finally:
#             await client.disconnect()
#             await client.disconnected
#
#     result = loop.run_until_complete(do_send())
#     print("✅ Send result:", result)
#     return jsonify(result)

















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
            client.session.save()
            return {"status": "sent"}

        except Exception as e:
            return {"status": "error", "detail": str(e)}

        finally:
            try:
                await client.disconnect()
                if hasattr(client, "disconnected") and client.disconnected:
                    await client.disconnected
            except Exception:
                pass

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





















# @app.route("/dialogs", methods=["GET"])
# def get_dialogs():
#     phone = request.args.get("phone")
#     if not phone:
#         return jsonify({"status": "error", "detail": "phone missing"}), 400
#
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#
#     async def do_get_dialogs(retry=0):
#         client = get_client(phone)
#         try:
#             await client.connect()
#             await client.start()
#
#             if not await client.is_user_authorized():
#                 await client.disconnect()
#                 return {"status": "error", "detail": "not authorized"}
#
#             dialogs = []
#             async for d in client.iter_dialogs(limit=50):
#                 dialogs.append({
#                     "id": d.id,
#                     "name": getattr(d.entity, 'title', getattr(d.entity, 'username', str(d.entity))),
#                     "unread_count": d.unread_count,
#                     "is_user": d.is_user,
#                     "is_group": d.is_group,
#                     "is_channel": d.is_channel
#                 })
#             await client.disconnect()
#             await client.disconnected
#             return {"status": "ok", "dialogs": dialogs}
#
#         except sqlite3.OperationalError as e:
#             if "database is locked" in str(e) and retry < 3:
#                 print(f"⏳ Database locked, retrying ({retry+1}) ...")
#                 time.sleep(0.5)
#                 return await do_get_dialogs(retry + 1)
#             return {"status": "error", "detail": f"SQLite lock error: {str(e)}"}
#
#         except Exception as e:
#             return {"status": "error", "detail": str(e)}
#         finally:
#             try:
#                 await client.disconnect()
#                 await client.disconnected
#             except Exception:
#                 pass
#
#     result = loop.run_until_complete(do_get_dialogs())
#     print("✅ Dialogs result:", result)
#     return jsonify(result)
















# @app.route("/dialogs", methods=["GET"])
# def get_dialogs():
#     phone = request.args.get("phone")
#     if not phone:
#         return jsonify({"status": "error", "detail": "phone missing"}), 400
#
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#
#     AVATAR_DIR = os.path.join("static", "avatars")
#     os.makedirs(AVATAR_DIR, exist_ok=True)
#
#     async def do_get_dialogs(retry=0):
#         client = get_client(phone)
#         try:
#             await client.connect()
#             await client.start()
#
#             if not await client.is_user_authorized():
#                 await client.disconnect()
#                 return {"status": "error", "detail": "not authorized"}
#
#             dialogs = []
#             async for d in client.iter_dialogs(limit=50):
#                 name = getattr(d.entity, 'title', getattr(d.entity, 'username', str(d.entity)))
#
#                 # 🧩 profile photo নাম তৈরি
#                 photo_path = None
#                 image_url = None
#                 try:
#                     if d.entity.photo:
#                         safe_id = str(d.id).replace("-", "_")
#                         photo_path = os.path.join(AVATAR_DIR, f"{safe_id}.jpg")
#                         await client.download_profile_photo(d.entity, file=photo_path)
#                         image_url = f"/avatars/{safe_id}.jpg"
#                 except Exception as e:
#                     print(f"⚠️ photo error ({name}): {e}")
#
#                 dialogs.append({
#                     "id": d.id,
#                     "name": name,
#                     "unread_count": d.unread_count,
#                     "is_user": d.is_user,
#                     "is_group": d.is_group,
#                     "is_channel": d.is_channel,
#                     "image": image_url  # 🧩 image URL যোগ
#                 })
#
#             await client.disconnect()
#             if hasattr(client, "disconnected") and client.disconnected:
#                 await client.disconnected
#
#             return {"status": "ok", "dialogs": dialogs}
#
#         except sqlite3.OperationalError as e:
#             if "database is locked" in str(e) and retry < 3:
#                 print(f"⏳ Database locked, retrying ({retry+1}) ...")
#                 time.sleep(0.5)
#                 return await do_get_dialogs(retry + 1)
#             return {"status": "error", "detail": f"SQLite lock error: {str(e)}"}
#
#         except Exception as e:
#             return {"status": "error", "detail": str(e)}
#
#         finally:
#             try:
#                 await client.disconnect()
#                 if hasattr(client, "disconnected") and client.disconnected:
#                     await client.disconnected
#             except Exception:
#                 pass
#
#     result = loop.run_until_complete(do_get_dialogs())
#     print("✅ Dialogs result:", result)
#     return jsonify(result)









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
                e = d.entity  # entity shortcut
                name = getattr(e, "title", getattr(e, "username", str(e)))

                # =============================
                # 🧩 detailed info extract করা
                # =============================
                dialog_info = {
                    "id": d.id,
                    "name": name,
                    "unread_count": d.unread_count,
                    "is_user": d.is_user,
                    "is_group": d.is_group,
                    "is_channel": d.is_channel,
                    "is_pinned": getattr(d, "pinned", False),
                    "is_verified": getattr(e, "verified", False),
                    "is_bot": getattr(e, "bot", False),
                    "username": getattr(e, "username", None),
                    "first_name": getattr(e, "first_name", None),
                    "last_name": getattr(e, "last_name", None),
                    "phone": getattr(e, "phone", None),
                    "title": getattr(e, "title", None),
                    "participants_count": getattr(getattr(e, "participants_count", None), "value", None),
                    "date": getattr(d.message, "date", None).isoformat() if d.message and getattr(d.message, "date", None) else None,
                    "last_message": getattr(d.message, "message", None),
                    "sender_id": getattr(getattr(d.message, "from_id", None), "user_id", None),
                    "peer_id": getattr(getattr(d.message, "peer_id", None), "channel_id", None)
                               or getattr(getattr(d.message, "peer_id", None), "user_id", None)
                               or getattr(getattr(d.message, "peer_id", None), "chat_id", None),
                    "message_id": getattr(d.message, "id", None)
                }

                dialogs.append(dialog_info)

            await client.disconnect()
            if hasattr(client, "disconnected") and client.disconnected:
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
                if hasattr(client, "disconnected") and client.disconnected:
                    await client.disconnected
            except Exception:
                pass

    result = loop.run_until_complete(do_get_dialogs())
    print("✅ Dialogs result:", result)
    return jsonify(result)



















# @app.route("/avatar_redirect", methods=["GET"])
# def avatar_redirect():
#     """
#     Telegram avatar live redirect (no file save)
#     Example:
#       /avatar_redirect?phone=+8801606100833&username=farhan_bd
#     """
#     phone = request.args.get("phone")
#     username = request.args.get("username")
#
#     if not phone or not username:
#         return jsonify({"error": "phone or username missing"}), 400
#
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#
#     async def get_avatar_bytes():
#         client = get_client(phone)
#         await client.connect()
#         if not await client.is_user_authorized():
#             await client.disconnect()
#             return None
#         try:
#             entity = await client.get_entity(username)
#             # ⚡️ Telegram থেকে avatar bytes আনো
#             avatar_bytes = await client.download_profile_photo(entity, file=bytes)
#             await client.disconnect()
#             return avatar_bytes
#         except Exception as e:
#             print(f"⚠️ avatar error for {username}: {e}")
#             return None
#
#     img_bytes = loop.run_until_complete(get_avatar_bytes())
#     if img_bytes is None:
#         # fallback: default avatar image দেখাবে
#         return redirect("https://telegram.org/img/t_logo.png")
#
#     # 🧠 Flask দিয়ে memory থেকে সরাসরি image পাঠাও
#     from io import BytesIO
#     return send_file(BytesIO(img_bytes), mimetype="image/jpeg")









@app.route("/avatar_redirect", methods=["GET"])
def avatar_redirect():
    """
    Telegram avatar live redirect (no file save)
    Example:
      /avatar_redirect?phone=+8801606100833&username=@usdt_identifi_bot
    """
    phone = request.args.get("phone")
    username = request.args.get("username")

    if not phone or not username:
        return jsonify({"error": "phone or username missing"}), 400

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # ⚙️ Safe Client Loader (isolation for avatar fetch)
    def get_temp_client(phone: str):
        safe_phone = phone.replace("+", "").replace(" ", "").strip()
        base_path = os.path.join(SESS_DIR, f"{safe_phone}.session")

        # প্রতিবার নতুন temp copy তৈরি করো যাতে SQLite lock না হয়
        tmp_path = os.path.join(SESS_DIR, f"{safe_phone}_{int(time.time()*1000)}.tmp.session")

        if os.path.exists(base_path):
            try:
                shutil.copy(base_path, tmp_path)
            except Exception as e:
                print(f"⚠️ Could not copy session file: {e}")
                tmp_path = base_path  # fallback

        print(f"📂 Using isolated session file: {tmp_path}")
        return TelegramClient(tmp_path, API_ID, API_HASH), tmp_path

    async def get_avatar_bytes():
        client, tmp_path = get_temp_client(phone)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                return None, tmp_path

            entity = await client.get_entity(username)

            # ⚡️ Telegram থেকে avatar bytes আনো (memory তে)
            avatar_bytes = await client.download_profile_photo(entity, file=bytes)
            await client.disconnect()
            return avatar_bytes, tmp_path

        except Exception as e:
            print(f"⚠️ avatar error for {username}: {e}")
            try:
                await client.disconnect()
            except Exception:
                pass
            return None, tmp_path

    # 🔹 Avatar fetch করো
    img_bytes, tmp_file = loop.run_until_complete(get_avatar_bytes())

    # 🧹 temp session cleanup
    try:
        if tmp_file and os.path.exists(tmp_file) and tmp_file.endswith(".tmp.session"):
            os.remove(tmp_file)
            print(f"🧹 Temp session removed: {tmp_file}")
    except Exception as e:
        print(f"⚠️ Could not delete temp session: {e}")

    # 🔸 যদি avatar না পাওয়া যায়, fallback Telegram logo দেখাও
    if img_bytes is None:
        return redirect("https://telegram.org/img/t_logo.png")

    # 🧠 Flask দিয়ে memory থেকে সরাসরি image পাঠাও
    from io import BytesIO
    return send_file(BytesIO(img_bytes), mimetype="image/jpeg")







# ==================================
# 🏁 RUN SERVER
# ==================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
