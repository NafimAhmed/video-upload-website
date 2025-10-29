
import os
import asyncio
from urllib.parse import urlencode, urljoin

from flask import Flask, redirect, send_file, has_request_context
from flask_sock import Sock
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import (
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
    PhoneNumberInvalidError, UsernameNotOccupiedError, UsernameInvalidError, UserPrivacyRestrictedError,
    ChatWriteForbiddenError, FloodWaitError, PeerIdInvalidError,
)
from queue import Queue, Empty
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



import asyncio, os
from telethon import TelegramClient
from telethon.sessions import StringSession

async def get_client(phone: str):
    """
    Hardened Telethon client with infinite auto-reconnect.
    """
    safe_phone = phone.strip().replace("+", "").replace(" ", "")
    doc = db.sessions.find_one({"phone": safe_phone})
    if doc and "session_string" in doc and doc["session_string"]:
        session_str = doc["session_string"]
        print(f"🔹 Restoring existing session for {phone}")
    else:
        session_str = ""
        print(f"⚠️ No session found for {phone}, creating new one.")

    # 🔒 hardened config
    client = TelegramClient(
        StringSession(session_str),
        API_ID,
        API_HASH,
        auto_reconnect=True,
        connection_retries=None,   # infinite
        retry_delay=2,             # seconds
        request_retries=5,
        flood_sleep_threshold=600  # auto-sleep up to 10 min on flood waits
    )
    return client
# ==============================================================










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
    UpdateUserTyping, UpdateChatUserTyping, UpdateChannelUserTyping, PeerChat, PeerUser, PeerChannel, UpdateNewMessage,
    UpdateNewChannelMessage
)
import asyncio, threading, json, time
from datetime import datetime, timezone

# --------------------------------------
# SMALL HELPER: map Telegram typing action → human name
# --------------------------------------





# ---------- tiny helpers used across WS handlers ----------
from datetime import datetime, timezone

def _now():
    return datetime.now(timezone.utc).isoformat()

def _peer_id(pid):
    if isinstance(pid, PeerUser): return pid.user_id
    if isinstance(pid, PeerChat): return pid.chat_id
    if isinstance(pid, PeerChannel): return pid.channel_id
    return None




def _event_media_type_fast(msg) -> str:
    """
    Fast media type detector (service/call aware)
    """
    act = getattr(msg, "action", None)
    # ✅ Call service message → call_* (NOT text)
    if isinstance(msg, MessageService) and isinstance(act, MessageActionPhoneCall):
        return "call_video" if bool(getattr(act, "video", False)) else "call_audio"

    # Others (same as before)
    if getattr(msg, "photo", None):    return "image"
    if getattr(msg, "video", None):    return "video"
    if getattr(msg, "voice", None):    return "voice"
    if getattr(msg, "audio", None):    return "audio"
    if getattr(msg, "sticker", None):  return "sticker"
    if getattr(msg, "media", None):    return "file"
    return "text"







from telethon.tl.types import MessageService, MessageActionPhoneCall  # ensure imported

def _event_to_api_quick(phone: str, chat_id: int, access_hash: int | None, event) -> dict:
    msg = event.message

    # call meta (if any)
    call_obj = None
    media_type = _event_media_type_fast(msg)
    if media_type in ("call_audio", "call_video"):
        try:
            info = _parse_call_action(getattr(msg, "action", None), bool(getattr(msg, "out", False)))
        except Exception:
            info = None
        if isinstance(info, dict):
            call_obj = {
                "status": info.get("status"),
                "duration": info.get("duration"),
                "is_video": bool(info.get("is_video")),
                "reason": info.get("raw_reason"),
                "direction": "outgoing" if info.get("direction") == "outgoing" else "incoming",
            }

    # media link only for non-text/non-call
    media_link = None
    if media_type not in ("text", "call_audio", "call_video"):
        params = {
            "phone": str(phone),
            "chat_id": int(chat_id),
            "msg_id": int(getattr(msg, "id", 0)),
        }
        if access_hash is not None:
            params["access_hash"] = int(access_hash)
        qs = urlencode(params, doseq=False, safe="")
        media_link = urljoin(_base_url(), f"message_media?{qs}")

    return {
        "id": int(getattr(msg, "id", 0)),
        "text": getattr(msg, "message", "") or "",
        "sender_id": None,
        "sender_name": "",
        "date": (getattr(msg, "date", None) or datetime.now(timezone.utc)).isoformat(),
        "is_out": bool(getattr(msg, "out", False)),
        "reply_to": getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None),
        "media_type": media_type,
        "media_link": media_link,
        "call": call_obj,
        "deleted_on_telegram": False,
        "exists_on_telegram": True,
    }
















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
















from collections import deque
import os, json, threading, time
from queue import Queue, Empty
from io import BytesIO
from urllib.parse import urlencode, urljoin

from gridfs import GridFS
from bson.objectid import ObjectId

from telethon import events, functions, types
from telethon.tl.types import (
    InputPeerUser, InputPeerChannel, InputPeerChat,
    UpdateUserTyping, UpdateChatUserTyping, UpdateChannelUserTyping,
)

def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()











from threading import RLock
ACTIVE_TG: dict[str, TelegramClient] = {}
ACTIVE_TG_LOCK = RLock()
# @sock.route("/chat_ws")
# def chat_ws(ws):
#     """
#     INIT (first frame):
#       {"phone":"<E.164>", "chat_id": <int>, "access_hash": <int|null>}
#     Then commands:
#       {"action":"send", "text":"hi"}  OR file_* keys
#       {"action":"typing_start"} / {"action":"typing_stop"}
#       {"action":"ping"} / {"action":"stop"}
#
#     Server emits:
#       {"status":"listening", "chat_id":"..."}
#       {"action":"seed", "messages":[...]}                # last 50 from Mongo (newest-last)
#       {"action":"new_message", ...}                      # realtime
#       {"action":"typing", ...} / {"action":"typing_stopped", ...}
#       {"action":"send_queued", "temp_id": "...", ...}    # immediate ack
#       {"action":"upload_progress", "temp_id":"...", "progress": 37.5}
#       {"action":"send_done", "temp_id":"...", "msg_id": 123, ...}
#       {"status":"error", "detail":"..."}
#     """
#     import json, threading, asyncio, os, time
#     from queue import Queue, Empty
#     from gridfs import GridFS
#     from bson.objectid import ObjectId
#     from io import BytesIO
#     from datetime import datetime, timezone
#     from threading import Timer
#
#     from telethon import events, functions, types
#     from telethon.tl.types import (
#         UpdateUserTyping, UpdateChatUserTyping, UpdateChannelUserTyping,
#         UpdateNewMessage, UpdateNewChannelMessage,
#         MessageService, MessageActionPhoneCall,
#         InputPeerUser, InputPeerChannel, InputPeerChat
#     )
#
#     print("🔗 [chat_ws] connected")
#
#     # ---------- single writer (never call ws.send from multiple threads) ----------
#     alive = True
#     out_q: Queue = Queue(maxsize=1000)
#
#     def ws_send(obj):
#         if not alive:
#             return
#         try:
#             out_q.put_nowait(obj)
#         except Exception:
#             # drop noisy events if congested
#             if isinstance(obj, dict) and obj.get("action") in ("upload_progress", "typing"):
#                 return
#             out_q.put(obj)
#
#     def writer():
#         nonlocal alive
#         while alive:
#             try:
#                 item = out_q.get(timeout=1)
#             except Empty:
#                 continue
#             if item is None:
#                 break
#             try:
#                 payload = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
#                 ws.send(payload)
#             except Exception as e:
#                 alive = False
#                 try: print(f"⚠️ ws writer send failed: {e}")
#                 except: pass
#                 break
#
#     threading.Thread(target=writer, daemon=True).start()
#
#     def safe_receive():
#         try:
#             return ws.receive()
#         except Exception as e:
#             if "closed" in str(e).lower():
#                 return None
#             raise
#
#     # ---------- INIT (FIRST FRAME = registration) ----------
#     init_msg = safe_receive()
#     if not init_msg:
#         print("❌ [chat_ws] no init, closing")
#         alive = False; out_q.put(None); return
#
#     try:
#         init = json.loads(init_msg)
#     except Exception:
#         ws_send({"status": "error", "detail": "invalid init json"})
#         alive = False; out_q.put(None); return
#
#     phone = (init.get("phone") or "").strip()
#     chat_id_raw = init.get("chat_id")
#     access_hash_raw = init.get("access_hash")
#
#     if not phone or chat_id_raw is None:
#         ws_send({"status": "error", "detail": "phone/chat_id missing"})
#         alive = False; out_q.put(None); return
#
#     try:
#         chat_id = int(chat_id_raw)
#     except Exception:
#         ws_send({"status": "error", "detail": "chat_id must be int"})
#         alive = False; out_q.put(None); return
#
#     try:
#         access_hash = int(access_hash_raw) if access_hash_raw not in (None, "") else None
#     except Exception:
#         access_hash = None
#
#     # Ensure PUBLIC_BASE_URL for absolute media_link in WS context
#     try:
#         host = ws.environ.get("HTTP_HOST") or "127.0.0.1:8080"
#         scheme = "https" if (ws.environ.get("wsgi.url_scheme") == "https" or
#                              ws.environ.get("HTTP_X_FORWARDED_PROTO") == "https") else "http"
#         os.environ.setdefault("PUBLIC_BASE_URL", f"{scheme}://{host}/")
#     except Exception:
#         pass
#
#     # ---------- Mongo bits ----------
#     MSG_COL = db.messages
#     try:
#         MSG_COL.create_index(
#             [("phone", 1), ("chat_id", 1), ("msg_id", 1)],
#             name="uniq_msg",
#             unique=True,
#             partialFilterExpression={"msg_id": {"$type": "number"}}
#         )
#     except Exception:
#         pass
#     fs = GridFS(db, collection="fs")
#
#     # ---------- Telethon listener (global loop) ----------
#     tg_client = None
#
#     async def resolve_entity():
#         try:
#             if access_hash:
#                 try: return InputPeerUser(int(chat_id), int(access_hash))
#                 except:
#                     try: return InputPeerChannel(int(chat_id), int(access_hash))
#                     except: return InputPeerChat(int(chat_id))
#             else:
#                 return await tg_client.get_entity(int(chat_id))
#         except:
#             return InputPeerChat(int(chat_id))
#
#     # --- typing TTL via one-shot timers (NO sleep loop) ---
#     TYPING_TTL = 6.0
#     typing_timers: dict[tuple[int,int], Timer] = {}
#
#     def schedule_typing_stop(cid: int, uid: int):
#         key = (cid, uid)
#         old = typing_timers.pop(key, None)
#         if old:
#             try: old.cancel()
#             except: pass
#
#         def fire():
#             if not alive: return
#             ws_send({"action": "typing_stopped", "chat_id": str(cid), "sender_id": uid, "date": _now()})
#             typing_timers.pop(key, None)
#
#         t = Timer(TYPING_TTL, fire)
#         t.daemon = True
#         typing_timers[key] = t
#         t.start()
#
#     async def run_listener():
#         nonlocal tg_client
#         tg_client = await get_client(phone)
#         await tg_client.connect()
#         if not await tg_client.is_user_authorized():
#             ws_send({"status": "error", "detail": "not authorized"})
#             await tg_client.disconnect()
#             return
#
#         # 🔗 register active client for this phone so /message_media can reuse it
#         try:
#             with ACTIVE_TG_LOCK:
#                 ACTIVE_TG[phone] = tg_client
#         except Exception:
#             pass
#
#         ws_send({"status": "listening", "chat_id": str(chat_id)})
#
#         # 1) seed last 50 from Mongo (newest last)
#         try:
#             seed_docs = list(
#                 MSG_COL.find({"phone": phone, "chat_id": int(chat_id)})
#                        .sort([("date", -1), ("msg_id", -1)]).limit(50)
#             )
#             seed_docs.reverse()
#             if seed_docs:
#                 ws_send({"action": "seed",
#                          "messages": [_doc_to_api(phone, int(chat_id), access_hash, d) for d in seed_docs]})
#         except Exception as se:
#             print("⚠️ seed history error:", se)
#
#         # 2) realtime emit + lazy archive
#         @tg_client.on(events.NewMessage(chats=int(chat_id)))
#         async def on_new_msg(event):
#             try:
#                 quick = _event_to_api_quick(phone, int(chat_id), access_hash, event)
#                 ws_send({"action": "new_message", **quick})
#                 async def _bg():
#                     try:
#                         await archive_incoming_event(db, phone, int(chat_id), access_hash, event)
#                     except Exception as e:
#                         print("⚠️ bg archive error:", e)
#                 asyncio.create_task(_bg())
#             except Exception as e:
#                 print(f"⚠️ new_message emit error: {e}")
#
#         # 3) typing indicators (timers handle stop)
#         @tg_client.on(events.Raw)
#         async def on_typing_raw(update):
#             try:
#                 upd_chat_id, user_id = None, None
#                 if isinstance(update, UpdateUserTyping):
#                     upd_chat_id = int(update.user_id); user_id = int(update.user_id)
#                 elif isinstance(update, UpdateChatUserTyping):
#                     upd_chat_id = int(update.chat_id); user_id = int(update.user_id)
#                 elif isinstance(update, UpdateChannelUserTyping):
#                     upd_chat_id = int(update.channel_id); user_id = int(update.user_id)
#                 if upd_chat_id and int(upd_chat_id) == int(chat_id):
#                     ws_send({"action": "typing", "chat_id": str(upd_chat_id),
#                              "sender_id": user_id, "typing": True, "date": _now()})
#                     schedule_typing_stop(upd_chat_id, user_id)
#             except Exception as e:
#                 print(f"⚠️ typing event error: {e}")
#
#         # 4) call service messages → persist + emit normalized
#         @tg_client.on(events.Raw)
#         async def on_raw_calllog(update):
#             try:
#                 if isinstance(update, (UpdateNewMessage, UpdateNewChannelMessage)):
#                     msg = update.message
#                     pid = _peer_id(getattr(msg, 'peer_id', None))
#                     if pid is None or int(pid) != int(chat_id):
#                         return
#                     if isinstance(msg, MessageService) and isinstance(msg.action, MessageActionPhoneCall):
#                         await _upsert_message_from_msg(tg_client, phone, int(chat_id), access_hash, msg)
#                         saved = MSG_COL.find_one({"phone": phone, "chat_id": int(chat_id),
#                                                   "msg_id": int(getattr(msg, "id", 0))})
#                         if saved:
#                             ws_send({"action": "new_message",
#                                      **_doc_to_api(phone, int(chat_id), access_hash, saved)})
#             except Exception as e:
#                 print(f"⚠️ raw calllog error: {e}")
#
#         await tg_client.run_until_disconnected()
#
#     # schedule on your global loop (must exist: `loop = asyncio.new_event_loop()` started in bg)
#     asyncio.run_coroutine_threadsafe(run_listener(), loop)
#
#     # ---------- upload progress throttle (no sleep, just time-based) ----------
#     progress_last = 0.0
#     def progress_emit(temp_id: str, pct: float):
#         nonlocal progress_last
#         now = time.time()
#         if now - progress_last < 0.15:
#             return
#         progress_last = now
#         ws_send({"action": "upload_progress", "temp_id": temp_id, "progress": pct})
#
#     # ---------- WS receive loop (commands) ----------
#     try:
#         while alive:
#             rec = safe_receive()
#             if rec is None:
#                 break
#             try:
#                 data = json.loads(rec)
#             except Exception:
#                 ws_send({"status": "error", "detail": "invalid json"})
#                 continue
#
#             act = data.get("action")
#
#             if act == "stop":
#                 break
#
#             elif act == "ping":
#                 ws_send({"status": "pong"})
#
#             elif act in ("typing_start", "typing_stop"):
#                 async def do_typing(act_=act):
#                     try:
#                         if not tg_client: return
#                         peer = await resolve_entity()
#                         req = (types.SendMessageTypingAction() if act_ == "typing_start"
#                                else types.SendMessageCancelAction())
#                         await tg_client(functions.messages.SetTypingRequest(peer=peer, action=req))
#                         ws_send({"status": f"{act_}_ok"})
#                     except Exception as e:
#                         ws_send({"status": "error", "detail": str(e)})
#                 asyncio.run_coroutine_threadsafe(do_typing(), loop)
#
#             elif act == "send":
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
#                 async def do_send():
#                     pre = None
#                     try:
#                         if not tg_client or not await tg_client.is_user_authorized():
#                             ws_send({"status": "error", "detail": "not authorized"})
#                             return
#
#                         # 1) DB pending insert + immediate ack
#                         pre = await archive_outgoing_pre(
#                             db=db, phone=phone, chat_id=int(chat_id), access_hash=access_hash,
#                             text=text, reply_to_id=reply_to_id,
#                             file_b64=file_b64, file_name=file_name, mime_type=mime_type
#                         )
#                         ws_send({
#                             "action": "send_queued",
#                             "temp_id": pre["temp_id"],
#                             "text": text or "",
#                             "media_type": pre["media_type"],
#                             "date": pre["date"].astimezone(timezone.utc).isoformat()
#                         })
#
#                         # 2) send to Telegram
#                         peer = await resolve_entity()
#                         msg_obj = None
#
#                         def cb(sent, total):
#                             pct = round((sent / max(1, total)) * 100.0, 1)
#                             progress_emit(pre["temp_id"], pct)
#
#                         if pre["media_type"] == "text":
#                             msg_obj = await tg_client.send_message(peer, text or "", reply_to=reply_to_id)
#                         else:
#                             blob = None
#                             if pre.get("media_fs_id"):
#                                 try:
#                                     blob = fs.get(ObjectId(pre["media_fs_id"])).read()
#                                 except Exception:
#                                     blob = None
#                             bio = BytesIO(blob) if blob else None
#                             if bio: bio.name = file_name
#
#                             mt = pre["media_type"]
#                             if mt == "voice":
#                                 msg_obj = await tg_client.send_file(
#                                     peer, bio, caption=text or "", voice_note=True,
#                                     reply_to=reply_to_id, progress_callback=cb
#                                 )
#                             elif mt == "video":
#                                 msg_obj = await tg_client.send_file(
#                                     peer, bio, caption=text or "", supports_streaming=True,
#                                     reply_to=reply_to_id, progress_callback=cb
#                                 )
#                             else:
#                                 msg_obj = await tg_client.send_file(
#                                     peer, bio, caption=text or "", reply_to=reply_to_id,
#                                     progress_callback=cb
#                                 )
#
#                         # 3) DB finalize + final ack
#                         await archive_outgoing_finalize(db, phone, int(chat_id), pre["temp_id"], msg_obj)
#                         ws_send({
#                             "action": "send_done",
#                             "temp_id": pre["temp_id"],
#                             "msg_id": int(getattr(msg_obj, "id", 0)),
#                             "date": getattr(msg_obj, "date", datetime.now(timezone.utc)).isoformat()
#                         })
#                         # NewMessage echo will also arrive via handler
#
#                     except Exception as e:
#                         err = {"status": "error", "detail": str(e)}
#                         if pre:
#                             err.update({"action": "send_failed", "temp_id": pre["temp_id"]})
#                         ws_send(err)
#
#                 asyncio.run_coroutine_threadsafe(do_send(), loop)
#
#             else:
#                 ws_send({"status": "error", "detail": "unknown action"})
#
#     except Exception as e:
#         if "closed" in str(e).lower():
#             print(f"ℹ️ [chat_ws] client closed: {e}")
#         else:
#             print(f"⚠️ [chat_ws] Exception: {e}")
#     finally:
#         # shutdown
#         alive = False
#         out_q.put(None)
#         # cancel typing timers
#         for t in list(typing_timers.values()):
#             try: t.cancel()
#             except: pass
#         # unregister active client (only if this ws owns it)
#         try:
#             with ACTIVE_TG_LOCK:
#                 if ACTIVE_TG.get(phone) is tg_client:
#                     ACTIVE_TG.pop(phone, None)
#         except Exception:
#             pass
#         try:
#             if tg_client:
#                 asyncio.run_coroutine_threadsafe(tg_client.disconnect(), loop).result(timeout=5)
#         except Exception:
#             pass
#         print("❌ [chat_ws] disconnected")













from threading import RLock, Timer
from queue import Queue, Empty

@sock.route("/chat_ws")
def chat_ws(ws):
    """
    INIT (first frame from client):
      {"phone":"<E.164>", "chat_id": <int>, "access_hash": <int|null>}
    Then commands (subsequent frames):
      {"action":"send", "text":"hi"}  OR file_* keys (file_base64/file_name/mime_type, reply_to)
      {"action":"typing_start"} / {"action":"typing_stop"}
      {"action":"ping"} / {"action":"stop"}

    Server emits (single-writer, de-duped):
      {"status":"listening", "chat_id":"..."}
      {"action":"seed", "messages":[...]}                # last 50 from Mongo (newest-last)
      {"action":"new_message", ...}                      # realtime + gap-fill
      {"action":"typing", ...} / {"action":"typing_stopped", ...}
      {"action":"upload_progress", "temp_id":"...", "progress": 37.5}
      {"action":"send_queued", "temp_id": "...", ...}
      {"action":"send_done", "temp_id": "...", "msg_id": 123, ...}
      {"status":"error", "detail":"..."}
    """
    import json, threading, asyncio, os, time
    from datetime import datetime, timezone
    from urllib.parse import urlencode, urljoin

    from telethon import events, functions, types
    from telethon.tl.types import (
        UpdateUserTyping, UpdateChatUserTyping, UpdateChannelUserTyping,
        UpdateNewMessage, UpdateNewChannelMessage,
        MessageService, MessageActionPhoneCall,
        PeerUser, PeerChat, PeerChannel
    )
    from gridfs import GridFS
    from bson.objectid import ObjectId
    from io import BytesIO

    print("🔗 [chat_ws] connected")

    # ---------- small helpers ----------
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def _peer_id(pid):
        if isinstance(pid, PeerUser): return pid.user_id
        if isinstance(pid, PeerChat): return pid.chat_id
        if isinstance(pid, PeerChannel): return pid.channel_id
        return None

    # ---------- single writer (never call ws.send from multiple threads) ----------
    alive = True
    out_q: Queue = Queue(maxsize=1000)

    def ws_send(obj):
        """Thread-safe enqueue; drops noisy events if congested."""
        if not alive:
            return
        try:
            out_q.put_nowait(obj)
        except Exception:
            if isinstance(obj, dict) and obj.get("action") in ("upload_progress", "typing"):
                return
            out_q.put(obj)

    def writer():
        nonlocal alive
        while alive:
            try:
                item = out_q.get(timeout=1)
            except Empty:
                continue
            if item is None:
                break
            try:
                payload = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
                ws.send(payload)
            except Exception as e:
                alive = False
                try: print(f"⚠️ ws writer send failed: {e}")
                except: pass
                break

    threading.Thread(target=writer, daemon=True).start()

    def safe_receive():
        try:
            return ws.receive()
        except Exception as e:
            if "closed" in str(e).lower():
                return None
            raise

    # ---------- INIT (FIRST FRAME = registration) ----------
    init_msg = safe_receive()
    if not init_msg:
        print("❌ [chat_ws] no init, closing")
        alive = False; out_q.put(None); return

    try:
        init = json.loads(init_msg)
    except Exception:
        ws_send({"status": "error", "detail": "invalid init json"})
        alive = False; out_q.put(None); return

    phone = (init.get("phone") or "").strip()
    chat_id_raw = init.get("chat_id")
    access_hash_raw = init.get("access_hash")

    if not phone or chat_id_raw is None:
        ws_send({"status": "error", "detail": "phone/chat_id missing"})
        alive = False; out_q.put(None); return

    try:
        chat_id = int(chat_id_raw)
    except Exception:
        ws_send({"status": "error", "detail": "chat_id must be int"})
        alive = False; out_q.put(None); return

    try:
        access_hash = int(access_hash_raw) if access_hash_raw not in (None, "") else None
    except Exception:
        access_hash = None

    # Ensure PUBLIC_BASE_URL for absolute media_link in WS context
    try:
        host = ws.environ.get("HTTP_HOST") or "127.0.0.1:8080"
        scheme = "https" if (ws.environ.get("wsgi.url_scheme") == "https" or
                             ws.environ.get("HTTP_X_FORWARDED_PROTO") == "https") else "http"
        os.environ.setdefault("PUBLIC_BASE_URL", f"{scheme}://{host}/")
    except Exception:
        pass

    # ---------- Mongo & FS ----------
    MSG_COL = db.messages
    try:
        MSG_COL.create_index(
            [("phone", 1), ("chat_id", 1), ("msg_id", 1)],
            name="uniq_msg",
            unique=True,
            partialFilterExpression={"msg_id": {"$type": "number"}}
        )
    except Exception:
        pass

    fs = GridFS(db, collection="fs")

    # --- typing TTL via one-shot timers (NO sleep loop) ---
    TYPING_TTL = 6.0
    typing_timers: dict[tuple[int,int], Timer] = {}

    def schedule_typing_stop(cid: int, uid: int):
        key = (cid, uid)
        old = typing_timers.pop(key, None)
        if old:
            try: old.cancel()
            except: pass

        def fire():
            if not alive: return
            ws_send({"action": "typing_stopped", "chat_id": str(cid), "sender_id": uid, "date": _now()})
            typing_timers.pop(key, None)

        t = Timer(TYPING_TTL, fire)
        t.daemon = True
        typing_timers[key] = t
        t.start()

    # ---------- Telethon listener (on the shared asyncio loop) ----------
    tg_client = None

    async def run_listener():
        """
        Connect → attach handlers immediately → send 'listening' →
        seed last 50 from Mongo → fill gap since last_db_id (no sleeps) →
        run_until_disconnected()
        """
        from collections import deque
        nonlocal tg_client
        tg_client = await get_client(phone)
        await tg_client.connect()

        if not await tg_client.is_user_authorized():
            ws_send({"status": "error", "detail": "not authorized"})
            await tg_client.disconnect()
            return

        # register active client so /message_media can reuse it
        try:
            with ACTIVE_TG_LOCK:
                ACTIVE_TG[phone] = tg_client
        except Exception:
            pass

        # --- de-dupe ring for emitted ids (seed/gap/handler overlap safe) ---
        EMIT_RING = deque(maxlen=600)
        EMIT_SET = set()

        def _mark_seen(mid: int | None) -> bool:
            if not isinstance(mid, int):
                return False  # treat as unseen
            if mid in EMIT_SET:
                return True
            EMIT_RING.append(mid)
            EMIT_SET.add(mid)
            while len(EMIT_SET) > EMIT_RING.maxlen:
                old = EMIT_RING.popleft()
                EMIT_SET.discard(old)
            return False

        # --- resolve peer once (robust) ---
        peer = await _resolve_peer_any(tg_client, int(chat_id), access_hash)

        # --- attach handlers FIRST (so nothing is missed after connect) ---
        async def _on_new_message(event):
            try:
                quick = _event_to_api_quick(phone, int(chat_id), access_hash, event)
                mid = quick.get("id")
                if not _mark_seen(mid):
                    ws_send({"action": "new_message", **quick})
                # lazy archive
                async def _bg():
                    try:
                        await archive_incoming_event(db, phone, int(chat_id), access_hash, event)
                    except Exception as e:
                        print("⚠️ bg archive error:", e)
                asyncio.create_task(_bg())
            except Exception as e:
                print(f"⚠️ new_message emit error: {e}")

        tg_client.add_event_handler(_on_new_message, events.NewMessage(chats=peer))

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
                    ws_send({"action": "typing", "chat_id": str(upd_chat_id),
                             "sender_id": user_id, "typing": True, "date": _now()})
                    schedule_typing_stop(upd_chat_id, user_id)
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
                        await _upsert_message_from_msg(tg_client, phone, int(chat_id), access_hash, msg)
                        saved = MSG_COL.find_one({"phone": phone, "chat_id": int(chat_id),
                                                  "msg_id": int(getattr(msg, "id", 0))})
                        if saved:
                            mid = int(getattr(msg, "id", 0))
                            if not _mark_seen(mid):
                                ws_send({"action": "new_message",
                                         **_doc_to_api(phone, int(chat_id), access_hash, saved)})
            except Exception as e:
                print(f"⚠️ raw calllog error: {e}")

        # --- now we are safely 'listening' ---
        ws_send({"status": "listening", "chat_id": str(chat_id)})

        # --- seed (Mongo newest→oldest, then reverse) ---
        last_db = MSG_COL.find_one(
            {"phone": phone, "chat_id": int(chat_id), "msg_id": {"$type": "number"}},
            sort=[("msg_id", -1)]
        )
        last_db_id = int(last_db["msg_id"]) if last_db else 0

        try:
            seed_docs = list(
                MSG_COL.find({"phone": phone, "chat_id": int(chat_id)})
                       .sort([("date", -1), ("msg_id", -1)]).limit(50)
            )
            seed_docs.reverse()
            if seed_docs:
                for d in seed_docs:
                    if isinstance(d.get("msg_id"), int):
                        _mark_seen(int(d["msg_id"]))
                ws_send({"action": "seed",
                         "messages": [_doc_to_api(phone, int(chat_id), access_hash, d) for d in seed_docs]})
        except Exception as se:
            print("⚠️ seed history error:", se)

        # --- fill gap since last_db_id (covers race) ---
        async def _fill_gap_since(min_id: int):
            try:
                if not min_id:
                    return
                got = []
                async for m in tg_client.iter_messages(peer, min_id=min_id, limit=200):
                    got.append(m)
                # emit oldest→newest
                for m in reversed(got):
                    class _Evt:
                        def __init__(self, cli, message): self.client, self.message = cli, message
                    quick = _event_to_api_quick(phone, int(chat_id), access_hash, _Evt(tg_client, m))
                    mid = quick.get("id")
                    if not _mark_seen(mid):
                        ws_send({"action": "new_message", **quick})
                    async def _bg2(msg_):
                        try:
                            await _upsert_message_from_msg(tg_client, phone, int(chat_id), access_hash, msg_)
                        except Exception as e:
                            print("⚠️ gap archive error:", e)
                    asyncio.create_task(_bg2(m))
            except Exception as e:
                print(f"⚠️ gap fill error: {e}")

        asyncio.create_task(_fill_gap_since(last_db_id))

        # --- process updates forever (no sleeps) ---
        await tg_client.run_until_disconnected()

    # schedule listener on the global loop
    asyncio.run_coroutine_threadsafe(run_listener(), loop)

    # ---------- upload progress throttle (no sleep, just time-based) ----------
    progress_last = 0.0
    def progress_emit(temp_id: str, pct: float):
        nonlocal progress_last
        now = time.time()
        if now - progress_last < 0.15:
            return
        progress_last = now
        ws_send({"action": "upload_progress", "temp_id": temp_id, "progress": pct})

    # ---------- WS command loop ----------
    try:
        while alive:
            rec = safe_receive()
            if rec is None:
                break
            try:
                data = json.loads(rec)
            except Exception:
                ws_send({"status": "error", "detail": "invalid json"})
                continue

            act = data.get("action")

            if act == "stop":
                break

            elif act == "ping":
                ws_send({"status": "pong"})

            elif act in ("typing_start", "typing_stop"):
                async def do_typing(act_=act):
                    try:
                        if not tg_client: return
                        peer = await _resolve_peer_any(tg_client, int(chat_id), access_hash)
                        req = (types.SendMessageTypingAction() if act_ == "typing_start"
                               else types.SendMessageCancelAction())
                        await tg_client(functions.messages.SetTypingRequest(peer=peer, action=req))
                        ws_send({"status": f"{act_}_ok"})
                    except Exception as e:
                        ws_send({"status": "error", "detail": str(e)})
                asyncio.run_coroutine_threadsafe(do_typing(), loop)

            elif act == "send":
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
                    pre = None
                    try:
                        if not tg_client or not await tg_client.is_user_authorized():
                            ws_send({"status": "error", "detail": "not authorized"})
                            return

                        # 1) DB pending insert + immediate ack
                        pre = await archive_outgoing_pre(
                            db=db, phone=phone, chat_id=int(chat_id), access_hash=access_hash,
                            text=text, reply_to_id=reply_to_id,
                            file_b64=file_b64, file_name=file_name, mime_type=mime_type
                        )
                        ws_send({
                            "action": "send_queued",
                            "temp_id": pre["temp_id"],
                            "text": text or "",
                            "media_type": pre["media_type"],
                            "date": pre["date"].astimezone(timezone.utc).isoformat()
                        })

                        # 2) send to Telegram
                        peer = await _resolve_peer_any(tg_client, int(chat_id), access_hash)
                        msg_obj = None

                        def cb(sent, total):
                            try:
                                pct = round((sent / max(1, total)) * 100.0, 1)
                            except Exception:
                                pct = 0.0
                            progress_emit(pre["temp_id"], pct)

                        if pre["media_type"] == "text":
                            msg_obj = await tg_client.send_message(peer, text or "", reply_to=reply_to_id)
                        else:
                            # load bytes from GridFS (saved in archive_outgoing_pre)
                            blob = None
                            if pre.get("media_fs_id"):
                                try:
                                    blob = fs.get(ObjectId(pre["media_fs_id"])).read()
                                except Exception:
                                    blob = None
                            bio = BytesIO(blob) if blob else None
                            if bio: bio.name = file_name

                            mt = pre["media_type"]
                            if mt == "voice":
                                msg_obj = await tg_client.send_file(
                                    peer, bio, caption=text or "", voice_note=True,
                                    reply_to=reply_to_id, progress_callback=cb
                                )
                            elif mt == "video":
                                msg_obj = await tg_client.send_file(
                                    peer, bio, caption=text or "", supports_streaming=True,
                                    reply_to=reply_to_id, progress_callback=cb
                                )
                            else:
                                msg_obj = await tg_client.send_file(
                                    peer, bio, caption=text or "", reply_to=reply_to_id,
                                    progress_callback=cb
                                )

                        # 3) DB finalize + final ack
                        await archive_outgoing_finalize(db, phone, int(chat_id), pre["temp_id"], msg_obj)
                        ws_send({
                            "action": "send_done",
                            "temp_id": pre["temp_id"],
                            "msg_id": int(getattr(msg_obj, "id", 0)),
                            "date": getattr(msg_obj, "date", datetime.now(timezone.utc)).isoformat()
                        })
                        # NewMessage echo will also arrive via handler (de-duped)

                    except Exception as e:
                        err = {"status": "error", "detail": str(e)}
                        if pre:
                            err.update({"action": "send_failed", "temp_id": pre["temp_id"]})
                        ws_send(err)

                asyncio.run_coroutine_threadsafe(do_send(), loop)

            else:
                ws_send({"status": "error", "detail": "unknown action"})

    except Exception as e:
        if "closed" in str(e).lower():
            print(f"ℹ️ [chat_ws] client closed: {e}")
        else:
            print(f"⚠️ [chat_ws] Exception: {e}")
    finally:
        # shutdown
        alive = False
        out_q.put(None)
        # cancel typing timers
        for t in list(typing_timers.values()):
            try: t.cancel()
            except: pass
        # unregister active client (only if this ws owns it)
        try:
            with ACTIVE_TG_LOCK:
                if ACTIVE_TG.get(phone) is tg_client:
                    ACTIVE_TG.pop(phone, None)
        except Exception:
            pass
        try:
            if tg_client:
                asyncio.run_coroutine_threadsafe(tg_client.disconnect(), loop).result(timeout=5)
        except Exception:
            pass
        print("❌ [chat_ws] disconnected")




















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





async def _verify_deleted_for_chat(phone: str, chat_id: int, access_hash: int | None, max_check: int = 300):
    """
    লাস্ট `max_check` টা Mongo মেসেজ টেলিগ্রামে এখনও আছে কিনা যাচাই করে।
    না থাকলে deleted_on_telegram=True সেট করে দেয়।
    """
    from telethon import types
    MSG_COL = db.messages

    # 1) ক্যান্ডিডেট আইডি নাও (newest→oldest then slice)
    ids = [int(d["msg_id"]) for d in
           MSG_COL.find({"phone": phone, "chat_id": int(chat_id), "msg_id": {"$type": "number"}})
                  .sort([("date", -1), ("msg_id", -1)])
                  .limit(max_check)]
    if not ids:
        return

    # 2) peer resolve
    client = await get_client(phone)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            return
        if access_hash:
            try: peer = types.InputPeerUser(int(chat_id), int(access_hash))
            except:
                try: peer = types.InputPeerChannel(int(chat_id), int(access_hash))
                except: peer = types.InputPeerChat(int(chat_id))
        else:
            try: peer = await client.get_entity(int(chat_id))
            except: peer = types.InputPeerChat(int(chat_id))

        # 3) batched get_messages
        existing = set()
        BATCH = 100
        for i in range(0, len(ids), BATCH):
            chunk = ids[i:i+BATCH]
            res = await client.get_messages(peer, ids=chunk)
            if not isinstance(res, list):
                res = [res]
            for m in res:
                if getattr(m, "id", None) is not None:
                    existing.add(int(m.id))

        # 4) যেগুলো নেই — মার্ক অ্যাজ ডিলিটেড
        missing = [i for i in ids if i not in existing]
        if missing:
            MSG_COL.update_many(
                {"phone": phone, "chat_id": int(chat_id), "msg_id": {"$in": missing}},
                {"$set": {"deleted_on_telegram": True}}
            )
    finally:
        try: await client.disconnect()
        except: pass








from telethon import types as TL

async def _resolve_peer_any(client, chat_id: int, access_hash: int | None):
    """
    Try to resolve a peer by (chat_id, access_hash) with multiple fallbacks.
    Works for users, supergroups/channels, and basic groups.
    """
    # If we have access_hash, attempt precise InputPeer* first
    if access_hash is not None:
        try:
            return TL.InputPeerUser(int(chat_id), int(access_hash))
        except Exception:
            try:
                return TL.InputPeerChannel(int(chat_id), int(access_hash))
            except Exception:
                pass

    # Without access_hash (or above failed), try get_entity
    try:
        return await client.get_entity(int(chat_id))
    except Exception:
        # Last resorts (won't always work; harmless if they fail)
        try:
            return TL.InputPeerChat(int(chat_id))
        except Exception:
            pass
        try:
            return TL.InputPeerChannel(abs(int(chat_id)), 0)
        except Exception:
            pass

    return None











async def _refresh_with_client(tg_client, phone: str, chat_id: int, access_hash: int | None,
                               max_new: int = 50) -> int:
    """
    Pull newest messages from Telegram into Mongo BEFORE serving /messages.
    - If DB has history: fetch only messages with id > last_id (min_id=last_id)
    - If DB is empty: seed latest `max_new` messages
    Returns: number of upserted messages.
    """
    MSG_COL = db.messages

    peer = await _resolve_peer_any(tg_client, chat_id, access_hash)
    if not peer:
        return 0

    # Highest msg_id already in DB
    last = MSG_COL.find_one(
        {"phone": str(phone), "chat_id": int(chat_id), "msg_id": {"$type": "number"}},
        sort=[("msg_id", -1)]
    )
    last_id = int(last["msg_id"]) if last and isinstance(last.get("msg_id"), int) else None

    upserted = 0
    if last_id:
        # Only newer than what we have
        async for msg in tg_client.iter_messages(peer, min_id=last_id):
            await _upsert_message_from_msg(tg_client, phone, int(chat_id), access_hash, msg)
            upserted += 1
            if upserted >= max_new:
                break
    else:
        # DB empty → seed latest N
        async for msg in tg_client.iter_messages(peer, limit=max_new):
            await _upsert_message_from_msg(tg_client, phone, int(chat_id), access_hash, msg)
            upserted += 1

    return upserted






def _refresh_latest_messages(phone: str, chat_id: int, access_hash: int | None,
                             max_new: int = 50) -> int:
    """
    Synchronous wrapper used by /messages.
    Prefers the ACTIVE_TG client (so WS won't disconnect). Fallback: ephemeral client.
    """
    import asyncio

    # Try active client first (registered by /chat_ws)
    try:
        with ACTIVE_TG_LOCK:
            active = ACTIVE_TG.get(phone)
    except NameError:
        active = None

    if active and active.is_connected() and getattr(active, "loop", None) and active.loop.is_running():
        try:
            fut = asyncio.run_coroutine_threadsafe(
                _refresh_with_client(active, phone, int(chat_id), access_hash, max_new=max_new),
                active.loop
            )
            return int(fut.result(timeout=25) or 0)
        except Exception:
            pass

    # Fallback: ephemeral client (connect → refresh → disconnect)
    async def _ephemeral():
        c = await get_client(phone)
        await c.connect()
        try:
            if not await c.is_user_authorized():
                return 0
            n = await _refresh_with_client(c, phone, int(chat_id), access_hash, max_new=max_new)
            return n
        finally:
            try:
                await c.disconnect()
            except:
                pass

    loop2 = asyncio.new_event_loop()
    asyncio.set_event_loop(loop2)
    try:
        return int(loop2.run_until_complete(_ephemeral()) or 0)
    finally:
        try:
            loop2.close()
        except:
            pass















@app.route("/messages", methods=["GET"])
def get_messages():
    """
    Mongo-first message feed with deterministic ordering + lazy refresh + live existence check.

    Query params:
      - phone=...                (required)
      - chat_id=...              (required, int)
      - access_hash=...          (optional, int)
      - limit=50                 (optional, default 50, max 500)
      - order=asc|desc           (optional, default asc)  -> we will return the OPPOSITE order
      - refresh_latest=0|1       (optional, default 1)    -> pull latest from Telegram before reading Mongo
      - refresh_count=N          (optional, default 50, max 200) -> how many to pull
      - verify_deleted=0|1       (optional, default 1)    -> live check returned ids for existence
      - only_deleted=1           (optional)  -> return only deleted ones from Mongo
      - hide_deleted=1           (optional)  -> exclude deleted ones from Mongo
      - patch_db=0|1             (optional, default 1)    -> write tombstones after live-check
    """
    from flask import request, jsonify
    from datetime import datetime
    import asyncio
    from bson.objectid import ObjectId  # <-- needed for sanitize

    # -------- helpers --------
    def _json_sanitize(x):
        """Recursively convert ObjectId -> str, datetime -> isoformat, containers -> sanitized."""
        if isinstance(x, ObjectId):
            return str(x)
        if isinstance(x, datetime):
            return x.isoformat()
        if isinstance(x, dict):
            return {k: _json_sanitize(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [_json_sanitize(v) for v in x]
        return x

    q = request.args

    # --- required args ---
    phone = q.get("phone")
    if not phone:
        return jsonify({"status": "error", "detail": "phone is required"}), 400

    try:
        chat_id = int(q.get("chat_id"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "detail": "chat_id (int) is required"}), 400

    # optional access_hash (helps resolve peer)
    try:
        access_hash = int(q.get("access_hash")) if q.get("access_hash") not in (None, "",) else None
    except Exception:
        access_hash = None

    # --- order (flip the requested one) ---
    order = (q.get("order", "asc") or "asc").lower()
    if order not in ("asc", "desc"):
        order = "asc"
    effective_order = "desc" if order == "asc" else "asc"
    sort_dir = 1 if effective_order == "asc" else -1

    # --- limits ---
    try:
        limit = int(q.get("limit", 50))
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 500))

    only_deleted   = str(q.get("only_deleted", "0")).lower()   in ("1", "true", "yes")
    hide_deleted   = str(q.get("hide_deleted", "0")).lower()   in ("1", "true", "yes")
    verify_deleted = str(q.get("verify_deleted", "1")).lower() in ("1", "true", "yes")
    patch_db       = str(q.get("patch_db", "1")).lower()       in ("1", "true", "yes")

    # --- optional lazy refresh from Telegram (DEFAULT ON) ---
    refresh_latest = str(q.get("refresh_latest", "1")).lower() in ("1", "true", "yes")
    try:
        refresh_count = int(q.get("refresh_count", 50))
    except Exception:
        refresh_count = 50
    refresh_count = max(1, min(refresh_count, 200))

    if refresh_latest:
        try:
            _ = _refresh_latest_messages(
                phone=phone, chat_id=chat_id, access_hash=access_hash, max_new=refresh_count
            )
        except Exception:
            pass  # return Mongo anyway

    # --- Mongo filter ---
    match = {"phone": phone, "chat_id": chat_id}
    if only_deleted:
        match["deleted_on_telegram"] = True
    elif hide_deleted:
        match["$or"] = [
            {"deleted_on_telegram": {"$exists": False}},
            {"deleted_on_telegram": False},
        ]

    # --- query Mongo in the flipped order (deterministic multi-key sort) ---
    cursor = db.messages.find(match).sort([
        ("msg_id", sort_dir),
        ("date",   sort_dir),
        ("_id",    sort_dir),
    ]).limit(limit)
    docs = list(cursor)

    # --- live existence check for returned docs (if enabled) ---
    existing_ids_page = None   # type: set|None
    verify_info = None

    if verify_deleted:
        ids_page = [int(d["msg_id"]) for d in docs if isinstance(d.get("msg_id"), int)]

        def _check_with_active(ids) -> set | None:
            # try using active client from /chat_ws
            try:
                with ACTIVE_TG_LOCK:
                    tg_client = ACTIVE_TG.get(phone)
            except NameError:
                tg_client = None
            if not (tg_client and tg_client.is_connected() and getattr(tg_client, "loop", None) and tg_client.loop.is_running()):
                return None

            async def _check():
                peer = await _resolve_peer_any(tg_client, chat_id, access_hash)
                if not peer or not ids:
                    return set()
                exist = set()
                BATCH = 100
                for i in range(0, len(ids), BATCH):
                    part = ids[i:i+BATCH]
                    res = await tg_client.get_messages(peer, ids=part)
                    if not isinstance(res, list):
                        res = [res]
                    for mid, msg in zip(part, res):
                        if msg is not None:
                            exist.add(mid)
                return exist

            try:
                fut = asyncio.run_coroutine_threadsafe(_check(), tg_client.loop)
                return fut.result(timeout=20)
            except Exception:
                return None

        # 1) Prefer active client
        existing_ids_page = _check_with_active(ids_page)

        # 2) Fallback: ephemeral checker on the global loop
        if existing_ids_page is None:
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    _probe_existing_ids(phone=phone, chat_id=chat_id, access_hash=access_hash, ids=ids_page),
                    loop
                )
                existing_ids_page = fut.result(timeout=30) or set()
            except Exception:
                existing_ids_page = set()

        removed = set(ids_page) - set(existing_ids_page)
        if patch_db and removed:
            db.messages.update_many(
                {"phone": phone, "chat_id": chat_id, "msg_id": {"$in": list(removed)}},
                {"$set": {"deleted_on_telegram": True}}
            )

        verify_info = {"checked": len(ids_page), "deleted_found": len(removed)}

    # --- transform for JSON (strip/convert ObjectId safely) ---
    def _to_json(doc):
        d = dict(doc)

        # _id → str
        _id = d.pop("_id", None)
        if _id is not None:
            d["_id"] = str(_id)

        # Optional: hide internal storage id (client doesn't need it)
        d.pop("media_fs_id", None)

        # date → ISO
        dt = d.get("date")
        if isinstance(dt, datetime):
            d["date"] = dt.isoformat()

        # Accurate exists_on_telegram
        mid = d.get("msg_id")
        deleted_flag = bool(d.get("deleted_on_telegram", False))
        if verify_deleted and isinstance(mid, int) and (existing_ids_page is not None):
            exists = mid in existing_ids_page
        else:
            exists = (mid is not None) and (not deleted_flag)
        d["exists_on_telegram"] = bool(exists)

        # Convert any leftover ObjectIds (defensive)
        for k, v in list(d.items()):
            if isinstance(v, ObjectId):
                d[k] = str(v)

        return d

    out = [_to_json(d) for d in docs]

    payload = {
        "status": "ok",
        "order_requested": order,
        "order_returned": effective_order,
        "count": len(out),
        "messages": out
    }
    if verify_info is not None:
        payload["verify_deleted"] = verify_info

    # Final defensive sanitize (nested structures, if any)
    return jsonify(_json_sanitize(payload))












async def _fetch_media_with_client(tg_client, chat_id: int, access_hash: int | None, msg_id: int):
    """
    Uses an already-connected Telethon client to fetch a single message's media as bytes.
    Returns: (blob_bytes, mime, filename) or (None, None, None)
    """
    from telethon import types

    # Robust peer resolve
    try:
        if access_hash is not None:
            try:
                peer = types.InputPeerUser(int(chat_id), int(access_hash))
            except Exception:
                try:
                    peer = types.InputPeerChannel(int(chat_id), int(access_hash))
                except Exception:
                    peer = types.InputPeerChat(int(chat_id))
        else:
            peer = await tg_client.get_entity(int(chat_id))
    except Exception:
        peer = types.InputPeerChat(int(chat_id))

    msg = await tg_client.get_messages(peer, ids=int(msg_id))
    if not msg or not getattr(msg, "media", None):
        return None, None, None

    blob = await msg.download_media(bytes)
    mime, fname = _guess_msg_media_meta(msg)
    return blob, mime, fname


# ==================================
# 📥 /message_media  (active-client aware, GridFS cached)
# ==================================
@app.route("/message_media")
def message_media():
    """
    Serves media from Mongo GridFS if available; otherwise downloads from Telegram,
    saves to GridFS with correct content_type, updates the doc, and serves inline.
    ⚠️ It first tries to reuse the active Telethon client from /chat_ws to avoid
       parallel connections that can disconnect the listener.
    Query:
      - phone (str, required)
      - chat_id (int, required)
      - msg_id (int, required)
      - access_hash (int, optional)
    """
    from flask import make_response
    from gridfs import GridFS
    from bson.objectid import ObjectId
    import asyncio

    phone = request.args.get("phone")
    chat_id = request.args.get("chat_id")
    access_hash = request.args.get("access_hash")
    msg_id = request.args.get("msg_id")

    if not all([phone, chat_id, msg_id]):
        return "Bad Request", 400

    try:
        chat_id = int(chat_id)
        msg_id = int(msg_id)
        access_hash = int(access_hash) if access_hash not in (None, "",) else None
    except Exception:
        return "Bad Request", 400

    MSG_COL = db.messages
    fs = GridFS(db, collection="fs")

    # 1) Try GridFS cache first
    doc = MSG_COL.find_one({"phone": phone, "chat_id": chat_id, "msg_id": msg_id})
    if doc and doc.get("media_fs_id"):
        try:
            gf = fs.get(ObjectId(doc["media_fs_id"]))
            data = gf.read()
            mime = getattr(gf, "content_type", None) or "application/octet-stream"
            fname = getattr(gf, "filename", None) or "file.bin"

            resp = make_response(data)
            resp.headers["Content-Type"] = mime
            resp.headers["Content-Disposition"] = f'inline; filename="{fname}"'
            resp.headers["Access-Control-Allow-Origin"] = "*"
            return resp
        except Exception:
            # fall through to Telegram fetch if FS read fails
            pass

    # 2) Fetch from Telegram — prefer active, connected client from /chat_ws
    def fetch_via_active():
        with ACTIVE_TG_LOCK:
            c = ACTIVE_TG.get(phone)
        if not c:
            return None
        try:
            fut = asyncio.run_coroutine_threadsafe(
                _fetch_media_with_client(c, chat_id, access_hash, msg_id),
                loop
            )
            return fut.result(timeout=25)
        except Exception:
            return None

    triple = fetch_via_active()

    if triple:
        data, mime, fname = triple
    else:
        # 3) Fallback: ephemeral client ONLY if no active client available
        async def fetch_ephemeral():
            tg_client = await get_client(phone)
            await tg_client.connect()
            try:
                if not await tg_client.is_user_authorized():
                    await tg_client.disconnect()
                    return None, None, None
                res = await _fetch_media_with_client(tg_client, chat_id, access_hash, msg_id)
                await tg_client.disconnect()
                return res
            except Exception:
                try:
                    await tg_client.disconnect()
                except:
                    pass
                return None, None, None

        loop2 = asyncio.new_event_loop()
        asyncio.set_event_loop(loop2)
        try:
            data, mime, fname = loop2.run_until_complete(fetch_ephemeral())
        finally:
            try:
                loop2.close()
            except Exception:
                pass

    if not data:
        return "No media", 404

    # 4) Save to GridFS with correct MIME and update Mongo doc
    try:
        fs_id = _put_fs(db, data, filename=(fname or "file.bin"), content_type=(mime or "application/octet-stream"))
        MSG_COL.update_one(
            {"phone": phone, "chat_id": chat_id, "msg_id": msg_id},
            {"$set": {
                "media_fs_id": fs_id,
                "file_name": fname,
                "mime_type": mime
            }},
            upsert=True
        )
    except Exception as e:
        # If FS write failed, still serve inline from memory
        pass

    # 5) Serve inline with proper headers (CORS-friendly)
    from flask import make_response
    resp = make_response(data)
    resp.headers["Content-Type"] = mime or "application/octet-stream"
    resp.headers["Content-Disposition"] = f'inline; filename="{(fname or "file.bin")}"'
    resp.headers["Access-Control-Allow-Origin"] = "*"
    # Optional cache headers:
    # resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp












# ---------- FULL: Mongo-first archivers ----------
async def archive_incoming_event(
    db,
    phone: str,
    chat_id: int,
    access_hash: int | None,
    event
) -> dict:
    """
    Mongo-first archiver (LAZY media: কোনো মিডিয়া ডাউনলোড নয়)
    - কল (voice/video) সার্ভিস-মেসেজ ধরতে পারে: media_type = call_audio|call_video + call_* ফিল্ড
    - is_out কেবল false→true আপগ্রেড হবে; true→false হবে না
    - ❗ update করার সময় NEVER touches `deleted_on_telegram` (শুধু insert এ default False)
    """
    from datetime import datetime, timezone

    MSG_COL = db.messages

    # Partial-unique index: কেবল msg_id numeric হলে ইউনিক
    try:
        MSG_COL.create_index(
            [("phone", 1), ("chat_id", 1), ("msg_id", 1)],
            name="uniq_msg",
            unique=True,
            partialFilterExpression={"msg_id": {"$type": "number"}}
        )
    except Exception:
        pass

    msg = event.message

    # ---- direction/status ----
    is_out = bool(getattr(msg, "out", False))
    direction = "out" if is_out else "in"
    status = "sent" if is_out else "arrived"

    # ---- helpers / media type (no download) ----
    def _event_media_type_fast_local(m) -> str:
        try:
            # যদি গ্লোবালে define থাকে, ওটাই নাও
            return _event_media_type_fast(m)  # type: ignore[name-defined]
        except Exception:
            pass
        if getattr(m, "action", None):   return "text"   # service/call হলে নিচে আলাদা
        if getattr(m, "photo", None):    return "image"
        if getattr(m, "video", None):    return "video"
        if getattr(m, "voice", None):    return "voice"
        if getattr(m, "audio", None):    return "audio"
        if getattr(m, "sticker", None):  return "sticker"
        if getattr(m, "media", None):    return "file"
        return "text"

    # ---- call detection ----
    try:
        call_media_type, call_info = _call_meta_from_msg(msg)  # type: ignore[name-defined]
    except Exception:
        call_media_type, call_info = (None, None)

    media_type = call_media_type if call_media_type else _event_media_type_fast_local(msg)

    # ---- sender (best-effort) ----
    sender_id, sender_name = None, None
    try:
        if is_out:
            me = await event.client.get_me()
            sender_id = getattr(me, "id", None)
            sender_name = (getattr(me, "first_name", None)
                           or getattr(me, "username", None)
                           or "Me")
        else:
            sender = await event.get_sender()
            sender_id = getattr(sender, "id", None)
            sender_name = (getattr(sender, "first_name", None)
                           or getattr(sender, "title", None)
                           or getattr(sender, "username", None))
    except Exception:
        pass

    # ---- date normalize (tz-aware) ----
    date_obj = getattr(msg, "date", None)
    if isinstance(date_obj, datetime):
        if date_obj.tzinfo is None:
            date_obj = date_obj.replace(tzinfo=timezone.utc)
    else:
        date_obj = datetime.now(timezone.utc)

    # ---- base doc (LAZY media placeholders) ----
    base_doc = {
        "phone": str(phone),
        "chat_id": int(chat_id),
        "access_hash": (int(access_hash) if access_hash is not None else None),

        "msg_id": int(getattr(msg, "id", 0)),

        "direction": direction,
        "is_out": is_out,

        "text": getattr(msg, "message", "") or "",
        "sender_id": sender_id,
        "sender_name": sender_name or "",

        "date": date_obj,
        "reply_to": getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None),

        "media_type": media_type,   # "text" | "image" | ... | "call_audio" | "call_video"
        "media_fs_id": None,        # lazy
        "file_name": None,          # lazy
        "mime_type": None,          # lazy

        "status": status,
        "deleted_on_telegram": False,   # <-- insert default; update এ আর টাচ করব না
    }

    if call_media_type:
        base_doc.update({
            "call_status":   call_info.get("status")     if isinstance(call_info, dict) else None,
            "call_is_video": call_info.get("is_video")   if isinstance(call_info, dict) else None,
            "call_duration": call_info.get("duration")   if isinstance(call_info, dict) else None,
            "call_reason":   call_info.get("raw_reason") if isinstance(call_info, dict) else None,
        })

    # ---- upsert (false→true upgrade only for is_out) ----
    filt = {"phone": str(phone), "chat_id": int(chat_id), "msg_id": int(getattr(msg, "id", 0))}
    existing = MSG_COL.find_one(filt)

    if existing:
        # ❗ NOTE: এখানে `deleted_on_telegram` একটুও টাচ করা হবে না
        patch = {
            "text": base_doc["text"],
            "date": base_doc["date"],
            "media_type": base_doc["media_type"],
        }

        # কেবল আপগ্রেড: false → true
        if is_out and not bool(existing.get("is_out", False)):
            patch.update({
                "is_out": True,
                "direction": "out",
                "status": "sent",
            })
            if sender_id is not None:
                patch["sender_id"] = int(sender_id)
            if sender_name:
                patch["sender_name"] = str(sender_name)

        # কল মেটা থাকলে idempotent আপডেট
        if call_media_type:
            patch.update({
                "call_status":   base_doc.get("call_status"),
                "call_is_video": base_doc.get("call_is_video"),
                "call_duration": base_doc.get("call_duration"),
                "call_reason":   base_doc.get("call_reason"),
            })

        MSG_COL.update_one(filt, {"$set": patch})

    else:
        MSG_COL.update_one(filt, {"$setOnInsert": base_doc}, upsert=True)

    # ---- return fresh copy ----
    return MSG_COL.find_one(filt)












from telethon.tl import types as TL

def _phone_call_state(pc, me_id: int):
    """
    TL.PhoneCall* -> (state, is_video, duration, other_user_id)
    state: requested|accepted|ongoing|ended|missed|busy|canceled
    """
    other = None
    is_video = bool(getattr(pc, "video", False))
    dur = getattr(pc, "duration", None)

    # figure out the other participant id (1:1 calls only)
    a = int(getattr(pc, "admin_id", 0) or 0)
    p = int(getattr(pc, "participant_id", 0) or 0)
    if a and p:
        other = p if a == me_id else a

    if isinstance(pc, TL.PhoneCallRequested):
        return "requested", is_video, None, other
    if isinstance(pc, TL.PhoneCallAccepted):
        return "accepted",  is_video, None, other
    if isinstance(pc, TL.PhoneCall):
        return "ongoing",   is_video, None, other
    if isinstance(pc, TL.PhoneCallDiscarded):
        reason = type(getattr(pc, "reason", None)).__name__ if getattr(pc, "reason", None) else None
        if   reason == "PhoneCallDiscardReasonMissed":  st = "missed"
        elif reason == "PhoneCallDiscardReasonBusy":    st = "busy"
        elif reason == "PhoneCallDiscardReasonHangup":  st = "canceled"
        else:                                           st = "ended"
        return st, is_video, dur, other
    return "unknown", is_video, dur, other

















import base64, uuid
from datetime import datetime, timezone

async def archive_outgoing_pre(
    db,
    phone: str,
    chat_id: int,
    access_hash: int | None,
    text: str | None,
    reply_to_id: int | None,
    file_b64: str | None,
    file_name: str | None,
    mime_type: str | None
) -> dict:
    """
    Pre-save an outgoing message into Mongo (status=pending), optionally with media.
    NOTE:
      - No 'msg_id' field is stored here (avoids duplicate-key on null).
      - A partial unique index on (phone, chat_id, msg_id) is ensured.
    """

    MSG_COL = db.messages

    # Ensure indexes (idempotent). Partial index only enforces uniqueness when msg_id is a number.
    try:
        MSG_COL.create_index(
            [("phone", 1), ("chat_id", 1), ("msg_id", 1)],
            name="uniq_msg",
            unique=True,
            # শুধু যেসব ডকে msg_id আছে এবং number, সেগুলোকেই unique ধরবে
            partialFilterExpression={"msg_id": {"$type": "number"}}
        )

    except Exception:
        pass

    try:
        MSG_COL.create_index(
            [("phone", 1), ("chat_id", 1), ("msg_id", 1)],
            name="uniq_msg",
            unique=True,
            # শুধু যেসব ডকে msg_id আছে এবং number, সেগুলোকেই unique ধরবে
            partialFilterExpression={"msg_id": {"$type": "number"}}
        )

    except Exception:
        pass

    # --- defaults ---
    media_type = "text"
    media_fs_id = None

    # --- optional media handling ---
    if file_b64:
        # accept both data:*;base64,.... and raw base64
        if isinstance(file_b64, str) and file_b64.startswith("data:"):
            try:
                _, file_b64 = file_b64.split(",", 1)
            except ValueError:
                file_b64 = ""  # malformed; will fail decode below

        def _b64decode_padded(s: str) -> bytes:
            s = (s or "").strip().replace("\n", "").replace("\r", "")
            # fix padding
            pad = len(s) % 4
            if pad:
                s += "=" * (4 - pad)
            return base64.b64decode(s)

        file_bytes = None
        try:
            file_bytes = _b64decode_padded(file_b64)
        except Exception:
            file_bytes = None

        if file_bytes:
            # save bytes to GridFS with correct content_type (helper already in your codebase)
            media_fs_id = _put_fs(
                db,
                file_bytes,
                filename=(file_name or "file.bin"),
                content_type=(mime_type or "application/octet-stream")
            )
            # detect media type (helper already in your codebase)
            media_type = _detect_media_type(mime_type, file_name)
        else:
            # couldn't decode; fall back to text-only (no raise)
            media_type = "text"
            media_fs_id = None

    # --- build pending doc (NO msg_id here) ---
    temp_id = f"local-{uuid.uuid4().hex[:12]}"
    doc = {
        "phone": str(phone),
        "chat_id": int(chat_id),
        "access_hash": (int(access_hash) if access_hash is not None else None),

        "temp_id": temp_id,
        # "msg_id": None,  # <-- intentionally omitted to avoid duplicate-key on null

        "direction": "out",
        "is_out": True,

        "text": (text or ""),
        "sender_id": None,
        "sender_name": None,
        "date": datetime.now(timezone.utc),

        "reply_to": (int(reply_to_id) if reply_to_id else None),

        "media_type": media_type,       # "text" | "image" | "video" | "audio" | "voice" | "sticker" | "file"
        "media_fs_id": media_fs_id,     # GridFS id or None
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



def _base_url():
    # e.g. http://192.168.0.247:8080/
    if has_request_context():
        return request.url_root
    # WS বা ব্যাকগ্রাউন্ড থ্রেডে থাকলে এখানে ফfallback
    return os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8080/")









def _doc_to_api(phone: str, chat_id: int, access_hash: int | None, doc: dict) -> dict:
    from datetime import datetime, timezone

    media_type = doc.get("media_type") or "text"

    # ---- flags: exists vs deleted ----
    deleted = bool(doc.get("deleted_on_telegram", False))
    # msg_id থাকলে আর deleted=False হলে ধরে নিচ্ছি Telegram-এ আছে
    exists = (doc.get("msg_id") is not None) and (not deleted)

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
        "call": call_obj,              # present only for call_* types

        # 🔥 New fields:
        "deleted_on_telegram": deleted,
        "exists_on_telegram": exists,
    }



















# ---------- FULL: archive all dialogs to Mongo (runs in background) ----------
import asyncio
from datetime import datetime, timezone
async def _upsert_message_from_msg(tg_client, phone: str, chat_id: int, access_hash, msg) -> dict:
    """
    Single Telegram Message -> Mongo upsert (LAZY media, no downloads).
    - call সার্ভিস মেসেজ detect করে media_type = call_audio|call_video + call_* ফিল্ড
    - is_out কেবল false→true আপগ্রেড হবে; কখনও true→false হবে না
    - ❗ update করার সময় NEVER touches `deleted_on_telegram` (শুধু insert এ default False)
    - partial unique index: (phone, chat_id, msg_id) কেবল msg_id numeric হলে unique
    """
    from datetime import datetime, timezone

    MSG_COL = db.messages

    # ✅ Partial-unique index (idempotent)
    try:
        MSG_COL.create_index(
            [("phone", 1), ("chat_id", 1), ("msg_id", 1)],
            name="uniq_msg",
            unique=True,
            partialFilterExpression={"msg_id": {"$type": "number"}}
        )
    except Exception:
        pass

    # ---------- helpers ----------
    def _event_media_type_fast_local(m) -> str:
        # যদি গ্লোবালে _event_media_type_fast থাকে, সেটাই ব্যবহার করি
        try:
            return _event_media_type_fast(m)  # type: ignore[name-defined]
        except Exception:
            pass
        if getattr(m, "action", None):   return "text"   # service/call হলে নিচে ধরবো
        if getattr(m, "photo", None):    return "image"
        if getattr(m, "video", None):    return "video"
        if getattr(m, "voice", None):    return "voice"
        if getattr(m, "audio", None):    return "audio"
        if getattr(m, "sticker", None):  return "sticker"
        if getattr(m, "media", None):    return "file"
        return "text"

    def _tz_safe(d):
        if isinstance(d, datetime):
            return d if d.tzinfo is not None else d.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc)

    # ---------- derive basics ----------
    is_out = bool(getattr(msg, "out", False))
    direction = "out" if is_out else "in"
    status = "sent" if is_out else "arrived"

    # call detect
    try:
        call_media_type, call_info = _call_meta_from_msg(msg)  # type: ignore[name-defined]
    except Exception:
        call_media_type, call_info = (None, None)

    # media type (lazy)
    media_type = call_media_type if call_media_type else _event_media_type_fast_local(msg)

    # sender (best-effort, no heavy awaits except entity once)
    sender_id, sender_name = None, None
    try:
        if getattr(msg, "from_id", None):
            sender_id = (getattr(msg.from_id, "user_id", None)
                         or getattr(msg.from_id, "channel_id", None)
                         or getattr(msg.from_id, "chat_id", None))
        if sender_id:
            try:
                ent = await tg_client.get_entity(sender_id)
                sender_name = (getattr(ent, "first_name", None)
                               or getattr(ent, "title", None)
                               or getattr(ent, "username", None))
            except Exception:
                sender_name = None
        if is_out and not sender_name:
            sender_name = "Me"
    except Exception:
        pass

    # date / reply_to
    date_obj = _tz_safe(getattr(msg, "date", None))
    reply_to_id = getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None)

    # ---------- build base doc (LAZY media fields) ----------
    base_doc = {
        "phone": str(phone),
        "chat_id": int(chat_id),
        "access_hash": (int(access_hash) if access_hash is not None else None),

        "msg_id": int(getattr(msg, "id", 0)),

        "direction": direction,
        "is_out": is_out,

        "text": getattr(msg, "message", "") or "",
        "sender_id": sender_id,
        "sender_name": sender_name or "",

        "date": date_obj,
        "reply_to": reply_to_id,

        "media_type": media_type,   # "text"|"image"|...|"call_audio"|"call_video"
        "media_fs_id": None,        # LAZY
        "file_name": None,          # LAZY
        "mime_type": None,          # LAZY

        "status": status,
        "deleted_on_telegram": False,   # <-- insert default only
    }

    if call_media_type:
        base_doc.update({
            "call_status":   call_info.get("status")     if isinstance(call_info, dict) else None,
            "call_is_video": call_info.get("is_video")   if isinstance(call_info, dict) else None,
            "call_duration": call_info.get("duration")   if isinstance(call_info, dict) else None,
            "call_reason":   call_info.get("raw_reason") if isinstance(call_info, dict) else None,
        })

    # ---------- upsert with false→true upgrade ----------
    filt = {"phone": str(phone), "chat_id": int(chat_id), "msg_id": int(getattr(msg, "id", 0))}
    existing = MSG_COL.find_one(filt)

    if existing:
        # ❗ এখানে deleted_on_telegram কখনও টাচ করা হবে না
        patch = {
            "text": base_doc["text"],
            "date": base_doc["date"],
            "media_type": base_doc["media_type"],
        }

        # কেবল আপগ্রেড: false → true
        if is_out and not bool(existing.get("is_out", False)):
            patch.update({
                "is_out": True,
                "direction": "out",
                "status": "sent",
            })
            if sender_id is not None:
                patch["sender_id"] = int(sender_id)
            if sender_name:
                patch["sender_name"] = str(sender_name)

        # কল মেটা থাকলে idempotent আপডেট
        if call_media_type:
            patch.update({
                "call_status":   base_doc.get("call_status"),
                "call_is_video": base_doc.get("call_is_video"),
                "call_duration": base_doc.get("call_duration"),
                "call_reason":   base_doc.get("call_reason"),
            })

        MSG_COL.update_one(filt, {"$set": patch})
    else:
        MSG_COL.update_one(filt, {"$setOnInsert": base_doc}, upsert=True)

    # ---------- return fresh copy ----------
    return MSG_COL.find_one(filt)









async def _probe_existing_ids(phone: str, chat_id: int, access_hash: int | None, ids: list[int]) -> set[int]:
    """
    Telegram-এ ওই chat-এর প্রদত্ত msg_id-গুলো এখনো আছে কিনা—সেট (existing_ids) রিটার্ন করে।
    """
    from telethon import types
    existing: set[int] = set()
    if not ids:
        return existing

    client = await get_client(phone)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            return existing

        # robust peer resolve
        try:
            if access_hash is not None:
                try: peer = types.InputPeerUser(int(chat_id), int(access_hash))
                except:
                    try: peer = types.InputPeerChannel(int(chat_id), int(access_hash))
                    except: peer = types.InputPeerChat(int(chat_id))
            else:
                peer = await client.get_entity(int(chat_id))
        except Exception:
            try: peer = types.InputPeerChat(int(chat_id))
            except Exception: return existing

        BATCH = 100
        for i in range(0, len(ids), BATCH):
            chunk = ids[i:i+BATCH]
            res = await client.get_messages(peer, ids=chunk)
            if not isinstance(res, list):
                res = [res]
            for m in res:
                # Telegram কোনো ডিলিটেড/অস্তিত্বহীন মেসেজে None/ফাঁকা দেয়
                if m and getattr(m, "id", None) is not None:
                    existing.add(int(m.id))
        return existing
    finally:
        try: await client.disconnect()
        except: pass









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

# --- put near your Telethon imports ---
from telethon.tl import types as TL

def _parse_call_action(action: TL.MessageActionPhoneCall | None, is_out: bool) -> dict | None:
    if not isinstance(action, TL.MessageActionPhoneCall):
        return None
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
    """
    act = getattr(msg, "action", None)
    if isinstance(msg, TL.MessageService) and isinstance(act, TL.MessageActionPhoneCall):
        info = _parse_call_action(act, bool(getattr(msg, "out", False)))
        media_type = "call_video" if info and info.get("is_video") else "call_audio"
        return media_type, info
    return None, None

def _event_media_type_fast(msg) -> str:
    """
    Fast media type detector (service/call aware)
    """
    act = getattr(msg, "action", None)
    if isinstance(msg, TL.MessageService) and isinstance(act, TL.MessageActionPhoneCall):
        return "call_video" if bool(getattr(act, "video", False)) else "call_audio"

    if getattr(msg, "photo", None):    return "image"
    if getattr(msg, "video", None):    return "video"
    if getattr(msg, "voice", None):    return "voice"
    if getattr(msg, "audio", None):    return "audio"
    if getattr(msg, "sticker", None):  return "sticker"
    if getattr(msg, "media", None):    return "file"
    return "text"















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
# loop = asyncio.new_event_loop()
# asyncio.set_event_loop(loop)

# ✅ Start loop in background thread before Flask starts
# ✅ Global asyncio loop (keep these)
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
def run_loop_forever():
    asyncio.set_event_loop(loop)
    loop.run_forever()
threading.Thread(target=run_loop_forever, daemon=True).start()



#============================
# 🏁 new chat
# ==================================



# ---------- Resolve exact username ----------
@app.route("/resolve_username", methods=["GET"])
def resolve_username():
    """
    GET /resolve_username?phone=...&username=@john (বা john)
    → { status, type: User/Channel/Chat, chat_id, access_hash, name, username, bot, scam, premium }
    """
    phone = (request.args.get("phone") or "").strip().replace(" ", "")
    username = (request.args.get("username") or "").strip()
    if not phone or not username:
        return jsonify({"status": "error", "detail": "phone/username missing"}), 400
    if username.startswith("@"):
        username = username[1:]

    async def do_resolve():
        client = await get_client(phone)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                return {"status": "error", "detail": "not authorized"}

            # exact resolve (global)
            ent = await client.get_entity(username)

            # figure out kind + basic fields
            kind = type(ent).__name__  # User / Channel / Chat
            chat_id = int(getattr(ent, "id", 0))
            access_hash = getattr(ent, "access_hash", None)

            name = (getattr(ent, "first_name", None)
                    or getattr(ent, "title", None)
                    or getattr(ent, "username", None)
                    or "")
            resp = {
                "status": "ok",
                "type": kind,
                "chat_id": chat_id,
                "access_hash": int(access_hash) if access_hash is not None else None,
                "name": name,
                "username": getattr(ent, "username", None),
                "bot": bool(getattr(ent, "bot", False)),
                "scam": bool(getattr(ent, "scam", False)),
                "premium": bool(getattr(ent, "premium", False)),
            }

            # cache → Mongo (optional but handy)
            try:
                db.peers.update_one(
                    {"phone": phone, "chat_id": chat_id},
                    {"$set": {
                        "phone": phone, "chat_id": chat_id,
                        "access_hash": resp["access_hash"],
                        "type": kind, "name": name,
                        "username": resp["username"]
                    }},
                    upsert=True
                )
            except Exception:
                pass

            return resp

        except UsernameNotOccupiedError:
            return {"status": "error", "detail": "username not found"}
        except UsernameInvalidError:
            return {"status": "error", "detail": "invalid username"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}
        finally:
            try: await client.disconnect()
            except: pass

    result = asyncio.run(do_resolve())
    code = 200 if result.get("status") == "ok" else 400
    return jsonify(result), code







# ---------- Fuzzy search users/chats/channels ----------
@app.route("/search_people", methods=["GET"])
def search_people():
    """
    GET /search_people?phone=...&q=jo   (limit ঐচ্ছিক, default 20)
    → { status, results: [ {type, chat_id, access_hash, name, username, is_user, is_channel, is_group} ] }
    """
    phone = (request.args.get("phone") or "").strip().replace(" ", "")
    q = (request.args.get("q") or "").strip()
    try:
        limit = int(request.args.get("limit", 20))
    except Exception:
        limit = 20

    if not phone or not q:
        return jsonify({"status": "error", "detail": "phone/q missing"}), 400

    async def do_search():
        client = await get_client(phone)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                return {"status": "error", "detail": "not authorized"}

            res = await client(functions.contacts.SearchRequest(q=q, limit=limit))
            out = []
            for u in getattr(res, "users", []):
                out.append({
                    "type": "User",
                    "chat_id": int(getattr(u, "id", 0)),
                    "access_hash": int(getattr(u, "access_hash", 0)) if getattr(u, "access_hash", None) else None,
                    "name": (getattr(u, "first_name", "") or "") + (" " + getattr(u, "last_name", "") if getattr(u, "last_name", None) else ""),
                    "username": getattr(u, "username", None),
                    "is_user": True, "is_channel": False, "is_group": False
                })
            for ch in getattr(res, "chats", []):
                out.append({
                    "type": type(ch).__name__,  # Channel/Chat
                    "chat_id": int(getattr(ch, "id", 0)),
                    "access_hash": int(getattr(ch, "access_hash", 0)) if getattr(ch, "access_hash", None) else None,
                    "name": getattr(ch, "title", "") or "",
                    "username": getattr(ch, "username", None),
                    "is_user": False,
                    "is_channel": hasattr(ch, "broadcast") and bool(getattr(ch, "broadcast", False)),
                    "is_group": hasattr(ch, "megagroup") and bool(getattr(ch, "megagroup", False))
                })

            return {"status": "ok", "results": out}

        except Exception as e:
            return {"status": "error", "detail": str(e)}
        finally:
            try: await client.disconnect()
            except: pass

    result = asyncio.run(do_search())
    code = 200 if result.get("status") == "ok" else 400
    return jsonify(result), code





# ---------- Start a new chat by sending first message ----------
@app.route("/start_chat", methods=["POST"])
def start_chat():
    """
    JSON:
    {
      "phone": "...",
      # EITHER:
      "username": "john" | "@john",
      # OR:
      "user_id": 123456789, "access_hash": 987654321,
      # optional:
      "text": "Hi there!"   # default: "Hi"
    }
    → { status, chat_id, access_hash, msg_id, date }
    """
    data = request.get_json(silent=True) or {}
    phone = (data.get("phone") or "").strip().replace(" ", "")
    username = data.get("username")
    user_id = data.get("user_id")
    access_hash = data.get("access_hash")
    text = data.get("text") or "Hi"

    if not phone or (not username and not user_id):
        return jsonify({"status": "error", "detail": "phone and (username OR user_id) required"}), 400

    async def do_start():
        client = await get_client(phone)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                return {"status": "error", "detail": "not authorized"}

            peer = None
            ent = None

            if username:
                uname = username[1:] if str(username).startswith("@") else str(username)
                ent = await client.get_entity(uname)
                peer = ent
            else:
                try:
                    peer = types.InputPeerUser(int(user_id), int(access_hash))
                except Exception:
                    return {"status": "error", "detail": "invalid user_id/access_hash"}

            # send first message (this will open the DM)
            msg_obj = await client.send_message(peer, text)

            # upsert into Mongo so that /messages and /chat_ws immediately know it
            try:
                cid = int(getattr((ent or peer), "id", 0))
                ah  = getattr((ent or peer), "access_hash", None)
                await _upsert_message_from_msg(client, phone, cid, ah, msg_obj)  # uses your existing helper
            except Exception as _:
                pass

            # prepare response essentials
            chat_id = int(getattr((ent or peer), "id", 0))
            acc_hash = getattr((ent or peer), "access_hash", None)

            return {
                "status": "sent",
                "chat_id": chat_id,
                "access_hash": int(acc_hash) if acc_hash is not None else None,
                "msg_id": int(getattr(msg_obj, "id", 0)),
                "date": getattr(msg_obj, "date", datetime.now(timezone.utc)).isoformat()
            }

        except UserPrivacyRestrictedError:
            return {"status": "error", "detail": "cannot message this user due to privacy settings"}
        except ChatWriteForbiddenError:
            return {"status": "error", "detail": "write forbidden in this dialog"}
        except FloodWaitError as e:
            return {"status": "error", "detail": f"rate limited, wait {getattr(e, 'seconds', 'some')}s"}
        except PeerIdInvalidError:
            return {"status": "error", "detail": "peer id invalid"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}
        finally:
            try: await client.disconnect()
            except: pass

    result = asyncio.run(do_start())
    code = 200 if result.get("status") == "sent" else 400
    return jsonify(result), code













# === JOIN A GROUP/CHANNEL ===
from telethon.tl import functions, types
from urllib.parse import urlparse

@app.route("/join", methods=["POST"])
def join_group():
    """
    JSON:
    - Public:  {"phone":"+8801...", "username":"@mygroup" | "mygroup"}
    - Private: {"phone":"+8801...", "invite":"https://t.me/+XXXX" | "https://t.me/joinchat/XXXX" | "XXXX"}
    → {status, chat_id, access_hash, type}
    """
    data = request.get_json(silent=True) or {}
    phone = (data.get("phone") or "").strip().replace(" ", "")
    username = (data.get("username") or "").strip()
    invite   = (data.get("invite") or "").strip()
    if not phone or (not username and not invite):
        return jsonify({"status":"error","detail":"phone and (username OR invite) required"}), 400

    async def do_join():
        client = await get_client(phone)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                return {"status":"error","detail":"not authorized"}

            # --- Public (username) ---
            if username:
                uname = username[1:] if username.startswith("@") else username
                ent = await client.get_entity(uname)  # User/Channel/Chat
                kind = type(ent).__name__            # 'Channel' (supergroup/channel) | 'Chat' (basic grp) | 'User'
                # Channel/Supergroup join
                if kind == "Channel":
                    await client(functions.channels.JoinChannelRequest(ent))
                # basic Chat এ username দিয়ে join করা যায় না; invite দরকার
                elif kind == "Chat":
                    # already visible হলে যোগ হয়ে আছো—না হলে ইনভাইট লাগে
                    pass

                chat_id = int(getattr(ent, "id", 0))
                acc     = getattr(ent, "access_hash", None)
                return {"status":"ok","type":kind,"chat_id":chat_id,
                        "access_hash": int(acc) if acc is not None else None}

            # --- Private invite ---
            code = invite
            # URL হলে কোড কেটে নাও
            try:
                u = urlparse(invite)
                if u.netloc in ("t.me","telegram.me"):
                    # /+XXXX বা /joinchat/XXXX
                    p = u.path.strip("/").split("/")
                    code = p[-1] if p else invite
            except Exception:
                pass
            # '+XXXX' হলে + কেটে ফেলো
            code = code.replace("+","").replace("joinchat/","")

            upd = await client(functions.messages.ImportChatInviteRequest(code))
            # আপডেট থেকে joined entity বের করা
            # ImportChatInviteRequest রেসপন্সে 'chats'/'channels' থাকে
            joined = None
            for ch in (getattr(upd, "chats", []) or []):
                joined = ch; break
            if joined is None:
                for ch in (getattr(upd, "channels", []) or []):
                    joined = ch; break
            if joined is None:
                return {"status":"error","detail":"unable to resolve joined chat"}

            kind = type(joined).__name__
            chat_id = int(getattr(joined, "id", 0))
            acc     = getattr(joined, "access_hash", None)
            return {"status":"ok","type":kind,"chat_id":chat_id,
                    "access_hash": int(acc) if acc is not None else None}
        except Exception as e:
            return {"status":"error","detail":str(e)}
        finally:
            try: await client.disconnect()
            except: pass

    res = asyncio.run(do_join())
    return jsonify(res), (200 if res.get("status")=="ok" else 400)



#=========================================================================
#Grooup
#========================================================



# =========================
# 👥 /group_members — list members for basic group (Chat) and megagroup/channel
# =========================
from flask import request, jsonify
from telethon.tl import types as T
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.functions.channels import GetFullChannelRequest, GetParticipantsRequest
from telethon.tl.types import (
    ChannelParticipantsAdmins, ChannelParticipantAdmin, ChannelParticipantCreator,
    UserStatusOnline, UserStatusOffline, UserStatusRecently, UserStatusLastWeek, UserStatusLastMonth
)

def _status_to_text(s):
    try:
        if isinstance(s, UserStatusOnline):
            return "online", getattr(s, "expires", None).isoformat() if getattr(s, "expires", None) else None
        if isinstance(s, UserStatusOffline):
            return "offline", getattr(s, "was_online", None).isoformat() if getattr(s, "was_online", None) else None
        if isinstance(s, UserStatusRecently):
            return "recently", None
        if isinstance(s, UserStatusLastWeek):
            return "last_week", None
        if isinstance(s, UserStatusLastMonth):
            return "last_month", None
    except:
        pass
    return "unknown", None





def _user_dict(u: T.User, phone: str, role: str = "member"):
    """
    Normalize a Telethon User → lightweight dict for /group_members.
    - status → "online" | "offline" | "recently" | "last_week" | "last_month" | "unknown"
    - last_seen/status_time → ISO-8601 or None
    - avatar_url points to /avatar_redirect (only if username exists)
    """
    st, when = _status_to_text(getattr(u, "status", None))

    full_name = (
        ((u.first_name or "") + (" " + u.last_name if getattr(u, "last_name", None) else "")).strip()
        or (u.username or "")
    )

    avatar_url = (
        f"/avatar_redirect?phone={phone}&username={u.username}"
        if getattr(u, "username", None) else None
    )

    return {
        "id": int(getattr(u, "id", 0) or 0),
        "access_hash": int(getattr(u, "access_hash", 0)) if getattr(u, "access_hash", None) else None,
        "username": getattr(u, "username", None),
        "first_name": getattr(u, "first_name", None),
        "last_name": getattr(u, "last_name", None),
        "name": full_name,
        "phone": getattr(u, "phone", None),

        "bot": bool(getattr(u, "bot", False)),
        "verified": bool(getattr(u, "verified", False)),
        "scam": bool(getattr(u, "scam", False)),
        "restricted": bool(getattr(u, "restricted", False)),

        "status": st,            # "online"|"offline"|"recently"|...
        "last_seen": when,       # ISO-8601 or None
        "role": role,            # "creator"|"admin"|"member"

        "has_photo": bool(getattr(u, "photo", None)),
        "avatar_url": avatar_url
    }












async def _resolve_group_or_channel(client, chat_id: int, access_hash: int | None):
    """
    Robust resolver:
      1) Try basic group (Chat) via GetFullChatRequest(chat_id) -> ("chat", full_chat, None)
      2) Else try megagroup/channel:
         - if access_hash: InputPeerChannel(chat_id, access_hash) -> entity
         - else: PeerChannel(chat_id) -> entity
         -> ("channel", None, channel_entity)
    Raises if neither path works.
    """
    # 1) Basic group (types.Chat) — entity ছাড়াই full আনা যায়
    try:
        full = await client(GetFullChatRequest(chat_id))
        return "chat", full, None
    except Exception:
        pass

    # 2) Channel / Megagroup
    ent = None
    if access_hash is not None:
        try:
            ent = T.InputPeerChannel(int(chat_id), int(access_hash))
            ent = await client.get_entity(ent)
            return "channel", None, ent
        except Exception:
            ent = None
    try:
        ent = await client.get_entity(T.PeerChannel(int(chat_id)))
        return "channel", None, ent
    except Exception:
        pass

    # Fallback: InputPeerChat (বিরল কেসে কাজে লাগে)
    try:
        _ = await client.get_entity(T.InputPeerChat(int(chat_id)))  # ensure exists
        full = await client(GetFullChatRequest(chat_id))
        return "chat", full, None
    except Exception as e:
        raise e

@app.route("/group_members", methods=["GET"])
def group_members():
    """
    GET /group_members?phone=...&(chat_id=... | username=@group)
       [&access_hash=...]  # only needed for channels when available
       [&limit=100&offset=0&search=jo&include_roles=0]

    Response: {
      status: "ok",
      group: { chat_id, access_hash, type, title, username, is_megagroup, participants_count },
      count, offset, limit, total_candidates,
      members: [ {id, username, name, status, last_seen, role, ...} ]
    }
    """
    q = request.args
    phone = (q.get("phone") or "").strip()
    if not phone:
        return jsonify({"status": "error", "detail": "phone missing"}), 400

    username = (q.get("username") or "").strip()
    chat_id = None
    if q.get("chat_id"):
        try:
            chat_id = int(q.get("chat_id"))
        except Exception:
            return jsonify({"status": "error", "detail": "chat_id must be int"}), 400

    try:
        access_hash = int(q.get("access_hash")) if q.get("access_hash") not in (None, "",) else None
    except Exception:
        access_hash = None

    try:
        limit  = max(1, min(int(q.get("limit", 100)), 500))
    except Exception:
        limit = 100
    try:
        offset = max(0, int(q.get("offset", 0)))
    except Exception:
        offset = 0

    search = (q.get("search") or "").strip()
    include_roles = str(q.get("include_roles", "0")).lower() in ("1", "true", "yes")

    async def do_list():
        client = await get_client(phone)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                await client.disconnect()
                return {"code": 401, "body": {"status": "error", "detail": "not authorized"}}

            # -------- resolve (username or chat_id) --------
            kind = None
            full_chat = None
            chan_ent = None

            if username:
                ent = await client.get_entity(username[1:] if username.startswith("@") else username)
                if isinstance(ent, T.Chat):
                    kind = "chat"
                    full_chat = await client(GetFullChatRequest(ent.id))
                elif isinstance(ent, T.Channel):
                    kind = "channel"
                    chan_ent = ent
                else:
                    await client.disconnect()
                    return {"code": 400, "body": {"status": "error", "detail": "not a group/channel entity"}}
            else:
                # chat_id path — এখানে কখনোই সরাসরি get_entity(int(chat_id)) করবো না
                try:
                    kind, full_chat, chan_ent = await _resolve_group_or_channel(client, chat_id, access_hash)
                except Exception as e:
                    await client.disconnect()
                    return {"code": 400, "body": {"status": "error", "detail": str(e)}}

            members_out = []
            participants_count = None
            total_candidates = 0

            if kind == "chat":
                # ---- BASIC GROUP (types.Chat) ----
                fc = full_chat.full_chat
                participants_count = getattr(fc, "participants_count", None)

                part = getattr(fc, "participants", None)
                if not isinstance(part, T.ChatParticipants):
                    # e.g., ChatParticipantsForbidden
                    await client.disconnect()
                    return {"code": 400, "body": {"status": "error", "detail": "participants list not available for this group"}}

                ids = [int(p.user_id) for p in part.participants if getattr(p, "user_id", None)]
                users_by_id = {int(u.id): u for u in getattr(full_chat, "users", [])}
                users = []
                s = (search or "").lower()
                for uid in ids:
                    u = users_by_id.get(uid)
                    if not u:
                        try:
                            u = await client.get_entity(uid)
                        except Exception:
                            continue
                    if s:
                        blob = ((u.first_name or "") + " " + (u.last_name or "") + " " + (u.username or "")).lower()
                        if s not in blob:
                            continue
                    users.append(u)

                total_candidates = len(users)
                page = users[offset:offset+limit]
                members_out = [_user_dict(u, phone, role="member") for u in page]

                group_meta = {
                    "chat_id": int(getattr(fc, "id", 0) or getattr(full_chat, "id", 0) or chat_id),
                    "access_hash": None,  # basic group এর access_hash থাকে না
                    "type": "Chat",
                    "title": getattr(fc, "about", None) or getattr(full_chat, "title", None) or "",
                    "username": None,
                    "is_megagroup": False,
                    "participants_count": participants_count
                }

            elif kind == "channel":
                # ---- MEGAGROUP / CHANNEL ----
                is_megagroup = bool(getattr(chan_ent, "megagroup", False))
                try:
                    f = await client(GetFullChannelRequest(chan_ent))
                    participants_count = getattr(f.full_chat, "participants_count", None)
                except Exception:
                    pass

                # Optional: collect admin/creator roles
                role_map = {}
                if include_roles and is_megagroup:
                    try:
                        offs = 0
                        while True:
                            res = await client(GetParticipantsRequest(
                                channel=chan_ent,
                                filter=ChannelParticipantsAdmins(),
                                offset=offs, limit=200, hash=0
                            ))
                            parts = getattr(res, "participants", None) or []
                            if not parts:
                                break
                            for p in parts:
                                uid = int(getattr(p, "user_id", 0))
                                if isinstance(p, ChannelParticipantCreator):
                                    role_map[uid] = "creator"
                                elif isinstance(p, ChannelParticipantAdmin):
                                    role_map[uid] = "admin"
                                else:
                                    role_map[uid] = "admin"
                            if len(parts) < 200:
                                break
                            offs += len(parts)
                    except Exception:
                        role_map = {}

                # Server-side participants with search
                want = offset + limit
                users = []
                async for u in client.iter_participants(
                    chan_ent, search=(search or None), aggressive=True, limit=want
                ):
                    users.append(u)
                total_candidates = len(users)
                page = users[offset:offset+limit]
                members_out = [_user_dict(u, phone, role=role_map.get(int(u.id), "member")) for u in page]

                group_meta = {
                    "chat_id": int(getattr(chan_ent, "id", 0)),
                    "access_hash": int(getattr(chan_ent, "access_hash", 0)) if getattr(chan_ent, "access_hash", None) else None,
                    "type": "Channel",
                    "title": getattr(chan_ent, "title", None) or "",
                    "username": getattr(chan_ent, "username", None),
                    "is_megagroup": is_megagroup,
                    "participants_count": participants_count
                }

            else:
                await client.disconnect()
                return {"code": 400, "body": {"status": "error", "detail": "unrecognized entity kind"}}

            body = {
                "status": "ok",
                "group": group_meta,
                "count": len(members_out),
                "offset": offset,
                "limit": limit,
                "members": members_out,
                "total_candidates": total_candidates
            }
            await client.disconnect()
            return {"code": 200, "body": body}

        except Exception as e:
            try:
                await client.disconnect()
            except:
                pass
            return {"code": 500, "body": {"status": "error", "detail": str(e)}}

    # run on the shared event loop to avoid blocking Flask
    fut = asyncio.run_coroutine_threadsafe(do_list(), loop)
    res = fut.result(timeout=60)
    return jsonify(res["body"]), res["code"]






#==============================================
# Add member
#==============================================











from telethon.errors import (
    ChatAdminRequiredError, UserPrivacyRestrictedError,
    FloodWaitError, PeerFloodError, UsernameNotOccupiedError,
    UsernameInvalidError, RPCError
)
from telethon.tl.functions.messages import AddChatUserRequest, ExportChatInviteRequest
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl import types as T

async def _export_invite_link(client, entity):
    """
    Basic group বা megagroup—দুটোর জন্যই কাজ করে।
    """
    try:
        inv = await client(ExportChatInviteRequest(peer=entity))
        # Telethon v1.36+: inv.link; কিছু ক্ষেত্রে inv.invite.link
        link = getattr(inv, "link", None) or getattr(getattr(inv, "invite", None), "link", None)
        return link
    except Exception:
        return None

@app.route("/group_add_members", methods=["POST"])
def group_add_members():
    data = request.get_json(silent=True) or {}
    phone       = (data.get("phone") or "").strip().replace(" ", "")
    chat_id     = data.get("chat_id")
    grp_uname   = data.get("username")
    acc_hash    = data.get("access_hash")
    members     = data.get("members") or []
    fwd_limit   = int(data.get("fwd_limit", 0))
    dm_invite   = bool(data.get("dm_invite", False))     # optional: ইউজারকে DM করে লিংক পাঠাতে চাইলে
    welcome_text= (data.get("welcome_text") or "Please join the group:") if dm_invite else None

    if not phone or (not chat_id and not grp_uname) or not isinstance(members, list) or not members:
        return jsonify({"status":"error","detail":"phone, (chat_id or username), members[] required"}), 400

    async def _to_input_user(client, item):
        if item.get("username"):
            uname = str(item["username"]).lstrip("@")
            ent = await client.get_entity(uname)
            return T.InputUser(int(ent.id), int(ent.access_hash)), ent
        uid = item.get("user_id"); ah = item.get("access_hash")
        if uid is None or ah is None:
            raise ValueError("user spec needs username OR (user_id+access_hash)")
        # entity resolve (for optional DM)
        ent = await client.get_entity(int(uid))
        return T.InputUser(int(uid), int(ah)), ent

    async def do_add():
        client = await get_client(phone)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                return {"code": 401, "body": {"status":"error","detail":"not authorized"}}

            # ---- resolve target group ----
            if grp_uname:
                entity = await client.get_entity(grp_uname.lstrip("@"))
            else:
                entity = None
                if acc_hash not in (None, "",):
                    try:
                        entity = await client.get_entity(T.InputPeerChannel(int(chat_id), int(acc_hash)))
                    except Exception:
                        pass
                if entity is None:
                    # basic group fallback
                    try:
                        entity = await client.get_entity(T.InputPeerChat(int(chat_id)))
                    except Exception:
                        entity = await client.get_entity(int(chat_id))
            kind = "channel" if isinstance(entity, T.Channel) else "chat"

            # ---- users ----
            parsed = []
            errors_prepare = []
            for m in members:
                try:
                    iu, ent_user = await _to_input_user(client, m)
                    parsed.append((m, iu, ent_user))
                except (UsernameNotOccupiedError, UsernameInvalidError, ValueError) as e:
                    errors_prepare.append({"target": m.get("username") or str(m.get("user_id")), "ok": False, "error": str(e)})

            results = []
            if errors_prepare:
                results += errors_prepare

            if kind == "chat":
                # basic group: AddChatUserRequest per user; fallback → invite link (+ optional DM)
                for original, iu, ent_user in parsed:
                    label = original.get("username") or str(original.get("user_id"))
                    try:
                        await client(AddChatUserRequest(
                            chat_id=int(getattr(entity, "id", chat_id)),
                            user_id=iu,
                            fwd_limit=max(0, int(fwd_limit))
                        ))
                        results.append({"target": label, "ok": True})
                    except (UserPrivacyRestrictedError, ChatAdminRequiredError) as e:
                        inv = await _export_invite_link(client, entity)
                        # optional DM
                        if dm_invite and inv:
                            try:
                                await client.send_message(ent_user, f"{welcome_text}\n{inv}")
                            except Exception:
                                pass
                        results.append({"target": label, "ok": False, "error": type(e).__name__, "invite_link": inv})
                    except RPCError as e:
                        # ← আপনার কেস: CHAT_MEMBER_ADD_FAILED
                        if "CHAT_MEMBER_ADD_FAILED" in str(e):
                            inv = await _export_invite_link(client, entity)
                            if dm_invite and inv:
                                try:
                                    await client.send_message(ent_user, f"{welcome_text}\n{inv}")
                                except Exception:
                                    pass
                            results.append({"target": label, "ok": False, "error": "CHAT_MEMBER_ADD_FAILED", "invite_link": inv})
                        else:
                            results.append({"target": label, "ok": False, "error": str(e)})
                    except FloodWaitError as e:
                        results.append({"target": label, "ok": False, "error": f"FloodWait {getattr(e,'seconds',0)}s"})
                    except PeerFloodError:
                        results.append({"target": label, "ok": False, "error":"PeerFloodError"})
                    except Exception as e:
                        results.append({"target": label, "ok": False, "error": str(e)})

            else:
                # megagroup/channel: InviteToChannelRequest (batch)
                CHUNK = 20
                batch, labels, ents = [], [], []
                async def flush():
                    nonlocal batch, labels, ents
                    if not batch: return
                    b, L, E = batch, labels, ents
                    batch, labels, ents = [], [], []
                    try:
                        await client(InviteToChannelRequest(channel=entity, users=b))
                        for lab in L: results.append({"target": lab, "ok": True})
                    except (ChatAdminRequiredError, UserPrivacyRestrictedError) as e:
                        for lab in L: results.append({"target": lab, "ok": False, "error": type(e).__name__})
                    except FloodWaitError as e:
                        for lab in L: results.append({"target": lab, "ok": False, "error": f"FloodWait {getattr(e,'seconds',0)}s"})
                    except PeerFloodError:
                        for lab in L: results.append({"target": lab, "ok": False, "error":"PeerFloodError"})
                    except RPCError as e:
                        # privacy হলে এখানেও invite link দিয়ে দিন
                        if "USER_PRIVACY_RESTRICTED" in str(e):
                            inv = await _export_invite_link(client, entity)
                            for lab, uent in zip(L, E):
                                if dm_invite and inv:
                                    try: await client.send_message(uent, f"{welcome_text}\n{inv}")
                                    except Exception: pass
                                results.append({"target": lab, "ok": False, "error": "UserPrivacyRestrictedError", "invite_link": inv})
                        else:
                            for lab in L: results.append({"target": lab, "ok": False, "error": str(e)})
                for original, iu, ent_user in parsed:
                    batch.append(iu)
                    labels.append(original.get("username") or str(original.get("user_id")))
                    ents.append(ent_user)
                    if len(batch) >= CHUNK:
                        await flush()
                await flush()

            body = {
                "status": "ok",
                "group": {"type": "Channel" if kind=="channel" else "Chat",
                          "chat_id": int(getattr(entity, "id", chat_id))},
                "results": results
            }
            return {"code": 200, "body": body}
        finally:
            try: await client.disconnect()
            except: pass

    res = asyncio.run(do_add())
    return jsonify(res["body"]), res["code"]






@app.route("/group_export_invite", methods=["POST"])
def group_export_invite():
    data = request.get_json(silent=True) or {}
    phone = (data.get("phone") or "").strip().replace(" ", "")
    chat_id = data.get("chat_id")
    username = data.get("username")
    access_hash = data.get("access_hash")

    if not phone or (not chat_id and not username):
        return jsonify({"status":"error","detail":"phone and (chat_id or username) required"}), 400

    async def do_export():
        client = await get_client(phone)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                return {"code":401,"body":{"status":"error","detail":"not authorized"}}
            if username:
                ent = await client.get_entity(username.lstrip("@"))
            else:
                ent = None
                if access_hash not in (None, "",):
                    try: ent = await client.get_entity(T.InputPeerChannel(int(chat_id), int(access_hash)))
                    except Exception: pass
                if ent is None:
                    try: ent = await client.get_entity(T.InputPeerChat(int(chat_id)))
                    except Exception: ent = await client.get_entity(int(chat_id))

            inv = await client(ExportChatInviteRequest(peer=ent))
            link = getattr(inv, "link", None) or getattr(getattr(inv, "invite", None), "link", None)
            return {"code":200,"body":{"status":"ok","invite_link":link}}
        except Exception as e:
            return {"code":400,"body":{"status":"error","detail":str(e)}}
        finally:
            try: await client.disconnect()
            except: pass

    r = asyncio.run(do_export())
    return jsonify(r["body"]), r["code"]








# ==================================
# 🏁 RUN SERVER
# ==================================
if __name__ == "__main__":
    # threading.Thread(target=loop.run_forever, daemon=True).start()
    app.run(host="0.0.0.0", port=8080, debug=False)