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
import db_log

# ----------------------------- CONFIG ---------------------------------------
DATE          = "04-09-2026"   # day you want (dd-mm-yyyy)
WATCH_FROM    = "12:30"        # alert on this time or later
INTERVAL_SEC  = 60             # seconds between checks (>=30 to stay polite)
JITTER_SEC    = 10
HEARTBEAT_H   = 1              # WhatsApp/Telegram "still alive" to YOU every N hours
EMAIL_HEARTBEAT_MIN = 15       # EMAIL "still alive" to ALL emails every N minutes
                               # (keep >= 10: Gmail free caps ~500 emails/day)
FAIL_THRESH   = 5              # notify a failure after N consecutive fails
WATCHDOG_MIN  = 30             # alert if the CLOUD watcher is silent this long (runs every 5 min)
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
    # unified cloud log (no-op if Supabase not configured; never raises)
    rec["db"] = db_log.log_check(rec, "local", CFG)

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
    last_hb_msg = None      # WhatsApp/Telegram heartbeat (hourly, to you)
    last_hb_email = None    # email heartbeat (every EMAIL_HEARTBEAT_MIN, to all)
    cloud_down = False      # watchdog: have we alerted that the CLOUD watcher is silent?

    while True:
        rec = {"ts": now().isoformat(), "date": DATE, "watch_from": WATCH_FROM}
        resp, err = core.fetch_schedule(DATE)

        if err or not resp:
            fails += 1
            rec.update(action="error", error=err or "empty", consecutive_fails=fails)
            log_json(rec)
            print(f"[{stamp()}] ⚠️ check failed ({err}) — fail #{fails}", flush=True)
            if fails >= FAIL_THRESH and not alerted_failure:
                local_alarm("Wedding watcher is having trouble", times=1)
                notifier.send(f"Watcher LOCAL cununie: probleme la verificare ({err}), "
                              f"a {fails}-a oară. ({DATE})", CFG, audience="primary",
                              subject=f"⚠️ Watcher LOCAL: PROBLEMĂ ({DATE})", importance="high")
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
            notifier.send(f"Watcher LOCAL cununie a revenit. ({DATE})", CFG, audience="primary",
                          subject=f"✅ Watcher LOCAL a revenit ({DATE})", importance="normal")
            alerted_failure = False
        fails = 0

        available, matches = core.classify(slots, WATCH_FROM)
        rec.update(grid=core.grid_dict(slots), available=available, matches=matches, action="none")
        print(f"[{stamp()}] {core.grid_str(slots)}", flush=True)

        new = [t for t in matches if t not in announced]
        if new:
            msg = (f"S-a ELIBERAT un interval pentru cununie pe {DATE} la ora: {', '.join(matches)}!\n\n"
                   f"Rezervă ACUM (se ocupă în minute):\n{core.BASE}")
            local_alarm(f"Slot available at {matches[0].replace(':',' ')}", times=3)
            res = notifier.send(
                msg, CFG, audience="all",
                subject=f"🔔 LOC LIBER cununie {DATE} — {', '.join(matches)} — REZERVĂ ACUM",
                importance="high")
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

        # heartbeats (skip if we just fired a real alert)
        n = now()
        when_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        grid = core.grid_str(slots)
        subj, body = core.heartbeat_msg(DATE, WATCH_FROM, grid, when_str, scope="LOCAL")

        # WhatsApp/Telegram heartbeat -> YOU, hourly
        if not new and (last_hb_msg is None or
                        (n - last_hb_msg).total_seconds() >= HEARTBEAT_H * 3600):
            res = notifier.send(body, CFG, audience="primary",
                                channels=["whatsapp", "telegram"], subject=subj)
            rec["heartbeat_msg"] = True
            last_hb_msg = n
            print(f"  -> WhatsApp/TG heartbeat -> you: {res}", flush=True)

        # Email heartbeat -> ALL emails, every EMAIL_HEARTBEAT_MIN
        if not new and (last_hb_email is None or
                        (n - last_hb_email).total_seconds() >= EMAIL_HEARTBEAT_MIN * 60):
            res = notifier.send(body, CFG, audience="all",
                                channels=["email"], subject=subj)
            rec["heartbeat_email"] = True
            last_hb_email = n
            print(f"  -> email heartbeat -> both: {res}", flush=True)

        # watchdog: is the CLOUD watcher still writing to the shared log?
        seen = db_log.last_seen("cloud", CFG)
        if seen:
            try:
                age_min = (now() - datetime.datetime.fromisoformat(seen)).total_seconds() / 60
            except Exception:
                age_min = None
            if age_min is not None:
                rec["cloud_age_min"] = round(age_min, 1)
                if age_min > WATCHDOG_MIN and not cloud_down:
                    notifier.send(
                        f"ATENTIE: Watcher-ul CLOUD nu a mai scris in jurnal de "
                        f"{age_min:.0f} minute. Verifica cron-job.org si GitHub Actions:\n"
                        f"https://github.com/patrueduard03/wedding-slot-watcher/actions\n"
                        f"Watcher-ul LOCAL verifica in continuare.",
                        CFG, audience="primary",
                        subject="⚠️ Watcher CLOUD pare OPRIT — local-ul inca verifica",
                        importance="high")
                    cloud_down = True
                    print(f"  -> watchdog: CLOUD silent {age_min:.0f}min — alerted", flush=True)
                elif age_min <= WATCHDOG_MIN and cloud_down:
                    notifier.send(
                        "Watcher-ul CLOUD scrie din nou in jurnal — ambele sisteme active.",
                        CFG, audience="primary",
                        subject="✅ Watcher CLOUD a revenit", importance="normal")
                    cloud_down = False

        log_json(rec)
        time.sleep(INTERVAL_SEC + random.randint(-JITTER_SEC, JITTER_SEC))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
