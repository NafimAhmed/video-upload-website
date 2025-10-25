
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










@sock.route("/chat_ws")
def chat_ws(ws):
    """
    🚀 WebSocket chat stream (DM/Group/Channel + call events)
    Handshake (client → server):
    {
      "phone": "+8801...",
      "chat_id": -100...,                # required
      "access_hash": 123456789,          # User/Channel হলে ভালো; basic Chat হলে optional
      "no_seed": false                   # true হলে seed/history পাঠাবে না
    }

    Commands (client → server):
      - {"action":"ping"}
      - {"action":"stop"}
      - {"action":"typing_start"} | {"action":"typing_stop"}
      - {"action":"seed","limit":100,"hide_deleted":true}
      - {"action":"resync","limit":100}                     # alias of seed
      - {"action":"send","text":"Hi","reply_to":123}
      - {"action":"send","file_base64":"data:...","file_name":"x.jpg","mime_type":"image/jpeg","text":""}
        (optional) {"op_id":"op-abc123"}  # দিলে ACK-এ একই op_id ফিরে পাবে

    Server emits:
      - {"status":"listening", "chat_id":..., "peer_kind":"Channel|Chat|User", "is_groupish":bool, "insert_hint":"append|prepend"}
      - {"action":"seed","messages":[...], "insert_hint":"append|prepend"}
      - {"action":"new_message", ...}          # realtime (ডুপ্লিকেট-সেফ)
      - {"action":"typing", ...} / {"action":"typing_stopped", ...}
      - {"action":"call_update","state":"requested|accepted|ongoing|ended|canceled|missed|busy", ...}
      - {"action":"upload_progress","op_id":"...","progress": 0..100}
      - ACK: {"action":"ack","op_id":"...","stage":"accepted","temp_id":"local-..."}
      - ACK: {"action":"ack","op_id":"...","stage":"sent","temp_id":"local-...","msg_id":12345}
      - (compat) {"status":"sent","temp_id":"local-...","msg_id":12345}
      - {"action":"_hb","t":"..."}           # heartbeat
    """
    # ---------- imports ----------
    import os, json, time, threading, asyncio
    from queue import Queue, Empty
    from collections import deque
    from io import BytesIO
    from bson.objectid import ObjectId
    from gridfs import GridFS
    from telethon import events, functions, types
    from telethon.tl import types as TL

    # ---------- small helpers ----------
    def _now_iso():
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()

    alive = True
    out_q: Queue = Queue(maxsize=1000)

    # single writer → no concurrent ws.send
    def ws_send(obj):
        if not alive:
            return
        try:
            out_q.put_nowait(obj)
        except Exception:
            # non-critical events drop if congested
            if isinstance(obj, dict) and obj.get("action") in ("upload_progress","typing","typing_stopped","_hb","call_update"):
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
                try: print(f"⚠️ ws writer failed: {e}")
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

    # heartbeat
    HEARTBEAT_SEC = int(os.getenv("WS_HEARTBEAT_SEC", "25"))
    def heartbeat():
        while alive:
            time.sleep(HEARTBEAT_SEC)
            ws_send({"action":"_hb","t":_now_iso()})
    threading.Thread(target=heartbeat, daemon=True).start()

    # typing tracker (auto-stop after TTL)
    typing_tracker = {}
    typing_lock = threading.Lock()
    TYPING_TTL = 6.0
    def typing_cleaner():
        while alive:
            time.sleep(2.0)
            now = time.time()
            expired = []
            with typing_lock:
                for key, last in list(typing_tracker.items()):
                    if now - last > TYPING_TTL:
                        expired.append(key); typing_tracker.pop(key, None)
            for (cid, uid) in expired:
                ws_send({"action":"typing_stopped","chat_id":int(cid),"sender_id":uid,"date":_now_iso()})
    threading.Thread(target=typing_cleaner, daemon=True).start()

    # ---------- INIT ----------
    init_msg = safe_receive()
    if not init_msg:
        alive = False; out_q.put(None); return
    try:
        init = json.loads(init_msg)
    except Exception:
        ws_send({"status":"error","detail":"invalid init json"})
        alive = False; out_q.put(None); return

    phone = (init.get("phone") or "").strip()
    chat_id_raw = init.get("chat_id")
    access_hash_raw = init.get("access_hash")
    no_seed = bool(init.get("no_seed", False))

    if not phone or chat_id_raw is None:
        ws_send({"status":"error","detail":"phone/chat_id missing"})
        alive = False; out_q.put(None); return

    try:
        chat_id = int(chat_id_raw)
    except Exception:
        ws_send({"status":"error","detail":"chat_id must be int"})
        alive = False; out_q.put(None); return

    try:
        access_hash = int(access_hash_raw) if access_hash_raw not in (None,"") else None
    except Exception:
        access_hash = None

    # public base url for absolute media links (if needed later)
    try:
        host = ws.environ.get("HTTP_HOST") or "127.0.0.1:8080"
        scheme = "https" if (ws.environ.get("wsgi.url_scheme") == "https" or
                             ws.environ.get("HTTP_X_FORWARDED_PROTO") == "https") else "http"
        os.environ.setdefault("PUBLIC_BASE_URL", f"{scheme}://{host}/")
    except Exception:
        pass

    # ---------- Mongo & GridFS ----------
    MSG_COL = db.messages
    try:
        MSG_COL.create_index(
            [("phone",1),("chat_id",1),("msg_id",1)],
            name="uniq_msg", unique=True,
            partialFilterExpression={"msg_id":{"$type":"number"}}
        )
    except Exception:
        pass
    fs = GridFS(db, collection="fs")

    tg_client = None
    insert_hint = "append"
    peer_kind = "Unknown"

    # WS-session de-dupe for realtime emits
    sent_ids = set()
    sent_fifo = deque(maxlen=2000)
    def _mark_sent(mid: int) -> bool:
        if not isinstance(mid, int) or mid <= 0:
            return True
        if mid in sent_ids:
            return False
        sent_ids.add(mid)
        sent_fifo.append(mid)
        return True

    # progress throttling
    _last_prog = 0.0
    def progress_emit(op_id: str, pct: float):
        nonlocal _last_prog
        now = time.time()
        if now - _last_prog < 0.15:
            return
        _last_prog = now
        ws_send({"action":"upload_progress","op_id":op_id,"progress":pct})

    # classify peer for UI insert hint
    async def _classify_peer_kind(tg_client_, cid: int):
        try:
            ent = await tg_client_.get_entity(int(cid))
            kind = type(ent).__name__
            return kind, (kind in ("Channel","Chat"))
        except Exception:
            return "Unknown", True

    # ---------- listener task ----------
    newmsg_ev = None
    raw_ev = None
    async def run_listener():
        nonlocal tg_client, peer_kind, insert_hint, newmsg_ev, raw_ev
        tg_client = await get_client(phone)
        await tg_client.connect()
        if not await tg_client.is_user_authorized():
            ws_send({"status":"error","detail":"not authorized"})
            try: await tg_client.disconnect()
            except: pass
            return

        me = await tg_client.get_me()
        me_id = int(getattr(me, "id", 0))

        # resolve entity once (entity-based filter avoids missing service messages)
        try:
            peer_ent = await tg_client.get_entity(int(chat_id))
        except Exception:
            try: peer_ent = types.InputPeerChat(int(chat_id))
            except Exception: peer_ent = int(chat_id)

        peer_kind, is_groupish = await _classify_peer_kind(tg_client, int(chat_id))
        insert_hint = "append" if is_groupish else "prepend"

        ws_send({
            "status":"listening",
            "chat_id": int(chat_id),
            "peer_kind": peer_kind,
            "is_groupish": is_groupish,
            "insert_hint": insert_hint
        })

        # seed (if asked)
        if not no_seed:
            try:
                seed_docs = list(
                    MSG_COL.find({"phone":phone,"chat_id":int(chat_id)})
                           .sort([("date",1),("msg_id",1)])
                           .limit(int(os.getenv("WS_SEED_LIMIT","50")))
                )
                ws_send({
                    "action":"seed",
                    "messages":[_doc_to_api(phone,int(chat_id),access_hash,d) for d in seed_docs],
                    "insert_hint": insert_hint
                })
                for d in seed_docs:
                    mid = d.get("msg_id")
                    if isinstance(mid,int):
                        sent_ids.add(mid); sent_fifo.append(mid)
            except Exception as se:
                print("⚠️ seed error:", se)

        async def on_new_msg(event):
            try:
                mid = int(getattr(event.message, "id", 0) or 0)
                if mid and not _mark_sent(mid):
                    return  # duplicate within this WS session
                quick = _event_to_api_quick(phone, int(chat_id), access_hash, event)
                # sort helpers
                if "__sort_id" not in quick:
                    quick["__sort_id"] = int(quick.get("id") or mid or 0)
                if "__sort_ts" not in quick:
                    from datetime import datetime, timezone
                    try:
                        ts = datetime.fromisoformat((quick.get("date") or "").replace("Z","+00:00"))
                    except Exception:
                        ts = datetime.now(timezone.utc)
                    quick["__sort_ts"] = int(ts.timestamp()*1000)
                quick["insert_hint"] = insert_hint
                ws_send({"action":"new_message", **quick})

                # background archive (lazy)
                async def _bg():
                    try:
                        await archive_incoming_event(db, phone, int(chat_id), access_hash, event)
                    except Exception as e:
                        print("⚠️ archive bg error:", e)
                try:
                    asyncio.create_task(_bg())
                except RuntimeError:
                    await _bg()
            except Exception as e:
                print("⚠️ new_message emit error:", e)

        async def on_raw(update):
            # --- call live updates (1:1 DM only) ---
            try:
                if isinstance(update, TL.UpdatePhoneCall):
                    pc = update.phone_call
                    state, is_video, duration, other_user = None, False, None, None

                    if isinstance(pc, TL.PhoneCallRequested):
                        state = "requested"
                        is_video = bool(getattr(pc, "video", False))
                        other_user = int(pc.participant_id if int(pc.admin_id) == me_id else pc.admin_id)
                    elif isinstance(pc, TL.PhoneCallAccepted):
                        state = "accepted"
                        other_user = int(pc.participant_id if int(pc.admin_id) == me_id else pc.admin_id)
                    elif isinstance(pc, TL.PhoneCall):
                        state = "ongoing"
                        is_video = bool(getattr(pc, "video", False))
                        other_user = int(pc.participant_id if int(pc.admin_id) == me_id else pc.admin_id)
                    elif isinstance(pc, TL.PhoneCallDiscarded):
                        reason = type(getattr(pc, "reason", None)).__name__ if getattr(pc, "reason", None) else None
                        if reason == 'PhoneCallDiscardReasonMissed':  state = 'missed'
                        elif reason == 'PhoneCallDiscardReasonBusy': state = 'busy'
                        elif reason == 'PhoneCallDiscardReasonHangup': state = 'canceled'
                        else: state = 'ended'
                        duration = getattr(pc, "duration", None)
                        other_user = int(pc.participant_id if int(pc.admin_id) == me_id else pc.admin_id)

                    # this WS is only for a single chat_id → match that user
                    if other_user and int(chat_id) == int(other_user):
                        ws_send({
                            "action": "call_update",
                            "chat_id": int(chat_id),
                            "state": state,
                            "is_video": bool(is_video),
                            "duration": duration,
                            "date": _now_iso()
                        })
            except Exception as e:
                print("⚠️ call raw handler error:", e)

            # --- typing updates (with TTL auto-stop) ---
            try:
                upd_chat_id, user_id = None, None
                if isinstance(update, types.UpdateUserTyping):
                    upd_chat_id = int(update.user_id); user_id = int(update.user_id)
                elif isinstance(update, types.UpdateChatUserTyping):
                    upd_chat_id = int(update.chat_id); user_id = int(update.user_id)
                elif isinstance(update, types.UpdateChannelUserTyping):
                    upd_chat_id = int(update.channel_id); user_id = int(update.user_id)
                if upd_chat_id and int(upd_chat_id) == int(chat_id):
                    with typing_lock:
                        typing_tracker[(upd_chat_id, user_id)] = time.time()
                    ws_send({"action":"typing","chat_id":int(upd_chat_id),"sender_id":user_id,"typing":True,"date":_now_iso()})
            except Exception as e:
                print("⚠️ typing event error:", e)

        newmsg_ev = events.NewMessage(chats=peer_ent)
        tg_client.add_event_handler(on_new_msg, newmsg_ev)
        raw_ev = events.Raw()
        tg_client.add_event_handler(on_raw, raw_ev)

        try:
            await tg_client.run_until_disconnected()
        finally:
            try: tg_client.remove_event_handler(on_new_msg, newmsg_ev)
            except Exception: pass
            try: tg_client.remove_event_handler(on_raw, raw_ev)
            except Exception: pass
            try: await tg_client.disconnect()
            except Exception: pass

    # start listener on global loop
    asyncio.run_coroutine_threadsafe(run_listener(), loop)

    # helper: robust peer resolve (for commands)
    async def _resolve_peer():
        from telethon import types as _t
        try:
            if access_hash:
                try: return _t.InputPeerUser(int(chat_id), int(access_hash))
                except:
                    try: return _t.InputPeerChannel(int(chat_id), int(access_hash))
                    except: return _t.InputPeerChat(int(chat_id))
            else:
                return await tg_client.get_entity(int(chat_id))
        except Exception:
            return _t.InputPeerChat(int(chat_id))

    # ---------- command loop ----------
    try:
        while alive:
            rec = safe_receive()
            if rec is None:
                break
            try:
                data = json.loads(rec)
            except Exception:
                ws_send({"status":"error","detail":"invalid json"})
                continue

            act = data.get("action")

            if act == "stop":
                break

            elif act == "ping":
                ws_send({"status":"pong"})

            elif act in ("typing_start","typing_stop"):
                async def do_typing(act_=act):
                    try:
                        if not tg_client: return
                        peer = await _resolve_peer()
                        req = (types.SendMessageTypingAction() if act_=="typing_start"
                               else types.SendMessageCancelAction())
                        await tg_client(functions.messages.SetTypingRequest(peer=peer, action=req))
                        ws_send({"status":f"{act_}_ok"})
                    except Exception as e:
                        ws_send({"status":"error","detail":str(e)})
                asyncio.run_coroutine_threadsafe(do_typing(), loop)

            elif act in ("seed", "resync"):
                # client-requested re-seed (manual)
                try:
                    limit = int(data.get("limit", os.getenv("WS_SEED_LIMIT", "50")))
                except Exception:
                    limit = 50
                only_deleted = bool(data.get("only_deleted", False))
                hide_deleted = bool(data.get("hide_deleted", False))

                filt = {"phone": phone, "chat_id": int(chat_id)}
                if only_deleted:
                    filt["deleted_on_telegram"] = True
                elif hide_deleted:
                    filt["deleted_on_telegram"] = {"$ne": True}

                try:
                    seed_docs = list(
                        MSG_COL.find(filt)
                               .sort([("date", 1), ("msg_id", 1)])
                               .limit(int(limit))
                    )
                    ws_send({
                        "action": "seed",
                        "messages": [
                            _doc_to_api(phone, int(chat_id), access_hash, d) for d in seed_docs
                        ],
                        "insert_hint": insert_hint
                    })
                    for d in seed_docs:
                        mid = d.get("msg_id")
                        if isinstance(mid, int):
                            try:
                                sent_ids.add(mid)
                                sent_fifo.append(mid)
                            except:
                                pass
                except Exception as e:
                    ws_send({"status": "error", "detail": f"seed_failed: {e}"})

            elif act == "send":
                import uuid as _uuid
                text = (data.get("text") or "").strip()
                file_b64 = data.get("file_base64") or data.get("file_b64")
                file_name = data.get("file_name","file.bin")
                mime_type = data.get("mime_type","")
                reply_to_raw = data.get("reply_to") or data.get("reply_to_msg_id")
                try:
                    reply_to_id = int(reply_to_raw) if reply_to_raw not in (None,"") else None
                except Exception:
                    reply_to_id = None
                op_id = data.get("op_id") or f"op-{_uuid.uuid4().hex[:8]}"

                # empty guard
                if not text and not file_b64:
                    ws_send({"action":"ack","op_id":op_id,"stage":"error","detail":"The message cannot be empty unless a file is provided"})
                    continue

                async def do_send():
                    nonlocal tg_client
                    try:
                        # ensure client ready
                        if tg_client is None:
                            tg_client = await get_client(phone)
                        if not tg_client.is_connected():
                            await tg_client.connect()
                        if not await tg_client.is_user_authorized():
                            ws_send({"action":"ack","op_id":op_id,"stage":"error","detail":"not authorized"})
                            return

                        # pre-archive → optimistic bubble
                        pre = await archive_outgoing_pre(
                            db=db,
                            phone=phone, chat_id=int(chat_id), access_hash=access_hash,
                            text=text, reply_to_id=reply_to_id,
                            file_b64=file_b64, file_name=file_name, mime_type=mime_type
                        )
                        # ACK #1
                        ws_send({"action":"ack","op_id":op_id,"stage":"accepted","temp_id":pre["temp_id"]})

                        # optimistic bubble
                        ws_send({
                            "action":"new_message",
                            "id": pre.get("temp_id"),
                            "text": text or "",
                            "sender_id": None,
                            "sender_name": "Me",
                            "date": _now_iso(),
                            "is_out": True,
                            "reply_to": reply_to_id,
                            "media_type": pre.get("media_type","text"),
                            "media_link": None,
                            "deleted_on_telegram": False,
                            "exists_on_telegram": False,
                            "insert_hint": insert_hint
                        })

                        # resolve & send
                        peer = await _resolve_peer()

                        msg_obj = None
                        if (pre.get("media_type") or "text") == "text":
                            msg_obj = await tg_client.send_message(peer, text or "", reply_to=reply_to_id)
                        else:
                            # send file from GridFS
                            blob = None
                            if pre.get("media_fs_id"):
                                try:
                                    gf = fs.get(ObjectId(pre["media_fs_id"]))
                                    blob = gf.read()
                                except Exception:
                                    blob = None
                            bio = BytesIO(blob) if blob else None
                            if bio: bio.name = file_name

                            def _cb(sent, total):
                                try:
                                    pct = round((sent / max(1,total)) * 100.0, 1)
                                except Exception:
                                    pct = 0.0
                                progress_emit(op_id, pct)

                            mt = pre.get("media_type") or "file"
                            if mt == "voice":
                                msg_obj = await tg_client.send_file(peer, bio, caption=text or "",
                                                                    voice_note=True, reply_to=reply_to_id,
                                                                    progress_callback=_cb)
                            elif mt == "video":
                                msg_obj = await tg_client.send_file(peer, bio, caption=text or "",
                                                                    supports_streaming=True, reply_to=reply_to_id,
                                                                    progress_callback=_cb)
                            else:
                                msg_obj = await tg_client.send_file(peer, bio, caption=text or "",
                                                                    reply_to=reply_to_id, progress_callback=_cb)

                        fin = await archive_outgoing_finalize(db, phone, int(chat_id), pre["temp_id"], msg_obj)
                        mid = int(getattr(msg_obj, "id", 0) or 0)
                        if mid:
                            try: _mark_sent(mid)
                            except: pass

                        # Final ACKs
                        ws_send({"action":"ack","op_id":op_id,"stage":"sent","temp_id":pre["temp_id"],"msg_id": mid})
                        ws_send({"status":"sent","temp_id":pre["temp_id"],"msg_id": mid})
                        # realtime echo আসলেও de-dup এর কারণে একবারই UI তে বসবে

                    except Exception as e:
                        ws_send({"action":"ack","op_id":op_id,"stage":"error","detail":str(e)})

                asyncio.run_coroutine_threadsafe(do_send(), loop)

            else:
                ws_send({"status":"error","detail":"unknown action"})

    except Exception as e:
        if "closed" in str(e).lower():
            print(f"ℹ️ [chat_ws] client closed: {e}")
        else:
            print(f"⚠️ [chat_ws] Exception: {e}")
    finally:
        alive = False
        out_q.put(None)
        print("❌ [chat_ws] disconnected")











# @sock.route("/chat_ws")
# def chat_ws(ws):
#     print("🔗 [chat_ws] connected")
#
#     alive = True
#     out_q: Queue = Queue(maxsize=1000)
#
#     # -------- single-writer --------
#     def ws_send(obj):
#         if not alive: return
#         try:
#             out_q.put_nowait(obj)
#         except Exception:
#             # drop chatty if congested
#             if isinstance(obj, dict) and obj.get("action") in ("upload_progress","typing","typing_stopped","_hb"):
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
#     threading.Thread(target=writer, daemon=True).start()
#
#     def safe_receive():
#         try:
#             return ws.receive()
#         except Exception as e:
#             if "closed" in str(e).lower(): return None
#             raise
#
#     # -------- heartbeat --------
#     HEARTBEAT_SEC = int(os.getenv("WS_HEARTBEAT_SEC", "25"))
#     def heartbeat():
#         while alive:
#             time.sleep(HEARTBEAT_SEC)
#             ws_send({"action": "_hb", "t": _now_iso()})
#     threading.Thread(target=heartbeat, daemon=True).start()
#
#     # -------- typing TTL --------
#     typing_tracker = {}
#     typing_lock = threading.Lock()
#     TYPING_TTL = 6.0
#     def typing_cleaner():
#         while alive:
#             time.sleep(2.0)
#             now = time.time()
#             expired = []
#             with typing_lock:
#                 for key, last in list(typing_tracker.items()):
#                     if now - last > TYPING_TTL:
#                         expired.append(key); typing_tracker.pop(key, None)
#             for (cid, uid) in expired:
#                 ws_send({"action":"typing_stopped","chat_id":int(cid),"sender_id":uid,"date":_now_iso()})
#     threading.Thread(target=typing_cleaner, daemon=True).start()
#
#     # -------- INIT --------
#     init_msg = safe_receive()
#     if not init_msg:
#         print("❌ [chat_ws] no init, closing")
#         alive = False; out_q.put(None); return
#
#     try:
#         init = json.loads(init_msg)
#     except Exception:
#         ws_send({"status":"error","detail":"invalid init json"})
#         alive = False; out_q.put(None); return
#
#     phone = (init.get("phone") or "").strip()
#     chat_id_raw = init.get("chat_id")
#     access_hash_raw = init.get("access_hash")
#     no_seed = bool(init.get("no_seed", False))       # NEW: client can skip seed if it already fetched via /messages
#
#     if not phone or chat_id_raw is None:
#         ws_send({"status":"error","detail":"phone/chat_id missing"})
#         alive = False; out_q.put(None); return
#
#     try:
#         chat_id = int(chat_id_raw)
#     except Exception:
#         ws_send({"status":"error","detail":"chat_id must be int"})
#         alive = False; out_q.put(None); return
#
#     try:
#         access_hash = int(access_hash_raw) if access_hash_raw not in (None,"") else None
#     except Exception:
#         access_hash = None
#
#     # PUBLIC_BASE_URL for absolute links
#     try:
#         host = ws.environ.get("HTTP_HOST") or "127.0.0.1:8080"
#         scheme = "https" if (ws.environ.get("wsgi.url_scheme") == "https" or
#                              ws.environ.get("HTTP_X_FORWARDED_PROTO") == "https") else "http"
#         os.environ.setdefault("PUBLIC_BASE_URL", f"{scheme}://{host}/")
#     except Exception:
#         pass
#
#     # -------- Mongo & FS --------
#     MSG_COL = db.messages
#     try:
#         MSG_COL.create_index(
#             [("phone",1),("chat_id",1),("msg_id",1)],
#             name="uniq_msg", unique=True,
#             partialFilterExpression={"msg_id":{"$type":"number"}}
#         )
#     except Exception:
#         pass
#     fs = GridFS(db, collection="fs")
#
#     tg_client = None
#     insert_hint = "append"
#     peer_kind = "Unknown"
#
#     # **Per-WS de-dupe** for realtime emits
#     sent_ids = set()             # msg_id set
#     sent_fifo = deque(maxlen=1000)  # to trim memory
#
#     def _mark_sent(mid: int) -> bool:
#         """return True if first time, False if duplicate"""
#         if mid in sent_ids:
#             return False
#         sent_ids.add(mid)
#         sent_fifo.append(mid)
#         if len(sent_fifo) == sent_fifo.maxlen:
#             # drop oldest from set when deque auto-drops (approximate)
#             try:
#                 # deque already keeps last N; we can't see the popped one directly,
#                 # but set won't grow unbounded since ids are reused per session.
#                 pass
#             except: pass
#         return True
#
#     async def _classify_peer_kind(tg_client_, cid: int):
#         try:
#             ent = await tg_client_.get_entity(int(cid))
#             kind = type(ent).__name__
#             return kind, (kind in ("Channel","Chat"))
#         except Exception:
#             return "Unknown", True
#
#     # Keep references to remove handlers on cleanup
#     newmsg_ev = None
#     raw_typing_ev = None
#     async def run_listener():
#         nonlocal tg_client, insert_hint, peer_kind, newmsg_ev, raw_typing_ev
#         tg_client = await get_client(phone)
#         await tg_client.connect()
#         if not await tg_client.is_user_authorized():
#             ws_send({"status":"error","detail":"not authorized"})
#             await tg_client.disconnect()
#             return
#
#         peer_kind, is_groupish = await _classify_peer_kind(tg_client, int(chat_id))
#         insert_hint = "append" if is_groupish else "prepend"
#
#         ws_send({
#             "status":"listening",
#             "chat_id":int(chat_id),
#             "peer_kind":peer_kind,
#             "is_groupish":is_groupish,
#             "insert_hint":insert_hint
#         })
#
#         # seed only if client didn't opt out
#         if not no_seed:
#             try:
#                 seed_docs = list(
#                     MSG_COL.find({"phone":phone,"chat_id":int(chat_id)})
#                            .sort([("date",1),("msg_id",1)])
#                            .limit(int(os.getenv("WS_SEED_LIMIT","50")))
#                 )
#                 ws_send({
#                     "action":"seed",
#                     "messages":[_doc_to_api(phone,int(chat_id),access_hash,d) for d in seed_docs],
#                     "insert_hint":insert_hint
#                 })
#                 # prime de-dupe with seed ids so realtime echo won't re-add them
#                 for d in seed_docs:
#                     mid = d.get("msg_id")
#                     if isinstance(mid,int): sent_ids.add(mid); sent_fifo.append(mid)
#             except Exception as se:
#                 print("⚠️ seed history error:", se)
#
#         # --- realtime handlers (explicit add/remove) ---
#         async def on_new_msg(event):
#             try:
#                 mid = int(getattr(event.message,"id",0) or 0)
#                 if mid and not _mark_sent(mid):
#                     return  # skip duplicate emit within this WS session
#
#                 quick = _event_to_api_quick(phone, int(chat_id), access_hash, event)
#
#                 # stable sort helpers (just in case)
#                 if "__sort_id" not in quick:
#                     quick["__sort_id"] = int(quick.get("id") or mid or 0)
#                 if "__sort_ts" not in quick:
#                     from datetime import datetime, timezone
#                     try:
#                         ts = datetime.fromisoformat((quick.get("date") or "").replace("Z","+00:00"))
#                     except Exception:
#                         ts = datetime.now(timezone.utc)
#                     quick["__sort_ts"] = int(ts.timestamp()*1000)
#
#                 quick["insert_hint"] = insert_hint
#                 ws_send({"action":"new_message", **quick})
#
#                 # archive in background
#                 async def _bg():
#                     try:
#                         await archive_incoming_event(db, phone, int(chat_id), access_hash, event)
#                     except Exception as e:
#                         print("⚠️ bg archive error:", e)
#                 try:
#                     asyncio.create_task(_bg())
#                 except RuntimeError:
#                     await _bg()
#             except Exception as e:
#                 print(f"⚠️ new_message emit error: {e}")
#
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
#                     with typing_lock:
#                         typing_tracker[(upd_chat_id, user_id)] = time.time()
#                     ws_send({"action":"typing","chat_id":int(upd_chat_id),
#                              "sender_id":user_id,"typing":True,"date":_now_iso()})
#             except Exception as e:
#                 print(f"⚠️ typing event error: {e}")
#
#         newmsg_ev = events.NewMessage(chats=int(chat_id))
#         tg_client.add_event_handler(on_new_msg, newmsg_ev)
#
#         raw_typing_ev = events.Raw()
#         tg_client.add_event_handler(on_typing_raw, raw_typing_ev)
#
#         try:
#             await tg_client.run_until_disconnected()
#         finally:
#             # remove handlers explicitly
#             try: tg_client.remove_event_handler(on_new_msg, newmsg_ev)
#             except Exception: pass
#             try: tg_client.remove_event_handler(on_typing_raw, raw_typing_ev)
#             except Exception: pass
#             try: await tg_client.disconnect()
#             except Exception: pass
#
#     asyncio.run_coroutine_threadsafe(run_listener(), loop)
#
#     # helpers for commands
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
#     progress_last = 0.0
#     def progress_emit(pct):
#         nonlocal progress_last
#         now = time.time()
#         if now - progress_last < 0.15: return
#         progress_last = now
#         ws_send({"action":"upload_progress","progress":pct})
#
#     # -------- WS command loop --------
#     try:
#         while alive:
#             rec = safe_receive()
#             if rec is None: break
#             try:
#                 data = json.loads(rec)
#             except Exception:
#                 ws_send({"status":"error","detail":"invalid json"})
#                 continue
#
#             act = data.get("action")
#
#             if act == "stop":
#                 break
#
#             elif act == "ping":
#                 ws_send({"status":"pong"})
#
#             elif act in ("typing_start","typing_stop"):
#                 async def do_typing(act_=act):
#                     try:
#                         if not tg_client: return
#                         peer = await resolve_entity()
#                         req = (types.SendMessageTypingAction() if act_=="typing_start"
#                                else types.SendMessageCancelAction())
#                         await tg_client(functions.messages.SetTypingRequest(peer=peer, action=req))
#                         ws_send({"status":f"{act_}_ok"})
#                     except Exception as e:
#                         ws_send({"status":"error","detail":str(e)})
#                 asyncio.run_coroutine_threadsafe(do_typing(), loop)
#
#             elif act == "send":
#                 text = data.get("text")
#                 file_b64 = data.get("file_base64")
#                 file_name = data.get("file_name","file.bin")
#                 mime_type = data.get("mime_type","")
#                 reply_to_raw = data.get("reply_to") or data.get("reply_to_msg_id")
#                 try:
#                     reply_to_id = int(reply_to_raw) if reply_to_raw else None
#                 except:
#                     reply_to_id = None
#
#                 async def do_send():
#                     try:
#                         if not tg_client or not await tg_client.is_user_authorized():
#                             ws_send({"status":"error","detail":"not authorized"})
#                             return
#
#                         pre = await archive_outgoing_pre(
#                             db=db, phone=phone, chat_id=int(chat_id), access_hash=access_hash,
#                             text=text, reply_to_id=reply_to_id, file_b64=file_b64,
#                             file_name=file_name, mime_type=mime_type
#                         )
#                         peer = await resolve_entity()
#
#                         msg_obj = None
#                         if (pre.get("media_type") or "text") == "text":
#                             msg_obj = await tg_client.send_message(peer, text or "", reply_to=reply_to_id)
#                         else:
#                             blob = None
#                             if pre.get("media_fs_id"):
#                                 try: blob = fs.get(ObjectId(pre["media_fs_id"])).read()
#                                 except Exception: blob = None
#                             bio = BytesIO(blob) if blob else None
#                             if bio: bio.name = file_name
#
#                             def cb(sent, total):
#                                 try:
#                                     pct = round((sent / max(1,total)) * 100.0, 1)
#                                 except Exception:
#                                     pct = 0.0
#                                 progress_emit(pct)
#
#                             mt = pre.get("media_type") or "file"
#                             if mt == "voice":
#                                 msg_obj = await tg_client.send_file(peer, bio, caption=text or "",
#                                                                     voice_note=True, reply_to=reply_to_id,
#                                                                     progress_callback=cb)
#                             elif mt == "video":
#                                 msg_obj = await tg_client.send_file(peer, bio, caption=text or "",
#                                                                     supports_streaming=True, reply_to=reply_to_id,
#                                                                     progress_callback=cb)
#                             else:
#                                 msg_obj = await tg_client.send_file(peer, bio, caption=text or "",
#                                                                     reply_to=reply_to_id, progress_callback=cb)
#
#                         await archive_outgoing_finalize(db, phone, int(chat_id), pre["temp_id"], msg_obj)
#                         # realtime echo will arrive via on_new_msg()
#
#                     except Exception as e:
#                         ws_send({"status":"error","detail":str(e)})
#
#                 asyncio.run_coroutine_threadsafe(do_send(), loop)
#
#             else:
#                 ws_send({"status":"error","detail":"unknown action"})
#
#     except Exception as e:
#         if "closed" in str(e).lower():
#             print(f"ℹ️ [chat_ws] client closed: {e}")
#         else:
#             print(f"⚠️ [chat_ws] Exception: {e}")
#     finally:
#         alive = False
#         out_q.put(None)
#         # tg_client cleanup handled inside run_listener()
#         print("❌ [chat_ws] disconnected")




# ======= END DROP-IN =======













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







@app.route("/messages")
def get_messages():
    """
    Mongo-first message feed + live existence verify:
      Query:
        phone=... (required)
        chat_id=... (required, int)
        access_hash=... (optional, int)
        limit=50 (optional)
        verify_deleted=1 (optional)  -> last 300 ids reconcile via get_messages()
        only_deleted=1 (optional)    -> return only deleted ones from Mongo
        hide_deleted=1 (optional)    -> exclude deleted ones from Mongo
        patch_db=0/1 (optional)      -> default 1: write tombstone to DB after live-check
    Response: newest-last (ascending by time)
    """
    import asyncio
    from telethon import types

    # ---------- parse params ----------
    raw_phone = request.args.get("phone")
    chat_id_raw = request.args.get("chat_id")
    access_hash_raw = request.args.get("access_hash")
    try:
        limit = int(request.args.get("limit", 50))
    except Exception:
        limit = 50

    verify_deleted = request.args.get("verify_deleted") == "1"
    only_deleted   = request.args.get("only_deleted") == "1"
    hide_deleted   = request.args.get("hide_deleted") == "1"
    patch_db       = (request.args.get("patch_db", "1") != "0")

    if not raw_phone or not chat_id_raw:
        return jsonify({"status": "error", "detail": "missing params"}), 400

    # normalize
    phone = raw_phone.strip().replace(" ", "")
    try:
        chat_id = int(chat_id_raw)
    except Exception:
        return jsonify({"status": "error", "detail": "chat_id must be int"}), 400

    try:
        access_hash_int = int(access_hash_raw) if access_hash_raw not in (None, "",) else None
    except Exception:
        access_hash_int = None

    # ---------- helper: pull recent window from Telegram (lazy media) ----------
    async def pull_once():
        tg_client = await get_client(phone)
        await tg_client.connect()
        try:
            if not await tg_client.is_user_authorized():
                return  # not authorized → serve from Mongo

            # resolve peer robustly
            try:
                if access_hash_int is not None:
                    try:
                        peer = types.InputPeerUser(int(chat_id), int(access_hash_int))
                    except Exception:
                        try:
                            peer = types.InputPeerChannel(int(chat_id), int(access_hash_int))
                        except Exception:
                            peer = types.InputPeerChat(int(chat_id))
                else:
                    peer = await tg_client.get_entity(int(chat_id))
            except Exception:
                try:
                    peer = types.InputPeerChat(int(chat_id))
                except Exception:
                    return

            # pull small window and upsert (no media download)
            PULL_LIMIT = 200
            async for msg in tg_client.iter_messages(peer, limit=PULL_LIMIT):
                await _upsert_message_from_msg(tg_client, phone, int(chat_id), access_hash_int, msg)
        finally:
            try:
                await tg_client.disconnect()
            except Exception:
                pass

    # ---------- helper: live probe which ids still exist on Telegram ----------
    async def _probe_existing_ids(phone: str, chat_id: int, access_hash: int | None, ids: list[int]) -> set[int]:
        """
        Telegram-এ ওই chat-এর প্রদত্ত msg_id-গুলো এখনো আছে কিনা—সেট (existing_ids) রিটার্ন করে।
        """
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
                    if m and getattr(m, "id", None) is not None:
                        existing.add(int(m.id))
            return existing
        finally:
            try: await client.disconnect()
            except: pass

    # ---------- run pull (+ optional verify_deleted) on a temp loop ----------
    tmp_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(tmp_loop)
    try:
        tmp_loop.run_until_complete(pull_once())
        if verify_deleted:
            # helper already defined elsewhere in your file
            tmp_loop.run_until_complete(
                _verify_deleted_for_chat(phone, int(chat_id), access_hash_int, max_check=300)
            )
    finally:
        try:
            tmp_loop.close()
        except Exception:
            pass

    # ---------- read from Mongo with filters ----------
    MSG_COL = db.messages
    filt = {"phone": phone, "chat_id": int(chat_id)}
    if only_deleted:
        filt["deleted_on_telegram"] = True
    elif hide_deleted:
        filt["deleted_on_telegram"] = {"$ne": True}

    latest_docs = list(
        MSG_COL.find(filt)
               .sort([("date", -1), ("msg_id", -1)])   # newest → oldest
               .limit(limit)
    )
    latest_docs.reverse()  # oldest → newest

    # ---------- live verify the exact docs we will return ----------
    # numeric msg_id only (temp/pending rows বাদ)
    ids: list[int] = []
    id_to_doc: dict[int, dict] = {}
    for d in latest_docs:
        mid = d.get("msg_id")
        try:
            if mid is not None:
                mid = int(mid)
                ids.append(mid)
                id_to_doc[mid] = d
        except Exception:
            continue

    existing_ids: set[int] = set()
    if ids:
        loop2 = asyncio.new_event_loop()
        asyncio.set_event_loop(loop2)
        try:
            existing_ids = loop2.run_until_complete(
                _probe_existing_ids(phone, int(chat_id), access_hash_int, ids)
            )
        finally:
            try: loop2.close()
            except: pass

    missing_ids = [i for i in ids if i not in existing_ids]
    if missing_ids:
        # in-memory flag set → _doc_to_api ঠিক তথ্য দেবে
        for mid in missing_ids:
            try:
                id_to_doc[mid]["deleted_on_telegram"] = True
            except Exception:
                pass
        # optional DB patch (default on)
        if patch_db:
            try:
                MSG_COL.update_many(
                    {"phone": phone, "chat_id": int(chat_id), "msg_id": {"$in": missing_ids}},
                    {"$set": {"deleted_on_telegram": True}}
                )
            except Exception as e:
                print("⚠️ patch_db update_many error:", e)

    # ---------- build API objects (flags now accurate) ----------
    msgs = [_doc_to_api(phone, int(chat_id), access_hash_int, d) for d in latest_docs]
    return jsonify({"status": "ok", "messages": msgs})






















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









# ==================================
# 🏁 RUN SERVER
# ==================================
if __name__ == "__main__":
    # threading.Thread(target=loop.run_forever, daemon=True).start()
    app.run(host="0.0.0.0", port=8080, debug=False)