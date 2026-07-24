#!/usr/bin/env python3
"""
notifier.py — sends alerts via CallMeBot (WhatsApp), Telegram, and/or Email(SMTP).

Config comes from (env vars win over the file):
  - config.local.json  (for the LOCAL watcher; gitignored, never committed)
  - env vars (for the CLOUD watcher; set as GitHub Secrets):
      CALLMEBOT_RECIPIENTS  "phone:key,phone:key,..."
      TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_IDS
      SMTP_HOST (default smtp.gmail.com) / SMTP_PORT (default 587)
      SMTP_USER / SMTP_PASS (Gmail App Password) / SMTP_FROM (default = SMTP_USER)
      EMAIL_TO   "a@x.com,b@y.com"

audience:
  "all"     -> every recipient (use for the real slot-open alert)
  "primary" -> only the FIRST recipient/chat/email (heartbeats & error notices)

send(text, cfg, audience, subject, importance):
  WhatsApp/Telegram use `text`; Email uses `subject` + `text` as the body.
  importance "high" adds urgent/high-priority mail headers.
"""
import os, json, subprocess, urllib.parse, smtplib, ssl
from email.message import EmailMessage

_HERE = os.path.dirname(os.path.abspath(__file__))


def _curl_get(url):
    try:
        r = subprocess.run(["curl", "-s", "--max-time", "20", url],
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip()
    except Exception as e:
        return f"__ERR__ {e}"


def load_config():
    cfg = {}
    path = os.path.join(_HERE, "config.local.json")
    if os.path.exists(path):
        try:
            cfg = json.load(open(path))
        except Exception:
            cfg = {}
    env_map = {
        "CALLMEBOT_RECIPIENTS": "callmebot_recipients",
        "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
        "TELEGRAM_CHAT_IDS": "telegram_chat_ids",
        "SMTP_HOST": "smtp_host", "SMTP_PORT": "smtp_port",
        "SMTP_USER": "smtp_user", "SMTP_PASS": "smtp_pass",
        "SMTP_FROM": "smtp_from", "EMAIL_TO": "email_to",
    }
    for env, key in env_map.items():
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    return cfg


def _recipients(cfg):
    out = []
    for pair in str(cfg.get("callmebot_recipients", "")).split(","):
        pair = pair.strip()
        if not pair:
            continue
        phone, _, key = pair.partition(":")
        if phone.strip() and key.strip():
            out.append((phone.strip(), key.strip()))
    return out


def _split(val):
    if isinstance(val, list):
        return [str(i).strip() for i in val if str(i).strip()]
    return [i.strip() for i in str(val).split(",") if i.strip()]


# ------------------------------- email --------------------------------------
def _send_email(subject, body, cfg, audience, importance):
    user = cfg.get("smtp_user", "").strip()
    pw   = str(cfg.get("smtp_pass", "")).strip()
    to   = _split(cfg.get("email_to", ""))
    if not (user and pw and to):
        return []                      # email not configured -> skip
    # Guard: the setup link is not a password
    if pw.startswith("http"):
        return ["email:SKIP (SMTP_PASS looks like a URL, not an App Password)"]
    if audience == "primary":
        to = to[:1]
    host = cfg.get("smtp_host", "smtp.gmail.com").strip() or "smtp.gmail.com"
    try:
        port = int(str(cfg.get("smtp_port", "587")).strip() or "587")
    except ValueError:
        port = 587
    sender = cfg.get("smtp_from", "").strip() or user

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    if importance == "high":
        msg["X-Priority"] = "1"
        msg["X-MSMail-Priority"] = "High"
        msg["Importance"] = "High"
        msg["Priority"] = "urgent"
    msg.set_content(body)

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=25,
                                  context=ssl.create_default_context()) as s:
                s.login(user, pw)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=25) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(user, pw)
                s.send_message(msg)
        return [f"email:{','.join(to)}:OK"]
    except Exception as e:
        return [f"email:ERROR:{str(e)[:90]}"]


# ------------------------------- main send ----------------------------------
def send(text, cfg, audience="all", subject=None, importance="normal"):
    """Send to every configured channel. Returns list of per-target result strings."""
    results = []

    recs = _recipients(cfg)
    if audience == "primary":
        recs = recs[:1]
    for phone, key in recs:
        url = ("https://api.callmebot.com/whatsapp.php?phone=%s&apikey=%s&text=%s"
               % (urllib.parse.quote(phone), urllib.parse.quote(key),
                  urllib.parse.quote(text)))
        out = _curl_get(url).lower()
        ok = any(w in out for w in ("queued", "message sent", "message to", "will receive"))
        results.append(f"whatsapp:{phone}:{'OK' if ok else out[:70]}")

    tok = cfg.get("telegram_bot_token")
    ids = _split(cfg.get("telegram_chat_ids", ""))
    if audience == "primary":
        ids = ids[:1]
    if tok and ids:
        for cid in ids:
            url = ("https://api.telegram.org/bot%s/sendMessage?chat_id=%s&text=%s"
                   % (tok, urllib.parse.quote(cid), urllib.parse.quote(text)))
            out = _curl_get(url)
            ok = '"ok":true' in out
            results.append(f"telegram:{cid}:{'OK' if ok else out[:70]}")

    results += _send_email(subject or text.split("\n", 1)[0], text, cfg, audience, importance)

    if not results:
        results.append("DRY(no channel configured): " + (subject or text))
    return results


def has_channel(cfg):
    return (bool(_recipients(cfg))
            or bool(cfg.get("telegram_bot_token") and _split(cfg.get("telegram_chat_ids", "")))
            or bool(cfg.get("smtp_user") and cfg.get("smtp_pass") and _split(cfg.get("email_to", ""))))
