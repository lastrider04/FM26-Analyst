# For developers

[← Privacy and data](privacy-and-data.md) · [Guide index](../../README.md#guide)

FM26 Analyst is written in Python (3.10+) with a FastAPI backend and a plain JavaScript single-page front end. There's no build step.

## Running from source
```
git clone https://github.com/lastrider04/FM26-Analyst.git
cd FM26-Analyst
install.bat --no-shortcuts
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python.exe run.py            # dashboard + hotkey, opens your browser
```
`run.py --help` lists the options: `--port`, `--no-hotkey`, `--no-browser`. Front-end changes show up on a browser refresh; Python changes need a restart.

## Tests
```
.venv\Scripts\python -m pytest
```
The tests use synthetic data and never touch the game or your `data\` folder. Each test gets its own empty temporary data folder (see `tests/conftest.py`). Please keep it that way: add tests with your change.

## Code layout

| Folder | What's in it |
|---|---|
| `reader/` | The read-only memory reader: process access, the offset **profile** per game build (`reader/profiles/*.json`), players, fixtures, match stats, and the start-up self-check |
| `capture/` | Building and storing a snapshot, auto-capture timing, the global hotkey |
| `store/` | SQLite schema and migrations, game snapshots (`careers.py`), backups |
| `analytics/` | Form, development, per-90s, role scores, alerts, next-match recommendations |
| `llm/` | The AI coach: OpenAI-compatible client, ChatGPT plan sign-in, context builder, look-up tools, saved conversations, system prompt |
| `web/` | FastAPI app (`app.py`), the phone listener and sign-in (`remote.py`), static UI (`static/`) |
| `app_config.py`, `keystore.py` | Settings, and DPAPI encryption of secrets |
| `launch.py`, `run.py` | Desktop launcher (background server and app window), and the server entry point |

## How game builds are handled
- **Identifying the build:** each FM26 build is identified by a short hash of `game_plugin.dll`.
- **Offset profiles:** the offsets for that build live in `reader/profiles/fm26_<hash>.json`. The reader refuses to run against a build without a profile.
- **Self-check:** on every game start, `reader/selfcheck.py` checks that it reads sensible values (game date, club names, a full squad). If anything looks wrong, captures pause rather than storing bad data.

A game patch usually needs a new profile. If you can produce one for a new build, a pull request with the profile (and how you checked it) is very welcome.

## Contributing
- **Issues** and **pull requests** are welcome on [GitHub](https://github.com/lastrider04/FM26-Analyst).
- Keep the reader **read-only**. Changes that write to game memory won't be accepted.
- Never commit anything from `data\`. It's git-ignored.
- The project is licensed under [GPL-3.0](../../LICENSE).

---
[← Privacy and data](privacy-and-data.md) · [Guide index](../../README.md#guide)
