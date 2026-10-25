# Phone app with Tailscale (untested suggestion)

[← Phone app](phone.md) · [Guide index](../../README.md#guide)

> ⚠️ **Untested suggestion.** This setup hasn't been tested with FM26 Analyst yet. It's written from how Tailscale normally works, so treat it as a starting point; the commands and dashboard menus may differ slightly. The tested routes are the [local network](phone-local-network.md) and a [reverse proxy with NGINX Proxy Manager](phone-reverse-proxy.md). If you try this, please [report how it went](https://github.com/lastrider04/FM26-Analyst/issues).

[Tailscale](https://tailscale.com) connects your own devices into a private network (a *tailnet*) that works anywhere: home Wi-Fi, mobile data, or someone else's Wi-Fi. With **Tailscale Serve**, your PC gets a real HTTPS address such as `https://my-pc.tail1234.ts.net` that only your devices can open.

| ✓ | ✗ |
|---|---|
| Works anywhere | The phone needs the Tailscale app, connected |
| Real HTTPS: installs as an app, offline copy | Only devices signed in to your tailnet can open it |
| Nothing exposed to the internet; no router or domain setup | |
| Free for personal use | |

## 1. Install Tailscale on the PC and the phone
1. **PC:** install Tailscale from [tailscale.com/download](https://tailscale.com/download) and sign in. A Google, Microsoft, Apple or GitHub account works.
2. **Phone:** install **Tailscale** from the App Store or Google Play, and sign in with the **same account**.
3. **Check:** both devices should appear in the [Tailscale admin console › Machines](https://login.tailscale.com/admin/machines).

## 2. Turn on HTTPS for your tailnet
In the admin console, open **[DNS](https://login.tailscale.com/admin/dns)**:
1. Make sure **MagicDNS** is enabled. It is by default.
2. Under **HTTPS Certificates**, click **Enable HTTPS**.

## 3. Serve FM26 Analyst on your tailnet
First, in FM26 Analyst's **Settings › Phone**, switch on **Allow phone access**. It should say *Listening on 0.0.0.0:8766*.

Then, on the PC, open a terminal and run:
```powershell
tailscale serve --bg 8766
```
Tailscale prints your HTTPS address, for example `https://my-pc.tail1234.ts.net`. The first request can take a few seconds while Tailscale gets the certificate.
- **Status:** `tailscale serve status` shows what's being served.
- **Stopping:** `tailscale serve reset` stops serving.
- **Restarts:** the `--bg` setting is remembered across restarts.

> Older Tailscale versions use a different syntax (`tailscale serve https / http://127.0.0.1:8766`). Update Tailscale if the command above isn't recognised.

## 4. Point FM26 Analyst at the Tailscale address
In **Settings › Phone**:

1. **Public address:** your Tailscale address, e.g. `https://my-pc.tail1234.ts.net`. Click **Save**.
2. **Only accept connections from:** `127.0.0.1, ::1`.

   Tailscale Serve passes connections on from the PC itself, so this blocks anything else on your network from reaching the phone listener directly. If the phone then gets *"Not allowed from this address"*, clear the field and save.

**No firewall rule is needed.** Tailscale Serve connects locally on the PC. If Windows asks whether Python can use the network, you can choose **Cancel**.

## 5. Set up sign-in and pair
1. Set a **password** (simplest), or [Google sign-in](phone-sign-in.md#google-sign-in) with your `ts.net` address as the redirect URI. See [Signing in and pairing](phone-sign-in.md).
2. With Tailscale connected on the phone, open your `https://…ts.net` address, sign in, and enter the pairing code from **Show pairing code** on the PC.
3. **Install it:** iPhone **Share › Add to Home Screen**, Android **⋮ › Install app**.

## Tips
- **The phone needs Tailscale connected** to reach the app. On iPhone, turn on *VPN On Demand* in the Tailscale app so it connects by itself.
- **Your PC's name** is in the address. Rename the machine in the admin console *before* serving if you want a nicer one.
- **Tailscale Funnel** (`tailscale funnel`) would make the address public on the internet. You don't need it, and it's safer not to use it.

## Tailscale problems

| Problem | What to do |
|---|---|
| The address doesn't open on the phone | Is Tailscale connected on the phone (VPN icon)? Is the PC online in the admin console? Run `tailscale serve status` on the PC. |
| Certificate or HTTPS error | HTTPS certificates aren't enabled in the admin console (step 2), or the first certificate is still being issued. Wait a minute. |
| *"Not allowed from this address"* | Clear **Only accept connections from** in Settings › Phone. |
| *502 Bad Gateway* | Phone access is off, or on another port. Check *Listening on … :8766* in Settings › Phone. |

---
[← Local network](phone-local-network.md) · [Phone app](phone.md) · [Reverse proxy →](phone-reverse-proxy.md)
