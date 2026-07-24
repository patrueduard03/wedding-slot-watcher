# Wedding-slot watcher — free & automatic (GitHub Actions + WhatsApp)

Checks the Râmnicu Vâlcea civil-marriage page every 5 minutes **in the cloud**
(your computer can be off) and sends a **WhatsApp** (and/or Telegram) message to
up to 3 people the moment a slot at **12:30 or later on 04-09-2026** becomes free.

It only *watches and alerts*. You still book by hand on the site (there's a
reCAPTCHA + you must enter both partners' CNP — that part is intentionally manual).

---

## Part A — Get a free WhatsApp key for each of the 3 people (CallMeBot)

**Each person does this once, on their own phone** (it's how CallMeBot gets their
consent — you cannot do it for them):

1. Save this contact: **+34 644 51 95 23** (CallMeBot).
2. From WhatsApp, send it this exact message: **`I allow callmebot to send me messages`**
3. CallMeBot replies with a personal **API key** (a number).
4. Note that person's phone (international format, e.g. `+40712345678`) and their key.

Do this for all 3 people. You'll end up with 3 pairs like:
`+40712345678:123456`

> Prefer Telegram instead? See Part D — it's unlimited and even more reliable, but
> everyone needs Telegram. You can also do both.

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
