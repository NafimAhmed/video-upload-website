


import os
import asyncio
from flask import Flask, request, jsonify
from telethon import TelegramClient
from telethon.errors import (
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
    PhoneNumberInvalidError,
)

# =============================
# 🔧 CONFIGURATION
# =============================

API_ID = int(os.getenv("TG_API_ID", "20767444"))        # ← তোমার Telegram App ID বসাও
API_HASH = os.getenv("TG_API_HASH", "2ca0cb711803e1aae9e45d34eb81e57a")  # ← তোমার App Hash বসাও
SESS_DIR = "./sessions"
os.makedirs(SESS_DIR, exist_ok=True)

# =============================
# 🚀 Flask App Init
# =============================
app = Flask(__name__)

def get_client(phone: str):
    """Session per phone number"""
    session_path = os.path.join(SESS_DIR, f"{phone}.session")
    return TelegramClient(session_path, API_ID, API_HASH)


# =============================
# 📱 1️⃣ Login Endpoint (send OTP)
# =============================
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
                return {"status": "already_authorized"}
            sent = await client.send_code_request(phone)
            print(f"📨 Sent code to {phone} | hash={sent.phone_code_hash}")
            return {
                "status": "code_sent",
                "phone_code_hash": sent.phone_code_hash
            }
        except PhoneNumberInvalidError:
            return {"status": "error", "detail": "Invalid phone number"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}
        finally:
            await client.disconnect()

    result = loop.run_until_complete(send_code())
    print("✅ Login result:", result)
    return jsonify(result)


# =============================
# 🔑 2️⃣ Verify Endpoint (verify OTP)
# =============================
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
                return {"status": "already_authorized"}
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            return {"status": "authorized"}
        except PhoneCodeInvalidError:
            return {"status": "error", "detail": "Invalid OTP code"}
        except SessionPasswordNeededError:
            return {"status": "error", "detail": "Two-step verification enabled"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}
        finally:
            await client.disconnect()

    result = loop.run_until_complete(do_verify())
    print("✅ Verify result:", result)
    return jsonify(result)


# =============================
# ✉️ 3️⃣ Send Message
# =============================
@app.route("/send", methods=["POST"])
def send_message():
    phone = request.form.get("phone")
    to = request.form.get("to")
    text = request.form.get("text")

    if not phone or not to or not text:
        return jsonify({"status": "error", "detail": "phone/to/text missing"}), 400

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def do_send():
        client = get_client(phone)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                return {"status": "error", "detail": "not authorized"}
            await client.send_message(to, text)
            return {"status": "sent"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}
        finally:
            await client.disconnect()

    result = loop.run_until_complete(do_send())
    print("✅ Send result:", result)
    return jsonify(result)


# =============================
# 💬 4️⃣ Get Dialogs (chat list)
# =============================
@app.route("/dialogs", methods=["GET"])
def get_dialogs():
    phone = request.args.get("phone")
    if not phone:
        return jsonify({"status": "error", "detail": "phone missing"}), 400

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def do_get_dialogs():
        client = get_client(phone)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                return {"status": "error", "detail": "not authorized"}
            dialogs = []
            async for d in client.iter_dialogs(limit=50):
                dialogs.append({
                    "id": d.id,
                    "name": getattr(d.entity, 'title', getattr(d.entity, 'username', str(d.entity)))
                })
            return {"status": "ok", "dialogs": dialogs}
        except Exception as e:
            return {"status": "error", "detail": str(e)}
        finally:
            await client.disconnect()

    result = loop.run_until_complete(do_get_dialogs())
    print("✅ Dialogs result:", result)
    return jsonify(result)


# =============================
# 🏁 RUN APP
# =============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
