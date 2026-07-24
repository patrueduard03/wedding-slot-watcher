# Wedding-slot watcher — free & automatic (GitHub Actions + WhatsApp)

Checks the Râmnicu Vâlcea civil-marriage page every 5 minutes **in the cloud**
(your computer can be off) and sends a **WhatsApp** (and/or Telegram) message to
up to 3 people the moment a slot at **12:30 or later on 04-09-2026** becomes free.

It only *watches and alerts*. You still book by hand on the site (there's a
reCAPTCHA + you must enter both partners' CNP — that part is intentionally manual).

---

## Part A — Get a free WhatsApp key for each of the 3 people (CallMeBot)

> ⚠️ **Important — how CallMeBot works:** an API key belongs to **one specific
> phone number**. A key only lets you message **that** number. So a key activated
> for `40736574053` can send **only** to `40736574053` — not to anyone else.
> To message 3 people, **each of those 3 phones must do the opt-in below and give
> you its own key.** (This is CallMeBot's consent/anti-spam rule — a good thing.)

**Each recipient does this once, on their own phone:**

1. Save this contact: **+34 644 51 95 23** (CallMeBot).
2. From WhatsApp, send it this exact message: **`I allow callmebot to send me messages`**
3. CallMeBot replies with **that phone's** API key (a number).
4. Write down the phone (e.g. `40736574054`) and its key.

Do this on all 3 phones (`40736574054`, `40748982549`, `40747315436`).
You'll end up with 3 `phone:key` pairs, combined comma-separated, no spaces:
```
40736574054:KEY1,40748982549:KEY2,40747315436:KEY3
```

> **Don't want to chase 3 opt-ins?** CallMeBot also has a **WhatsApp Group** mode:
> put the 3 people in one group, add CallMeBot to it, and you get a **single** key
> that messages the whole group — everyone sees the alert. Steps here:
> https://www.callmebot.com/blog/group-message-api/
>
> Prefer Telegram? See Part D — unlimited and even more reliable, but everyone
> needs Telegram. You can use WhatsApp, the group, Telegram, or any mix.

---

## Part B — Put the code on GitHub

1. Create a **public** repo (public = unlimited free Actions minutes).
2. Upload these files (keep the folder layout):
   - `check_once.py`
   - `state.json`
   - `.github/workflows/watch.yml`
3. Or from this folder:
   ```bash
   cd ~/Documents/wedding
   git init
   git add check_once.py state.json .github/workflows/watch.yml .gitignore
   git commit -m "wedding slot watcher"
   git branch -M main
   git remote add origin https://github.com/<YOUR_USERNAME>/<YOUR_REPO>.git
   git push -u origin main
   ```

---

## Part C — Add your secret (the phone numbers stay private)

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

- Name: `CALLMEBOT_RECIPIENTS`
- Value (comma-separated `phone:apikey`, no spaces):
  ```
  +40712345678:123456,+40723456789:234567,+40734567890:345678
  ```

That's it. Go to the **Actions** tab → **watch-wedding-slots** → **Run workflow**
to test it immediately. Check the run log — it prints the current slot grid.

---

## Part D — (Optional) Telegram instead of / in addition to WhatsApp

1. In Telegram, message **@BotFather** → `/newbot` → get a **bot token**.
2. Each person opens your bot and taps **Start** (or add the bot to a group).
3. Get each chat id: message **@userinfobot** (personal id) or use a group id.
4. Add two secrets:
   - `TELEGRAM_BOT_TOKEN` = the token from BotFather
   - `TELEGRAM_CHAT_IDS`  = `id1,id2,id3`

The script sends via whichever secrets exist, so you can use WhatsApp, Telegram, or both.

---

## Good to know

- **Timing:** GitHub cron is every 5 min and can run a few minutes late. For a
  slot that frees up rarely, that's fine. Want ~1-minute checks? Use the local
  `watch_wedding_slots.py` on a Mac that stays on, or ask me for the Google
  Apps Script version (also free, 1-minute triggers).
- **No spam:** once a slot is announced, `state.json` remembers it and nobody
  gets re-messaged until it closes and reopens.
- **60-day rule:** GitHub pauses scheduled workflows after 60 days with **no repo
  activity**. Sept 4 is ~6 weeks out, so you're inside the window. If you ever hit
  it, just push any commit (or click "Run workflow") to re-enable.
- **Change what you watch:** edit `WATCH_DATE` / `WATCH_FROM` in
  `.github/workflows/watch.yml`. `WATCH_FROM=12:30` means "12:30 or later".
