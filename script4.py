

import os
import asyncio
import threading
from flask import Flask, request, jsonify, redirect, send_file
from flask_sock import Sock
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
from flask_socketio import SocketIO, emit
from telethon import events



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

sock = Sock(app)
connected_clients = set()



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



###############################################################################

# ==================================
# 🌐 WEBSOCKET ENDPOINT
# ==================================


@sock.route('/ws')
def ws_route(ws):
    connected_clients.add(ws)
    print("🔗 WebSocket connected")

    active_clients = {}  # phone → TelegramClient map

    try:
        while True:
            msg = ws.receive()
            if msg is None:
                break

            print(f"📩 Received from client: {msg}")

            try:
                data = json.loads(msg)
                action = data.get("action")

                # ✅ SEND message to Telegram
                if action == "send":
                    phone = data.get("phone")
                    to = data.get("to")
                    text = data.get("text")

                    if not all([phone, to, text]):
                        ws.send(json.dumps({"status": "error", "detail": "phone/to/text missing"}))
                        continue

                    async def do_send():
                        client = await get_client(phone)
                        await client.connect()

                        # 🔹 যদি এখনও authorized না থাকে
                        if not await client.is_user_authorized():
                            await client.disconnect()
                            return {"status": "error", "detail": "not authorized"}

                        # 🔹 Telegram-এ পাঠানো
                        await client.send_message(to, text)
                        await save_session(phone, client)
                        await client.disconnect()
                        return {"status": "sent", "to": to, "text": text}

                    result = asyncio.run(do_send())
                    ws.send(json.dumps(result))
                    print("✅ Sent:", result)

                # ✅ LISTEN / SUBSCRIBE for incoming Telegram messages
                elif action == "listen":
                    phone = data.get("phone")
                    if not phone:
                        ws.send(json.dumps({"status": "error", "detail": "phone missing"}))
                        continue

                    async def start_listener():
                        client = await get_client(phone)
                        await client.connect()

                        if not await client.is_user_authorized():
                            await client.disconnect()
                            ws.send(json.dumps({"status": "error", "detail": "not authorized"}))
                            return

                        # 🔹 New message handler
                        @client.on(events.NewMessage)
                        async def handler(event):
                            sender = await event.get_sender()
                            payload = {
                                "action": "new_message",
                                "phone": phone,
                                "chat_id": getattr(event.chat, "id", None),
                                "text": event.raw_text,
                                "sender_id": getattr(sender, "id", None),
                                "sender_name": getattr(sender, "first_name", None),
                                "date": event.date.isoformat() if event.date else None
                            }
                            try:
                                ws.send(json.dumps(payload))
                                print(f"📨 Broadcasted Telegram msg → WS: {payload}")
                            except Exception as e:
                                print(f"⚠️ WebSocket send failed: {e}")

                        active_clients[phone] = client
                        ws.send(json.dumps({"status": "listening", "phone": phone}))
                        print(f"👂 Started listening for {phone}")

                        # 🔄 Keep running listener loop
                        await client.run_until_disconnected()

                    threading.Thread(target=lambda: asyncio.run(start_listener()), daemon=True).start()

                # ✅ Ping test
                elif action == "ping":
                    ws.send(json.dumps({"status": "pong"}))

                else:
                    ws.send(json.dumps({"status": "error", "detail": "unknown action"}))

            except Exception as e:
                ws.send(json.dumps({"status": "error", "detail": str(e)}))
                print(f"⚠️ WS error: {e}")

    except Exception as e:
        print(f"⚠️ WebSocket loop error: {e}")

    finally:
        connected_clients.remove(ws)
        print("❌ WebSocket disconnected")

        # সব Telegram client বন্ধ করা
        for phone, c in active_clients.items():
            try:
                asyncio.run(c.disconnect())
            except:
                pass



import asyncio
import threading
from telethon import events
from telethon.tl.types import InputPeerUser, InputPeerChannel, InputPeerChat

@sock.route('/chat_ws')
def chat_ws(ws):
    """
    🌐 Real-time Telegram Chat WebSocket (FINAL FIXED)
    -------------------------------------------------------
    ✅ Real-time send & receive per chat
    ✅ Async-safe (uses asyncio.run_coroutine_threadsafe)
    ✅ Auto entity resolver (fixes PeerUser error)
    ✅ Background listener thread
    -------------------------------------------------------
    Protocol:
      Connect → ws://127.0.0.1:8080/chat_ws

      1️⃣ Initialize:
        {
          "phone": "8801731979364",
          "chat_id": "9181472862369316499"
        }

      2️⃣ Send message:
        {
          "action": "send",
          "phone": "8801731979364",
          "chat_id": "9181472862369316499",
          "access_hash": "89021312341",
          "text": "Hello Telegram!"
        }

      3️⃣ Receive:
        {
          "action": "new_message",
          "phone": "8801731979364",
          "chat_id": "9181472862369316499",
          "text": "Hey there!",
          "sender_name": "John",
          "date": "2025-10-14T04:12:00Z"
        }

      4️⃣ Stop:
        {"action": "stop"}
    """

    print("🔗 [chat_ws] WebSocket connected")
    tg_client = None
    chat_id = None
    phone = None
    loop = None

    try:
        # =====================================================
        # 1️⃣ First client message: phone + chat_id
        # =====================================================
        msg = ws.receive()
        if msg is None:
            return

        data = json.loads(msg)
        phone = data.get("phone")
        chat_id = data.get("chat_id")

        if not all([phone, chat_id]):
            ws.send(json.dumps({"status": "error", "detail": "phone/chat_id missing"}))
            return

        # =====================================================
        # 2️⃣ Background listener setup
        # =====================================================
        async def run_chat_listener():
            nonlocal tg_client, loop
            tg_client = await get_client(phone)
            loop = asyncio.get_event_loop()
            await tg_client.connect()

            if not await tg_client.is_user_authorized():
                ws.send(json.dumps({"status": "error", "detail": "not authorized"}))
                await tg_client.disconnect()
                return

            ws.send(json.dumps({"status": "listening", "chat_id": chat_id}))
            print(f"👂 [chat_ws] Listening to chat {chat_id} for {phone}")

            # 🔹 Event: new message from Telegram
            @tg_client.on(events.NewMessage(chats=int(chat_id)))
            async def handler(event):
                try:
                    sender = await event.get_sender()
                    payload = {
                        "action": "new_message",
                        "phone": phone,
                        "chat_id": chat_id,
                        "text": event.raw_text,
                        "sender_name": getattr(sender, "first_name", None),
                        "date": event.date.isoformat() if event.date else None
                    }
                    ws.send(json.dumps(payload))
                    print(f"📨 [chat_ws] New message from chat {chat_id}: {payload['text']}")
                except Exception as e:
                    print(f"⚠️ [chat_ws] handler error: {e}")

            await tg_client.run_until_disconnected()

        # Run listener thread
        threading.Thread(target=lambda: asyncio.run(run_chat_listener()), daemon=True).start()

        # =====================================================
        # 3️⃣ WebSocket main loop for incoming commands
        # =====================================================
        while True:
            recv = ws.receive()
            if recv is None:
                break

            try:
                data = json.loads(recv)
                action = data.get("action")

                # 🛑 Stop listener
                if action == "stop":
                    print("🛑 [chat_ws] Stop command received")
                    break

                # ✅ SEND message
                elif action == "send":
                    text = data.get("text")
                    access_hash = data.get("access_hash")
                    if not text:
                        ws.send(json.dumps({"status": "error", "detail": "text missing"}))
                        continue

                    async def send_msg():
                        try:
                            if not tg_client or not await tg_client.is_user_authorized():
                                ws.send(json.dumps({"status": "error", "detail": "not authorized"}))
                                return

                            # ✅ Entity resolve
                            entity = None
                            try:
                                # If access_hash provided, construct InputPeer manually
                                if access_hash:
                                    try:
                                        entity = InputPeerUser(int(chat_id), int(access_hash))
                                    except Exception:
                                        try:
                                            entity = InputPeerChannel(int(chat_id), int(access_hash))
                                        except Exception:
                                            entity = InputPeerChat(int(chat_id))
                                else:
                                    entity = await tg_client.get_entity(int(chat_id))
                            except Exception as e:
                                ws.send(json.dumps({
                                    "status": "error",
                                    "detail": f"Entity resolve failed: {str(e)}"
                                }))
                                return

                            # ✅ Send Telegram message
                            await tg_client.send_message(entity, text)
                            ws.send(json.dumps({
                                "status": "sent",
                                "chat_id": chat_id,
                                "text": text
                            }))
                            print(f"✅ [chat_ws] Sent to chat {chat_id}: {text}")

                        except Exception as e:
                            print(f"⚠️ [chat_ws] send_msg error: {e}")
                            ws.send(json.dumps({"status": "error", "detail": str(e)}))

                    # ✅ Run safely inside same event loop
                    if loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(send_msg(), loop)
                    else:
                        new_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(new_loop)
                        new_loop.run_until_complete(send_msg())

                # 🔄 Optional Ping
                elif action == "ping":
                    ws.send(json.dumps({"status": "pong"}))

                else:
                    ws.send(json.dumps({"status": "error", "detail": "unknown action"}))

            except Exception as e:
                print(f"⚠️ [chat_ws] Error: {e}")
                ws.send(json.dumps({"status": "error", "detail": str(e)}))

    except Exception as e:
        print(f"⚠️ [chat_ws] Unexpected error: {e}")

    finally:
        if tg_client:
            try:
                asyncio.run(tg_client.disconnect())
            except:
                pass
        print("❌ [chat_ws] WebSocket disconnected")




















async def add_new_message_listener(phone: str, client: TelegramClient):
    """Listen for incoming Telegram messages in real-time"""
    @client.on(events.NewMessage)
    async def handler(event):
        try:
            sender = await event.get_sender()
            data = {
                "phone": phone,
                "chat_id": getattr(event.chat, "id", None),
                "text": event.raw_text,
                "sender_id": getattr(sender, "id", None),
                "sender_name": getattr(sender, "first_name", None),
                "date": event.date.isoformat() if event.date else None
            }
            print(f"📩 New message for {phone}: {data}")

            # 🔹 Send real-time data to all WebSocket clients
            for client_ws in list(connected_clients):
                try:
                    client_ws.send(json.dumps(data))
                except Exception as e:
                    print(f"⚠️ WebSocket send failed: {e}")

        except Exception as e:
            print(f"⚠️ Error in new_message handler: {e}")















##########################################################




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



@app.route("/verify", methods=["POST"])
def verify():
    """
    Telegram OTP verification endpoint (Full JSON + Safe for bytes + type rename)
    - সব user ফিল্ড ফেরত দেয়
    - bytes গুলো base64 এ কনভার্ট করে
    - "_" key কে "type" এ rename করে
    """

    phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
    code = request.form.get("code") or (request.json.get("code") if request.is_json else None)
    phone_code_hash = request.form.get("phone_code_hash") or (
        request.json.get("phone_code_hash") if request.is_json else None
    )

    if not all([phone, code, phone_code_hash]):
        return jsonify({"status": "error", "detail": "phone/code/phone_code_hash missing"}), 400

    # 🔹 Recursive helper: makes all data JSON-safe and renames "_" → "type"
    def make_json_safe(obj):
        if isinstance(obj, dict):
            new_dict = {}
            for k, v in obj.items():
                key = "type" if k == "_" else k
                new_dict[key] = make_json_safe(v)
            return new_dict
        elif isinstance(obj, list):
            return [make_json_safe(v) for v in obj]
        elif isinstance(obj, bytes):
            return base64.b64encode(obj).decode("utf-8")
        elif isinstance(obj, datetime):
            return obj.isoformat()
        else:
            return obj

    async def do_verify():
        client = await get_client(phone)
        await client.connect()
        try:
            # ✅ already authorized
            if await client.is_user_authorized():
                me = await client.get_me()
                user_data = make_json_safe(me.to_dict())
                await client.disconnect()
                return {"status": "already_authorized", "user": user_data}

            # ✅ try OTP sign in
            user = await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            if not user:
                await client.disconnect()
                return {"status": "error", "detail": "sign_in returned None (invalid code or hash)"}

            await client.send_message("me", "✅ Flask API login successful!")
            await save_session(phone, client)

            me = await client.get_me()
            user_data = make_json_safe(me.to_dict())
            await client.disconnect()

            return {"status": "authorized", "user": user_data}

        except SessionPasswordNeededError:
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



import base64
import json
from datetime import datetime

@app.route("/verify_password", methods=["POST"])
def verify_password():
    """
    Verify Telegram 2FA password and return full user data (JSON safe)
    - Converts all bytes → base64
    - Renames "_" → "type"
    - Returns all user fields
    Example Response:
        {
          "status": "authorized_by_password",
          "user": {
            "type": "User",
            "id": 7216261663,
            "first_name": "小美",
            "username": "HZ166688",
            "phone": "8801731979364",
            "photo": {
              "type": "UserProfilePhoto",
              "photo_id": "6244245629744302038",
              "dc_id": 5,
              "stripped_thumb": "AQgIjVd3leckcH+YooorPw=="
            },
            "status": {
              "type": "UserStatusOnline",
              "expires": "2025-10-13T12:29:01+00:00"
            }
          }
        }
    """

    phone = request.form.get("phone") or (request.json.get("phone") if request.is_json else None)
    password = request.form.get("password") or (request.json.get("password") if request.is_json else None)
    if not all([phone, password]):
        return jsonify({"status": "error", "detail": "phone/password missing"}), 400

    # 🔹 Helper: Convert any structure safely into JSON (bytes→base64, "_"→type)
    def make_json_safe(obj):
        if isinstance(obj, dict):
            new_dict = {}
            for k, v in obj.items():
                key = "type" if k == "_" else k
                new_dict[key] = make_json_safe(v)
            return new_dict
        elif isinstance(obj, list):
            return [make_json_safe(v) for v in obj]
        elif isinstance(obj, bytes):
            return base64.b64encode(obj).decode("utf-8")
        elif isinstance(obj, datetime):
            return obj.isoformat()
        else:
            return obj

    async def do_verify_password():
        client = await get_client(phone)
        await client.connect()
        try:
            # 🔹 Already authorized
            if await client.is_user_authorized():
                me = await client.get_me()
                user_data = make_json_safe(me.to_dict())
                await client.disconnect()
                return {"status": "already_authorized", "user": user_data}

            # 🔹 Sign in with password (2FA)
            await client.sign_in(password=password)
            await client.send_message("me", "✅ 2FA password verified successfully!")
            await save_session(phone, client)

            me = await client.get_me()
            user_data = make_json_safe(me.to_dict())

            await client.disconnect()
            return {"status": "authorized_by_password", "user": user_data}

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




@app.route("/dialogs", methods=["GET"])
def get_dialogs():
    """
    Telegram থেকে সমস্ত dialogs (chats, groups, channels)
    পুরো detailed structured JSON format এ ফেরত দেয়।
    Example:
      /dialogs?phone=+8801731979364
    """
    phone = request.args.get("phone")
    if not phone:
        return jsonify({"status": "error", "detail": "phone missing"}), 400

    async def do_get_dialogs():
        from telethon.tl.functions.channels import GetFullChannelRequest
        from telethon.tl.functions.messages import GetFullChatRequest

        try:
            client = await get_client(phone)
            if not client.is_connected():
                await client.connect()

            # ✅ authorized কিনা check
            if not await client.is_user_authorized():
                await client.disconnect()
                return {"status": "error", "detail": "not authorized"}

            dialogs = []

            async for d in client.iter_dialogs(limit=50):
                e = d.entity
                msg = d.message

                # 🔹 Last message info
                last_msg = {
                    "id": getattr(msg, "id", None),
                    "text": getattr(msg, "message", None),
                    "date": getattr(msg, "date", None).isoformat() if getattr(msg, "date", None) else None,
                    "sender_id": getattr(getattr(msg, "from_id", None), "user_id", None),
                    "reply_to": getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None),
                    "media": str(type(getattr(msg, "media", None)).__name__) if getattr(msg, "media", None) else None,
                } if msg else None

                # 🔹 Channel/Group participant count
                participants_count = None
                about = None
                dc_id = getattr(getattr(e, "photo", None), "dc_id", None)

                try:
                    if d.is_channel:
                        full = await client(GetFullChannelRequest(e))
                        participants_count = getattr(full.full_chat, "participants_count", None)
                        about = getattr(full.full_chat, "about", None)
                    elif d.is_group:
                        full = await client(GetFullChatRequest(e.id))
                        participants_count = getattr(full.full_chat, "participants_count", None)
                        about = getattr(full.full_chat, "about", None)
                except Exception:
                    pass

                # 🔹 Build dialog info
                dialog_info = {
                    "id": getattr(e, "id", None),
                    "name": getattr(e, "title", getattr(e, "username", str(e))),
                    "title": getattr(e, "title", None),
                    "first_name": getattr(e, "first_name", None),
                    "last_name": getattr(e, "last_name", None),
                    "username": getattr(e, "username", None),
                    "phone": getattr(e, "phone", None),
                    "about": about,
                    "access_hash": getattr(e, "access_hash", None),
                    "dc_id": dc_id,
                    "is_user": d.is_user,
                    "is_group": d.is_group,
                    "is_channel": d.is_channel,
                    "unread_count": d.unread_count,
                    "pinned": getattr(d, "pinned", False),
                    "verified": getattr(e, "verified", False),
                    "restricted": getattr(e, "restricted", False),
                    "bot": getattr(e, "bot", False),
                    "fake": getattr(e, "fake", False),
                    "scam": getattr(e, "scam", False),
                    "premium": getattr(e, "premium", False),
                    "participants_count": participants_count,
                    "has_photo": bool(getattr(e, "photo", None)),
                    "last_message": last_msg,
                }

                dialogs.append(dialog_info)

            await client.disconnect()
            return {
                "status": "ok",
                "count": len(dialogs),
                "dialogs": dialogs
            }

        except Exception as e:
            import traceback
            print("❌ Exception in /dialogs:\n", traceback.format_exc())
            return {"status": "error", "detail": str(e)}

    result = asyncio.run(do_get_dialogs())

    # ✅ Safe print (no KeyError possible)
    if result.get("status") == "ok":
        print(f"✅ Dialogs fetched successfully: {result.get('count', 0)} items.")
    else:
        print(f"⚠️ Dialog fetch error: {result.get('detail', 'unknown error')}")

    return jsonify(result)





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





@app.route("/messages", methods=["GET"])
def get_messages():
    """
    ✅ Get Telegram chat messages (with chat_id + optional access_hash)
    Example:
      /messages?phone=+8801731979364&chat_id=9181472862369316499&access_hash=89021312341
    """
    phone = request.args.get("phone")
    chat_id = request.args.get("chat_id")
    access_hash = request.args.get("access_hash")  # optional
    limit = int(request.args.get("limit", 30))

    if not phone or not chat_id:
        return jsonify({"status": "error", "detail": "phone/chat_id missing"}), 400

    async def do_get_messages():
        from telethon.tl.types import InputPeerUser, InputPeerChannel, InputPeerChat

        client = await get_client(phone)
        await client.connect()

        if not await client.is_user_authorized():
            await client.disconnect()
            return {"status": "error", "detail": "not authorized"}

        try:
            chat_id_int = int(chat_id)

            # ✅ Step 1: Try resolving entity using access_hash (if provided)
            entity = None
            if access_hash:
                try:
                    # Try as User
                    entity = InputPeerUser(chat_id_int, int(access_hash))
                except Exception:
                    try:
                        # Try as Channel
                        entity = InputPeerChannel(chat_id_int, int(access_hash))
                    except Exception:
                        try:
                            # Try as Group
                            entity = InputPeerChat(chat_id_int)
                        except Exception:
                            entity = None

            # ✅ Step 2: Fallback if entity still not found
            if entity is None:
                try:
                    entity = await client.get_entity(chat_id_int)
                except Exception as e:
                    await client.disconnect()
                    return {
                        "status": "error",
                        "detail": f"Could not resolve entity: {str(e)}"
                    }

            # ✅ Step 3: Fetch messages
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
            import traceback
            print("❌ Exception in /messages:\n", traceback.format_exc())
            await client.disconnect()
            return {"status": "error", "detail": str(e)}

    # 🔹 Run async
    result = asyncio.run(do_get_messages())
    print("✅ Messages result:", result)
    return jsonify(result)

# ==================================
# 🏁 RUN SERVER
# ==================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
