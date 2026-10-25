# FM26 Analyst

**A companion app for Football Manager 26.** It watches your save while you play, and builds a history of your squad:
- **every match:** ratings and stats;
- **over time:** attributes, CA and development;
- **fitness:** condition, sharpness and injuries.

From that history you get a dashboard, a recommended XI for the next match, and an AI assistant manager you can ask about your squad. It also works on your phone.

![Overview](docs/screenshots/01-overview.png)

- 🔄 **Automatic.** It captures by itself after each of your matches. You never type anything in.
- 🔒 **Read-only.** It only *reads* the game's memory, and never changes the game, your save or FM26's files.
- 💻 **Local.** Everything stays on your PC. Nothing leaves it unless you set up the AI coach, and then only your squad summary goes to the provider you choose.

> Unofficial fan project, not affiliated with or endorsed by Sports Interactive or SEGA. For single-player saves only.

## Quick start
1. **Install [Python 3.10+](docs/guide/installation.md#1-install-python)**, e.g. `winget install Python.Python.3.12`.
2. **Download** the latest release from the [Releases page](https://github.com/lastrider04/FM26-Analyst/releases) (**Source code (zip)**). Extract it to a permanent folder such as `Documents\FM26-Analyst`.
3. **Double-click `install.bat`.** It installs everything and adds **FM26 Analyst** shortcuts.
4. **Start FM26, load your save, and open FM26 Analyst.** Choose your club on the Overview, then press **Capture**.

The full walkthrough is in [Installation](docs/guide/installation.md) and [Getting started](docs/guide/getting-started.md).

## Guide

| | Page | What's in it |
|---|---|---|
| 1 | **[Installation](docs/guide/installation.md)** | Requirements, installing Python, `install.bat`, command-line install, updating, uninstalling |
| 2 | **[Getting started](docs/guide/getting-started.md)** | First start, choosing your club, captures and auto-capture, the top bar, running in the background |
| 3 | **[Using the dashboard](docs/guide/dashboard.md)** | Overview and next-match picks, Players, player pages, Compare, Development, Per 90, Fixtures and match reports |
| 4 | **[AI coach](docs/guide/ai-coach.md)** | Asking questions, and setting up the ChatGPT plan, OpenAI, OpenRouter, Ollama or LM Studio; coach instructions; privacy |
| 5 | **[Phone app](docs/guide/phone.md)** | How it works, choosing a connection method, installing it on your phone, what a phone can do |
| | ↳ [Local network (IP and port)](docs/guide/phone-local-network.md) | On home Wi-Fi only: the simplest setup |
| | ↳ [Tailscale](docs/guide/phone-tailscale.md) | Anywhere, private, with HTTPS and no router changes. **Recommended.** |
| | ↳ [Reverse proxy](docs/guide/phone-reverse-proxy.md) | Your own domain via NGINX Proxy Manager, Caddy or nginx: DNS, port forwarding, Let's Encrypt |
| | ↳ [Cloudflare Tunnel](docs/guide/phone-cloudflare-tunnel.md) | Your own domain with no open ports |
| | ↳ [Signing in and pairing](docs/guide/phone-sign-in.md) | Password, Google sign-in (OAuth client setup), pairing codes, managing devices |
| | ↳ [Windows Firewall](docs/guide/firewall.md) | Which rule you need for each method, adding, checking and removing it |
| 6 | **[Game snapshots and backups](docs/guide/game-snapshots.md)** | Separate histories per save or job, new games, backups, restoring, moving to a new PC |
| 7 | **[Troubleshooting](docs/guide/troubleshooting.md)** | Install, capture, game-update banner, data, coach and phone problems |
| 8 | **[Privacy, security and your data](docs/guide/privacy-and-data.md)** | What's read, what's sent where, the `data\` folder, how secrets are stored |
| 9 | **[For developers](docs/guide/development.md)** | Running from source, tests, code layout, game builds, contributing |

## Features at a glance

<table>
<tr>
<td width="50%"><a href="docs/guide/dashboard.md#player-page"><img src="docs/screenshots/03-player.png" alt="Player page"></a><br><b>Player pages</b>: attribute radar, CA history, match log, role profile, similar players.</td>
<td width="50%"><a href="docs/guide/dashboard.md#development"><img src="docs/screenshots/05-development.png" alt="Development"></a><br><b>Development</b>: who's improving or declining, by CA and attribute group.</td>
</tr>
<tr>
<td><a href="docs/guide/dashboard.md#per-90"><img src="docs/screenshots/06-per90.png" alt="Per 90"></a><br><b>Per 90 and role scores</b>: goalkeeping, chance creation, goal threat, finishing, defensive work, ball security.</td>
<td><a href="docs/guide/dashboard.md#fixtures-and-match-reports"><img src="docs/screenshots/08-match.png" alt="Match report"></a><br><b>Match reports</b>: every player's stats from every captured match.</td>
</tr>
<tr>
<td><a href="docs/guide/ai-coach.md"><img src="docs/screenshots/09-coach.png" alt="AI coach"></a><br><b>AI coach</b>: ask who to rest, rotate or develop. It answers from your data.</td>
<td><a href="docs/guide/phone.md"><img src="docs/screenshots/20-phone-overview.png" width="180" alt="Phone app"> <img src="docs/screenshots/22-phone-coach.png" width="180" alt="Phone coach"></a><br><b>Phone app</b>: installable, works anywhere, with two-step pairing.</td>
</tr>
</table>

## Requirements
- **Windows** 10 or 11.
- **Football Manager 26** (PC), game build `FM26.fm26-rel-prod.2329565`. After a game patch, the app tells you if it needs an update; see [Troubleshooting](docs/guide/troubleshooting.md#fm26-has-been-updated-banner).
- **Python** 3.10 or newer.
- **Edge or Chrome** (Edge comes with Windows).

## Help and feedback
- **Problems:** see [Troubleshooting](docs/guide/troubleshooting.md), or [open an issue](https://github.com/lastrider04/FM26-Analyst/issues).
- **Ideas and pull requests** are welcome; see [For developers](docs/guide/development.md).

## Licence
[GPL-3.0](LICENSE). You're free to use, change and share FM26 Analyst. If you share a modified version, you must share its source under the same licence.
