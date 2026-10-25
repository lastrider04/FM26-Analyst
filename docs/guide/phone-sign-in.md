# Signing in and pairing a phone

[← Phone app](phone.md) · [Guide index](../../README.md#guide)

A phone (or tablet, or another computer) gets into FM26 Analyst only after **pairing**, and pairing takes **two steps**:

1. **Sign in:** with **Google** (only accounts you allow) or the **password** you set.
2. **Enter the pairing code** shown on your PC. Scan its QR code, or type it.

Neither works alone. A stolen password is no use without a fresh code from your PC, and someone who photographs the code still needs your sign-in. The two steps can be done in either order, within 15 minutes.

![Phone sign-in](../screenshots/23-phone-sign-in.png)

- [Password](#password)
- [Google sign-in](#google-sign-in)
- [Pairing a device](#pairing-a-device)
- [Managing devices](#managing-devices)
- [How it's protected](#how-its-protected)

You need **at least one** of the two sign-in methods before the PC will hand out pairing codes.

## Password
The simplest option, and the only one for [local network](phone-local-network.md) use, where there's no HTTPS.

1. In **Settings › Phone › Password (backup)**, enter a **username** and a **password** of at least 10 characters. A passphrase like `three random football words` is ideal.
2. Click **Save**. It shows *✓ Set for …*.

How it's stored and protected:
- **Storage:** only a scrypt hash of the password is stored, in `data\config.json`, never the password itself.
- **Wrong attempts:** after 5 wrong passwords or codes in 15 minutes, password and code sign-in pause for everyone until the 15 minutes are up. Google sign-in isn't affected.
- **Changing it:** enter a new password and **Save**. **Remove password** turns password sign-in off. Devices that are already paired stay paired either way.

## Google sign-in
Needs an **HTTPS public address**: [Tailscale](phone-tailscale.md), a [reverse proxy](phone-reverse-proxy.md) or a [Cloudflare Tunnel](phone-cloudflare-tunnel.md). First set the **Public address** in **Settings › Phone**; the **Redirect URI** box then shows the exact address you'll need below.

### Create a Google OAuth client (one-off, about 5 minutes)
1. Go to [Google Cloud Console](https://console.cloud.google.com/) and sign in. Create a project, e.g. *FM26 Analyst* (top bar › project picker › **New project**).
2. **OAuth consent screen:** open **APIs & Services › OAuth consent screen** (in newer layouts, *Google Auth Platform › Branding*).
   - **App name:** `FM26 Analyst`, plus your email as the support and developer contact.
   - **Audience / User type:** **External**.
   - **Test users:** add the Google account(s) you'll sign in with. Leaving the app in **Testing** is fine; it never needs Google's review for personal use.
3. **Create the client:** open **APIs & Services › Credentials › Create credentials › OAuth client ID** (or *Google Auth Platform › Clients › Create client*).
   - **Application type:** **Web application**.
   - **Name:** anything, e.g. `FM26 Analyst phone`.
   - **Authorized JavaScript origins:** your public address, e.g. `https://fm26.example.com`, with no trailing slash.
   - **Authorized redirect URIs:** the **Redirect URI** from Settings › Phone, e.g. `https://fm26.example.com/auth/google/callback`.
   - Click **Create**.
4. Copy the **Client ID** (ends in `.apps.googleusercontent.com`) and the **Client secret** (starts with `GOCSPX-`).

### Connect it to FM26 Analyst
In **Settings › Phone › Google sign-in**:
1. Paste the **Client ID** and **Client secret**.
2. **Allowed Google accounts:** your Gmail address. Separate several with commas. Only these accounts can sign in, even if others get past Google.
3. Click **Save**. It shows *✓ Ready*.

The client secret is encrypted with Windows DPAPI. **Remove** clears the Google settings; paired devices stay paired.

### How Google sign-in works on the phone
1. Tap **Sign in with Google**. Google opens in a new window.
2. Sign in, then come back to FM26 Analyst. It finishes by itself, even if Google sent you back to a different browser (common with installed iPhone apps).
3. Enter the pairing code.

### Google problems

| Error | Fix |
|---|---|
| *redirect_uri_mismatch* | The redirect URI in Google doesn't exactly match the one in Settings › Phone. Check https, the domain and the path, with no trailing slash. |
| *Access blocked: app is in testing* / *403 access_denied* | Add your account under **Test users** on the OAuth consent screen. |
| *"… isn't allowed to use this dashboard"* | Add that email to **Allowed Google accounts**. |
| *"Google didn't accept the sign-in"* | The client ID or secret is wrong. Paste both again. |
| Google sign-in button missing | Google isn't fully set up. You need the public address (https), client ID, secret and at least one allowed account. |

## Pairing a device
1. **On the PC:** in **Settings › Phone › Pair a device**, click **Show pairing code**. It shows:
   - a **QR code** that opens the pairing page with the code filled in;
   - the code itself, e.g. `K7QF-2M9P`, to type instead.

   It works **once**, for **10 minutes**.
2. **On the phone:**
   - open your address (or scan the QR code);
   - **name the device** (e.g. *My iPhone*);
   - **sign in** (step 1);
   - **enter the code** (step 2).

   You can do the two steps in either order.
3. You're in. The device stays signed in until you revoke it, or it's unused for 180 days.

> **Installed iPhone app:** the home-screen app has its own storage, separate from Safari. Pair **inside the installed app**, and type the code, because scanning a QR code opens Safari instead.

## Managing devices
**Settings › Phone › Paired devices** lists every device: its name, how it signed in (*Google + pairing code*, *password + pairing code*), when it was paired and when it was last used.

- **Revoke:** signs that device out immediately. Do this for a lost phone, or one you no longer use.
- **On the phone:** the **Device** tab (where Settings is on the PC) has **Sign out**, which also clears its offline copy.

## How it's protected
- **A separate listener:** phones use their own locked-down listener (port 8766). Even paired, they can't reach Settings, snapshots, sign-ins, backups or Quit.
- **Device tokens:** each paired device holds a random token in an HttpOnly cookie. The PC stores only a SHA-256 hash of it, in `data\devices.json`.
- **Cross-site protection:** changes from the phone must carry the app's own request header and come from your address, so other websites can't trigger actions.
- **Address restriction:** **Only accept connections from** limits who can connect at all, e.g. just your proxy.

---
[← Cloudflare Tunnel](phone-cloudflare-tunnel.md) · [Phone app](phone.md) · [Windows Firewall →](firewall.md)
