#!/usr/bin/env python3
"""
slots_core.py — shared logic for both watchers (cloud + local).

Fetches the Orar (schedule) for a date and classifies each time slot.
READ-ONLY: never books, never sends personal data to the site.
"""
import os, re, html, subprocess, tempfile

BASE = "https://se.primariavl.ro/starecivila/"
UA   = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120 Safari/537.36")

# Ship the Certum CA chain so TLS verifies on Linux/CI (never --insecure).
CA_BUNDLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cacert.pem")
CA_ARGS = ["--cacert", CA_BUNDLE] if os.path.exists(CA_BUNDLE) else []


def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _curl(extra, jar):
    try:
        r = subprocess.run(["curl", "-s", "--compressed", "--max-time", "30",
                            "-A", UA, "-c", jar, "-b", jar] + CA_ARGS + extra,
                           capture_output=True, text=True, timeout=45)
        if r.returncode != 0:
            return "", f"curl exit {r.returncode}: {r.stderr.strip()[:120]}"
        return r.stdout, None
    except Exception as e:
        return "", f"curl exception: {e}"


def fetch_schedule(date):
    """Return (html, None) on success or (None, error_reason) on failure."""
    jar = tempfile.NamedTemporaryFile(delete=False, suffix=".cookies").name
    try:
        page, err = _curl([BASE], jar)
        if not page:
            return None, err or "empty GET response"

        def grab(name):
            m = re.search(r'name="%s"[^>]*value="([^"]*)"' % re.escape(name), page)
            return html.unescape(m.group(1)) if m else ""

        vs = grab("__VIEWSTATE")
        if not vs:
            return None, "no __VIEWSTATE (page blocked or changed)"

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
        resp, err = _curl(args, jar)
        if not resp:
            return None, err or "empty POST response"
        return resp, None
    finally:
        try: os.unlink(jar)
        except Exception: pass


def parse_slots(resp):
    """Return list of (time_str, status) with status taken/available/blocked/unknown."""
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


def classify(slots, watch_from):
    """Return (available_times, matching_times>=watch_from)."""
    wmin = to_min(watch_from)
    available = [t for t, s in slots if s == "available"]
    matches = sorted({t for t in available if to_min(t) >= wmin}, key=to_min)
    return available, matches


def grid_str(slots):
    mark = {"available": "✅", "taken": "❌", "blocked": "⬜", "unknown": "❓"}
    return " ".join(f"{t}{mark.get(s, '❓')}" for t, s in slots)


def grid_dict(slots):
    return {t: s for t, s in slots}


def heartbeat_msg(date, watch_from, grid, when, scope="", test=False):
    """Return (subject, body) for a very-clear 'still alive' heartbeat."""
    tag = "TEST — " if test else ""
    sc = f" {scope}" if scope else ""
    subject = f"✅ {tag}HEARTBEAT {when} — Watcher cununie{sc} FUNCTIONEAZA (nimic liber inca)"
    body = (
        f"{tag}Acesta este un mesaj automat de tip HEARTBEAT.\n"
        f"Rolul lui: sa confirme ca sistemul de urmarire FUNCTIONEAZA.\n\n"
        f"✅ Watcher-ul{sc} este ACTIV si verifica in continuare.\n"
        f"Data urmarita: {date} — caut un interval liber la ora {watch_from} sau mai tarziu.\n"
        f"Momentan: NICIUN loc liber inca.\n"
        f"Stare curenta: {grid}\n"
        f"Verificat la: {when}\n\n"
        f"⚠️ Vei primi un mesaj DIFERIT si URGENT (subiect '🔔 LOC LIBER') doar cand se\n"
        f"elibereaza un loc. Daca NU mai primesti aceste heartbeat-uri, sistemul s-a\n"
        f"oprit — verifica-l.\n\n"
        f"Rezervari: {BASE}"
    )
    return subject, body
