#!/usr/bin/env python3
"""
check_once.py  —  ONE availability check, for cloud cron (GitHub Actions).

Fetches the Orar (schedule) for WATCH_DATE, and if any slot at WATCH_FROM or
later is free (green) that WASN'T free on the previous run, it sends a WhatsApp
(CallMeBot) and/or Telegram alert to your people. State is kept in state.json so
nobody gets spammed while a slot stays open.

READ-ONLY: it never books anything and never touches CNP / personal data.

Config via environment variables (set as GitHub repo Secrets/Variables):
  WATCH_DATE            e.g. 04-09-2026        (default 04-09-2026)
  WATCH_FROM            e.g. 12:30             (default 12:30)  -> alert on this time or later
  CALLMEBOT_RECIPIENTS  "phone:apikey,phone:apikey,phone:apikey"
  TELEGRAM_BOT_TOKEN    bot token from @BotFather (optional)
  TELEGRAM_CHAT_IDS     "id1,id2,id3"          (optional)
If no channel is configured, it runs in DRY mode and just prints the message.
"""
import os, re, sys, json, html, subprocess, tempfile, datetime, urllib.parse

BASE = "https://se.primariavl.ro/starecivila/"
UA   = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120 Safari/537.36")

DATE       = os.environ.get("WATCH_DATE", "04-09-2026")
WATCH_FROM = os.environ.get("WATCH_FROM", "12:30")
STATE_FILE = os.environ.get("STATE_FILE", "state.json")
JAR        = tempfile.NamedTemporaryFile(delete=False, suffix=".cookies").name

def to_min(hhmm):
    h, m = hhmm.split(":"); return int(h) * 60 + int(m)
WATCH_MIN = to_min(WATCH_FROM)


def curl(extra):
    try:
        r = subprocess.run(["curl", "-s", "--compressed", "--max-time", "30",
                            "-A", UA, "-c", JAR, "-b", JAR] + extra,
                           capture_output=True, text=True, timeout=45)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def fetch_schedule(date):
    page = curl([BASE])
    if not page:
        return None
    def grab(name):
        m = re.search(r'name="%s"[^>]*value="([^"]*)"' % re.escape(name), page)
        return html.unescape(m.group(1)) if m else ""
    vs = grab("__VIEWSTATE")
    if not vs:
        return None
    fields = [
        ("__EVENTTARGET", ""), ("__EVENTARGUMENT", ""), ("__LASTFOCUS", ""),
        ("__VIEWSTATE", vs),
        ("__VIEWSTATEGENERATOR", grab("__VIEWSTATEGENERATOR")),
        ("ctl00$ContentHolder$hfZileDisponibile", grab("ctl00$ContentHolder$hfZileDisponibile")),
        ("ctl00$ContentHolder$hfZileLibere", grab("ctl00$ContentHolder$hfZileLibere")),
        ("ctl00$ContentHolder$hfDefaultDate", grab("ctl00$ContentHolder$hfDefaultDate")),
        ("ctl00$ContentHolder$DisabledDates", grab("ctl00$ContentHolder$DisabledDates")),
        ("ctl00$ContentHolder$SelectedDate", date),
        ("ctl00$ContentHolder$Hour", ""),
        ("ctl00$ContentHolder$DisplayScheduleButton", "Button"),
    ]
    args = ["-e", BASE]
    for k, v in fields:
        args += ["--data-urlencode", f"{k}={v}"]
    args += [BASE]
    return curl(args) or None


def parse_slots(resp):
    slots = []
    for m in re.finditer(r'<td([^>]*)>\s*(\d{1,2}:\d{2})\s*</td>', resp):
        attrs, t = m.group(1).lower(), m.group(2)
        if "disabled" in attrs or "d9d9d9" in attrs:
            s = "blocked"
        elif "24ac21" in attrs or "background-color:green" in attrs:
            s = "available"
        elif "background-color:red" in attrs or "background-color:#ff" in attrs:
            s = "taken"
        else:
            s = "unknown"
        slots.append((t, s))
    return slots


# ------------------------------ notifications -------------------------------
def send_callmebot(phone, apikey, text):
    url = ("https://api.callmebot.com/whatsapp.php?phone=%s&apikey=%s&text=%s"
           % (urllib.parse.quote(phone), urllib.parse.quote(apikey),
              urllib.parse.quote(text)))
    out = curl([url])
    print(f"  callmebot {phone}: {out[:120].strip()}")

def send_telegram(token, chat_id, text):
    url = ("https://api.telegram.org/bot%s/sendMessage?chat_id=%s&text=%s"
           % (token, urllib.parse.quote(chat_id), urllib.parse.quote(text)))
    out = curl([url])
    ok = '"ok":true' in out
    print(f"  telegram {chat_id}: {'OK' if ok else out[:120].strip()}")

def notify(text):
    sent = 0
    recips = os.environ.get("CALLMEBOT_RECIPIENTS", "").strip()
    if recips:
        for pair in recips.split(","):
            pair = pair.strip()
            if not pair:
                continue
            phone, _, key = pair.partition(":")
            send_callmebot(phone.strip(), key.strip(), text); sent += 1
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    ids = os.environ.get("TELEGRAM_CHAT_IDS", "").strip()
    if tok and ids:
        for cid in ids.split(","):
            if cid.strip():
                send_telegram(tok, cid.strip(), text); sent += 1
    if sent == 0:
        print("  [DRY MODE — no channel configured] Would have sent:")
        print("  " + text)
    return sent


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"announced": []}

def save_state(state):
    state["last_check"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def main():
    resp = fetch_schedule(DATE)
    if not resp:
        print("check failed (network / page). State unchanged."); return
    slots = parse_slots(resp)
    if not slots:
        print(f"No slots parsed for {DATE} (date closed or page changed). State unchanged.")
        return

    summary = " ".join(f"{t}[{s[:4]}]" for t, s in slots)
    matches = sorted({t for t, s in slots if s == "available" and to_min(t) >= WATCH_MIN},
                     key=to_min)
    print(f"{DATE}: {summary}")
    print(f"Wanted (>= {WATCH_FROM}) available: {matches or 'none'}")

    state = load_state()
    announced = set(state.get("announced", []))
    new = [t for t in matches if t not in announced]

    if new:
        text = (f"🔔 Loc liber pentru cununie pe {DATE} la ora: {', '.join(matches)}. "
                f"Rezerva ACUM (se ocupa rapid): {BASE}")
        print(f"NEW slot(s) open: {new} -> alerting")
        notify(text)
        state["announced"] = sorted(set(matches) | announced, key=to_min)
    elif not matches:
        state["announced"] = []   # all wanted slots gone -> reset so it can alert again
    else:
        print("Wanted slots already announced earlier — not re-sending.")
        state["announced"] = sorted(set(matches), key=to_min)

    save_state(state)


if __name__ == "__main__":
    try:
        main()
    finally:
        try: os.unlink(JAR)
        except Exception: pass
