
import os
import asyncio
from urllib.parse import urlencode, urljoin

from flask import Flask, request, jsonify, redirect, send_file, has_request_context
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






# @sock.route('/chat_ws')
# def chat_ws(ws):
#     """
#     🌐 Real-time Telegram Chat WebSocket (Text + Image + Voice + Video + Reply)
#     ----------------------------------------------------------
#     Client first sends init:
#       {"phone":"8801731979364","chat_id":"9181472862369316499","access_hash":"-1478755446656361465"}
#
#     Supported actions:
#       {"action":"send","text":"Hi!"}
#       {"action":"send","file_name":"photo.jpg","file_base64":"...","text":"optional caption"}
#       {"action":"send","file_name":"voice.ogg","file_base64":"...","mime_type":"audio/ogg"}
#       {"action":"send","file_name":"video.mp4","file_base64":"...","mime_type":"video/mp4","text":"optional"}
#       {"action":"send","text":"Reply here","reply_to":12345}
#       {"action":"typing_start"}
#       {"action":"typing_stop"}
#       {"action":"ping"}
#       {"action":"stop"}
#     ----------------------------------------------------------
#     """
#
#     import json, time, base64, threading, asyncio
#     from datetime import datetime, timezone
#     from io import BytesIO
#     from telethon import events, functions, types
#     from telethon.tl.types import (
#         InputPeerUser, InputPeerChannel, InputPeerChat,
#         UpdateUserTyping, UpdateChatUserTyping, UpdateChannelUserTyping
#     )
#
#     print("🔗 [chat_ws] connected")
#     tg_client = None
#     phone = None
#     chat_id = None
#     loop = None
#
#     # --- typing tracker ---
#     typing_tracker = {}
#     tracker_lock = threading.Lock()
#     TYPING_TTL = 6.0
#
#     def typing_cleaner():
#         while True:
#             time.sleep(2.0)
#             now = time.time()
#             expired = []
#             with tracker_lock:
#                 for key, last in list(typing_tracker.items()):
#                     if now - last > TYPING_TTL:
#                         expired.append(key)
#                         typing_tracker.pop(key, None)
#             for (cid, uid) in expired:
#                 try:
#                     ws.send(json.dumps({
#                         "action": "typing_stopped",
#                         "phone": phone,
#                         "chat_id": str(cid),
#                         "sender_id": uid,
#                         "date": datetime.now(timezone.utc).isoformat()
#                     }))
#                 except:
#                     pass
#
#     threading.Thread(target=typing_cleaner, daemon=True).start()
#
#     try:
#         # =========== 1️⃣ INIT ===========
#         init_msg = ws.receive()
#         if not init_msg:
#             return
#         init = json.loads(init_msg)
#         phone = init.get("phone")
#         chat_id = init.get("chat_id")
#         access_hash = init.get("access_hash")
#         if not all([phone, chat_id]):
#             ws.send(json.dumps({"status": "error", "detail": "phone/chat_id missing"}))
#             return
#
#         # =========== 2️⃣ Listener ===========
#         async def run_listener():
#             nonlocal tg_client, loop
#             tg_client = await get_client(phone)
#             loop = asyncio.get_event_loop()
#             await tg_client.connect()
#             if not await tg_client.is_user_authorized():
#                 ws.send(json.dumps({"status": "error", "detail": "not authorized"}))
#                 await tg_client.disconnect()
#                 return
#
#             ws.send(json.dumps({"status": "listening", "chat_id": str(chat_id)}))
#             print(f"👂 Listening for chat {chat_id} ({phone})")
#
#             @tg_client.on(events.NewMessage(chats=int(chat_id)))
#             async def on_new_msg(event):
#                 try:
#                     sender = await event.get_sender()
#                     ws.send(json.dumps({
#                         "action": "new_message",
#                         "phone": phone,
#                         "chat_id": str(chat_id),
#                         "id": event.id,
#                         "text": event.raw_text,
#                         "sender_id": getattr(sender, "id", None),
#                         "sender_name": getattr(sender, "first_name", None),
#                         "date": event.date.isoformat() if event.date else None
#                     }))
#                 except Exception as e:
#                     print(f"⚠️ new_message error: {e}")
#
#             @tg_client.on(events.Raw)
#             async def on_raw(update):
#                 try:
#                     upd_chat_id, user_id = None, None
#                     if isinstance(update, UpdateUserTyping):
#                         upd_chat_id = int(update.user_id)
#                         user_id = int(update.user_id)
#                     elif isinstance(update, UpdateChatUserTyping):
#                         upd_chat_id = int(update.chat_id)
#                         user_id = int(update.user_id)
#                     elif isinstance(update, UpdateChannelUserTyping):
#                         upd_chat_id = int(update.channel_id)
#                         user_id = int(update.user_id)
#                     if upd_chat_id and int(upd_chat_id) == int(chat_id):
#                         with tracker_lock:
#                             typing_tracker[(upd_chat_id, user_id)] = time.time()
#                         ws.send(json.dumps({
#                             "action": "typing",
#                             "phone": phone,
#                             "chat_id": str(upd_chat_id),
#                             "sender_id": user_id,
#                             "typing": True,
#                             "date": datetime.now(timezone.utc).isoformat()
#                         }))
#                 except Exception as e:
#                     print(f"⚠️ typing event error: {e}")
#
#             await tg_client.run_until_disconnected()
#
#         threading.Thread(target=lambda: asyncio.run(run_listener()), daemon=True).start()
#
#         async def resolve_entity():
#             try:
#                 if access_hash:
#                     try:
#                         return InputPeerUser(int(chat_id), int(access_hash))
#                     except:
#                         try:
#                             return InputPeerChannel(int(chat_id), int(access_hash))
#                         except:
#                             return InputPeerChat(int(chat_id))
#                 else:
#                     return await tg_client.get_entity(int(chat_id))
#             except:
#                 return InputPeerChat(int(chat_id))
#
#         # =========== 3️⃣ WS LOOP ===========
#         while True:
#             recv = ws.receive()
#             if recv is None:
#                 break
#             data = json.loads(recv)
#             action = data.get("action")
#
#             if action == "stop":
#                 break
#             elif action == "ping":
#                 ws.send(json.dumps({"status": "pong"}))
#
#             elif action in ("typing_start", "typing_stop"):
#                 async def do_typing(act=action):
#                     try:
#                         peer = await resolve_entity()
#                         req = (types.SendMessageTypingAction()
#                                if act == "typing_start"
#                                else types.SendMessageCancelAction())
#                         await tg_client(functions.messages.SetTypingRequest(peer=peer, action=req))
#                         ws.send(json.dumps({"status": f"{act}_ok"}))
#                     except Exception as e:
#                         ws.send(json.dumps({"status": "error", "detail": str(e)}))
#                 asyncio.run_coroutine_threadsafe(do_typing(), loop)
#
#             elif action == "send":
#                 text = data.get("text")
#                 file_b64 = data.get("file_base64")
#                 file_name = data.get("file_name", "file.bin")
#                 mime_type = data.get("mime_type", "")
#                 reply_to_raw = data.get("reply_to") or data.get("reply_to_msg_id")
#                 try:
#                     reply_to_id = int(reply_to_raw) if reply_to_raw else None
#                 except:
#                     reply_to_id = None
#
#                 async def do_send(file_b64=file_b64, text=text,
#                                  file_name=file_name, mime_type=mime_type,
#                                  reply_to_id=reply_to_id):
#                     try:
#                         if not await tg_client.is_user_authorized():
#                             ws.send(json.dumps({"status": "error", "detail": "not authorized"}))
#                             return
#                         peer = await resolve_entity()
#
#                         # ✅ Text message only
#                         if text and not file_b64:
#                             msg_obj = await tg_client.send_message(peer, text, reply_to=reply_to_id)
#                             ws.send(json.dumps({
#                                 "status": "sent_text",
#                                 "text": text,
#                                 "chat_id": str(chat_id),
#                                 "id": getattr(msg_obj, "id", None),
#                                 "reply_to": reply_to_id
#                             }))
#                             return
#
#                         # ✅ File message (Image/Voice/Video)
#                         if file_b64:
#                             if isinstance(file_b64, str) and file_b64.startswith("data:"):
#                                 file_b64 = file_b64.split(",", 1)[1]
#                             try:
#                                 file_bytes = base64.b64decode(file_b64 + "==")
#                             except Exception as e:
#                                 ws.send(json.dumps({"status": "error", "detail": f"base64 decode failed: {e}"}))
#                                 return
#                             bio = BytesIO(file_bytes)
#                             bio.name = file_name
#
#                             def progress(sent, total):
#                                 try:
#                                     ws.send(json.dumps({
#                                         "action": "upload_progress",
#                                         "progress": round((sent / max(1, total)) * 100.0, 1)
#                                     }))
#                                 except:
#                                     pass
#
#                             name = (file_name or "").lower()
#                             is_voice = (mime_type or "").startswith("audio/ogg") or name.endswith(".ogg")
#                             is_video = (mime_type or "").startswith("video/") or name.endswith((".mp4", ".mkv", ".mov"))
#                             is_image = (mime_type or "").startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))
#
#                             if is_voice:
#                                 msg_obj = await tg_client.send_file(peer, bio, caption=text or "",
#                                                                     voice_note=True, reply_to=reply_to_id,
#                                                                     progress_callback=progress)
#                                 ws.send(json.dumps({
#                                     "status": "sent_voice",
#                                     "file_name": file_name,
#                                     "id": getattr(msg_obj, "id", None)
#                                 }))
#
#                             elif is_video:
#                                 msg_obj = await tg_client.send_file(peer, bio, caption=text or "",
#                                                                     supports_streaming=True, reply_to=reply_to_id,
#                                                                     progress_callback=progress)
#                                 ws.send(json.dumps({
#                                     "status": "sent_video",
#                                     "file_name": file_name,
#                                     "id": getattr(msg_obj, "id", None)
#                                 }))
#
#                             else:
#                                 msg_obj = await tg_client.send_file(peer, bio, caption=text or "",
#                                                                     reply_to=reply_to_id,
#                                                                     progress_callback=progress)
#                                 ws.send(json.dumps({
#                                     "status": "sent_file",
#                                     "file_name": file_name,
#                                     "id": getattr(msg_obj, "id", None)
#                                 }))
#                         else:
#                             ws.send(json.dumps({"status": "error", "detail": "text or file required"}))
#
#                     except Exception as e:
#                         ws.send(json.dumps({"status": "error", "detail": str(e)}))
#
#                 asyncio.run_coroutine_threadsafe(do_send(), loop)
#
#             else:
#                 ws.send(json.dumps({"status": "error", "detail": "unknown action"}))
#
#     except Exception as e:
#         print(f"⚠️ [chat_ws] Exception: {e}")
#     finally:
#         if tg_client:
#             try:
#                 asyncio.run(tg_client.disconnect())
#             except:
#                 pass
#         print("❌ [chat_ws] disconnected")












# ---------- FULL: /chat_ws (thread-safe send + heartbeat + mongo-first) ----------
@sock.route('/chat_ws')
def chat_ws(ws):
    """
    Real-time Telegram Chat WS (text/media/reply/typing + call-log)
    Improvements:
      - Thread-safe ws.send via a global lock
      - Server heartbeat every 25s to prevent idle timeouts
      - Graceful handling of client-close (1000) without crashing
      - Mongo-first: incoming saved before emit; outgoing saved before send
    API inputs/outputs unchanged.
    """
    import json, time, threading, asyncio, base64
    from io import BytesIO
    from datetime import datetime, timezone
    from telethon import events, functions, types
    from telethon.tl.types import (
        InputPeerUser, InputPeerChannel, InputPeerChat,
        UpdateUserTyping, UpdateChatUserTyping, UpdateChannelUserTyping,
        UpdateNewMessage, UpdateNewChannelMessage,
        MessageService, MessageActionPhoneCall,
        PeerUser, PeerChat, PeerChannel
    )
    from gridfs import GridFS
    from bson.objectid import ObjectId

    # --- locals/state ---
    fs = GridFS(db, collection="fs")
    MSG_COL = db.messages
    try:
        MSG_COL.create_index([("phone", 1), ("chat_id", 1), ("msg_id", 1)],
                             unique=True, sparse=True, name="uniq_msg")
    except Exception:
        pass

    print("🔗 [chat_ws] connected")
    tg_client = None
    tg_loop = None
    phone = None
    chat_id = None
    access_hash = None

    # --- send guard (thread-safe) + liveness ---
    ws_send_lock = threading.Lock()
    alive = True

    def _now():
        return datetime.now(timezone.utc).isoformat()

    def ws_send(payload):
        """Thread-safe ws.send (str or dict). Marks dead on failure."""
        nonlocal alive
        if not alive:
            return
        try:
            data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
            with ws_send_lock:
                ws.send(data)
        except Exception as e:
            # Most common: "Connection closed: 1000"
            alive = False
            try:
                print(f"⚠️ ws_send failed: {e}")
            except:
                pass

    def safe_receive():
        """Receive but swallow normal close into None."""
        try:
            return ws.receive()
        except Exception as e:
            # Treat any "Connection closed: 1000" (or transport closed) as None
            if "Connection closed" in str(e) or "closed" in str(e).lower():
                return None
            raise

    # --- helpers ---
    def _peer_id(pid):
        if isinstance(pid, PeerUser): return pid.user_id
        if isinstance(pid, PeerChat): return pid.chat_id
        if isinstance(pid, PeerChannel): return pid.channel_id
        return None

    def _call_status_from_action(act, is_out):
        reason = type(getattr(act, 'reason', None)).__name__ if getattr(act, 'reason', None) else None
        dur = getattr(act, 'duration', None)
        video = bool(getattr(act, 'video', False))
        if reason == 'PhoneCallDiscardReasonMissed': status = 'missed'
        elif reason == 'PhoneCallDiscardReasonBusy': status = 'busy'
        elif reason == 'PhoneCallDiscardReasonHangup': status = 'canceled'
        elif reason == 'PhoneCallDiscardReasonDisconnect': status = 'ended'
        elif dur: status = 'ended'
        else: status = 'unknown'
        return {"status": status, "direction": "outgoing" if is_out else "incoming",
                "duration": dur, "is_video": video, "raw_reason": reason}

    # --- typing tracker (sends from server) ---
    typing_tracker = {}
    tracker_lock = threading.Lock()
    TYPING_TTL = 6.0

    def typing_cleaner():
        while alive:
            time.sleep(2.0)
            now = time.time()
            expired = []
            with tracker_lock:
                for key, last in list(typing_tracker.items()):
                    if now - last > TYPING_TTL:
                        expired.append(key)
                        typing_tracker.pop(key, None)
            for (cid, uid) in expired:
                ws_send({
                    "action": "typing_stopped",
                    "phone": phone,
                    "chat_id": str(cid),
                    "sender_id": uid,
                    "date": _now()
                })

    threading.Thread(target=typing_cleaner, daemon=True).start()

    # --- heartbeat to keep the connection alive (idle proxies/browsers) ---
    def heartbeat():
        while alive:
            time.sleep(25)
            ws_send({"action": "_hb", "t": _now()})

    threading.Thread(target=heartbeat, daemon=True).start()

    try:
        # 1) INIT
        init_msg = safe_receive()
        if not init_msg:
            return
        try:
            init = json.loads(init_msg)
        except Exception:
            ws_send({"status": "error", "detail": "invalid init json"})
            return

        phone = (init.get("phone") or "").strip()
        chat_id_raw = init.get("chat_id")
        access_hash_raw = init.get("access_hash")

        if not phone or chat_id_raw is None:
            ws_send({"status": "error", "detail": "phone/chat_id missing"})
            return

        try:
            chat_id = int(chat_id_raw)
        except Exception:
            ws_send({"status": "error", "detail": "chat_id must be int"})
            return

        try:
            access_hash = int(access_hash_raw) if access_hash_raw not in (None, "") else None
        except Exception:
            access_hash = None

        # 2) LISTENER (Telethon) in its own thread+loop
        async def run_listener():
            nonlocal tg_client, tg_loop
            tg_client = await get_client(phone)
            tg_loop = asyncio.get_event_loop()
            await tg_client.connect()
            if not await tg_client.is_user_authorized():
                ws_send({"status": "error", "detail": "not authorized"})
                await tg_client.disconnect()
                return

            ws_send({"status": "listening", "chat_id": str(chat_id)})
            print(f"👂 Listening for chat {chat_id} ({phone})")

            @tg_client.on(events.NewMessage(chats=int(chat_id)))
            async def on_new_msg(event):
                try:
                    saved = await archive_incoming_event(db, phone, int(chat_id), access_hash, event)
                    payload = _doc_to_api(phone, int(chat_id), access_hash, saved)
                    payload.update({"action": "new_message"})
                    ws_send(payload)

                    # Call events on service messages
                    msg = event.message
                    if isinstance(msg, MessageService) and isinstance(msg.action, MessageActionPhoneCall):
                        info = _call_status_from_action(msg.action, bool(msg.out))
                        ws_send({
                            "action": "call_event",
                            "phone": phone,
                            "chat_id": str(chat_id),
                            "id": int(getattr(msg, "id", 0)),
                            "date": msg.date.isoformat() if getattr(msg, "date", None) else _now(),
                            **info
                        })
                except Exception as e:
                    print(f"⚠️ new_message error: {e}")

            @tg_client.on(events.Raw)
            async def on_typing_raw(update):
                try:
                    upd_chat_id, user_id = None, None
                    if isinstance(update, UpdateUserTyping):
                        upd_chat_id = int(update.user_id); user_id = int(update.user_id)
                    elif isinstance(update, UpdateChatUserTyping):
                        upd_chat_id = int(update.chat_id); user_id = int(update.user_id)
                    elif isinstance(update, UpdateChannelUserTyping):
                        upd_chat_id = int(update.channel_id); user_id = int(update.user_id)

                    if upd_chat_id and int(upd_chat_id) == int(chat_id):
                        with tracker_lock:
                            typing_tracker[(upd_chat_id, user_id)] = time.time()
                        ws_send({
                            "action": "typing",
                            "phone": phone,
                            "chat_id": str(upd_chat_id),
                            "sender_id": user_id,
                            "typing": True,
                            "date": _now()
                        })
                except Exception as e:
                    print(f"⚠️ typing event error: {e}")

            @tg_client.on(events.Raw)
            async def on_raw_calllog(update):
                try:
                    if isinstance(update, (UpdateNewMessage, UpdateNewChannelMessage)):
                        msg = update.message
                        pid = _peer_id(getattr(msg, 'peer_id', None))
                        if pid is None or int(pid) != int(chat_id):
                            return
                        if isinstance(msg, MessageService) and isinstance(msg.action, MessageActionPhoneCall):
                            info = _call_status_from_action(msg.action, bool(getattr(msg, 'out', False)))
                            ws_send({
                                "action": "call_event",
                                "phone": phone,
                                "chat_id": str(chat_id),
                                "id": int(getattr(msg, 'id', 0)),
                                "date": _now(),
                                **info
                            })
                except Exception as e:
                    print(f"⚠️ raw calllog error: {e}")

            # mark deletions but do NOT delete from Mongo
            @tg_client.on(events.MessageDeleted(chats=int(chat_id)))
            async def on_deleted(ev):
                try:
                    for mid in ev.deleted_ids or []:
                        MSG_COL.update_one(
                            {"phone": phone, "chat_id": int(chat_id), "msg_id": int(mid)},
                            {"$set": {"deleted_on_telegram": True}}
                        )
                except Exception as e:
                    print("⚠️ delete mark error:", e)

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

        # 3) WS LOOP (recv actions). We only send via ws_send()
        while alive:
            recv = safe_receive()
            if recv is None:
                break
            try:
                data = json.loads(recv)
            except Exception:
                ws_send({"status": "error", "detail": "invalid json"})
                continue

            action = data.get("action")

            if action == "stop":
                break
            elif action == "ping":
                ws_send({"status": "pong"})

            elif action in ("typing_start", "typing_stop"):
                async def do_typing(act=action):
                    try:
                        peer = await resolve_entity()
                        req = (types.SendMessageTypingAction()
                               if act == "typing_start"
                               else types.SendMessageCancelAction())
                        await tg_client(functions.messages.SetTypingRequest(peer=peer, action=req))
                        ws_send({"status": f"{act}_ok"})
                    except Exception as e:
                        ws_send({"status": "error", "detail": str(e)})
                # schedule on Telethon loop
                if tg_loop:
                    asyncio.run_coroutine_threadsafe(do_typing(), tg_loop)

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

                async def do_send():
                    try:
                        if not await tg_client.is_user_authorized():
                            ws_send({"status": "error", "detail": "not authorized"})
                            return

                        # PRE-SAVE to Mongo
                        pre = await archive_outgoing_pre(
                            db=db, phone=phone, chat_id=int(chat_id), access_hash=access_hash,
                            text=text, reply_to_id=reply_to_id, file_b64=file_b64,
                            file_name=file_name, mime_type=mime_type
                        )
                        temp_id = pre["temp_id"]

                        peer = await resolve_entity()

                        # Load bytes from GridFS if needed
                        bio = None
                        if pre["media_type"] != "text" and pre.get("media_fs_id"):
                            blob = fs.get(ObjectId(pre["media_fs_id"])).read()
                            bio = BytesIO(blob); bio.name = file_name

                        # Send to Telegram
                        if pre["media_type"] == "text":
                            msg_obj = await tg_client.send_message(peer, text or "", reply_to=reply_to_id)
                            ws_send({
                                "status": "sent_text",
                                "text": text or "",
                                "chat_id": str(chat_id),
                                "id": int(getattr(msg_obj, "id", 0)),
                                "reply_to": reply_to_id
                            })
                        else:
                            def progress(sent, total):
                                ws_send({"action": "upload_progress",
                                         "progress": round((sent / max(1, total)) * 100.0, 1)})
                            is_voice = pre["media_type"] == "voice"
                            is_video = pre["media_type"] == "video"
                            if is_voice:
                                msg_obj = await tg_client.send_file(
                                    peer, bio, caption=text or "",
                                    voice_note=True, reply_to=reply_to_id,
                                    progress_callback=progress
                                )
                                ws_send({"status": "sent_voice", "file_name": file_name,
                                         "id": int(getattr(msg_obj, "id", 0))})
                            elif is_video:
                                msg_obj = await tg_client.send_file(
                                    peer, bio, caption=text or "",
                                    supports_streaming=True, reply_to=reply_to_id,
                                    progress_callback=progress
                                )
                                ws_send({"status": "sent_video", "file_name": file_name,
                                         "id": int(getattr(msg_obj, "id", 0))})
                            else:
                                msg_obj = await tg_client.send_file(
                                    peer, bio, caption=text or "",
                                    reply_to=reply_to_id,
                                    progress_callback=progress
                                )
                                ws_send({"status": "sent_file", "file_name": file_name,
                                         "id": int(getattr(msg_obj, "id", 0))})

                        # FINALIZE in Mongo
                        await archive_outgoing_finalize(db, phone, int(chat_id), temp_id, msg_obj)

                    except Exception as e:
                        ws_send({"status": "error", "detail": str(e)})

                if tg_loop:
                    asyncio.run_coroutine_threadsafe(do_send(), tg_loop)

            else:
                ws_send({"status": "error", "detail": "unknown action"})

    except Exception as e:
        # Swallow normal close, log others
        msg = str(e)
        if "Connection closed" in msg:
            print(f"ℹ️ [chat_ws] client closed: {msg}")
        else:
            print(f"⚠️ [chat_ws] Exception: {e}")
    finally:
        # mark dead so heartbeat/cleaners stop
        alive = False
        # Disconnect Telethon gracefully
        try:
            if tg_client:
                if tg_loop and tg_loop.is_running():
                    fut = asyncio.run_coroutine_threadsafe(tg_client.disconnect(), tg_loop)
                    try: fut.result(timeout=5)
                    except: pass
        except Exception:
            pass
        print("❌ [chat_ws] disconnected")























# @sock.route('/chat_ws')
# def chat_ws(ws):
#     """
#     Real-time Telegram Chat WS (text/media/reply/typing + call-log via MessageActionPhoneCall)
#     """
#
#     import json, time, base64, threading, asyncio
#     from datetime import datetime, timezone
#     from io import BytesIO
#     from telethon import events, functions, types
#     from telethon.tl.types import (
#         InputPeerUser, InputPeerChannel, InputPeerChat,
#         UpdateUserTyping, UpdateChatUserTyping, UpdateChannelUserTyping,
#         UpdateNewMessage, UpdateNewChannelMessage,
#         Message, MessageService, MessageActionPhoneCall,
#         PhoneCallDiscardReasonMissed, PhoneCallDiscardReasonBusy,
#         PhoneCallDiscardReasonDisconnect, PhoneCallDiscardReasonHangup,
#         PeerUser, PeerChat, PeerChannel
#     )
#
#     print("🔗 [chat_ws] connected")
#     tg_client = None
#     phone = None
#     chat_id = None
#     loop = None
#
#     # --- typing tracker ---
#     typing_tracker = {}
#     tracker_lock = threading.Lock()
#     TYPING_TTL = 6.0
#
#     def typing_cleaner():
#         while True:
#             time.sleep(2.0)
#             now = time.time()
#             expired = []
#             with tracker_lock:
#                 for key, last in list(typing_tracker.items()):
#                     if now - last > TYPING_TTL:
#                         expired.append(key)
#                         typing_tracker.pop(key, None)
#             for (cid, uid) in expired:
#                 try:
#                     ws.send(json.dumps({
#                         "action": "typing_stopped",
#                         "phone": phone,
#                         "chat_id": str(cid),
#                         "sender_id": uid,
#                         "date": datetime.now(timezone.utc).isoformat()
#                     }))
#                 except:
#                     pass
#
#     threading.Thread(target=typing_cleaner, daemon=True).start()
#
#     # -------- helpers --------
#     def _now():
#         return datetime.now(timezone.utc).isoformat()
#
#     def _peer_id(pid):
#         if isinstance(pid, PeerUser): return pid.user_id
#         if isinstance(pid, PeerChat): return pid.chat_id
#         if isinstance(pid, PeerChannel): return pid.channel_id
#         return None
#
#     def _call_status_from_action(act, is_out):
#         # act: MessageActionPhoneCall
#         reason = type(getattr(act, 'reason', None)).__name__ if getattr(act, 'reason', None) else None
#         dur = getattr(act, 'duration', None)
#         video = bool(getattr(act, 'video', False))
#
#         if reason == 'PhoneCallDiscardReasonMissed':
#             status = 'missed'
#         elif reason == 'PhoneCallDiscardReasonBusy':
#             status = 'busy'
#         elif reason == 'PhoneCallDiscardReasonHangup':
#             status = 'canceled'  # caller canceled before connect
#         elif reason == 'PhoneCallDiscardReasonDisconnect':
#             status = 'ended'
#         elif dur:
#             status = 'ended'
#         else:
#             status = 'unknown'
#
#         return {
#             "status": status,
#             "direction": "outgoing" if is_out else "incoming",
#             "duration": dur,
#             "is_video": video,
#             "raw_reason": reason
#         }
#
#     try:
#         # 1) INIT
#         init_msg = ws.receive()
#         if not init_msg:
#             return
#         init = json.loads(init_msg)
#         phone = (init.get("phone") or "").strip()
#         chat_id = init.get("chat_id")
#         access_hash = init.get("access_hash")
#         if not all([phone, chat_id]):
#             ws.send(json.dumps({"status": "error", "detail": "phone/chat_id missing"}))
#             return
#
#         # 2) LISTENER
#         async def run_listener():
#             nonlocal tg_client, loop
#             tg_client = await get_client(phone)
#             loop = asyncio.get_event_loop()
#             await tg_client.connect()
#             if not await tg_client.is_user_authorized():
#                 ws.send(json.dumps({"status": "error", "detail": "not authorized"}))
#                 await tg_client.disconnect()
#                 return
#
#             ws.send(json.dumps({"status": "listening", "chat_id": str(chat_id)}))
#             print(f"👂 Listening for chat {chat_id} ({phone})")
#
#             # --- chat-specific messages (includes service messages)
#             @tg_client.on(events.NewMessage(chats=int(chat_id)))
#             async def on_new_msg(event):
#                 try:
#                     sender = await event.get_sender()
#                     msg = event.message
#
#                     # always emit generic new_message (text may be empty for service)
#                     ws.send(json.dumps({
#                         "action": "new_message",
#                         "phone": phone,
#                         "chat_id": str(chat_id),
#                         "id": event.id,
#                         "text": getattr(msg, "message", None),
#                         "sender_id": getattr(sender, "id", None),
#                         "sender_name": getattr(sender, "first_name", None),
#                         "date": event.date.isoformat() if event.date else None
#                     }))
#
#                     # ---- CALL LOG via MessageService → MessageActionPhoneCall
#                     if isinstance(msg, MessageService) and isinstance(msg.action, MessageActionPhoneCall):
#                         info = _call_status_from_action(msg.action, bool(msg.out))
#                         ws.send(json.dumps({
#                             "action": "call_event",
#                             "phone": phone,
#                             "chat_id": str(chat_id),
#                             "id": event.id,
#                             "date": event.date.isoformat() if event.date else None,
#                             **info
#                         }))
#                         print(f"📞 [Service/NewMessage] call_event → {info}")
#
#                 except Exception as e:
#                     print(f"⚠️ new_message error: {e}")
#
#             # --- typing detector (scoped)
#             @tg_client.on(events.Raw)
#             async def on_typing_raw(update):
#                 try:
#                     upd_chat_id, user_id = None, None
#                     if isinstance(update, UpdateUserTyping):
#                         upd_chat_id = int(update.user_id)
#                         user_id = int(update.user_id)
#                     elif isinstance(update, UpdateChatUserTyping):
#                         upd_chat_id = int(update.chat_id)
#                         user_id = int(update.user_id)
#                     elif isinstance(update, UpdateChannelUserTyping):
#                         upd_chat_id = int(update.channel_id)
#                         user_id = int(update.user_id)
#
#                     if upd_chat_id and int(upd_chat_id) == int(chat_id):
#                         with tracker_lock:
#                             typing_tracker[(upd_chat_id, user_id)] = time.time()
#                         ws.send(json.dumps({
#                             "action": "typing",
#                             "phone": phone,
#                             "chat_id": str(upd_chat_id),
#                             "sender_id": user_id,
#                             "typing": True,
#                             "date": _now()
#                         }))
#                 except Exception as e:
#                     print(f"⚠️ typing event error: {e}")
#
#             # --- LOW-LEVEL RAW fallback: UpdateNewMessage / UpdateNewChannelMessage → MessageService/PhoneCall
#             @tg_client.on(events.Raw)
#             async def on_raw_calllog(update):
#                 try:
#                     if isinstance(update, (UpdateNewMessage, UpdateNewChannelMessage)):
#                         msg = update.message
#                         # peer filter → only this chat
#                         pid = _peer_id(getattr(msg, 'peer_id', None))
#                         if pid is None or int(pid) != int(chat_id):
#                             return
#
#                         if isinstance(msg, MessageService) and isinstance(msg.action, MessageActionPhoneCall):
#                             info = _call_status_from_action(msg.action, bool(getattr(msg, 'out', False)))
#                             ws.send(json.dumps({
#                                 "action": "call_event",
#                                 "phone": phone,
#                                 "chat_id": str(chat_id),
#                                 "id": getattr(msg, 'id', None),
#                                 "date": _now(),  # raw update has no tz date easily; using server time
#                                 **info
#                             }))
#                             print(f"📞 [Service/Raw] call_event → {info}")
#                 except Exception as e:
#                     print(f"⚠️ raw calllog error: {e}")
#
#             await tg_client.run_until_disconnected()
#
#         threading.Thread(target=lambda: asyncio.run(run_listener()), daemon=True).start()
#
#         # --- resolve entity for sending ---
#         async def resolve_entity():
#             try:
#                 if access_hash:
#                     try:
#                         return InputPeerUser(int(chat_id), int(access_hash))
#                     except:
#                         try:
#                             return InputPeerChannel(int(chat_id), int(access_hash))
#                         except:
#                             return InputPeerChat(int(chat_id))
#                 else:
#                     return await tg_client.get_entity(int(chat_id))
#             except:
#                 return InputPeerChat(int(chat_id))
#
#         # 3) WS LOOP
#         while True:
#             recv = ws.receive()
#             if recv is None:
#                 break
#             data = json.loads(recv)
#             action = data.get("action")
#
#             if action == "stop":
#                 break
#             elif action == "ping":
#                 ws.send(json.dumps({"status": "pong"}))
#
#             elif action in ("typing_start", "typing_stop"):
#                 async def do_typing(act=action):
#                     try:
#                         peer = await resolve_entity()
#                         req = (types.SendMessageTypingAction()
#                                if act == "typing_start"
#                                else types.SendMessageCancelAction())
#                         await tg_client(functions.messages.SetTypingRequest(peer=peer, action=req))
#                         ws.send(json.dumps({"status": f"{act}_ok"}))
#                     except Exception as e:
#                         ws.send(json.dumps({"status": "error", "detail": str(e)}))
#                 asyncio.run_coroutine_threadsafe(do_typing(), loop)
#
#             elif action == "send":
#                 text = data.get("text")
#                 file_b64 = data.get("file_base64")
#                 file_name = data.get("file_name", "file.bin")
#                 mime_type = data.get("mime_type", "")
#                 reply_to_raw = data.get("reply_to") or data.get("reply_to_msg_id")
#                 try:
#                     reply_to_id = int(reply_to_raw) if reply_to_raw else None
#                 except:
#                     reply_to_id = None
#
#                 async def do_send(file_b64=file_b64, text=text,
#                                  file_name=file_name, mime_type=mime_type,
#                                  reply_to_id=reply_to_id):
#                     try:
#                         if not await tg_client.is_user_authorized():
#                             ws.send(json.dumps({"status": "error", "detail": "not authorized"}))
#                             return
#                         peer = await resolve_entity()
#
#                         # text only
#                         if text and not file_b64:
#                             msg_obj = await tg_client.send_message(peer, text, reply_to=reply_to_id)
#                             ws.send(json.dumps({
#                                 "status": "sent_text",
#                                 "text": text,
#                                 "chat_id": str(chat_id),
#                                 "id": getattr(msg_obj, "id", None),
#                                 "reply_to": reply_to_id
#                             }))
#                             return
#
#                         # file
#                         if file_b64:
#                             if isinstance(file_b64, str) and file_b64.startswith("data:"):
#                                 file_b64 = file_b64.split(",", 1)[1]
#                             try:
#                                 file_bytes = base64.b64decode(file_b64 + "==")
#                             except Exception as e:
#                                 ws.send(json.dumps({"status": "error", "detail": f"base64 decode failed: {e}"}))
#                                 return
#                             bio = BytesIO(file_bytes)
#                             bio.name = file_name
#
#                             def progress(sent, total):
#                                 try:
#                                     ws.send(json.dumps({
#                                         "action": "upload_progress",
#                                         "progress": round((sent / max(1, total)) * 100.0, 1)
#                                     }))
#                                 except:
#                                     pass
#
#                             name = (file_name or "").lower()
#                             is_voice = (mime_type or "").startswith("audio/ogg") or name.endswith(".ogg")
#                             is_video = (mime_type or "").startswith("video/") or name.endswith((".mp4", ".mkv", ".mov"))
#
#                             if is_voice:
#                                 msg_obj = await tg_client.send_file(
#                                     peer, bio, caption=text or "",
#                                     voice_note=True, reply_to=reply_to_id,
#                                     progress_callback=progress
#                                 )
#                                 ws.send(json.dumps({
#                                     "status": "sent_voice",
#                                     "file_name": file_name,
#                                     "id": getattr(msg_obj, "id", None)
#                                 }))
#                             elif is_video:
#                                 msg_obj = await tg_client.send_file(
#                                     peer, bio, caption=text or "",
#                                     supports_streaming=True, reply_to=reply_to_id,
#                                     progress_callback=progress
#                                 )
#                                 ws.send(json.dumps({
#                                     "status": "sent_video",
#                                     "file_name": file_name,
#                                     "id": getattr(msg_obj, "id", None)
#                                 }))
#                             else:
#                                 msg_obj = await tg_client.send_file(
#                                     peer, bio, caption=text or "",
#                                     reply_to=reply_to_id,
#                                     progress_callback=progress
#                                 )
#                                 ws.send(json.dumps({
#                                     "status": "sent_file",
#                                     "file_name": file_name,
#                                     "id": getattr(msg_obj, "id", None)
#                                 }))
#                         else:
#                             ws.send(json.dumps({"status": "error", "detail": "text or file required"}))
#                     except Exception as e:
#                         ws.send(json.dumps({"status": "error", "detail": str(e)}))
#
#                 asyncio.run_coroutine_threadsafe(do_send(), loop)
#
#             else:
#                 ws.send(json.dumps({"status": "error", "detail": "unknown action"}))
#
#     except Exception as e:
#         print(f"⚠️ [chat_ws] Exception: {e}")
#     finally:
#         if tg_client:
#             try:
#                 asyncio.run(tg_client.disconnect())
#             except:
#                 pass
#         print("❌ [chat_ws] disconnected")



















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












# ---------- FULL: /dialogs (fires background archiver immediately) ----------
@app.route("/dialogs", methods=["GET"])
def get_dialogs():
    """
    Telegram থেকে সমস্ত dialogs (chats, groups, channels) structured JSON-এ ফেরত দেয়।
    এই এন্ডপয়েন্ট হিট করলেই ব্যাকগ্রাউন্ডে সব ডায়ালগের সাম্প্রতিক মেসেজ MongoDB-তে আর্কাইভ শুরু হয়।
    Query params (optional):
      - archive_limit: per chat কতগুলো মেসেজ আর্কাইভ করবে (default 200)
      - dialog_limit: কয়টা ডায়ালগ স্ক্যান করবে (default 50)
    """
    phone = request.args.get("phone")
    if not phone:
        return jsonify({"status": "error", "detail": "phone missing"}), 400

    # --- parse optional limits for archiver (without changing response shape) ---
    try:
        per_chat_limit = int(request.args.get("archive_limit", 200))
    except Exception:
        per_chat_limit = 200
    try:
        dialog_limit = int(request.args.get("dialog_limit", 50))
    except Exception:
        dialog_limit = 50

    async def do_get_dialogs():
        from telethon.tl.functions.channels import GetFullChannelRequest
        from telethon.tl.functions.messages import GetFullChatRequest
        try:
            client = await get_client(phone)
            if not client.is_connected():
                await client.connect()

            if not await client.is_user_authorized():
                await client.disconnect()
                return {"status": "error", "detail": "not authorized"}

            dialogs = []
            async for d in client.iter_dialogs(limit=50):
                e = d.entity
                msg = d.message

                last_msg = {
                    "id": getattr(msg, "id", None),
                    "text": getattr(msg, "message", None),
                    "date": getattr(msg, "date", None).isoformat() if getattr(msg, "date", None) else None,
                    "sender_id": getattr(getattr(msg, "from_id", None), "user_id", None),
                    "reply_to": getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None),
                    "media": str(type(getattr(msg, "media", None)).__name__) if getattr(msg, "media", None) else None,
                } if msg else None

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
            return {"status": "ok", "count": len(dialogs), "dialogs": dialogs}

        except Exception as e:
            import traceback
            print("❌ Exception in /dialogs:\n", traceback.format_exc())
            return {"status": "error", "detail": str(e)}

    # ✅ fetch dialogs (same as before)
    result = asyncio.run(do_get_dialogs())

    # ✅ immediately kick off background archiver (non-blocking)
    try:
        asyncio.run_coroutine_threadsafe(
            archive_all_dialogs(phone=phone, per_chat_limit=per_chat_limit, dialog_limit=dialog_limit),
            loop  # <-- your global event loop already running
        )
        print(f"🧵 Archive job started for {phone} (limit {per_chat_limit}/chat, dialogs {dialog_limit})")
    except Exception as ex:
        print(f"⚠️ archive kickoff error: {ex}")

    # ✅ Safe log + return original shape
    if result.get("status") == "ok":
        print(f"✅ Dialogs fetched successfully: {result.get('count', 0)} items.")
    else:
        print(f"⚠️ Dialog fetch error: {result.get('detail', 'unknown error')}")

    return jsonify(result)









# @app.route("/dialogs", methods=["GET"])
# def get_dialogs():
#     """
#     Telegram থেকে সমস্ত dialogs (chats, groups, channels)
#     পুরো detailed structured JSON format এ ফেরত দেয়।
#     Example:
#       /dialogs?phone=+8801731979364
#     """
#     phone = request.args.get("phone")
#     if not phone:
#         return jsonify({"status": "error", "detail": "phone missing"}), 400
#
#     async def do_get_dialogs():
#         from telethon.tl.functions.channels import GetFullChannelRequest
#         from telethon.tl.functions.messages import GetFullChatRequest
#
#         try:
#             client = await get_client(phone)
#             if not client.is_connected():
#                 await client.connect()
#
#             # ✅ authorized কিনা check
#             if not await client.is_user_authorized():
#                 await client.disconnect()
#                 return {"status": "error", "detail": "not authorized"}
#
#             dialogs = []
#
#             async for d in client.iter_dialogs(limit=50):
#                 e = d.entity
#                 msg = d.message
#
#                 # 🔹 Last message info
#                 last_msg = {
#                     "id": getattr(msg, "id", None),
#                     "text": getattr(msg, "message", None),
#                     "date": getattr(msg, "date", None).isoformat() if getattr(msg, "date", None) else None,
#                     "sender_id": getattr(getattr(msg, "from_id", None), "user_id", None),
#                     "reply_to": getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None),
#                     "media": str(type(getattr(msg, "media", None)).__name__) if getattr(msg, "media", None) else None,
#                 } if msg else None
#
#                 # 🔹 Channel/Group participant count
#                 participants_count = None
#                 about = None
#                 dc_id = getattr(getattr(e, "photo", None), "dc_id", None)
#
#                 try:
#                     if d.is_channel:
#                         full = await client(GetFullChannelRequest(e))
#                         participants_count = getattr(full.full_chat, "participants_count", None)
#                         about = getattr(full.full_chat, "about", None)
#                     elif d.is_group:
#                         full = await client(GetFullChatRequest(e.id))
#                         participants_count = getattr(full.full_chat, "participants_count", None)
#                         about = getattr(full.full_chat, "about", None)
#                 except Exception:
#                     pass
#
#                 # 🔹 Build dialog info
#                 dialog_info = {
#                     "id": getattr(e, "id", None),
#                     "name": getattr(e, "title", getattr(e, "username", str(e))),
#                     "title": getattr(e, "title", None),
#                     "first_name": getattr(e, "first_name", None),
#                     "last_name": getattr(e, "last_name", None),
#                     "username": getattr(e, "username", None),
#                     "phone": getattr(e, "phone", None),
#                     "about": about,
#                     "access_hash": getattr(e, "access_hash", None),
#                     "dc_id": dc_id,
#                     "is_user": d.is_user,
#                     "is_group": d.is_group,
#                     "is_channel": d.is_channel,
#                     "unread_count": d.unread_count,
#                     "pinned": getattr(d, "pinned", False),
#                     "verified": getattr(e, "verified", False),
#                     "restricted": getattr(e, "restricted", False),
#                     "bot": getattr(e, "bot", False),
#                     "fake": getattr(e, "fake", False),
#                     "scam": getattr(e, "scam", False),
#                     "premium": getattr(e, "premium", False),
#                     "participants_count": participants_count,
#                     "has_photo": bool(getattr(e, "photo", None)),
#                     "last_message": last_msg,
#                 }
#
#                 dialogs.append(dialog_info)
#
#             await client.disconnect()
#             return {
#                 "status": "ok",
#                 "count": len(dialogs),
#                 "dialogs": dialogs
#             }
#
#         except Exception as e:
#             import traceback
#             print("❌ Exception in /dialogs:\n", traceback.format_exc())
#             return {"status": "error", "detail": str(e)}
#
#     result = asyncio.run(do_get_dialogs())
#
#     # ✅ Safe print (no KeyError possible)
#     if result.get("status") == "ok":
#         print(f"✅ Dialogs fetched successfully: {result.get('count', 0)} items.")
#     else:
#         print(f"⚠️ Dialog fetch error: {result.get('detail', 'unknown error')}")
#
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























# @app.route("/messages")
# def get_messages():
#     """
#     ✅ Unified Telegram Messages API (v6)
#     -------------------------------------
#     - Supports text, image, video, voice, audio, sticker, file
#     - Includes call events (audio/video)
#     - Provides 'media_link' for media messages
#     - Returns uniform JSON objects for easy Flutter UI parsing
#     """
#     import base64, asyncio
#     from telethon import types
#     from datetime import datetime, timezone
#
#     phone = request.args.get("phone")
#     chat_id = int(request.args.get("chat_id"))
#     access_hash = int(request.args.get("access_hash"))
#     limit = int(request.args.get("limit", 50))
#
#     if not phone or not chat_id:
#         return jsonify({"status": "error", "detail": "missing params"}), 400
#
#     async def fetch_messages():
#         tg_client = await get_client(phone)
#         await tg_client.connect()
#
#         if not await tg_client.is_user_authorized():
#             await tg_client.disconnect()
#             return {"status": "error", "detail": "not authorized"}
#
#         peer = types.InputPeerUser(chat_id, access_hash)
#
#         msgs = []
#         async for msg in tg_client.iter_messages(peer, limit=limit):
#             media_type = "text"
#             media_link = None
#
#             if msg.media:
#                 if msg.photo:
#                     media_type = "image"
#                     media_link = f"/message_media?phone={phone}&chat_id={chat_id}&msg_id={msg.id}&access_hash={access_hash}"
#                 elif msg.video:
#                     media_type = "video"
#                     media_link = f"/message_media?phone={phone}&chat_id={chat_id}&msg_id={msg.id}&access_hash={access_hash}"
#                 elif msg.voice:
#                     media_type = "voice"
#                     media_link = f"/message_media?phone={phone}&chat_id={chat_id}&msg_id={msg.id}&access_hash={access_hash}"
#                 elif msg.audio:
#                     media_type = "audio"
#                     media_link = f"/message_media?phone={phone}&chat_id={chat_id}&msg_id={msg.id}&access_hash={access_hash}"
#                 elif msg.sticker:
#                     media_type = "sticker"
#                     media_link = f"/message_media?phone={phone}&chat_id={chat_id}&msg_id={msg.id}&access_hash={access_hash}"
#                 elif msg.file:
#                     media_type = "file"
#                     media_link = f"/message_media?phone={phone}&chat_id={chat_id}&msg_id={msg.id}&access_hash={access_hash}"
#             elif msg.action:
#                 if isinstance(msg.action, types.MessageActionPhoneCall):
#                     media_type = "call_audio"
#                 elif isinstance(msg.action, types.MessageActionVideoChatStarted):
#                     media_type = "call_video"
#                 elif isinstance(msg.action, types.MessageActionVideoChatEnded):
#                     media_type = "call_video"
#
#             msgs.append({
#                 "id": msg.id,
#                 "text": msg.message or "",
#                 "sender_id": getattr(msg.sender_id, "to_json", lambda: msg.sender_id)(),
#                 "sender_name": getattr(msg.sender, "first_name", "") if msg.sender else "",
#                 "date": msg.date.replace(tzinfo=timezone.utc).isoformat(),
#                 "is_out": msg.out,
#                 "reply_to": msg.reply_to_msg_id,
#                 "media_type": media_type,
#                 "media_link": media_link
#             })
#
#         await tg_client.disconnect()
#         return {"status": "ok", "messages": msgs[::-1]}  # newest last
#
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#     return jsonify(loop.run_until_complete(fetch_messages()))







# ---------- FULL: /messages from Mongo-first ----------
# ---------- FULL: /messages (pull-from-Telegram-once → return-from-Mongo) ----------
# ---------- FULL: /messages (pull-from-Telegram → return latest-from-Mongo) ----------
@app.route("/messages")
def get_messages():
    """
    Mongo-first message feed (same API/shape as before)
    - On each call: pull recent messages from Telegram for this chat, save to Mongo
    - Then read the latest 'limit' messages from Mongo and return
      (response is newest last / ascending order)
    """
    from telethon.tl.types import InputPeerUser, InputPeerChannel, InputPeerChat
    import asyncio

    raw_phone = request.args.get("phone")
    chat_id_raw = request.args.get("chat_id")
    access_hash_raw = request.args.get("access_hash")  # only for media link shape
    limit = int(request.args.get("limit", 50))

    if not raw_phone or not chat_id_raw:
        return jsonify({"status": "error", "detail": "missing params"}), 400

    # normalize phone a little (space remove; '+' রাখা হবে যাতে DB key না ভাঙে)
    phone = raw_phone.strip().replace(" ", "")

    try:
        chat_id = int(chat_id_raw)
    except Exception:
        return jsonify({"status": "error", "detail": "chat_id must be int"}), 400

    try:
        access_hash_int = int(access_hash_raw) if access_hash_raw not in (None, "",) else None
    except Exception:
        access_hash_int = None

    # -------- pull once from Telegram so Mongo is fresh --------
    async def pull_once():
        tg_client = await get_client(phone)
        await tg_client.connect()
        try:
            if not await tg_client.is_user_authorized():
                # Not authorized: skip pulling; still serve from Mongo
                return

            # Resolve entity robustly (user/channel/chat)
            try:
                if access_hash_int:
                    try:
                        peer = InputPeerUser(int(chat_id), int(access_hash_int))
                    except Exception:
                        try:
                            peer = InputPeerChannel(int(chat_id), int(access_hash_int))
                        except Exception:
                            peer = InputPeerChat(int(chat_id))
                else:
                    peer = await tg_client.get_entity(int(chat_id))
            except Exception:
                # Fallback
                try:
                    peer = InputPeerChat(int(chat_id))
                except Exception:
                    return  # can't resolve; bail out but still return Mongo data

            # Pull a reasonable window each time; idempotent upserts inside helper
            PULL_LIMIT = 200
            count = 0
            async for msg in tg_client.iter_messages(peer, limit=PULL_LIMIT):
                await _upsert_message_from_msg(tg_client, phone, int(chat_id), access_hash_int, msg)
                count += 1
            if count:
                print(f"📥 /messages pull_once({phone}, {chat_id}): +{count}")

        except Exception as e:
            print(f"⚠️ /messages pull_once error: {e}")
        finally:
            try:
                await tg_client.disconnect()
            except Exception:
                pass

    # Run the pull inline so we return fresh Mongo data
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(pull_once())
    finally:
        try:
            loop.close()
        except Exception:
            pass

    # -------- now return latest N from Mongo (newest last) --------
    MSG_COL = db.messages

    # 1) নিয়ে আসি সর্বশেষ 'limit' ডক—DESC sort করে
    latest_docs = list(
        MSG_COL.find({"phone": phone, "chat_id": int(chat_id)})
               .sort([("date", -1), ("msg_id", -1)])  # newest→oldest
               .limit(limit)
    )

    # 2) ক্লায়েন্টে দেখানো হবে oldest→newest (নিউয়েস্ট লাস্ট), তাই রিভার্স
    latest_docs.reverse()

    msgs = []
    for doc in latest_docs:
        api_obj = _doc_to_api(phone, int(chat_id), access_hash_int, doc)
        msgs.append(api_obj)

    return jsonify({"status": "ok", "messages": msgs})













# @app.route("/messages")
# def get_messages():
#     """
#     ✅ Unified Telegram Messages API (v6)
#     -------------------------------------
#     - Supports text, image, video, voice, audio, sticker, file
#     - Includes call events (audio/video)
#     - Provides 'media_link' for media messages
#     - Returns uniform JSON objects for easy Flutter UI parsing
#     """
#     import base64, asyncio
#     from telethon import types
#     from datetime import datetime, timezone
#
#     phone = request.args.get("phone")
#     chat_id = int(request.args.get("chat_id"))
#     access_hash = int(request.args.get("access_hash"))
#     limit = int(request.args.get("limit", 50))
#
#     if not phone or not chat_id:
#         return jsonify({"status": "error", "detail": "missing params"}), 400
#
#     async def fetch_messages():
#         tg_client = await get_client(phone)
#         await tg_client.connect()
#
#         if not await tg_client.is_user_authorized():
#             await tg_client.disconnect()
#             return {"status": "error", "detail": "not authorized"}
#
#         peer = types.InputPeerUser(chat_id, access_hash)
#
#         msgs = []
#         async for msg in tg_client.iter_messages(peer, limit=limit):
#             media_type = "text"
#             media_link = None
#
#             if msg.media:
#                 if msg.photo:
#                     media_type = "image"
#                     media_link = f"/message_media?phone={phone}&chat_id={chat_id}&msg_id={msg.id}&access_hash={access_hash}"
#                 elif msg.video:
#                     media_type = "video"
#                     media_link = f"/message_media?phone={phone}&chat_id={chat_id}&msg_id={msg.id}&access_hash={access_hash}"
#                 elif msg.voice:
#                     media_type = "voice"
#                     media_link = f"/message_media?phone={phone}&chat_id={chat_id}&msg_id={msg.id}&access_hash={access_hash}"
#                 elif msg.audio:
#                     media_type = "audio"
#                     media_link = f"/message_media?phone={phone}&chat_id={chat_id}&msg_id={msg.id}&access_hash={access_hash}"
#                 elif msg.sticker:
#                     media_type = "sticker"
#                     media_link = f"/message_media?phone={phone}&chat_id={chat_id}&msg_id={msg.id}&access_hash={access_hash}"
#                 elif msg.file:
#                     media_type = "file"
#                     media_link = f"/message_media?phone={phone}&chat_id={chat_id}&msg_id={msg.id}&access_hash={access_hash}"
#             elif msg.action:
#                 if isinstance(msg.action, types.MessageActionPhoneCall):
#                     media_type = "call_audio"
#                 elif isinstance(msg.action, types.MessageActionVideoChatStarted):
#                     media_type = "call_video"
#                 elif isinstance(msg.action, types.MessageActionVideoChatEnded):
#                     media_type = "call_video"
#
#             msgs.append({
#                 "id": msg.id,
#                 "text": msg.message or "",
#                 "sender_id": getattr(msg.sender_id, "to_json", lambda: msg.sender_id)(),
#                 "sender_name": getattr(msg.sender, "first_name", "") if msg.sender else "",
#                 "date": msg.date.replace(tzinfo=timezone.utc).isoformat(),
#                 "is_out": msg.out,
#                 "reply_to": msg.reply_to_msg_id,
#                 "media_type": media_type,
#                 "media_link": media_link
#             })
#
#         await tg_client.disconnect()
#         return {"status": "ok", "messages": msgs[::-1]}  # newest last
#
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#     return jsonify(loop.run_until_complete(fetch_messages()))















# ---------- FULL: /message_media with FS-first, Telegram fallback ----------
# @app.route("/message_media")
# def message_media():
#     """
#     Serves media from Mongo GridFS if available; otherwise download from Telegram,
#     save to GridFS, update doc, and serve. API inputs unchanged.
#     """
#     from telethon import types
#     from flask import send_file
#     from io import BytesIO
#
#     phone = request.args.get("phone")
#     chat_id = request.args.get("chat_id")
#     access_hash = request.args.get("access_hash")
#     msg_id = request.args.get("msg_id")
#
#     if not all([phone, chat_id, access_hash, msg_id]):
#         return "Bad Request", 400
#
#     chat_id = int(chat_id)
#     access_hash = int(access_hash)
#     msg_id = int(msg_id)
#
#     MSG_COL = db.messages
#     fs = GridFS(db, collection="fs")
#
#     # 1) Try Mongo/FS first
#     doc = MSG_COL.find_one({"phone": phone, "chat_id": chat_id, "msg_id": msg_id})
#     if doc and doc.get("media_fs_id"):
#         try:
#             gf = fs.get(ObjectId(doc["media_fs_id"]))
#             return send_file(BytesIO(gf.read()),
#                              mimetype=(gf.content_type or "application/octet-stream"))
#         except Exception:
#             pass  # fallback
#
#     # 2) Telegram fallback → store to FS → update doc
#     import asyncio
#     async def get_media():
#         tg_client = await get_client(phone)
#         await tg_client.connect()
#         try:
#             peer = types.InputPeerUser(chat_id, access_hash)
#         except Exception:
#             peer = types.InputPeerUser(chat_id, access_hash)
#         msg = await tg_client.get_messages(peer, ids=msg_id)
#         if not msg or not msg.media:
#             await tg_client.disconnect()
#             return None, None, None
#         data = await msg.download_media(bytes)
#         await tg_client.disconnect()
#         return data, "file.bin", "application/octet-stream"
#
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#     data, fname, ctype = loop.run_until_complete(get_media())
#     if not data:
#         return "No media", 404
#
#     fs_id = _put_fs(db, data, filename=fname, content_type=ctype)
#     MSG_COL.update_one(
#         {"phone": phone, "chat_id": chat_id, "msg_id": msg_id},
#         {"$set": {"media_fs_id": fs_id}},
#         upsert=True
#     )
#     return send_file(BytesIO(data), mimetype=ctype or "application/octet-stream")


@app.route("/message_media")
def message_media():
    """
    Serves media from Mongo GridFS if available; otherwise download from Telegram,
    save to GridFS with correct content_type, update doc, and serve inline.
    """
    from telethon import types
    from flask import send_file, make_response
    from io import BytesIO

    phone = request.args.get("phone")
    chat_id = request.args.get("chat_id")
    access_hash = request.args.get("access_hash")
    msg_id = request.args.get("msg_id")

    if not all([phone, chat_id, msg_id]):
        return "Bad Request", 400

    chat_id = int(chat_id)
    msg_id = int(msg_id)
    access_hash = int(access_hash) if access_hash not in (None, "",) else None

    MSG_COL = db.messages
    fs = GridFS(db, collection="fs")

    # 1) Try GridFS first
    from bson.objectid import ObjectId
    doc = MSG_COL.find_one({"phone": phone, "chat_id": chat_id, "msg_id": msg_id})
    if doc and doc.get("media_fs_id"):
        try:
            gf = fs.get(ObjectId(doc["media_fs_id"]))
            data = gf.read()
            resp = make_response(data)
            # Correct MIME + inline
            mime = getattr(gf, "content_type", None) or "application/octet-stream"
            fname = getattr(gf, "filename", None) or "file.bin"
            resp.headers["Content-Type"] = mime
            resp.headers["Content-Disposition"] = f'inline; filename="{fname}"'
            # optional CORS (Flutter web)
            resp.headers["Access-Control-Allow-Origin"] = "*"
            return resp
        except Exception:
            pass  # fallback to Telegram

    # 2) Fallback to Telegram → download → save to FS → update doc → return
    import asyncio

    async def fetch_from_telegram():
        tg_client = await get_client(phone)
        await tg_client.connect()
        try:
            # resolve entity robustly
            peer = None
            if access_hash is not None:
                try:
                    peer = types.InputPeerUser(chat_id, access_hash)
                except Exception:
                    try:
                        peer = types.InputPeerChannel(chat_id, access_hash)
                    except Exception:
                        peer = types.InputPeerChat(chat_id)
            if peer is None:
                try:
                    peer = await tg_client.get_entity(int(chat_id))
                except Exception:
                    peer = types.InputPeerChat(chat_id)

            msg = await tg_client.get_messages(peer, ids=msg_id)
            if not msg or not getattr(msg, "media", None):
                await tg_client.disconnect()
                return None, None, None

            blob = await msg.download_media(bytes)
            mime, fname = _guess_msg_media_meta(msg)
            await tg_client.disconnect()
            return blob, mime, fname
        except Exception:
            try:
                await tg_client.disconnect()
            except:
                pass
            return None, None, None

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    data, mime, fname = loop.run_until_complete(fetch_from_telegram())
    if not data:
        return "No media", 404

    # Save to FS with correct content_type
    fs_id = _put_fs(db, data, filename=fname, content_type=mime)
    MSG_COL.update_one(
        {"phone": phone, "chat_id": chat_id, "msg_id": msg_id},
        {"$set": {"media_fs_id": fs_id}},
        upsert=True
    )

    # Return inline
    resp = make_response(data)
    resp.headers["Content-Type"] = mime or "application/octet-stream"
    resp.headers["Content-Disposition"] = f'inline; filename="{fname or "file.bin"}"'
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp





# ---------- FULL: Mongo-first archivers ----------
from io import BytesIO

async def archive_incoming_event(db, phone: str, chat_id: int, access_hash: int | None, event) -> dict:
    MSG_COL = db.messages
    try:
        MSG_COL.create_index([("phone", 1), ("chat_id", 1), ("msg_id", 1)], unique=True, sparse=True, name="uniq_msg")
    except Exception:
        pass

    msg = event.message
    sender = await event.get_sender()

    # ---- call detect first ----
    media_type = "text"
    media_fs_id = None
    file_name = None
    mime_type = None

    call_media_type, call_info = _call_meta_from_msg(msg)
    if call_media_type:
        media_type = call_media_type
    else:
        # ---- normal media path ----
        if getattr(msg, "media", None):
            if getattr(msg, "photo", None): media_type = "image"
            elif getattr(msg, "video", None): media_type = "video"
            elif getattr(msg, "voice", None): media_type = "voice"
            elif getattr(msg, "audio", None): media_type = "audio"
            elif getattr(msg, "sticker", None): media_type = "sticker"
            else: media_type = "file"

            try:
                blob = await msg.download_media(bytes)
                mime_type, file_name = _guess_msg_media_meta(msg)
                media_fs_id = _put_fs(db, blob, filename=file_name or "tg_in.bin", content_type=mime_type)
            except Exception:
                media_fs_id = None

    doc = {
        "phone": phone,
        "chat_id": int(chat_id),
        "access_hash": int(access_hash) if access_hash else None,
        "msg_id": int(msg.id),
        "direction": "in",
        "is_out": False,
        "text": msg.message or "",
        "sender_id": getattr(sender, "id", None),
        "sender_name": getattr(sender, "first_name", None),
        "date": msg.date if isinstance(msg.date, datetime) else datetime.now(timezone.utc),
        "reply_to": getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None),
        "media_type": media_type,
        "media_fs_id": media_fs_id,
        "file_name": file_name,
        "mime_type": mime_type,
        "status": "arrived",
        "deleted_on_telegram": False,
    }

    if call_media_type:
        doc.update({
            "call_status": call_info["status"],
            "call_is_video": call_info["is_video"],
            "call_duration": call_info["duration"],
            "call_reason": call_info["raw_reason"],
        })

    MSG_COL.update_one(
        {"phone": phone, "chat_id": int(chat_id), "msg_id": int(msg.id)},
        {"$set": doc},
        upsert=True
    )
    return MSG_COL.find_one({"phone": phone, "chat_id": int(chat_id), "msg_id": int(msg.id)})











async def archive_outgoing_pre(db, phone: str, chat_id: int, access_hash: int | None,
                               text: str | None, reply_to_id: int | None,
                               file_b64: str | None, file_name: str | None, mime_type: str | None) -> dict:
    MSG_COL = db.messages
    try:
        MSG_COL.create_index([("phone", 1), ("chat_id", 1), ("msg_id", 1)], unique=True, sparse=True, name="uniq_msg")
    except Exception:
        pass

    media_type = "text"
    media_fs_id = None

    if file_b64:
        if isinstance(file_b64, str) and file_b64.startswith("data:"):
            file_b64 = file_b64.split(",", 1)[1]
        file_bytes = base64.b64decode(file_b64 + "==")
        media_fs_id = _put_fs(db, file_bytes, filename=file_name or "file.bin",
                              content_type=mime_type or "application/octet-stream")
        media_type = _detect_media_type(mime_type, file_name)

    temp_id = f"local-{uuid.uuid4().hex[:12]}"
    doc = {
        "phone": phone,
        "chat_id": int(chat_id),
        "access_hash": int(access_hash) if access_hash else None,
        "temp_id": temp_id,
        "msg_id": None,
        "direction": "out",
        "is_out": True,
        "text": text or "",
        "sender_id": None,
        "sender_name": None,
        "date": datetime.now(timezone.utc),
        "reply_to": reply_to_id,
        "media_type": media_type,
        "media_fs_id": media_fs_id,
        "file_name": file_name,
        "mime_type": mime_type,
        "status": "pending",
        "deleted_on_telegram": False
    }
    MSG_COL.insert_one(doc)
    return doc












async def archive_outgoing_finalize(db, phone: str, chat_id: int, temp_id: str, msg_obj) -> dict:
    MSG_COL = db.messages
    upd = {
        "msg_id": int(getattr(msg_obj, "id", 0)),
        "date": getattr(msg_obj, "date", datetime.now(timezone.utc)),
        "status": "sent"
    }
    MSG_COL.update_one(
        {"phone": phone, "chat_id": int(chat_id), "temp_id": temp_id},
        {"$set": upd}
    )
    return MSG_COL.find_one({"phone": phone, "chat_id": int(chat_id), "temp_id": temp_id})







# ---------- FULL: Helpers for archive ----------
from gridfs import GridFS
from bson.objectid import ObjectId
import base64, uuid
from datetime import datetime, timezone
from io import BytesIO

def _detect_media_type(mime_type: str, file_name: str = "") -> str:
    name = (file_name or "").lower()
    mt = (mime_type or "").lower()
    if mt.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return "image"
    if mt.startswith("video/") or name.endswith((".mp4", ".mkv", ".mov")):
        return "video"
    if mt.startswith("audio/ogg") or name.endswith(".ogg"):
        return "voice"
    if mt.startswith("audio/"):
        return "audio"
    if name.endswith(".webp") and "sticker" in name:
        return "sticker"
    return "file"










from gridfs import GridFS
def _put_fs(db, bytes_or_bio, filename: str = None, content_type: str = None):
    """
    Save bytes to GridFS with a correct MIME type so that /message_media can return inline.
    """
    fs = GridFS(db, collection="fs")
    data = bytes_or_bio.getvalue() if hasattr(bytes_or_bio, "getvalue") else bytes_or_bio
    # IMPORTANT: use content_type= (not contentType)
    return fs.put(
        data,
        filename=filename or "file.bin",
        content_type=content_type or "application/octet-stream",
        # keep a copy for older readers if you ever used contentType before:
        contentType=content_type or "application/octet-stream"
    )





import mimetypes

def _guess_msg_media_meta(msg):
    """
    Best-effort mime/filename guess from a Telethon Message.
    """
    # defaults
    ctype = "application/octet-stream"
    fname = f"file_{getattr(msg, 'id', 0)}.bin"

    # photos
    if getattr(msg, "photo", None):
        return "image/jpeg", f"photo_{msg.id}.jpg"

    # voice
    if getattr(msg, "voice", None):
        return "audio/ogg", f"voice_{msg.id}.ogg"

    # video
    if getattr(msg, "video", None):
        # Telethon docs typically give video/mp4
        return "video/mp4", f"video_{msg.id}.mp4"

    # audio (music)
    if getattr(msg, "audio", None):
        # Often audio/mpeg
        return "audio/mpeg", f"audio_{msg.id}.mp3"

    # sticker (often webp)
    if getattr(msg, "sticker", None):
        return "image/webp", f"sticker_{msg.id}.webp"

    # generic document mime
    doc = getattr(msg, "document", None)
    if doc and getattr(doc, "mime_type", None):
        ctype = doc.mime_type
        ext = mimetypes.guess_extension(ctype) or ".bin"
        fname = f"doc_{msg.id}{ext}"
        return ctype, fname

    return ctype, fname










# def _doc_to_api(phone: str, chat_id: int, access_hash: int | None, doc: dict) -> dict:
#     media_type = doc.get("media_type") or "text"
#     media_link = None
#     if media_type != "text" and doc.get("msg_id") is not None:
#         media_link = f"/message_media?phone={phone}&chat_id={chat_id}&msg_id={doc['msg_id']}&access_hash={access_hash}"
#     return {
#         "id": doc.get("msg_id") if doc.get("msg_id") is not None else doc.get("temp_id"),
#         "text": doc.get("text") or "",
#         "sender_id": doc.get("sender_id"),
#         "sender_name": doc.get("sender_name") or "",
#         "date": (doc.get("date").astimezone(timezone.utc).isoformat()
#                  if isinstance(doc.get("date"), datetime) else doc.get("date")),
#         "is_out": bool(doc.get("is_out", doc.get("direction") == "out")),
#         "reply_to": doc.get("reply_to"),
#         "media_type": media_type,
#         "media_link": media_link
#     }






def _base_url():
    # e.g. http://192.168.0.247:8080/
    if has_request_context():
        return request.url_root
    # WS বা ব্যাকগ্রাউন্ড থ্রেডে থাকলে এখানে ফfallback
    return os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8080/")









def _doc_to_api(phone: str, chat_id: int, access_hash: int | None, doc: dict) -> dict:
    from datetime import datetime, timezone

    media_type = doc.get("media_type") or "text"

    # ---- absolute media_link (non-text, non-call only) ----
    media_link = None
    if media_type not in ("text", "call_audio", "call_video") and doc.get("msg_id") is not None:
        params = {"phone": str(phone), "chat_id": int(chat_id), "msg_id": int(doc["msg_id"])}
        if access_hash is not None:
            params["access_hash"] = int(access_hash)
        qs = urlencode(params, doseq=False, safe="")
        media_link = urljoin(_base_url(), f"message_media?{qs}")

    # ---- normalize a small 'call' object for API consumers ----
    call_obj = None
    if media_type in ("call_audio", "call_video"):
        call_obj = {
            "status": doc.get("call_status"),
            "duration": doc.get("call_duration"),
            "is_video": bool(doc.get("call_is_video")),
            "reason": doc.get("call_reason"),
            "direction": "outgoing" if bool(doc.get("is_out")) else "incoming",
        }

    return {
        "id": (doc.get("msg_id") if doc.get("msg_id") is not None else doc.get("temp_id")),
        "text": doc.get("text") or "",
        "sender_id": doc.get("sender_id"),
        "sender_name": doc.get("sender_name") or "",
        "date": (doc.get("date").astimezone(timezone.utc).isoformat()
                 if isinstance(doc.get("date"), datetime) else doc.get("date")),
        "is_out": bool(doc.get("is_out", doc.get("direction") == "out")),
        "reply_to": doc.get("reply_to"),
        "media_type": media_type,      # "text" | "image" | ... | "call_audio" | "call_video"
        "media_link": media_link,      # None for calls/text
        "call": call_obj               # present only for call_* types
    }





# ---------- FULL: archive all dialogs to Mongo (runs in background) ----------
import asyncio
from datetime import datetime, timezone
async def _upsert_message_from_msg(tg_client, phone: str, chat_id: int, access_hash, msg):
    """
    Single Telegram message -> Mongo upsert (now with call detection).
    """
    MSG_COL = db.messages

    # ---- detect call service message first ----
    media_type = "text"
    media_fs_id = None
    file_name = None
    mime_type = None

    call_media_type, call_info = _call_meta_from_msg(msg)
    if call_media_type:
        media_type = call_media_type
    else:
        # ---- normal media classification ----
        if getattr(msg, "media", None):
            if getattr(msg, "photo", None): media_type = "image"
            elif getattr(msg, "video", None): media_type = "video"
            elif getattr(msg, "voice", None): media_type = "voice"
            elif getattr(msg, "audio", None): media_type = "audio"
            elif getattr(msg, "sticker", None): media_type = "sticker"
            else: media_type = "file"

            # only download real media (call service message has no downloadable media)
            try:
                blob = await msg.download_media(bytes)
                mime_type, file_name = _guess_msg_media_meta(msg)
                media_fs_id = _put_fs(db, blob, filename=file_name or "tg_import.bin", content_type=mime_type)
            except Exception:
                media_fs_id = None

    # ---- sender info (best-effort) ----
    sender_id = None
    sender_name = None
    try:
        if getattr(msg, "from_id", None):
            sender_id = getattr(msg.from_id, "user_id", None) or getattr(msg.from_id, "channel_id", None) or getattr(msg.from_id, "chat_id", None)
        if sender_id:
            ent = await tg_client.get_entity(sender_id)
            sender_name = getattr(ent, "first_name", None) or getattr(ent, "title", None)
    except Exception:
        pass

    # ---- build doc ----
    doc = {
        "phone": phone,
        "chat_id": int(chat_id),
        "access_hash": int(access_hash) if access_hash else None,
        "msg_id": int(getattr(msg, "id", 0)),
        "direction": "out" if bool(getattr(msg, "out", False)) else "in",
        "is_out": bool(getattr(msg, "out", False)),
        "text": getattr(msg, "message", "") or "",
        "sender_id": sender_id,
        "sender_name": sender_name,
        "date": getattr(msg, "date", datetime.now(timezone.utc)),
        "reply_to": getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None),
        "media_type": media_type,
        "media_fs_id": media_fs_id,
        "file_name": file_name,
        "mime_type": mime_type,
        "status": "sent" if bool(getattr(msg, "out", False)) else "arrived",
        "deleted_on_telegram": False,
    }

    # ---- enrich call meta if present ----
    if call_media_type:
        doc.update({
            "call_status": call_info["status"],
            "call_is_video": call_info["is_video"],
            "call_duration": call_info["duration"],
            "call_reason": call_info["raw_reason"],
        })

    # insert-if-absent (keep earlier copies intact)
    MSG_COL.update_one(
        {"phone": phone, "chat_id": int(chat_id), "msg_id": int(getattr(msg, "id", 0))},
        {"$setOnInsert": doc},
        upsert=True
    )













async def archive_all_dialogs(phone: str, per_chat_limit: int = 200, dialog_limit: int = 50):
    """
    Fetch recent messages for each dialog and archive to Mongo (non-blocking to /dialogs response).
    """
    from telethon import types
    try:
        tg_client = await get_client(phone)
        await tg_client.connect()
        if not await tg_client.is_user_authorized():
            print("⚠️ archive_all_dialogs: not authorized")
            await tg_client.disconnect()
            return

        archived_total = 0
        async for d in tg_client.iter_dialogs(limit=dialog_limit):
            e = d.entity
            chat_id = int(getattr(e, "id", 0))
            access_hash = getattr(e, "access_hash", None)

            # Telethon accepts entity directly as peer
            peer = e
            count = 0
            try:
                async for msg in tg_client.iter_messages(peer, limit=per_chat_limit):
                    # skip if already present
                    exists = db.messages.find_one({"phone": phone, "chat_id": chat_id, "msg_id": int(getattr(msg, "id", 0))})
                    if exists:
                        continue
                    await _upsert_message_from_msg(tg_client, phone, chat_id, access_hash, msg)
                    count += 1
                archived_total += count
                print(f"📥 archived chat {chat_id}: +{count}")
            except Exception as ex:
                print(f"⚠️ archive chat error for chat_id={chat_id}: {ex}")

        print(f"✅ archive_all_dialogs finished: +{archived_total} new")
    except Exception as e:
        print(f"❌ archive_all_dialogs fatal: {e}")
    finally:
        try:
            await tg_client.disconnect()
        except Exception:
            pass










# @app.route("/message_media")
# def message_media():
#     """
#     Serves Telegram media (photo/video/audio/voice/file)
#     """
#     import asyncio
#     from telethon import types
#     from io import BytesIO
#     from flask import send_file
#
#     phone = request.args.get("phone")
#     chat_id = int(request.args.get("chat_id"))
#     access_hash = int(request.args.get("access_hash"))
#     msg_id = int(request.args.get("msg_id"))
#
#     async def get_media():
#         tg_client = await get_client(phone)
#         await tg_client.connect()
#         peer = types.InputPeerUser(chat_id, access_hash)
#         msg = await tg_client.get_messages(peer, ids=msg_id)
#         if not msg or not msg.media:
#             await tg_client.disconnect()
#             return None
#         data = await msg.download_media(bytes)
#         await tg_client.disconnect()
#         return BytesIO(data)
#
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#     media_bytes = loop.run_until_complete(get_media())
#     if not media_bytes:
#         return "No media", 404
#
#     return send_file(media_bytes, mimetype="application/octet-stream")


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







# async def wait_for_qr(auth_id: str):
#     """
#     🔁 Fixed version: handles delayed QR approval properly.
#     """
#     import traceback, base64, asyncio
#     try:
#         cache = QR_CACHE.get(auth_id)
#         if not cache:
#             print(f"⚠️ No cache found for {auth_id}")
#             return
#
#         client = cache["client"]
#         qr = cache["qr"]
#
#         if not client.is_connected():
#             await client.connect()
#
#         print(f"⌛ [wait_for_qr] Waiting for Telegram auth for {auth_id}")
#
#         # 🔹 Wait until user scans QR (keep alive for long polling)
#         user = None
#         for attempt in range(12):  # wait up to 12 * 50s = 10 minutes
#             try:
#                 user = await asyncio.wait_for(qr.wait(), timeout=50)
#                 if user:
#                     break
#             except asyncio.TimeoutError:
#                 # keep alive check
#                 if not client.is_connected():
#                     await client.connect()
#                 print(f"⏳ waiting... ({attempt+1}/12)")
#                 continue
#
#         if not user:
#             print(f"⏰ Timeout: No authorization for {auth_id}")
#             QR_COLLECTION.update_one(
#                 {"auth_id": auth_id},
#                 {"$set": {"status": "expired", "updated_at": datetime.now(timezone.utc)}}
#             )
#             await client.disconnect()
#             return
#
#         # ✅ Authorized user
#         phone = getattr(user, "phone", None) or f"qr_{auth_id[:8]}"
#         print(f"✅ Telegram QR Authorized → {user.first_name} ({phone})")
#
#         await save_session(phone, client)
#
#         # --- Make JSON-safe ---
#         def make_json_safe(obj):
#             if isinstance(obj, dict):
#                 return {k: make_json_safe(v) for k, v in obj.items()}
#             elif isinstance(obj, list):
#                 return [make_json_safe(v) for v in obj]
#             elif isinstance(obj, bytes):
#                 return base64.b64encode(obj).decode("utf-8")
#             elif isinstance(obj, datetime):
#                 return obj.isoformat()
#             else:
#                 return obj
#
#         user_data = make_json_safe(user.to_dict())
#
#         # ✅ MongoDB update
#         QR_COLLECTION.update_one(
#             {"auth_id": auth_id},
#             {"$set": {
#                 "status": "authorized",
#                 "user": user_data,
#                 "updated_at": datetime.now(timezone.utc)
#             }},
#             upsert=True
#         )
#
#         print(f"💾 MongoDB updated → authorized for {auth_id}")
#         await client.disconnect()
#
#     except Exception as e:
#         print(f"❌ Fatal in wait_for_qr: {e}")
#         print(traceback.format_exc())
#         try:
#             await client.disconnect()
#         except:
#             pass




# ✅ 2️⃣ Wait for QR Authorization (Final Fixed)
# ✅ 2️⃣ Wait for QR Authorization (Final Fixed)
async def wait_for_qr(auth_id: str):
    """
    🔁 Waits for Telegram QR authorization, saves session, and updates MongoDB.
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

        user = None
        for attempt in range(12):  # wait up to 10 minutes
            try:
                user = await asyncio.wait_for(qr.wait(), timeout=50)
                if user:
                    break
            except asyncio.TimeoutError:
                if not client.is_connected():
                    await client.connect()
                print(f"⏳ waiting... ({attempt + 1}/12)")
                continue

        if not user:
            print(f"⏰ Timeout: No authorization for {auth_id}")
            QR_COLLECTION.update_one(
                {"auth_id": auth_id},
                {"$set": {"status": "expired", "updated_at": datetime.now(timezone.utc)}}
            )
            await client.disconnect()
            return

        # ✅ Authorized user found
        phone = getattr(user, "phone", None)
        if not phone:
            # যদি Telegram user ফোন নম্বর না দেয় (bot / anonymous)
            phone = f"qr_{auth_id[:8]}"

        print(f"✅ Telegram QR Authorized → {user.first_name} ({phone})")

        # ✅ Save Telegram session
        await save_session(phone, client)

        # ✅ Convert safely to JSON
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

        # ✅ MongoDB update with phone + status
        QR_COLLECTION.update_one(
            {"auth_id": auth_id},
            {"$set": {
                "status": "authorized",
                "user": user_data,
                "phone": phone,
                "updated_at": datetime.now(timezone.utc)
            }},
            upsert=True
        )

        print(f"💾 MongoDB updated → authorized for {auth_id} ({phone})")
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

# threading.Thread(target=qr_cleaner, daemon=True).start()





# --- CALL helpers (1:1 voice/video call service message) ---
from telethon.tl.types import MessageService, MessageActionPhoneCall

def _parse_call_action(action, is_out: bool):
    """
    MessageActionPhoneCall → normalized call meta
    """
    reason = type(getattr(action, 'reason', None)).__name__ if getattr(action, 'reason', None) else None
    dur = getattr(action, 'duration', None)
    is_video = bool(getattr(action, 'video', False))

    if reason == 'PhoneCallDiscardReasonMissed':
        status = 'missed'
    elif reason == 'PhoneCallDiscardReasonBusy':
        status = 'busy'
    elif reason == 'PhoneCallDiscardReasonHangup':
        status = 'canceled'
    elif reason == 'PhoneCallDiscardReasonDisconnect':
        status = 'ended'
    elif dur:
        status = 'ended'
    else:
        status = 'unknown'

    return {
        "status": status,
        "direction": "outgoing" if is_out else "incoming",
        "duration": dur,
        "is_video": is_video,
        "raw_reason": reason,
    }

def _call_meta_from_msg(msg):
    """
    Telethon Message → (media_type, call_info) or (None, None)
    media_type: 'call_audio' | 'call_video'
    """
    action = getattr(msg, "action", None)
    if isinstance(msg, MessageService) and isinstance(action, MessageActionPhoneCall):
        info = _parse_call_action(action, bool(getattr(msg, "out", False)))
        media_type = "call_video" if info["is_video"] else "call_audio"
        return media_type, info
    return None, None










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
