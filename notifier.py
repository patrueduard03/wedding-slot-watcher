#!/usr/bin/env python3
"""
notifier.py — sends alerts via CallMeBot (WhatsApp) and/or Telegram.

Config comes from (env vars win over the file):
  - config.local.json  (for the LOCAL watcher; gitignored, never committed)
  - env vars CALLMEBOT_RECIPIENTS / TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_IDS
    (for the CLOUD watcher; set as GitHub Secrets)

audience:
  "all"     -> every recipient (use for the real slot-open alert)
  "primary" -> only the FIRST recipient/chat (use for heartbeats & error notices,
               so the other people aren't pinged with operational noise)
"""
import os, json, subprocess, urllib.parse

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
    if os.environ.get("CALLMEBOT_RECIPIENTS"):
        cfg["callmebot_recipients"] = os.environ["CALLMEBOT_RECIPIENTS"]
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        cfg["telegram_bot_token"] = os.environ["TELEGRAM_BOT_TOKEN"]
    if os.environ.get("TELEGRAM_CHAT_IDS"):
        cfg["telegram_chat_ids"] = os.environ["TELEGRAM_CHAT_IDS"]
    return cfg


def _recipients(cfg):
    raw = cfg.get("callmebot_recipients", "")
    out = []
    for pair in str(raw).split(","):
        pair = pair.strip()
        if not pair:
            continue
        phone, _, key = pair.partition(":")
        if phone.strip() and key.strip():
            out.append((phone.strip(), key.strip()))
    return out


def _tg_ids(cfg):
    ids = cfg.get("telegram_chat_ids", "")
    if isinstance(ids, list):
        return [str(i).strip() for i in ids if str(i).strip()]
    return [i.strip() for i in str(ids).split(",") if i.strip()]


def send(text, cfg, audience="all"):
    """Send `text` to configured channels. Returns list of per-target result strings."""
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
    ids = _tg_ids(cfg)
    if audience == "primary":
        ids = ids[:1]
    if tok and ids:
        for cid in ids:
            url = ("https://api.telegram.org/bot%s/sendMessage?chat_id=%s&text=%s"
                   % (tok, urllib.parse.quote(cid), urllib.parse.quote(text)))
            out = _curl_get(url)
            ok = '"ok":true' in out
            results.append(f"telegram:{cid}:{'OK' if ok else out[:70]}")

    if not results:
        results.append("DRY(no channel configured): " + text)
    return results


def has_channel(cfg):
    return bool(_recipients(cfg)) or bool(cfg.get("telegram_bot_token") and _tg_ids(cfg))
