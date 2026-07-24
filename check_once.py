#!/usr/bin/env python3
"""
check_once.py — ONE check, for the cloud cron (GitHub Actions).

Layers of safety:
  * slot-open alert  -> WhatsApp/Telegram to EVERYONE, the instant a wanted slot frees
  * heartbeat        -> periodic "still watching" to the PRIMARY, so you know it's alive
  * failure alert    -> tells the PRIMARY if checks start failing, and again on recovery
  * JSON record      -> prints one machine-readable line per run (kept in Actions logs)

State (dedup + heartbeat + failure) lives in state.json, committed only when it
changes. READ-ONLY against the site — never books, never sends personal data.

Env: WATCH_DATE, WATCH_FROM, HEARTBEAT_HOURS, FAIL_THRESHOLD, FORCE_TEST,
     CALLMEBOT_RECIPIENTS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS
"""
import os, sys, json, datetime
import slots_core as core
import notifier

DATE        = os.environ.get("WATCH_DATE", "04-09-2026")
WATCH_FROM  = os.environ.get("WATCH_FROM", "12:30")
HEARTBEAT_H = float(os.environ.get("HEARTBEAT_HOURS", "12"))
FAIL_THRESH = int(os.environ.get("FAIL_THRESHOLD", "3"))
FORCE_TEST  = os.environ.get("FORCE_TEST", "").strip().lower() in ("1", "true", "yes")
STATE_FILE  = os.environ.get("STATE_FILE", "state.json")


def now():
    return datetime.datetime.now(datetime.timezone.utc)

def load_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {}

def save_state(s):
    json.dump(s, open(STATE_FILE, "w"), indent=2)

def hb_due(last_iso):
    if not last_iso:
        return True
    try:
        last = datetime.datetime.fromisoformat(last_iso)
    except Exception:
        return True
    return (now() - last).total_seconds() >= HEARTBEAT_H * 3600


def main():
    cfg = notifier.load_config()
    state = load_state()
    announced = set(state.get("announced", []))
    fails = int(state.get("fails", 0))
    alerted_failure = bool(state.get("alerted_failure", False))
    last_heartbeat = state.get("last_heartbeat")

    record = {"ts": now().isoformat(), "date": DATE, "watch_from": WATCH_FROM}

    resp, err = core.fetch_schedule(DATE)

    # ---------- failure path ----------
    if err:
        fails += 1
        record.update(action="error", error=err, consecutive_fails=fails)
        if fails >= FAIL_THRESH and not alerted_failure:
            res = notifier.send(
                f"⚠️ Watcher cununie: probleme la verificare ({err}), a {fails}-a oară la rând. "
                f"Voi anunța când revine. (data {DATE})", cfg, audience="primary")
            record["notify"] = res
            alerted_failure = True
        state.update(announced=sorted(announced, key=core.to_min),
                     fails=fails, alerted_failure=alerted_failure,
                     last_heartbeat=last_heartbeat)
        save_state(state)
        print("RECORD " + json.dumps(record, ensure_ascii=False))
        return

    # ---------- success path ----------
    slots = core.parse_slots(resp)
    if not slots:
        # Treat "no slots parsed" as a soft failure (date may be closed / page changed)
        fails += 1
        record.update(action="empty", error="no slots parsed", consecutive_fails=fails)
        if fails >= FAIL_THRESH and not alerted_failure:
            res = notifier.send(
                f"⚠️ Watcher cununie: pagina nu mai afișează intervale pentru {DATE}. "
                f"Verifică dacă data e încă disponibilă.", cfg, audience="primary")
            record["notify"] = res
            alerted_failure = True
        state.update(announced=sorted(announced, key=core.to_min), fails=fails,
                     alerted_failure=alerted_failure, last_heartbeat=last_heartbeat)
        save_state(state)
        print("RECORD " + json.dumps(record, ensure_ascii=False))
        return

    available, matches = core.classify(slots, WATCH_FROM)
    record.update(grid=core.grid_dict(slots), available=available, matches=matches)

    notify_res = []
    # recovered from a previous outage?
    if alerted_failure:
        notify_res += notifier.send(
            f"✅ Watcher cununie a revenit și verifică din nou. ({DATE})",
            cfg, audience="primary")
        record["recovered"] = True
        alerted_failure = False
    fails = 0

    new = [t for t in matches if t not in announced]

    if new:
        msg = (f"🔔🔔 LOC LIBER pentru cununie pe {DATE} la ora: {', '.join(matches)}! "
               f"Rezervă ACUM (se ocupă în minute): {core.BASE}")
        notify_res += notifier.send(msg, cfg, audience="all")
        announced |= set(matches)
        record["action"] = "SLOT_ALERT"
    elif not matches:
        announced = set()
        record["action"] = "none"
    else:
        record["action"] = "already_announced"

    # heartbeat (skip if we just sent a real slot alert)
    do_hb = (FORCE_TEST or hb_due(last_heartbeat)) and not new
    if do_hb:
        tag = "TEST — " if FORCE_TEST else ""
        msg = (f"✅ {tag}Watcher cununie activ. {DATE}: încă nimic liber după {WATCH_FROM}. "
               f"Stare: {core.grid_str(slots)}")
        notify_res += notifier.send(msg, cfg, audience="primary")
        last_heartbeat = now().isoformat()
        record["heartbeat"] = True

    if notify_res:
        record["notify"] = notify_res

    state.update(announced=sorted(announced, key=core.to_min), fails=0,
                 alerted_failure=False, last_heartbeat=last_heartbeat)
    save_state(state)
    print("RECORD " + json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()
