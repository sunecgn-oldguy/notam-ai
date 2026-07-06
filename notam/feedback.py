"""Collect pilot feedback: append to a local file (backup) and email it.

The file is a BACKUP only — on Render's free tier the disk is ephemeral (wiped
on redeploy), and the server can't write back to the git repo, so EMAIL is the
durable channel. Credentials live in environment variables on the server, NEVER
in code:

  FEEDBACK_SMTP_USER   Gmail address to send from
  FEEDBACK_SMTP_PASS   Gmail App Password (16 chars, NOT your normal password)
  FEEDBACK_TO          where feedback is delivered (defaults to the sender)

If the SMTP vars are unset, email is skipped and only the file is written — so
the endpoint works before any credentials exist. Swapping Gmail for another
provider (e.g. Resend) means changing only _send_email().
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "feedback.jsonl")


def submit(message: str, email: str, context: dict) -> dict:
    """Store + email one feedback entry. Returns what actually happened."""
    message = (message or "").strip()
    if not message:
        return {"ok": False, "error": "empty message"}
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "email": (email or "").strip(),
        "message": message,
        "context": context or {},
    }
    saved = _save(entry)
    emailed = _send_email(entry)
    return {"ok": saved or emailed, "saved": saved, "emailed": emailed}


def _save(entry: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(_FILE), exist_ok=True)
        with open(_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def _send_email(entry: dict) -> bool:
    user = os.environ.get("FEEDBACK_SMTP_USER")
    pw = os.environ.get("FEEDBACK_SMTP_PASS")
    to = os.environ.get("FEEDBACK_TO") or user
    if not (user and pw and to):
        return False                          # not configured yet — file backup still ran
    try:
        who = entry["email"] or "anonymous pilot"
        msg = MIMEMultipart()
        msg["Subject"] = f"NOTAM & WX feedback — {who}"
        msg["From"] = user
        msg["To"] = to
        if entry["email"]:
            msg["Reply-To"] = entry["email"]
        body = (f"From:  {who}\n"
                f"When:  {entry['ts']}\n\n"
                f"{entry['message']}\n\n"
                f"— the pilot's screen at that moment is attached as feedback.json —\n")
        msg.attach(MIMEText(body, "plain", "utf-8"))
        ctx = json.dumps(entry["context"], ensure_ascii=False, indent=2)
        att = MIMEApplication(ctx.encode("utf-8"), _subtype="json")
        att.add_header("Content-Disposition", "attachment", filename="feedback.json")
        msg.attach(att)
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(user, pw)
            s.sendmail(user, [to], msg.as_string())
        return True
    except Exception:
        return False                          # never let a mail failure break the request
