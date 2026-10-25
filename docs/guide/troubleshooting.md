# Troubleshooting

[← Game snapshots](game-snapshots.md) · [Guide index](../../README.md#guide)

**Start here:** the app's log is `data\app.log`. Running `start.bat` shows the app's output in a console window, which helps when something won't start.

- [Installing and starting](#installing-and-starting)
- [Game and capture](#game-and-capture)
- ["FM26 has been updated" banner](#fm26-has-been-updated-banner)
- [Data looks wrong](#data-looks-wrong)
- [AI coach](#ai-coach)
- [Phone app](#phone-app)
- [Getting help](#getting-help)

## Installing and starting

| Problem | What to do |
|---|---|
| *"Python 3.10 or newer wasn't found"* | Install Python ([Installation › step 1](installation.md#1-install-python)), close the window, then run `install.bat` again. |
| *"Windows protected your PC"* | Click **More info › Run anyway**, or unblock the zip before extracting ([how](installation.md#2-download-fm26-analyst)). |
| The shortcut does nothing | The app may already be running in the background: wait a few seconds. Otherwise run `start.bat` to see errors, and check `data\app.log`. |
| *"Address already in use"* / port 8765 | Another copy of the app is already running. Use **Settings › App › Quit**, or end `pythonw.exe` in Task Manager, then start it again. |
| The window opens as a normal browser tab | Edge or Chrome wasn't found, so it opened your default browser. Everything still works. |
| Shortcuts disappeared | Run `powershell -ExecutionPolicy Bypass -File tools\make_shortcut.ps1` in the app folder. |

## Game and capture

| Problem | What to do |
|---|---|
| *"Game not running"* although FM26 is open | Wait up to 15 seconds. The game must be fully started, not still on the splash screen. |
| No clubs found when choosing your club | FM26 must be running **with your save loaded**, not just the main menu. |
| Capture button is greyed out | The game isn't running, you haven't chosen a club yet, or the reader self-check failed (see the banner). |
| Auto-capture didn't capture after a match | Check the **Auto** switch is on and hover over it to see what it's waiting for. It captures about 2½ game hours after kick-off, so keep the game running a little past full time, or press **Capture**. |
| The hotkey does nothing | Another program may be using Ctrl+Alt+S. Change it in **Settings › Capture** and restart the app. |
| A capture says "failed" | Read the message. A capture taken while the game is loading or saving can fail; try again a moment later. If it keeps failing, check `data\app.log`. |

## "FM26 has been updated" banner
Each time FM26 starts, the app checks that it can read this game build. If the game has been patched since this version of FM26 Analyst was made, the memory layout can change:

- **What happens:** captures and auto-capture **pause**, so no wrong data is stored. Your history and the dashboard keep working.
- **"has been updated" (unknown build):** this game build has no reader profile yet. Check the [Releases page](https://github.com/lastrider04/FM26-Analyst/releases) for an update, or [open an issue](https://github.com/lastrider04/FM26-Analyst/issues) with your game version (from the FM26 main menu).
- **"reader doesn't match":** the build is recognised, but the self-check found values that don't look right. Click **Check again** once your save has fully loaded. If it still fails, open an issue, and include the *Self-check details* shown in the banner.

## Data looks wrong

| Problem | What to do |
|---|---|
| A match is missing its player stats | Capture shortly after the match, while the game still has the match in memory. Matches from before your first capture don't have per-match stats. |
| Development shows nothing | It needs two captures some game time apart. Pick a longer period at the top of the page. |
| Per 90 is empty for a player | Players need 180+ minutes in captured matches. |
| A different save's players appeared | The app should have created a new snapshot by itself. If it didn't, use **Settings › Game snapshots** ([guide](game-snapshots.md)). |
| Condition values differ slightly from FM | The app shows the game's stored values. FM's screens round them, and some scouting tools show a blend of condition and match fitness. |

## AI coach
See [AI coach › Coach problems](ai-coach.md#coach-problems).

## Phone app
See [Phone app › Phone problems](phone.md#phone-problems), and the page for your connection method:
- [Local network](phone-local-network.md#checking-it-works)
- [Tailscale](phone-tailscale.md#tailscale-problems)
- [Reverse proxy](phone-reverse-proxy.md#proxy-problems)
- [Cloudflare Tunnel](phone-cloudflare-tunnel.md#cloudflare-problems)

## Getting help
[Open an issue](https://github.com/lastrider04/FM26-Analyst/issues) with:
- your FM26 version (main menu) and Windows version;
- what you did, and what you expected;
- the relevant lines from `data\app.log`.

The log never contains passwords, keys or tokens, but check it before posting anyway.

---
[← Game snapshots](game-snapshots.md) · [Guide index](../../README.md#guide) · Next: [Privacy and data →](privacy-and-data.md)
