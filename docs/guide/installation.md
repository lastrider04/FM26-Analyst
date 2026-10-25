# Installation

[← Guide index](../../README.md#guide) · Next: [Getting started →](getting-started.md)

This page covers what you need, how to install FM26 Analyst, how to update it, and how to remove it.

- [What you need](#what-you-need)
- [1. Install Python](#1-install-python)
- [2. Download FM26 Analyst](#2-download-fm26-analyst)
- [3. Run the installer](#3-run-the-installer)
- [Installing with git or the command line](#installing-with-git-or-the-command-line)
- [Updating](#updating)
- [Uninstalling](#uninstalling)
- [Installation problems](#installation-problems)

## What you need

| | |
|---|---|
| **Windows** | Windows 10 or 11, 64-bit. |
| **Football Manager 26** | The PC version. The reader matches game build `FM26.fm26-rel-prod.2329565`. After a game patch, the app tells you if it doesn't recognise the new build; see [Troubleshooting](troubleshooting.md#fm26-has-been-updated-banner). |
| **Python** | 3.10 or newer. It's free; see below. The app runs in its own private Python environment, so it won't affect anything else you use Python for. |
| **A browser** | Microsoft Edge (built into Windows) or Google Chrome, used to show the app in its own window. |
| **Disk space** | About 200 MB for the app and its packages, plus a few MB per season of history. |

You don't need admin rights to install or run the app. You only need them for the optional firewall rule in the [phone app](phone.md) setup.

## 1. Install Python
If you already have Python 3.10 or newer, skip this step. The installer checks for you anyway.

**Option A: winget** (quickest). Open *Terminal* or *PowerShell* and run:
```powershell
winget install Python.Python.3.12
```

**Option B: python.org.** Download the installer from [python.org/downloads](https://www.python.org/downloads/). On the first screen, tick **"Add python.exe to PATH"**, then click *Install Now*.

Close and reopen any terminal windows afterwards so they pick up the new Python.

## 2. Download FM26 Analyst
1. Go to the [Releases page](https://github.com/lastrider04/FM26-Analyst/releases) and download **Source code (zip)** from the latest release.
2. **Before extracting:** right-click the zip, choose **Properties**, tick **Unblock** if you see it, then click **OK**. This stops Windows from showing a security warning for every file.
3. **Extract** the zip to a permanent folder, for example `Documents\FM26-Analyst`.

   > Your history (every capture, backup and setting) is saved **inside this folder**, in `data\`. Don't extract it to Downloads or a temporary folder you might clear out.

## 3. Run the installer
Double-click **`install.bat`** in the folder. It:

1. **Finds Python 3.10+:** it looks for the `py` launcher, then `python`. If neither is found, it explains how to install Python and stops.
2. **Creates a private environment** in `.venv\` inside the app folder.
3. **Installs the packages** listed in `requirements.txt`: FastAPI, Uvicorn, httpx, Pydantic, NumPy and PyJWT.
4. **Adds shortcuts:** **FM26 Analyst** on your Desktop and in the Start menu.
5. **Offers to start the app.**

It takes about a minute the first time.

> **"Windows protected your PC"?** That's SmartScreen being cautious about a downloaded script. Click **More info › Run anyway**. Unblocking the zip before extracting (step 2) usually prevents it.

You're ready. Continue with [Getting started](getting-started.md).

## Installing with git or the command line
```
git clone https://github.com/lastrider04/FM26-Analyst.git
cd FM26-Analyst
install.bat
```

Other ways to install and run it:

| Command | What it does |
|---|---|
| `install.bat --no-shortcuts` | Installs without adding shortcuts, for a portable setup. |
| `.venv\Scripts\pythonw.exe launch.py` | Starts the app the same way the shortcut does (background app and its own window). |
| `start.bat` | Runs the app in a console window, so you can watch its output, and opens your normal browser. Closing the console stops the app. |
| `.venv\Scripts\python.exe run.py --help` | Options for running the server directly (`--port`, `--no-hotkey`, `--no-browser`). |

To recreate missing shortcuts later:
```
powershell -ExecutionPolicy Bypass -File tools\make_shortcut.ps1
```

## Updating
1. Quit the app: **Settings › App › Quit FM26 Analyst**.
2. Download the new release zip, unblock it, and extract it **over your existing folder**, replacing the files when asked. Your `data\` folder isn't in the zip, so your history and settings are kept.
3. Run `install.bat` again to install any new packages.

If you installed with git: quit the app, run `git pull`, then run `install.bat`.

## Uninstalling
1. Quit the app: **Settings › App › Quit FM26 Analyst**.
2. *(Optional)* Keep a copy of the `data\` folder if you might want your history later.
3. Delete the app folder. That removes the app, its Python environment and your history.
4. Delete the **FM26 Analyst** shortcuts from the Desktop and from the Start menu (`%AppData%\Microsoft\Windows\Start Menu\Programs`).
5. If you set up the phone app:
   - remove the firewall rule (see [Firewall](firewall.md#removing-the-rule));
   - remove any proxy, Tailscale or tunnel configuration you created for it.

## Installation problems

| Problem | What to do |
|---|---|
| *"Python 3.10 or newer wasn't found"* | Install Python (step 1). If you just installed it, close and reopen the window, then run `install.bat` again. If you used python.org, check that *Add python.exe to PATH* was ticked, or reinstall with it ticked. |
| Typing `python` opens the Microsoft Store | That's a Windows placeholder, not real Python. Install Python as in step 1. |
| Package installation fails | Check your internet connection, then run `install.bat` again. If it keeps failing, delete the `.venv` folder and try again. |
| Nothing happens when you double-click the shortcut | Run `start.bat` to see error messages in a console window, and check `data\app.log`. |

See also [Troubleshooting](troubleshooting.md).

---
[← Guide index](../../README.md#guide) · Next: [Getting started →](getting-started.md)
