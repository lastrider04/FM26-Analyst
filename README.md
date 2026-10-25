# FM26 Analyst

**A companion app for Football Manager 26.** It watches your save while you play and builds up a history of your squad:
- **After every match:** form, ratings and per-match stats.
- **Over time:** attributes, CA and development.
- **Fitness:** condition, sharpness and injuries.

You get a dashboard, a recommended XI for the next match, and an AI assistant manager you can ask about your squad. There's also a phone app for when you're away from your PC.

![Overview](docs/screenshots/01-overview.png)

- **Automatic:** it captures by itself after each of your matches, so you never type anything in.
- **Read-only:** it only *reads* the game's memory. It never changes the game, your save or any files of FM26.
- **Local:** everything stays on your PC. Nothing is sent anywhere unless you set up the AI coach, which then sends squad data to the AI provider you choose.

> FM26 Analyst is an unofficial fan project. It isn't affiliated with or endorsed by Sports Interactive or SEGA. Use it with single-player saves only.

---

## Contents
- [What you need](#what-you-need)
- [Install](#install)
- [First start](#first-start)
- [Using the dashboard](#using-the-dashboard)
- [AI coach](#ai-coach)
- [Phone app](#phone-app)
- [Game snapshots and backups](#game-snapshots-and-backups)
- [Updating, uninstalling and troubleshooting](#updating)
- [Your data](#your-data)

## What you need
- **Windows 10 or 11.**
- **Football Manager 26** (PC). The reader matches game build `FM26.fm26-rel-prod.2329565`. After a game patch, the app tells you if the reader no longer matches; see [Troubleshooting](#troubleshooting).
- **Python 3.10 or newer.** The installer checks for it and tells you how to get it. The quickest way is to open a terminal and run `winget install Python.Python.3.12`, or download it from [python.org](https://www.python.org/downloads/) and tick **"Add python.exe to PATH"**.
- **Microsoft Edge or Google Chrome**, to show the app in its own window. Windows already has Edge.

## Install
1. **Download** the latest release from the [Releases page](../../releases): **Source code (zip)**.
2. **Extract** it somewhere permanent, for example `Documents\FM26-Analyst`. Your history is stored in this folder, so don't use your Downloads or Temp folder.
3. **Double-click `install.bat`.** It:
   - checks for Python;
   - creates a private Python environment in `.venv`;
   - installs the packages the app needs;
   - adds **FM26 Analyst** shortcuts to your Desktop and Start menu.

   It takes about a minute. At the end it offers to start the app.

That's it. From now on, open **FM26 Analyst** from the Desktop or Start menu.

<details><summary>Prefer the command line, or using git?</summary>

```
git clone https://github.com/lastrider04/FM26-Analyst.git
cd FM26-Analyst
install.bat
```
`install.bat --no-shortcuts` installs without adding shortcuts. Start the app with `.venv\Scripts\pythonw.exe launch.py`.
You can also run `start.bat`, which runs the app in a console window and opens your normal browser.
</details>

## First start
1. **Start FM26 and load your save.** It doesn't matter which you start first.
2. **Open FM26 Analyst.** The dashboard opens in its own window at `http://127.0.0.1:8765`.
3. **Choose your club.** On first start the Overview asks which club you manage. Type a few letters, pick your club and click **Use this club**. Some names exist more than once in the game's database; those show their club ID so you can tell them apart.

   ![Choose your club](docs/screenshots/10-first-run.png)

4. **Press Capture** (top right) to take your first snapshot. From now on the app captures by itself shortly after each of your matches, and once a week of game time when there's no match. You can also capture at any time with **Ctrl+Alt+S** while you're in the game.

**The top bar:**
- **Snapshot chip:** the game snapshot in use.
- **Green dot:** FM26 is running.
- **Last update:** the date of the last capture.
- **Auto switch:** turns automatic capture on or off.
- **Capture button:** takes a snapshot now.

Hover over any of them for details. Look for the **ⓘ** icons around the app for short explanations.

> **Closing the window doesn't stop the app.** It keeps running in the background, so auto-capture and the hotkey keep working while you play. Open the shortcut again to bring the window back. To stop it completely, use **Settings › App › Quit FM26 Analyst**.

## Using the dashboard

### Overview
The page you'll use most. It shows:
- **Last match:** score, KPI tiles, best-rated player, and the full player stats in tabs (Key stats, Passing, Attacking, Defending, Goalkeeping, Set pieces).
- **Team form:** recent results and upcoming fixtures.
- **Alerts:** injured players, low condition, high jadedness, low sharpness.
- **In form:** your best performers over the last 5 captured matches.
- **Recommended for the next match:**
  - **Picks:** the best-placed starters from form, trend, goal threat, ability and fitness;
  - **Swaps:** a like-for-like replacement for anyone who should rest;
  - **Injured players** are never picked.

### Players
Every player at the club: first team, loanees and youth.

![Players](docs/screenshots/02-players.png)

Click a player to open their **player page**:
- attribute radar and CA history;
- match log;
- role profile;
- similar players;
- injury status;
- goalkeeping numbers for keepers.

![Player page](docs/screenshots/03-player.png)

### Compare
Two players side by side: attributes, CA/PA and their stats.

![Compare](docs/screenshots/04-compare.png)

### Development
Who is improving and who is declining between captures, by CA and by attribute group. Pick the period at the top.

![Development](docs/screenshots/05-development.png)

### Per 90
Per-90 stats for the whole squad (players with 180+ minutes):
- **Goalkeepers:** save %, goals conceded per 90, clean sheets.
- **Outfield role scores:** chance creation, goal threat, finishing, defensive work and ball security, each ranked against the rest of your squad.

Hover over any column header for what it means.

![Per 90](docs/screenshots/06-per90.png)

### Fixtures
Results and upcoming fixtures with kick-off times.

![Fixtures](docs/screenshots/07-fixtures.png)

Click a result for its **match report**, with the full player stats for that match.

![Match report](docs/screenshots/08-match.png)

## AI coach
Click **Ask the coach** (bottom right, on every page) and ask about selection, rotation, fitness, form or development. Some examples:
- *Who should I rest for the next match?*
- *Who isn't performing and should I rotate?*
- *Which young players need development minutes?*

The coach knows your squad from the captured stats, focuses on the page you're viewing, and looks up extra player and match detail when it needs to. Answers show the usage (tokens, and the cost where the provider reports it). Conversations are saved; **🕘** reopens them.

![AI coach](docs/screenshots/09-coach.png)

**Set it up in Settings › AI coach.** Choose one:
- **ChatGPT plan:** click *Continue with ChatGPT* and sign in, with no API key needed. Answers count against your ChatGPT plan's usage. The model list shows roughly how heavily each model draws on your plan.
- **API key / other provider:** OpenAI, OpenRouter, or a free local model through [Ollama](https://ollama.com) or [LM Studio](https://lmstudio.ai). Any OpenAI-compatible endpoint works. Use *Test connection* to check it.

![AI coach settings](docs/screenshots/12-settings-coach.png)

The API key and sign-in tokens are encrypted with Windows (DPAPI), tied to your Windows account, and never shown again. Under **Coach instructions** you can change how the coach answers.

## Phone app
FM26 Analyst also runs on your phone as an installable web app. It has a mobile layout with tabs at the bottom, and the coach opens full screen. When your PC is off, the phone still shows the last data it loaded.

<p>
<img src="docs/screenshots/20-phone-overview.png" width="200" alt="Phone overview">
<img src="docs/screenshots/21-phone-player.png" width="200" alt="Phone player page">
<img src="docs/screenshots/22-phone-coach.png" width="200" alt="Phone coach">
<img src="docs/screenshots/23-phone-sign-in.png" width="200" alt="Phone sign-in">
</p>

The phone reaches your PC through **your own reverse proxy with HTTPS**, for example [NGINX Proxy Manager](https://nginxproxymanager.com) with a free Let's Encrypt certificate and your own domain. It then works from anywhere, not just on your Wi-Fi.

**What a phone can and can't do:**
- **Can:** read every page, use the coach, Capture and switch Auto.
- **Can't:** change Settings, game snapshots or sign-ins, or quit the app. Those stay on the PC.

**What protects it:** the phone talks to a separate, locked-down listener (port 8766), which is **off** until you turn it on. Pairing a phone takes **two steps**:
1. **Sign in** with Google (only accounts you allow) or with a username and password you set;
2. **Enter the one-time pairing code** shown on your PC. Scan its QR code, or type it.

Neither step works alone. You can revoke any paired device in Settings › Phone.

![Phone settings](docs/screenshots/14-settings-phone.png)

**Setup.** Settings › Phone has a **Setup guide** with your PC's own IP and port filled in.
1. Give your PC a fixed IP on your home network (a DHCP reservation in your router).
2. Allow the port through Windows Firewall. Open PowerShell as administrator and run this, using the IP of the machine running your proxy:
   ```powershell
   New-NetFirewallRule -DisplayName "FM26 Analyst phone" -Direction Inbound -Protocol TCP -LocalPort 8766 -RemoteAddress <proxy IP> -Action Allow
   ```
3. In NGINX Proxy Manager, add a **Proxy Host** for your domain:
   - **Scheme:** `http`, the PC's IP, port `8766`;
   - **SSL tab:** request a Let's Encrypt certificate and tick *Force SSL*;
   - **Advanced tab:** add `proxy_buffering off;` so coach answers stream.
4. In Settings › Phone:
   - enter the **public address** (`https://…`) and the proxy's IP under *Only accept connections from*;
   - turn on **Allow phone access**.
5. Set up at least one sign-in method:
   - **Google:** in [Google Cloud Console › Credentials](https://console.cloud.google.com/apis/credentials), create an **OAuth client ID** of type *Web application*. Add your public address under *Authorized JavaScript origins*, and the **redirect URI** shown in Settings › Phone (`https://<your domain>/auth/google/callback`). Paste the client ID and secret into Settings › Phone, and add your Google account under *Allowed Google accounts*.
   - **Password:** set a username and a password of at least 10 characters.
6. On your phone:
   - open your address, sign in, and enter the pairing code from **Show pairing code** on the PC;
   - add the app to your home screen: Safari *Share › Add to Home Screen*, or Chrome *Install app*.

<details><summary>Phone troubleshooting</summary>

- **NGINX shows "Internal error" or 502:** check the proxy host's scheme is `http`, not `https`. The app speaks plain HTTP behind the proxy.
- **Works on mobile data but not on home Wi-Fi:** your router probably can't loop back to its own public address. Add a local DNS record for your domain that points to the **proxy's** LAN IP, for example in Pi-hole: *Local DNS › DNS Records*.
- **"DNS address could not be found" only at home:** your local DNS server may have cached the name from before you created it. Flush its cache, or add the local record above.
</details>

## Game snapshots and backups
Each **game snapshot** is a separate history: one save, or one job.
- **New saves are detected automatically:** the app recognises a different save from the players at your club, so two careers' histories never mix.
- **New jobs:** when you start a new save or take a job at another club, use **Settings › Game snapshots › Start a new game**. You can switch between snapshots, rename them, or delete old ones.
- **Backups:** the database is backed up once a day and before each new game, and the newest 14 are kept. **Back up now** makes one at any time.

![Game snapshots](docs/screenshots/13-settings-snapshots.png)

<a id="updating"></a>
## Updating
Download the new release and extract it **over** your existing folder, replacing the files. Your history in `data\` is kept. Then run `install.bat` again to pick up any new packages.

## Uninstalling
1. Quit the app: **Settings › App › Quit**.
2. Delete the FM26 Analyst folder. This deletes your history too.
3. Delete the Desktop and Start menu shortcuts.

## Troubleshooting
- **"FM26 has been updated" banner:** the game build changed and the reader doesn't recognise it yet. Captures pause so no bad data is stored, and your history and the dashboard still work. Check the [Releases page](../../releases) for an update that supports the new build.
- **No clubs found when choosing your club:** FM26 must be running with your save loaded (not just the main menu).
- **"Game not running" while it is:** wait a moment: the app checks every 15 seconds.
- **The hotkey does nothing:** another program may be using Ctrl+Alt+S. Change it in **Settings › Capture**, then restart the app.
- **Logs:** `data\app.log`.

![Capture settings](docs/screenshots/11-settings-capture.png)

## Your data
Everything personal stays in the `data\` folder inside the app folder:

| Path | What it is |
|------|------------|
| `data\fm_analyst.db` | Your first game snapshot's history (SQLite) |
| `data\careers\<n>\` | Later game snapshots |
| `data\snapshots\` | A raw copy of each capture |
| `data\backups\` | Automatic database backups |
| `data\chats\` | Saved coach conversations |
| `data\config.json` | Settings. API keys and secrets in it are encrypted. |
| `data\chatgpt.json` | Encrypted ChatGPT sign-in tokens, if you use your ChatGPT plan |
| `data\devices.json` | Paired phones (only token hashes) |
| `data\app.log` | The app's log |

**What the app does with the game and your data:**
- It reads FM26's memory with read-only access. It never writes to or injects into the game.
- Your data is only sent anywhere when you ask the AI coach a question, and then only to the provider you chose.

## For developers
- **Tests:**
  ```
  .venv\Scripts\pip install -r requirements-dev.txt
  .venv\Scripts\python -m pytest
  ```
  The tests use synthetic data and never touch the game or your `data\` folder.
- **Code layout:**
  - `reader\`: the memory reader and its offset profile per game build;
  - `capture\`: snapshots and auto-capture;
  - `store\`: database, game snapshots and backups;
  - `analytics\`;
  - `llm\`: the coach;
  - `web\`: the dashboard and the phone listener.

## Licence
[GPL-3.0](LICENSE). You're free to use, change and share FM26 Analyst. If you share a modified version, you must share its source under the same licence.
