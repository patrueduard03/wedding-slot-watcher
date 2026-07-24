#!/usr/bin/env python3
"""
watch_wedding_slots.py
----------------------
Safely watches the Râmnicu Vâlcea civil-marriage booking page and alerts you
the moment a time slot you want becomes available (turns green).

It ONLY reads the page. It never books anything and never sends your personal
data anywhere. When a wanted slot opens, it makes noise + a desktop notification
and opens the booking page so YOU can reserve it by hand.

Site:  https://se.primariavl.ro/starecivila/
Usage: python3 watch_wedding_slots.py
Stop:  press Ctrl-C
"""

import re, sys, time, html, random, subprocess, tempfile, os, datetime

# ----------------------------- CONFIG ---------------------------------------
DATE          = "04-09-2026"   # the day you want (dd-mm-yyyy)
WATCH_FROM    = "12:30"        # alert when THIS time or any LATER time is free
INTERVAL_SEC  = 60             # seconds between checks (>=30 to stay polite)
JITTER_SEC    = 10             # random +/- added to the interval (gentler)
OPEN_BROWSER  = True           # open the booking page once when a slot appears
REPEAT_SOUND  = True           # keep beeping every cycle while a slot is free
# ----------------------------------------------------------------------------

BASE = "https://se.primariavl.ro/starecivila/"
UA   = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120 Safari/537.36")
JAR  = tempfile.NamedTemporaryFile(delete=False, suffix=".cookies").name

def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)

WATCH_MIN = to_min(WATCH_FROM)


def curl(extra):
    """Run curl with the shared cookie jar. Returns (ok, text)."""
    try:
        r = subprocess.run(
            ["curl", "-s", "--compressed", "--max-time", "30",
             "-A", UA, "-c", JAR, "-b", JAR] + extra,
            capture_output=True, text=True, timeout=45)
        return (r.returncode == 0 and bool(r.stdout), r.stdout)
    except Exception as e:
        return (False, f"__ERR__ {e}")


def fetch_schedule(date):
    """GET fresh viewstate, then POST the date. Returns response HTML or None."""
    ok, page = curl([BASE])
    if not ok:
        return None

    def grab(name):
        m = re.search(r'name="%s"[^>]*value="([^"]*)"' % re.escape(name), page)
        return html.unescape(m.group(1)) if m else ""

    fields = [
        ("__EVENTTARGET", ""),
        ("__EVENTARGUMENT", ""),
        ("__LASTFOCUS", ""),
        ("__VIEWSTATE", grab("__VIEWSTATE")),
        ("__VIEWSTATEGENERATOR", grab("__VIEWSTATEGENERATOR")),
        ("ctl00$ContentHolder$hfZileDisponibile", grab("ctl00$ContentHolder$hfZileDisponibile")),
        ("ctl00$ContentHolder$hfZileLibere", grab("ctl00$ContentHolder$hfZileLibere")),
        ("ctl00$ContentHolder$hfDefaultDate", grab("ctl00$ContentHolder$hfDefaultDate")),
        ("ctl00$ContentHolder$DisabledDates", grab("ctl00$ContentHolder$DisabledDates")),
        ("ctl00$ContentHolder$SelectedDate", date),
        ("ctl00$ContentHolder$Hour", ""),
        ("ctl00$ContentHolder$DisplayScheduleButton", "Button"),
    ]
    if not fields[3][1]:          # no viewstate -> bad page
        return None
    args = ["-e", BASE]
    for k, v in fields:
        args += ["--data-urlencode", f"{k}={v}"]
    args += [BASE]
    ok, resp = curl(args)
    return resp if ok else None


def parse_slots(resp):
    """Return list of (time_str, status) where status in taken/available/blocked."""
    slots = []
    for m in re.finditer(r'<td([^>]*)>\s*(\d{1,2}:\d{2})\s*</td>', resp):
        attrs, t = m.group(1).lower(), m.group(2)
        if "disabled" in attrs or "d9d9d9" in attrs:
            status = "blocked"
        elif "24ac21" in attrs or "background-color:green" in attrs:
            status = "available"
        elif "background-color:red" in attrs or "background-color:#ff" in attrs:
            status = "taken"
        else:
            status = "unknown"
        slots.append((t, status))
    return slots


def alert(matches, first_time):
    times = ", ".join(matches)
    line = f"SLOT AVAILABLE on {DATE}: {times}"
    print("\n" + "=" * 60)
    print("  🔔🔔🔔  " + line)
    print("  Book now: " + BASE)
    print("=" * 60 + "\n", flush=True)
    # spoken + notification + sound (macOS)
    try:
        subprocess.Popen(["say", f"Wedding slot available at {matches[0].replace(':',' ')}"])
    except Exception:
        pass
    try:
        subprocess.run(["osascript", "-e",
            f'display notification "{times} on {DATE}" '
            f'with title "Wedding slot FREE!" sound name "Glass"'])
    except Exception:
        pass
    snd = "/System/Library/Sounds/Glass.aiff"
    for _ in range(3 if first_time else 1):
        try:
            subprocess.run(["afplay", snd])
        except Exception:
            sys.stdout.write("\a"); sys.stdout.flush()
    if first_time and OPEN_BROWSER:
        try:
            subprocess.Popen(["open", BASE])
        except Exception:
            pass


def main():
    print(f"Watching {DATE}, alerting on slots >= {WATCH_FROM}.")
    print(f"Checking every ~{INTERVAL_SEC}s. Read-only, no booking. Ctrl-C to stop.\n",
          flush=True)
    announced = set()      # slots we've already alerted for
    fails = 0
    while True:
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        resp = fetch_schedule(DATE)
        if resp is None:
            fails += 1
            print(f"[{stamp}] check failed (network?), retry #{fails}", flush=True)
            time.sleep(min(300, 30 * fails))          # back off on errors
            continue
        fails = 0
        slots = parse_slots(resp)
        if not slots:
            print(f"[{stamp}] no slots parsed (date closed or page changed).", flush=True)
            time.sleep(INTERVAL_SEC)
            continue

        avail   = [t for t, s in slots if s == "available"]
        matches = [t for t in avail if to_min(t) >= WATCH_MIN]
        summary = " ".join(
            f"{t}{'✅' if s=='available' else '❌' if s=='taken' else '⬜'}"
            for t, s in slots)
        print(f"[{stamp}] {summary}", flush=True)

        new = [t for t in matches if t not in announced]
        if matches:
            alert(matches, first_time=bool(new))
            announced.update(matches)
            if not REPEAT_SOUND and not new:
                pass
        else:
            announced.clear()   # reset so a re-opened slot alerts again later

        time.sleep(INTERVAL_SEC + random.randint(-JITTER_SEC, JITTER_SEC))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        try: os.unlink(JAR)
        except Exception: pass
