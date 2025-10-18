
import os
import asyncio
import threading
import uuid
import base64
import time
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, redirect, send_file
from flask_sock import Sock
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import (
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
    PhoneNumberInvalidError,
)
from pymongo import MongoClient
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



from telethon import events
from telethon.tl import functions, types
from telethon.tl.types import (
    InputPeerUser, InputPeerChannel, InputPeerChat,
    UpdateUserTyping, UpdateChatUserTyping, UpdateChannelUserTyping
)
import asyncio, threading, json, time
from datetime import datetime, timezone

# --------------------------------------
# SMALL HELPER: map Telegram typing action → human name
# --------------------------------------
def _typing_action_name(act):
    # examples: types.SendMessageTypingAction, SendMessageUploadPhotoAction, ...
    n = type(act).__name__
    return (
        "typing" if "TypingAction" in n else
        "record_video" if "RecordVideo" in n else
        "upload_video" if "UploadVideo" in n else
        "record_voice" if "RecordAudio" in n or "RecordRound" in n else
        "upload_voice" if "UploadAudio" in n else
        "upload_photo" if "UploadPhoto" in n else
        "upload_document" if "UploadDocument" in n else
        "choose_sticker" if "ChooseSticker" in n else
        "game" if "GamePlay" in n else
        "geo" if "GeoLocation" in n else
        "contact" if "Contact" in n else
        "emoji" if "EmojiInteraction" in n else
        "cancel" if "CancelAction" in n else
        n
    )







@sock.route('/chat_ws')
def chat_ws(ws):
    """
    🌐 Real-time Telegram Chat WebSocket (Text + Image + Voice + Video + Reply)
    ----------------------------------------------------------
    Client first sends init:
      {"phone":"8801731979364","chat_id":"9181472862369316499","access_hash":"-1478755446656361465"}

    Supported actions:
      {"action":"send","text":"Hi!"}
      {"action":"send","file_name":"photo.jpg","file_base64":"...","text":"optional caption"}
      {"action":"send","file_name":"voice.ogg","file_base64":"...","mime_type":"audio/ogg"}
      {"action":"send","file_name":"video.mp4","file_base64":"...","mime_type":"video/mp4","text":"optional"}
      {"action":"send","text":"Reply here","reply_to":12345}
      {"action":"typing_start"}
      {"action":"typing_stop"}
      {"action":"ping"}
      {"action":"stop"}
    ----------------------------------------------------------
    """

    import json, time, base64, threading, asyncio
    from datetime import datetime, timezone
    from io import BytesIO
    from telethon import events, functions, types
    from telethon.tl.types import (
        InputPeerUser, InputPeerChannel, InputPeerChat,
        UpdateUserTyping, UpdateChatUserTyping, UpdateChannelUserTyping
    )

    print("🔗 [chat_ws] connected")
    tg_client = None
    phone = None
    chat_id = None
    loop = None

    # --- typing tracker ---
    typing_tracker = {}
    tracker_lock = threading.Lock()
    TYPING_TTL = 6.0

    def typing_cleaner():
        while True:
            time.sleep(2.0)
            now = time.time()
            expired = []
            with tracker_lock:
                for key, last in list(typing_tracker.items()):
                    if now - last > TYPING_TTL:
                        expired.append(key)
                        typing_tracker.pop(key, None)
            for (cid, uid) in expired:
                try:
                    ws.send(json.dumps({
                        "action": "typing_stopped",
                        "phone": phone,
                        "chat_id": str(cid),
                        "sender_id": uid,
                        "date": datetime.now(timezone.utc).isoformat()
                    }))
                except:
                    pass

    threading.Thread(target=typing_cleaner, daemon=True).start()

    try:
        # =========== 1️⃣ INIT ===========
        init_msg = ws.receive()
        if not init_msg:
            return
        init = json.loads(init_msg)
        phone = init.get("phone")
        chat_id = init.get("chat_id")
        access_hash = init.get("access_hash")
        if not all([phone, chat_id]):
            ws.send(json.dumps({"status": "error", "detail": "phone/chat_id missing"}))
            return

        # =========== 2️⃣ Listener ===========
        async def run_listener():
            nonlocal tg_client, loop
            tg_client = await get_client(phone)
            loop = asyncio.get_event_loop()
            await tg_client.connect()
            if not await tg_client.is_user_authorized():
                ws.send(json.dumps({"status": "error", "detail": "not authorized"}))
                await tg_client.disconnect()
                return

            ws.send(json.dumps({"status": "listening", "chat_id": str(chat_id)}))
            print(f"👂 Listening for chat {chat_id} ({phone})")

            @tg_client.on(events.NewMessage(chats=int(chat_id)))
            async def on_new_msg(event):
                try:
                    sender = await event.get_sender()
                    ws.send(json.dumps({
                        "action": "new_message",
                        "phone": phone,
                        "chat_id": str(chat_id),
                        "id": event.id,
                        "text": event.raw_text,
                        "sender_id": getattr(sender, "id", None),
                        "sender_name": getattr(sender, "first_name", None),
                        "date": event.date.isoformat() if event.date else None
                    }))
                except Exception as e:
                    print(f"⚠️ new_message error: {e}")

            @tg_client.on(events.Raw)
            async def on_raw(update):
                try:
                    upd_chat_id, user_id = None, None
                    if isinstance(update, UpdateUserTyping):
                        upd_chat_id = int(update.user_id)
                        user_id = int(update.user_id)
                    elif isinstance(update, UpdateChatUserTyping):
                        upd_chat_id = int(update.chat_id)
                        user_id = int(update.user_id)
                    elif isinstance(update, UpdateChannelUserTyping):
                        upd_chat_id = int(update.channel_id)
                        user_id = int(update.user_id)
                    if upd_chat_id and int(upd_chat_id) == int(chat_id):
                        with tracker_lock:
                            typing_tracker[(upd_chat_id, user_id)] = time.time()
                        ws.send(json.dumps({
                            "action": "typing",
                            "phone": phone,
                            "chat_id": str(upd_chat_id),
                            "sender_id": user_id,
                            "typing": True,
                            "date": datetime.now(timezone.utc).isoformat()
                        }))
                except Exception as e:
                    print(f"⚠️ typing event error: {e}")

            await tg_client.run_until_disconnected()

        threading.Thread(target=lambda: asyncio.run(run_listener()), daemon=True).start()

        async def resolve_entity():
            try:
                if access_hash:
                    try:
                        return InputPeerUser(int(chat_id), int(access_hash))
                    except:
                        try:
                            return InputPeerChannel(int(chat_id), int(access_hash))
                        except:
                            return InputPeerChat(int(chat_id))
                else:
                    return await tg_client.get_entity(int(chat_id))
            except:
                return InputPeerChat(int(chat_id))

        # =========== 3️⃣ WS LOOP ===========
        while True:
            recv = ws.receive()
            if recv is None:
                break
            data = json.loads(recv)
            action = data.get("action")

            if action == "stop":
                break
            elif action == "ping":
                ws.send(json.dumps({"status": "pong"}))

            elif action in ("typing_start", "typing_stop"):
                async def do_typing(act=action):
                    try:
                        peer = await resolve_entity()
                        req = (types.SendMessageTypingAction()
                               if act == "typing_start"
                               else types.SendMessageCancelAction())
                        await tg_client(functions.messages.SetTypingRequest(peer=peer, action=req))
                        ws.send(json.dumps({"status": f"{act}_ok"}))
                    except Exception as e:
                        ws.send(json.dumps({"status": "error", "detail": str(e)}))
                asyncio.run_coroutine_threadsafe(do_typing(), loop)

            elif action == "send":
                text = data.get("text")
                file_b64 = data.get("file_base64")
                file_name = data.get("file_name", "file.bin")
                mime_type = data.get("mime_type", "")
                reply_to_raw = data.get("reply_to") or data.get("reply_to_msg_id")
                try:
                    reply_to_id = int(reply_to_raw) if reply_to_raw else None
                except:
                    reply_to_id = None

                async def do_send(file_b64=file_b64, text=text,
                                 file_name=file_name, mime_type=mime_type,
                                 reply_to_id=reply_to_id):
                    try:
                        if not await tg_client.is_user_authorized():
                            ws.send(json.dumps({"status": "error", "detail": "not authorized"}))
                            return
                        peer = await resolve_entity()

                        # ✅ Text message only
                        if text and not file_b64:
                            msg_obj = await tg_client.send_message(peer, text, reply_to=reply_to_id)
                            ws.send(json.dumps({
                                "status": "sent_text",
                                "text": text,
                                "chat_id": str(chat_id),
                                "id": getattr(msg_obj, "id", None),
                                "reply_to": reply_to_id
                            }))
                            return

                        # ✅ File message (Image/Voice/Video)
                        if file_b64:
                            if isinstance(file_b64, str) and file_b64.startswith("data:"):
                                file_b64 = file_b64.split(",", 1)[1]
                            try:
                                file_bytes = base64.b64decode(file_b64 + "==")
                            except Exception as e:
                                ws.send(json.dumps({"status": "error", "detail": f"base64 decode failed: {e}"}))
                                return
                            bio = BytesIO(file_bytes)
                            bio.name = file_name

                            def progress(sent, total):
                                try:
                                    ws.send(json.dumps({
                                        "action": "upload_progress",
                                        "progress": round((sent / max(1, total)) * 100.0, 1)
                                    }))
                                except:
                                    pass

                            name = (file_name or "").lower()
                            is_voice = (mime_type or "").startswith("audio/ogg") or name.endswith(".ogg")
                            is_video = (mime_type or "").startswith("video/") or name.endswith((".mp4", ".mkv", ".mov"))
                            is_image = (mime_type or "").startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))

                            if is_voice:
                                msg_obj = await tg_client.send_file(peer, bio, caption=text or "",
                                                                    voice_note=True, reply_to=reply_to_id,
                                                                    progress_callback=progress)
                                ws.send(json.dumps({
                                    "status": "sent_voice",
                                    "file_name": file_name,
                                    "id": getattr(msg_obj, "id", None)
                                }))

                            elif is_video:
                                msg_obj = await tg_client.send_file(peer, bio, caption=text or "",
                                                                    supports_streaming=True, reply_to=reply_to_id,
                                                                    progress_callback=progress)
                                ws.send(json.dumps({
                                    "status": "sent_video",
                                    "file_name": file_name,
                                    "id": getattr(msg_obj, "id", None)
                                }))

                            else:
                                msg_obj = await tg_client.send_file(peer, bio, caption=text or "",
                                                                    reply_to=reply_to_id,
                                                                    progress_callback=progress)
                                ws.send(json.dumps({
                                    "status": "sent_file",
                                    "file_name": file_name,
                                    "id": getattr(msg_obj, "id", None)
                                }))
                        else:
                            ws.send(json.dumps({"status": "error", "detail": "text or file required"}))

                    except Exception as e:
                        ws.send(json.dumps({"status": "error", "detail": str(e)}))

                asyncio.run_coroutine_threadsafe(do_send(), loop)

            else:
                ws.send(json.dumps({"status": "error", "detail": "unknown action"}))

    except Exception as e:
        print(f"⚠️ [chat_ws] Exception: {e}")
    finally:
        if tg_client:
            try:
                asyncio.run(tg_client.disconnect())
            except:
                pass
        print("❌ [chat_ws] disconnected")


#################################################################################

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
# 🏁 QR code Scanner
# ==================================




import uuid, asyncio, threading, base64
from datetime import datetime, timezone, timedelta
from flask import jsonify, request
from telethon import TelegramClient



# ✅ Shared global cache
QR_CACHE = {}
QR_COLLECTION = db.qr_sessions

# ✅ 1️⃣ Generate Telegram QR Login Link



@app.route("/login_qr_link", methods=["POST"])
def login_qr_link():
    """
    ✅ FIXED VERSION
    Works on Python 3.12 + Flask + Telethon 1.36+
    """
    import uuid
    import concurrent.futures
    from datetime import datetime, timezone

    try:
        auth_id = str(uuid.uuid4())

        async def do_qr_create():
            # সবকিছু asyncio loop-এর ভিতরে চলবে
            client = TelegramClient(f"qr_{auth_id}", API_ID, API_HASH)
            await client.connect()

            if await client.is_user_authorized():
                me = await client.get_me()
                await client.disconnect()
                return {"status": "already_authorized", "user": me.to_dict()}

            qr = await client.qr_login()

            # Cache & DB update
            QR_CACHE[auth_id] = {"client": client, "qr": qr}
            QR_COLLECTION.update_one(
                {"auth_id": auth_id},
                {"$set": {
                    "auth_id": auth_id,
                    "qr_url": qr.url,
                    "status": "pending",
                    "created_at": datetime.now(timezone.utc)
                }},
                upsert=True
            )

            print(f"✅ QR created: {auth_id}")
            print(f"🔗 {qr.url}")

            # Background watcher (detect approve)
            asyncio.create_task(wait_for_qr(auth_id))
            return {"status": "ok", "auth_id": auth_id, "qr_url": qr.url}

        # 🔹 সব async কাজ global loop-এ পাঠাও (thread-safe ভাবে)
        future = asyncio.run_coroutine_threadsafe(do_qr_create(), loop)
        result = future.result(timeout=15)

        return jsonify(result)

    except concurrent.futures.TimeoutError:
        return jsonify({"status": "error", "detail": "QR creation timeout"}), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "detail": str(e)}), 500



















# ✅ 2️⃣ Wait for QR Authorization
async def wait_for_qr(auth_id: str):
    """
    🔁 Fixed version: handles delayed QR approval properly.
    """
    import traceback, base64, asyncio
    try:
        cache = QR_CACHE.get(auth_id)
        if not cache:
            print(f"⚠️ No cache found for {auth_id}")
            return

        client = cache["client"]
        qr = cache["qr"]

        if not client.is_connected():
            await client.connect()

        print(f"⌛ [wait_for_qr] Waiting for Telegram auth for {auth_id}")

        # 🔹 Wait until user scans QR (keep alive for long polling)
        user = None
        for attempt in range(12):  # wait up to 12 * 50s = 10 minutes
            try:
                user = await asyncio.wait_for(qr.wait(), timeout=50)
                if user:
                    break
            except asyncio.TimeoutError:
                # keep alive check
                if not client.is_connected():
                    await client.connect()
                print(f"⏳ waiting... ({attempt+1}/12)")
                continue

        if not user:
            print(f"⏰ Timeout: No authorization for {auth_id}")
            QR_COLLECTION.update_one(
                {"auth_id": auth_id},
                {"$set": {"status": "expired", "updated_at": datetime.now(timezone.utc)}}
            )
            await client.disconnect()
            return

        # ✅ Authorized user
        phone = getattr(user, "phone", None) or f"qr_{auth_id[:8]}"
        print(f"✅ Telegram QR Authorized → {user.first_name} ({phone})")

        await save_session(phone, client)

        # --- Make JSON-safe ---
        def make_json_safe(obj):
            if isinstance(obj, dict):
                return {k: make_json_safe(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [make_json_safe(v) for v in obj]
            elif isinstance(obj, bytes):
                return base64.b64encode(obj).decode("utf-8")
            elif isinstance(obj, datetime):
                return obj.isoformat()
            else:
                return obj

        user_data = make_json_safe(user.to_dict())

        # ✅ MongoDB update
        QR_COLLECTION.update_one(
            {"auth_id": auth_id},
            {"$set": {
                "status": "authorized",
                "user": user_data,
                "updated_at": datetime.now(timezone.utc)
            }},
            upsert=True
        )

        print(f"💾 MongoDB updated → authorized for {auth_id}")
        await client.disconnect()

    except Exception as e:
        print(f"❌ Fatal in wait_for_qr: {e}")
        print(traceback.format_exc())
        try:
            await client.disconnect()
        except:
            pass



















# ✅ 3️⃣ Check QR Login Status
@app.route("/login_qr_status", methods=["GET"])
def login_qr_status():
    """
    Check Telegram QR login status by auth_id
    """
    auth_id = request.args.get("auth_id")
    if not auth_id:
        return jsonify({"status": "error", "detail": "auth_id missing"}), 400

    doc = QR_COLLECTION.find_one({"auth_id": auth_id})
    if not doc:
        return jsonify({"status": "not_found"}), 404

    created_at = doc.get("created_at")
    if created_at:
        now_utc = datetime.now(timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if now_utc - created_at > timedelta(minutes=15):
            if doc.get("status") not in ("authorized", "error"):
                QR_COLLECTION.update_one(
                    {"auth_id": auth_id},
                    {"$set": {"status": "expired", "updated_at": now_utc}}
                )
                doc["status"] = "expired"

    # Authorized → full user data return
    if doc.get("status") == "authorized":
        return jsonify({"status": "authorized", "user": doc.get("user", {})})

    return jsonify({
        "auth_id": auth_id,
        "qr_url": doc.get("qr_url"),
        "status": doc.get("status", "pending")
    })


# ✅ 4️⃣ Background Cleaner
def qr_cleaner():
    """Periodically cleans old QR entries"""
    while True:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=20)
            result = QR_COLLECTION.delete_many({
                "status": {"$in": ["authorized", "error", "expired"]},
                "created_at": {"$lt": cutoff}
            })
            if result.deleted_count:
                print(f"🧹 Cleaned {result.deleted_count} old QR entries")
        except Exception as e:
            print(f"⚠️ Cleaner error: {e}")
        time.sleep(300)

threading.Thread(target=qr_cleaner, daemon=True).start()















def qr_cleaner():
    while True:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
            result = QR_COLLECTION.delete_many({
                "status": {"$in": ["authorized", "error"]},
                "created_at": {"$lt": cutoff}
            })
            if result.deleted_count:
                print(f"🧹 Cleaned {result.deleted_count} old QR sessions")
        except Exception as e:
            print(f"⚠️ Cleaner error: {e}")
        time.sleep(300)  # every 5 min

# ✅ Global asyncio loop (shared for all threads)
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# ✅ Start loop in background thread before Flask starts
def run_loop_forever():
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=run_loop_forever, daemon=True).start()




# ==================================
# 🏁 RUN SERVER
# ==================================
if __name__ == "__main__":
    threading.Thread(target=loop.run_forever, daemon=True).start()
    app.run(host="0.0.0.0", port=8080, debug=False)
