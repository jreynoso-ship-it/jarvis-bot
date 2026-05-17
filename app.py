import os
import re
import json
import logging
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Config
BOT_TOKEN    = os.environ["BOT_TOKEN"]
OPENAI_KEY   = os.environ["OPENAI_KEY"]
SENDGRID_KEY = os.environ["SENDGRID_KEY"]
FROM_EMAIL   = os.environ.get("FROM_EMAIL", "jreynoso@a-solution.org")
FROM_NAME    = os.environ.get("FROM_NAME",  "James Reynoso | AST Agency")
BASE_URL     = f"https://api.telegram.org/bot{BOT_TOKEN}"
STATE_FILE   = "/tmp/jarvis_state.json"

# ── Persistent state (survives between requests, reloads after restarts) ──────
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"james_chat_id": None, "pending": {}, "pending_emails": {}}

def save_state(s):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(s, f)
    except Exception as e:
        logging.error(f"State save error: {e}")

state = load_state()

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

EMAIL_CMD = re.compile(
    r'(?:send\s+)?email\s+(?:to\s+)?([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\s*(.*)',
    re.IGNORECASE | re.DOTALL
)

# ── Helpers ───────────────────────────────────────────────────────────────────
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
                    "company run by James Reynoso. Products: Carrier Development Playbook ($35), "
                    "AST Agency Skool Community, Truck Business Blueprint, 1-on-1 consulting. "
                    "Website: https://astagency.base44.app\n"
                    "Be warm, motivating, and direct. Under 200 words. Use emojis sparingly."
                )},
                {"role": "user", "content": question}
            ],
            "max_tokens": 400
        }, timeout=30
    )
    return r.json()["choices"][0]["message"]["content"]

def gpt_email_draft(to_email, context):
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_KEY}"},
        json={
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": (
                    "You write emails on behalf of James Reynoso, founder of AST Agency.\n\n"
                    "Products:\n"
                    "- Carrier Development Playbook ($35) - step-by-step trucking startup guide\n"
                    "- AST Agency Skool Community - online community for trucking entrepreneurs\n"
                    "- Truck Business Blueprint - comprehensive business framework\n"
                    "- 1-on-1 Consulting with James\n"
                    "Website: https://astagency.base44.app\n"
                    "Blueprint: https://truckbusinessblueprint.base44.app\n\n"
                    "INSTRUCTIONS:\n"
                    "1. Use deep inferential reasoning - read the context and add insights they would value.\n"
                    "2. Reference specific strategies for their truck type (cargo van, box truck, hot shot) if mentioned.\n"
                    "3. Naturally weave in the most relevant product for their situation.\n"
                    "4. Warm, direct, not salesy. Under 300 words.\n"
                    "5. FORMAT EXACTLY:\n"
                    "Subject: [subject line]\n"
                    "\n"
                    "[email body]\n"
                    "\n"
                    "James Reynoso\n"
                    "AST Agency | https://astagency.base44.app"
                )},
                {"role": "user", "content": f"Write an email to {to_email}.\nContext: {context}"}
            ],
            "max_tokens": 700
        }, timeout=30
    )
    return r.json()["choices"][0]["message"]["content"]

def send_email(to_email, subject, body):
    r = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {SENDGRID_KEY}", "Content-Type": "application/json"},
        json={
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": FROM_EMAIL, "name": FROM_NAME},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}]
        },
        timeout=15
    )
    logging.info(f"SendGrid response: {r.status_code} | {r.text[:200]}")
    return r.status_code == 202, r.status_code, r.text

# ── Webhook ───────────────────────────────────────────────────────────────────
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

    # Always reload fresh state
    state = load_state()
    james_id       = state.get("james_chat_id")
    pending        = state.get("pending", {})
    pending_emails = state.get("pending_emails", {})

    def persist():
        save_state({"james_chat_id": james_id, "pending": pending, "pending_emails": pending_emails})

    # Admin registration
    if text.lower() in ["/admin", "/james", "/start admin"]:
        state["james_chat_id"] = chat_id
        save_state({**state, "james_chat_id": chat_id})
        send_msg(chat_id,
            "\u2705 <b>Registered as admin, James!</b>\n\n"
            "Jarvis is monitoring all messages. \U0001f514\n\n"
            "<b>Email command:</b>\n"
            "<code>email someone@email.com [context about them]</code>\n\n"
            "<b>After I send a draft:</b>\n"
            "<code>SENDMAIL someone@email.com</code> - send it\n"
            "<code>EDITMAIL someone@email.com: [notes]</code> - revise\n"
            "<code>CANCELMAIL someone@email.com</code> - cancel")
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

    # James commands
    if james_id and chat_id == james_id:
        t_up = text.strip().upper()

        # ── Email draft command ───────────────────────────────────────────────
        email_match = EMAIL_CMD.match(text.strip())
        if email_match:
            to_email = email_match.group(1).strip().lower()
            context  = email_match.group(2).strip() or "General outreach about AST Agency services"

            send_msg(james_id, f"\u23f3 Writing email to <b>{to_email}</b>...\nUsing GPT-4o + inferential reasoning.")

            try:
                raw = gpt_email_draft(to_email, context)
                lines  = raw.strip().split("\n")
                subject   = "Growing Your Trucking Business with AST Agency"
                body_start = 0
                for i, line in enumerate(lines):
                    if line.lower().startswith("subject:"):
                        subject   = line[8:].strip()
                        body_start = i + 1
                        break
                while body_start < len(lines) and not lines[body_start].strip():
                    body_start += 1
                body = "\n".join(lines[body_start:]).strip()

                # Use email address as key for easy lookup
                pending_emails[to_email] = {
                    "to": to_email, "subject": subject,
                    "body": body, "context": context
                }
                persist()

                preview = body[:700] + ("..." if len(body) > 700 else "")
                send_msg(james_id,
                    f"\U0001f4e7 <b>Email Draft Ready</b>\n"
                    f"\U0001f4ec To: <b>{to_email}</b>\n"
                    f"\U0001f4cc Subject: <b>{subject}</b>\n\n"
                    f"{preview}\n\n"
                    f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                    f"\u2705 <code>SENDMAIL {to_email}</code>\n"
                    f"\u270f\ufe0f <code>EDITMAIL {to_email}: [notes]</code>\n"
                    f"\u274c <code>CANCELMAIL {to_email}</code>")

            except Exception as e:
                logging.error(f"Draft error: {e}")
                send_msg(james_id, f"\u274c Error generating draft: {e}")
            return jsonify({"ok": True})

        # ── SENDMAIL ──────────────────────────────────────────────────────────
        if t_up.startswith("SENDMAIL "):
            to_email = text.strip()[9:].strip().lower()
            if to_email in pending_emails:
                e = pending_emails.pop(to_email)
                persist()
                ok, code, body_resp = send_email(e["to"], e["subject"], e["body"])
                if ok:
                    send_msg(james_id,
                        f"\u2705 <b>Email sent!</b>\n"
                        f"\U0001f4ec To: {e['to']}\n"
                        f"\U0001f4cc Subject: {e['subject']}")
                else:
                    send_msg(james_id,
                        f"\u274c <b>Send failed (code {code})</b>\n\n"
                        f"Most likely fix: verify <b>{FROM_EMAIL}</b> as a sender in SendGrid.\n"
                        f"Go to: SendGrid \u2192 Settings \u2192 Sender Authentication\n\n"
                        f"Error: {body_resp[:200]}")
            else:
                # List what's pending
                if pending_emails:
                    keys = "\n".join([f"\u2022 <code>SENDMAIL {k}</code>" for k in pending_emails])
                    send_msg(james_id, f"\u26a0\ufe0f No draft for <b>{to_email}</b>.\n\nPending drafts:\n{keys}")
                else:
                    send_msg(james_id,
                        f"\u26a0\ufe0f No draft found for <b>{to_email}</b>.\n"
                        "The server may have restarted and cleared it.\n"
                        "Just re-send the email command to generate a new draft!")
            return jsonify({"ok": True})

        # ── EDITMAIL ──────────────────────────────────────────────────────────
        edit_match = re.match(r'(?i)EDITMAIL\s+(\S+@\S+):\s*(.*)', text.strip(), re.DOTALL)
        if edit_match:
            to_email, notes = edit_match.group(1).lower(), edit_match.group(2).strip()
            if to_email in pending_emails:
                e = pending_emails[to_email]
                send_msg(james_id, f"\u23f3 Revising draft for <b>{to_email}</b>...")
                try:
                    revised_context = f"{e['context']}. Additional instructions: {notes}"
                    raw = gpt_email_draft(to_email, revised_context)
                    lines = raw.strip().split("\n")
                    subject = e["subject"]
                    body_start = 0
                    for i, line in enumerate(lines):
                        if line.lower().startswith("subject:"):
                            subject = line[8:].strip()
                            body_start = i + 1
                            break
                    while body_start < len(lines) and not lines[body_start].strip():
                        body_start += 1
                    body = "\n".join(lines[body_start:]).strip()
                    pending_emails[to_email].update({"subject": subject, "body": body})
                    persist()
                    preview = body[:700] + ("..." if len(body) > 700 else "")
                    send_msg(james_id,
                        f"\u270f\ufe0f <b>Revised Draft</b>\n"
                        f"\U0001f4ec To: <b>{to_email}</b>\n"
                        f"\U0001f4cc Subject: <b>{subject}</b>\n\n"
                        f"{preview}\n\n"
                        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                        f"\u2705 <code>SENDMAIL {to_email}</code>\n"
                        f"\u270f\ufe0f <code>EDITMAIL {to_email}: [more notes]</code>")
                except Exception as ex:
                    send_msg(james_id, f"\u274c Revision failed: {ex}")
            else:
                send_msg(james_id, f"\u26a0\ufe0f No draft found for {to_email}. Re-send the email command.")
            return jsonify({"ok": True})

        # ── CANCELMAIL ────────────────────────────────────────────────────────
        if t_up.startswith("CANCELMAIL "):
            to_email = text.strip()[11:].strip().lower()
            if to_email in pending_emails:
                pending_emails.pop(to_email)
                persist()
                send_msg(james_id, f"\u274c Email to {to_email} cancelled.")
            return jsonify({"ok": True})

        # ── Message approvals ─────────────────────────────────────────────────
        if t_up == "APPROVE" and pending:
            pid = sorted(pending.keys())[0]
            p = pending.pop(pid)
            persist()
            send_msg(p["cid"], p["draft"])
            send_msg(james_id, f"\u2705 Sent to {p['name']}!")

        elif t_up.startswith("APPROVE "):
            pid = text.strip()[8:].strip()
            if pid in pending:
                p = pending.pop(pid)
                persist()
                send_msg(p["cid"], p["draft"])
                send_msg(james_id, f"\u2705 Sent to {p['name']}!")

        elif re.match(r'(?i)SEND\s+\S+:', text.strip()):
            m = re.match(r'(?i)SEND\s+(\S+):\s*(.*)', text.strip(), re.DOTALL)
            if m:
                pid, custom = m.group(1), m.group(2).strip()
                if pid in pending:
                    p = pending.pop(pid)
                    persist()
                    send_msg(p["cid"], custom)
                    send_msg(james_id, f"\u2705 Reply sent to {p['name']}!")

        elif t_up.startswith("SKIP "):
            pid = text.strip()[5:].strip()
            if pid in pending:
                p = pending.pop(pid)
                persist()
                send_msg(p["cid"], "Thanks for reaching out! Our team will follow up soon. \U0001f64f")
                send_msg(james_id, f"\u23ed\ufe0f Skipped {p['name']}.")

        return jsonify({"ok": True})

    # ── Public user messages ──────────────────────────────────────────────────
    cat = classify(text)
    if cat == "informational":
        try:
            send_msg(chat_id, gpt_reply(text))
        except Exception as e:
            logging.error(f"GPT error: {e}")
            send_msg(chat_id, "Hey! I'm Jarvis \U0001f916 - one moment, please try again!")
    else:
        send_msg(chat_id,
            f"Great question, {first_name}! \U0001f64c\n"
            "Checking with our team - hang tight! \u26a1")
        try:
            draft = gpt_reply(text)
        except Exception:
            draft = "[Draft unavailable - please reply manually]"
        pending[uid] = {"cid": chat_id, "name": first_name, "question": text, "draft": draft}
        save_state({"james_chat_id": james_id, "pending": pending, "pending_emails": pending_emails})
        if james_id:
            send_msg(james_id,
                f"\U0001f514 <b>Approval Needed</b>\n"
                f"\U0001f464 From: <b>{first_name}</b>\n\n"
                f"\u2753 <b>Question:</b>\n{text}\n\n"
                f"\U0001f4dd <b>Draft:</b>\n{draft}\n\n"
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                f"\u2705 <code>APPROVE {uid}</code>\n"
                f"\u270f\ufe0f <code>SEND {uid}: custom reply</code>\n"
                f"\u23ed\ufe0f <code>SKIP {uid}</code>")

    return jsonify({"ok": True})

@app.route("/", methods=["GET"])
def health():
    return "Jarvis is live! \U0001f916", 200

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
