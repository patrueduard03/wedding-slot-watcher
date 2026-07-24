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
import db_log

DATE        = os.environ.get("WATCH_DATE", "04-09-2026")
WATCH_FROM  = os.environ.get("WATCH_FROM", "12:30")
HEARTBEAT_H = float(os.environ.get("HEARTBEAT_HOURS", "12"))
FAIL_THRESH = int(os.environ.get("FAIL_THRESHOLD", "3"))
WATCHDOG_MIN = float(os.environ.get("WATCHDOG_MIN", "30"))  # alert if LOCAL silent this long
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
                f"Watcher cununie: probleme la verificare ({err}), a {fails}-a oară la rând. "
                f"Voi anunța când revine. (data {DATE})", cfg, audience="primary",
                subject=f"⚠️ Watcher cununie: PROBLEMĂ la verificare ({DATE})",
                importance="high")
            record["notify"] = res
            alerted_failure = True
        state.update(announced=sorted(announced, key=core.to_min),
                     fails=fails, alerted_failure=alerted_failure,
                     last_heartbeat=last_heartbeat)
        save_state(state)
        record["db"] = db_log.log_check(record, "cloud", cfg)
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
                f"Watcher cununie: pagina nu mai afișează intervale pentru {DATE}. "
                f"Verifică dacă data e încă disponibilă.", cfg, audience="primary",
                subject=f"⚠️ Watcher cununie: fără intervale pentru {DATE}",
                importance="high")
            record["notify"] = res
            alerted_failure = True
        state.update(announced=sorted(announced, key=core.to_min), fails=fails,
                     alerted_failure=alerted_failure, last_heartbeat=last_heartbeat)
        save_state(state)
        record["db"] = db_log.log_check(record, "cloud", cfg)
        print("RECORD " + json.dumps(record, ensure_ascii=False))
        return

    available, matches = core.classify(slots, WATCH_FROM)
    record.update(grid=core.grid_dict(slots), available=available, matches=matches)

    notify_res = []
    # recovered from a previous outage?
    if alerted_failure:
        notify_res += notifier.send(
            f"Watcher cununie a revenit și verifică din nou. ({DATE})",
            cfg, audience="primary",
            subject=f"✅ Watcher cununie a revenit ({DATE})", importance="normal")
        record["recovered"] = True
        alerted_failure = False
    fails = 0

    new = [t for t in matches if t not in announced]

    if new:
        msg = (f"S-a ELIBERAT un interval pentru cununie pe {DATE} la ora: {', '.join(matches)}!\n\n"
               f"Rezervă ACUM (se ocupă în minute):\n{core.BASE}")
        notify_res += notifier.send(
            msg, cfg, audience="all",
            subject=f"🔔 LOC LIBER cununie {DATE} — {', '.join(matches)} — REZERVĂ ACUM",
            importance="high")
        announced |= set(matches)
        record["action"] = "SLOT_ALERT"
    elif not matches:
        announced = set()
        record["action"] = "none"
    else:
        record["action"] = "already_announced"

    # heartbeat (hourly; skip if we just sent a real slot alert).
    # Cross-check the shared Supabase log: if a heartbeat was already sent more
    # recently than state.json remembers (e.g. a failed state push), trust the
    # log — prevents duplicate heartbeats. DB unreachable -> state.json alone.
    db_hb = db_log.last_heartbeat("cloud", cfg)
    eff_last = max((t for t in (last_heartbeat, db_hb) if t), default=None)
    if eff_last and eff_last != last_heartbeat:
        last_heartbeat = eff_last          # self-heal state.json from the log
    do_hb = (FORCE_TEST or hb_due(eff_last)) and not new
    if do_hb:
        when = now().strftime("%Y-%m-%d %H:%M UTC")
        subj, body = core.heartbeat_msg(DATE, WATCH_FROM, core.grid_str(slots),
                                        when, test=FORCE_TEST)
        # email -> BOTH addresses; WhatsApp/Telegram -> YOU (primary)
        notify_res += notifier.send(body, cfg, audience="all", channels=["email"], subject=subj)
        notify_res += notifier.send(body, cfg, audience="primary",
                                    channels=["whatsapp", "telegram"], subject=subj)
        last_heartbeat = now().isoformat()
        record["heartbeat"] = True

    # ---------- watchdog: is the LOCAL watcher still writing to the log? ----------
    # One calm notice per transition (stopped/back), never repeated. The local
    # watcher is EXPECTED to be off when the laptop is away — the notice just
    # confirms the cloud noticed and still covers. Set WATCHDOG_MIN=0 to disable.
    local_down = bool(state.get("watchdog_local_down", False))
    seen = db_log.last_seen("local", cfg) if WATCHDOG_MIN > 0 else None
    if seen:
        try:
            age_min = (now() - datetime.datetime.fromisoformat(seen)).total_seconds() / 60
        except Exception:
            age_min = None
        if age_min is not None:
            record["local_age_min"] = round(age_min, 1)
            if age_min > WATCHDOG_MIN and not local_down:
                notify_res += notifier.send(
                    f"Info: watcher-ul LOCAL (laptop) nu mai scrie in jurnal de "
                    f"{age_min:.0f} min — probabil l-ai oprit / laptopul e inchis. "
                    f"NICIO problema: CLOUD-ul verifica in continuare la 5 minute. "
                    f"Cand revii la laptop: cd ~/Documents/wedding && python3 watch_wedding_slots.py",
                    cfg, audience="primary",
                    subject="ℹ️ Watcher LOCAL oprit — CLOUD-ul te acopera",
                    importance="normal")
                local_down = True
            elif age_min <= WATCHDOG_MIN and local_down:
                notify_res += notifier.send(
                    "Watcher-ul LOCAL scrie din nou in jurnal — ambele sisteme active.",
                    cfg, audience="primary",
                    subject="✅ Watcher LOCAL pornit — ambele sisteme active",
                    importance="normal")
                local_down = False

    if notify_res:
        record["notify"] = notify_res

    state.update(announced=sorted(announced, key=core.to_min), fails=0,
                 alerted_failure=False, last_heartbeat=last_heartbeat,
                 watchdog_local_down=local_down)
    save_state(state)
    record["db"] = db_log.log_check(record, "cloud", cfg)
    print("RECORD " + json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()
