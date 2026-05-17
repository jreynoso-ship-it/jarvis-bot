import os
import re
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

# In-memory state
state = {"james_chat_id": None, "pending": {}, "pending_emails": {}}

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

def gpt_email_draft(to_email, context):
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_KEY}"},
        json={
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": (
                    "You write emails on behalf of James Reynoso, founder of AST Agency - "
                    "a trucking business coaching company.\n\n"
                    "Products:\n"
                    "- Carrier Development Playbook ($35) - step-by-step trucking startup guide\n"
                    "- AST Agency Skool Community - online community for trucking entrepreneurs\n"
                    "- Truck Business Blueprint - comprehensive business framework\n"
                    "- 1-on-1 Consulting with James\n"
                    "Website: https://astagency.base44.app\n"
                    "Blueprint: https://truckbusinessblueprint.base44.app\n\n"
                    "INSTRUCTIONS:\n"
                    "1. Use inferential reasoning - read the context deeply and add relevant insights, "
                    "tips, and recommendations the person would actually find valuable.\n"
                    "2. If they have a specific truck type (cargo van, box truck, hot shot) - "
                    "reference specific strategies for that equipment.\n"
                    "3. Naturally weave in the most relevant product based on their situation.\n"
                    "4. Keep it under 300 words. Warm, direct, not salesy.\n"
                    "5. FORMAT YOUR RESPONSE EXACTLY LIKE THIS:\n"
                    "Subject: [compelling subject line]\n"
                    "\n"
                    "[email body here]\n"
                    "\n"
                    "James Reynoso\n"
                    "AST Agency\n"
                    "https://astagency.base44.app"
                )},
                {"role": "user", "content": f"Write an email to {to_email}.\n\nContext/Instructions: {context}"}
            ],
            "max_tokens": 700
        }, timeout=30
    )
    return r.json()["choices"][0]["message"]["content"]

def send_email(to_email, subject, body):
    r = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={
            "Authorization": f"Bearer {SENDGRID_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": FROM_EMAIL, "name": FROM_NAME},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}]
        },
        timeout=15
    )
    return r.status_code == 202, r.status_code

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

    james_id       = state["james_chat_id"]
    pending        = state["pending"]
    pending_emails = state["pending_emails"]

    # ── Admin registration ────────────────────────────────────────────────────
    if text.lower() in ["/admin", "/james", "/start admin"]:
        state["james_chat_id"] = chat_id
        send_msg(chat_id,
            "\u2705 <b>Registered as admin, James!</b>\n\n"
            "Jarvis is live and monitoring all messages.\n"
            "You will get notified here for anything sensitive. \U0001f514\n\n"
            "<b>Email command:</b>\n"
            "<code>email someone@email.com [context about them]</code>")
        return jsonify({"ok": True})

    # ── Welcome ───────────────────────────────────────────────────────────────
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

    # ── James commands ────────────────────────────────────────────────────────
    if james_id and chat_id == james_id:
        t_up = text.strip().upper()

        # Email draft command — "email someone@domain.com [context]"
        email_match = EMAIL_CMD.match(text.strip())
        if email_match:
            to_email = email_match.group(1).strip()
            context  = email_match.group(2).strip() or "General outreach about AST Agency services"

            send_msg(james_id, f"\u23f3 Writing email to <b>{to_email}</b>...\nUsing GPT-4o to craft the perfect message.")

            try:
                raw_draft = gpt_email_draft(to_email, context)

                # Parse subject and body from GPT response
                lines = raw_draft.strip().split("\n")
                subject = "Growing Your Trucking Business with AST Agency"
                body_start = 0
                for i, line in enumerate(lines):
                    if line.lower().startswith("subject:"):
                        subject = line[8:].strip()
                        body_start = i + 1
                        break

                # Skip blank line after subject
                while body_start < len(lines) and lines[body_start].strip() == "":
                    body_start += 1

                body = "\n".join(lines[body_start:]).strip()

                # Store pending email
                pending_emails[uid] = {
                    "to":      to_email,
                    "subject": subject,
                    "body":    body,
                    "context": context
                }

                # Send draft to James for approval
                preview = body[:600] + ("..." if len(body) > 600 else "")
                send_msg(james_id,
                    f"\U0001f4e7 <b>Email Draft Ready</b>\n"
                    f"\U0001f4ec <b>To:</b> {to_email}\n"
                    f"\U0001f4cc <b>Subject:</b> {subject}\n\n"
                    f"{preview}\n\n"
                    f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                    f"\u2705 <code>SENDMAIL {uid}</code> \u2014 approve & send\n"
                    f"\u270f\ufe0f <code>EDITMAIL {uid}: [new instructions]</code> \u2014 revise\n"
                    f"\u274c <code>CANCELMAIL {uid}</code> \u2014 cancel")

            except Exception as e:
                logging.error(f"Email draft error: {e}")
                send_msg(james_id, f"\u274c Error generating draft: {e}")

            return jsonify({"ok": True})

        # SENDMAIL command
        if t_up.startswith("SENDMAIL "):
            eid = text.strip()[9:].strip()
            if eid in pending_emails:
                e = pending_emails.pop(eid)
                ok, code = send_email(e["to"], e["subject"], e["body"])
                if ok:
                    send_msg(james_id, f"\u2705 <b>Email sent!</b>\n\U0001f4ec To: {e['to']}\n\U0001f4cc Subject: {e['subject']}")
                else:
                    send_msg(james_id, f"\u274c Send failed (code {code}). Check SendGrid sender verification.")
            else:
                send_msg(james_id, "\u26a0\ufe0f Email draft not found. It may have expired.")
            return jsonify({"ok": True})

        # EDITMAIL command — revise the draft with new instructions
        edit_match = re.match(r'(?i)EDITMAIL\s+(\S+):\s*(.*)', text.strip(), re.DOTALL)
        if edit_match:
            eid, new_instructions = edit_match.group(1), edit_match.group(2).strip()
            if eid in pending_emails:
                e = pending_emails[eid]
                send_msg(james_id, f"\u23f3 Revising draft for <b>{e['to']}</b>...")
                try:
                    revised_context = f"{e['context']}. REVISION: {new_instructions}"
                    raw_draft = gpt_email_draft(e["to"], revised_context)

                    lines = raw_draft.strip().split("\n")
                    subject = e["subject"]
                    body_start = 0
                    for i, line in enumerate(lines):
                        if line.lower().startswith("subject:"):
                            subject = line[8:].strip()
                            body_start = i + 1
                            break
                    while body_start < len(lines) and lines[body_start].strip() == "":
                        body_start += 1
                    body = "\n".join(lines[body_start:]).strip()

                    pending_emails[eid]["subject"] = subject
                    pending_emails[eid]["body"] = body

                    preview = body[:600] + ("..." if len(body) > 600 else "")
                    send_msg(james_id,
                        f"\u270f\ufe0f <b>Revised Draft</b>\n"
                        f"\U0001f4ec <b>To:</b> {e['to']}\n"
                        f"\U0001f4cc <b>Subject:</b> {subject}\n\n"
                        f"{preview}\n\n"
                        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                        f"\u2705 <code>SENDMAIL {eid}</code> \u2014 approve & send\n"
                        f"\u270f\ufe0f <code>EDITMAIL {eid}: [more instructions]</code> \u2014 revise again\n"
                        f"\u274c <code>CANCELMAIL {eid}</code> \u2014 cancel")
                except Exception as ex:
                    send_msg(james_id, f"\u274c Revision failed: {ex}")
            else:
                send_msg(james_id, "\u26a0\ufe0f Email draft not found.")
            return jsonify({"ok": True})

        # CANCELMAIL command
        if t_up.startswith("CANCELMAIL "):
            eid = text.strip()[11:].strip()
            if eid in pending_emails:
                e = pending_emails.pop(eid)
                send_msg(james_id, f"\u274c Email to {e['to']} cancelled.")
            return jsonify({"ok": True})

        # Message approval commands
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

    # ── Public user messages ──────────────────────────────────────────────────
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
