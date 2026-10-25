# Privacy, security and your data

[← Troubleshooting](troubleshooting.md) · [Guide index](../../README.md#guide)

## What the app does with the game
- **Read-only:** FM26 Analyst opens the FM26 process with **read-only** access (`PROCESS_VM_READ`) and reads values from memory, like an external scouting tool.
- **Nothing is changed:** it never writes to the game's memory, injects code, or changes your save or any FM26 files.
- **Single-player only:** use it with single-player saves only.

## What stays on your PC
Everything. The app has no account, no server of its own, and no telemetry. It only connects to:
- **The AI provider you choose,** when you ask the coach a question. It sends a summary of your squad, the page you're viewing and your question. With Ollama or LM Studio, nothing leaves your PC. Click **ⓘ** in the coach to see exactly what's sent.
- **OpenAI's sign-in,** if you use your ChatGPT plan.
- **Google's sign-in,** if you set up Google sign-in for the phone.
- **cdnjs.cloudflare.com,** which serves the open-source chart and QR code libraries the dashboard uses.

## The `data\` folder
Everything personal lives in `data\` inside the app folder. It's never part of the app's files or of updates.

| Path | Contents |
|---|---|
| `data\fm_analyst.db` | Your first game snapshot's history (SQLite database) |
| `data\careers\<n>\` | Later game snapshots: database and capture files |
| `data\careers.json` | The list of game snapshots, and which one is in use |
| `data\snapshots\` | A raw copy of each capture (JSON) |
| `data\backups\save-<n>\` | Automatic database backups, newest 14 |
| `data\chats\save-<n>\` | Saved coach conversations |
| `data\coach_prompt.md` | Your edited coach instructions, if you changed them |
| `data\config.json` | Settings. Secrets are encrypted (see below). |
| `data\chatgpt.json` | ChatGPT sign-in tokens, encrypted |
| `data\devices.json` | Paired phones: names, dates and token **hashes** only |
| `data\app.log` | The app's log, with no passwords, keys or tokens |
| `data\app-window\` | The app window's browser profile |

To start completely fresh, quit the app and delete `data\`.

## How secrets are stored

| Secret | How it's stored |
|---|---|
| AI provider API key | Encrypted with Windows DPAPI, tied to your Windows account |
| ChatGPT sign-in tokens | Encrypted with Windows DPAPI |
| Google client secret | Encrypted with Windows DPAPI |
| Phone password | Never stored. Only a salted scrypt hash. |
| Phone device tokens | Never stored. Only SHA-256 hashes; each phone keeps its own token in an HttpOnly cookie. |

DPAPI means only your Windows account on this PC can decrypt them. That's also why secrets need re-entering after [moving to a new PC](game-snapshots.md#moving-to-a-new-pc). Secrets are never shown again in Settings, and never written to the log.

## Security of the phone app
- **The desktop dashboard** listens only on `127.0.0.1:8765`, so it can't be reached from other devices.
- **The phone listener** (port 8766) is **off by default**. When it's on:
  - **Who gets in:** only paired devices. Pairing needs a sign-in **and** a one-time code from the PC ([details](phone-sign-in.md#how-its-protected)).
  - **What they can do:** paired devices can read the dashboard, use the coach, Capture and switch Auto, and nothing else. Settings, game snapshots, sign-ins, backups and Quit are always refused.
  - **Cross-site protection:** changes need the app's own request header from your own address, so other websites can't trigger them.
  - **Wrong attempts:** password and code sign-in pause after 5 wrong attempts in 15 minutes.
  - **Address restriction:** *Only accept connections from* can limit connections to your proxy or tunnel.
- **Recommendations:**
  - prefer [Tailscale](phone-tailscale.md) if you don't need public access;
  - never forward port 8766 directly to the internet;
  - revoke devices you no longer use.

---
[← Troubleshooting](troubleshooting.md) · [Guide index](../../README.md#guide) · Next: [For developers →](development.md)
