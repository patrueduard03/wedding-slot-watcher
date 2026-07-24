#!/usr/bin/env python3
"""
watch_wedding_slots.py — LOCAL real-time watcher (run on a Mac that stays on).

Faster than the cloud cron (~60s vs 5 min) and fully redundant. On a wanted slot
it: plays an alarm, speaks aloud, shows a macOS notification, opens the booking
page, AND sends WhatsApp/Telegram to everyone (same as the cloud version).

Also: periodic heartbeat + failure/recovery alerts, and a JSON-lines audit log
(checks.jsonl) recording every check — when, and exactly what was returned.

READ-ONLY: it never books and never sends personal data to the site.
Configure recipients in config.local.json (see config.local.example.json).
Run:  python3 watch_wedding_slots.py     Stop: Ctrl-C
"""
import sys, time, random, subprocess, datetime, json, os
import slots_core as core
import notifier

# ----------------------------- CONFIG ---------------------------------------
DATE          = "04-09-2026"   # day you want (dd-mm-yyyy)
WATCH_FROM    = "12:30"        # alert on this time or later
INTERVAL_SEC  = 60             # seconds between checks (>=30 to stay polite)
JITTER_SEC    = 10
HEARTBEAT_H   = 12             # send a "still alive" WhatsApp every N hours
FAIL_THRESH   = 5              # WhatsApp a failure notice after N consecutive fails
OPEN_BROWSER  = True
LOGFILE       = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checks.jsonl")
# ----------------------------------------------------------------------------

CFG = notifier.load_config()


def stamp():
    return datetime.datetime.now().strftime("%H:%M:%S")

def now():
    return datetime.datetime.now(datetime.timezone.utc)

def log_json(rec):
    try:
        with open(LOGFILE, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

def local_alarm(text, times=3):
    try: subprocess.Popen(["say", text])
    except Exception: pass
    try:
        subprocess.run(["osascript", "-e",
            f'display notification "{text}" with title "Wedding watcher" sound name "Glass"'])
    except Exception: pass
    for _ in range(times):
        try: subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"])
        except Exception: sys.stdout.write("\a"); sys.stdout.flush()


def main():
    print(f"LOCAL watcher — {DATE}, alerting on slots >= {WATCH_FROM}, every ~{INTERVAL_SEC}s.")
    print(f"Channels configured: {'yes' if notifier.has_channel(CFG) else 'NO (local alerts only)'}")
    print("Read-only. Ctrl-C to stop.\n", flush=True)

    announced = set()
    fails = 0
    alerted_failure = False
    last_heartbeat = None

    while True:
        rec = {"ts": now().isoformat(), "date": DATE}
        resp, err = core.fetch_schedule(DATE)

        if err or not resp:
            fails += 1
            rec.update(action="error", error=err or "empty", consecutive_fails=fails)
            log_json(rec)
            print(f"[{stamp()}] ⚠️ check failed ({err}) — fail #{fails}", flush=True)
            if fails >= FAIL_THRESH and not alerted_failure:
                local_alarm("Wedding watcher is having trouble", times=1)
                notifier.send(f"⚠️ Watcher LOCAL cununie: probleme la verificare ({err}), "
                              f"a {fails}-a oară. ({DATE})", CFG, audience="primary")
                alerted_failure = True
            time.sleep(min(300, 30 * fails))
            continue

        slots = core.parse_slots(resp)
        if not slots:
            fails += 1
            rec.update(action="empty", error="no slots parsed", consecutive_fails=fails)
            log_json(rec)
            print(f"[{stamp()}] no slots parsed (date closed / page changed) #{fails}", flush=True)
            time.sleep(INTERVAL_SEC)
            continue

        if alerted_failure:
            notifier.send(f"✅ Watcher LOCAL cununie a revenit. ({DATE})", CFG, audience="primary")
            alerted_failure = False
        fails = 0

        available, matches = core.classify(slots, WATCH_FROM)
        rec.update(grid=core.grid_dict(slots), available=available, matches=matches, action="none")
        print(f"[{stamp()}] {core.grid_str(slots)}", flush=True)

        new = [t for t in matches if t not in announced]
        if new:
            msg = (f"🔔🔔 LOC LIBER pentru cununie pe {DATE} la ora: {', '.join(matches)}! "
                   f"Rezervă ACUM: {core.BASE}")
            local_alarm(f"Slot available at {matches[0].replace(':',' ')}", times=3)
            res = notifier.send(msg, CFG, audience="all")
            rec.update(action="SLOT_ALERT", notify=res)
            print(f"  -> ALERT sent: {res}", flush=True)
            if OPEN_BROWSER:
                try: subprocess.Popen(["open", core.BASE])
                except Exception: pass
            announced |= set(matches)
        elif matches:
            rec["action"] = "already_announced"
            local_alarm("Slot still available", times=1)  # keep nagging until booked
        else:
            announced.clear()

        # heartbeat (skip if we just fired a real alert)
        if not new and (last_heartbeat is None or
                        (now() - last_heartbeat).total_seconds() >= HEARTBEAT_H * 3600):
            res = notifier.send(f"✅ Watcher LOCAL activ. {DATE}: încă nimic după {WATCH_FROM}. "
                                f"Stare: {core.grid_str(slots)}", CFG, audience="primary")
            rec["heartbeat"] = True
            last_heartbeat = now()
            print(f"  -> heartbeat sent: {res}", flush=True)

        log_json(rec)
        time.sleep(INTERVAL_SEC + random.randint(-JITTER_SEC, JITTER_SEC))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
