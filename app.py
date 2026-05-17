import os
import re
import logging
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Config — set these in Render environment variables
BOT_TOKEN  = os.environ["BOT_TOKEN"]
OPENAI_KEY = os.environ["OPENAI_KEY"]
BASE_URL   = f"https://api.telegram.org/bot{BOT_TOKEN}"

# In-memory state
state = {"james_chat_id": None, "pending": {}}

SENSITIVE = [
    "price", "pricing", "how much", "cost", "pay", "payment",
    "fee", "invoice", "charge", "refund", "discount", "deal",
    "contract", "hire", "sign up", "purchase", "buy", "commit",
    "guarantee", "personal info", "phone number", "my address",
    "legal", "lawsuit", "attorney", "liability",
    "invest", "partner", "equity", "revenue", "profit",
    "join the team", "work with you", "consulting",
    "coaching price", "playbook price", "skool price",
    "how do i get started", "how to join", "register", "enroll"
]

def classify(text):
    t = text.lower()
    for kw in SENSITIVE:
        if kw in t:
            return "sensitive"
    return "informational"

def send_msg(chat_id, text):
    try:
        requests.post(f"{BASE_URL}/sendMessage", json={
            "chat_id": chat_id, "text": text, "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        logging.error(f"send_msg error: {e}")

def gpt_reply(question):
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_KEY}"},
        json={
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": (
                    "You are Jarvis, the AI assistant for AST Agency - a trucking business coaching "
                    "company run by James Reynoso. AST Agency helps owner-operators, cargo van drivers, "
                    "box truck owners, hot shot carriers, and freight dispatchers build profitable businesses.\n\n"
                    "Products: Carrier Development Playbook ($35), AST Agency Skool Community, "
                    "Truck Business Blueprint, 1-on-1 consulting.\n"
                    "Website: https://astagency.base44.app\n\n"
                    "Be warm, motivating, and direct. Keep replies under 200 words. Use emojis sparingly."
                )},
                {"role": "user", "content": question}
            ],
            "max_tokens": 400
        }, timeout=30
    )
    return r.json()["choices"][0]["message"]["content"]

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(silent=True)
    if not update:
        return jsonify({"ok": True})

    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return jsonify({"ok": True})

    text       = (msg.get("text") or "").strip()
    chat_id    = str(msg["chat"]["id"])
    first_name = msg["chat"].get("first_name", "there")
    uid        = str(update.get("update_id", ""))

    if not text:
        return jsonify({"ok": True})

    james_id = state["james_chat_id"]
    pending  = state["pending"]

    # Admin registration
    if text.lower() in ["/admin", "/james", "/start admin"]:
        state["james_chat_id"] = chat_id
        send_msg(chat_id,
            "\u2705 <b>Registered as admin, James!</b>\n\n"
            "Jarvis is live and monitoring all messages.\n"
            "You'll get notified here for anything sensitive. \U0001f514")
        return jsonify({"ok": True})

    # Welcome
    if text.lower() == "/start":
        send_msg(chat_id,
            f"Hey {first_name}! \U0001f44b I'm <b>Jarvis</b>, AI assistant for <b>AST Agency</b>.\n\n"
            "I can help with:\n"
            "\U0001f69b Starting & growing your trucking business\n"
            "\U0001f4e6 Cargo van, box truck & hot shot operations\n"
            "\U0001f4cb Freight dispatching tips\n"
            "\U0001f4da Training & coaching programs\n\n"
            "Just ask me anything!")
        return jsonify({"ok": True})

    # James approval commands
    if james_id and chat_id == james_id:
        t_up = text.strip().upper()

        if t_up == "APPROVE" and pending:
            pid = sorted(pending.keys())[0]
            p = pending.pop(pid)
            send_msg(p["cid"], p["draft"])
            send_msg(james_id, f"\u2705 Sent to {p['name']}!")

        elif t_up.startswith("APPROVE "):
            pid = text.strip()[8:].strip()
            if pid in pending:
                p = pending.pop(pid)
                send_msg(p["cid"], p["draft"])
                send_msg(james_id, f"\u2705 Sent to {p['name']}!")

        elif re.match(r'(?i)SEND\s+\S+:', text.strip()):
            m = re.match(r'(?i)SEND\s+(\S+):\s*(.*)', text.strip(), re.DOTALL)
            if m:
                pid, custom = m.group(1), m.group(2).strip()
                if pid in pending:
                    p = pending.pop(pid)
                    send_msg(p["cid"], custom)
                    send_msg(james_id, f"\u2705 Custom reply sent to {p['name']}!")

        elif t_up.startswith("SKIP "):
            pid = text.strip()[5:].strip()
            if pid in pending:
                p = pending.pop(pid)
                send_msg(p["cid"], "Thanks for reaching out! Our team will follow up soon. \U0001f64f")
                send_msg(james_id, f"\u23ed\ufe0f Skipped message from {p['name']}.")

        return jsonify({"ok": True})

    # Classify & respond
    cat = classify(text)

    if cat == "informational":
        try:
            reply = gpt_reply(text)
            send_msg(chat_id, reply)
        except Exception as e:
            logging.error(f"GPT error: {e}")
            send_msg(chat_id, "Hey! I'm Jarvis \U0001f916 - having a brief moment, please try again shortly!")
    else:
        send_msg(chat_id,
            f"Great question, {first_name}! \U0001f64c\n"
            "Let me check with our team and get you the best answer - hang tight! \u26a1")
        try:
            draft = gpt_reply(text)
        except Exception:
            draft = "[Draft unavailable - please reply manually]"

        pending[uid] = {"cid": chat_id, "name": first_name, "question": text, "draft": draft}

        if james_id:
            send_msg(james_id,
                f"\U0001f514 <b>Needs Your Approval</b>\n"
                f"\U0001f464 From: <b>{first_name}</b>\n\n"
                f"\u2753 <b>Question:</b>\n{text}\n\n"
                f"\U0001f4dd <b>Jarvis Draft:</b>\n{draft}\n\n"
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                f"Reply with:\n"
                f"\u2705 <code>APPROVE {uid}</code> - send draft\n"
                f"\u270f\ufe0f <code>SEND {uid}: your reply</code> - custom reply\n"
                f"\u23ed\ufe0f <code>SKIP {uid}</code> - dismiss")

    return jsonify({"ok": True})

@app.route("/", methods=["GET"])
def health():
    return "Jarvis is live! 🤖", 200

@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    url = request.args.get("url")
    if not url:
        return "Pass ?url=https://your-app.onrender.com", 400
    r = requests.get(f"{BASE_URL}/setWebhook", params={"url": f"{url}/webhook"})
    return r.json()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
