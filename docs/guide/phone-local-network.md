# Phone app on your local network (IP and port)

[← Phone app](phone.md) · [Guide index](../../README.md#guide)

The simplest setup: your phone opens `http://<your PC's IP>:8766` while it's on the same Wi-Fi as your PC. There's no account, domain or extra software.

| ✓ | ✗ |
|---|---|
| Works in a few minutes | Only at home, on the same network |
| Nothing exposed to the internet | Plain `http://`: no app install, no offline copy, and no Google sign-in, so you use a password |

Want it outside the house, or installable as an app? Use [Tailscale](phone-tailscale.md) instead. It's nearly as quick to set up.

## 1. Give your PC a fixed IP address
Your phone needs an address for the PC that doesn't change.

1. **Find the PC's current IP:** look at the **Setup guide** in **Settings › Phone**, which shows it (e.g. `192.168.1.10`). Or run `ipconfig` in a terminal and read the *IPv4 Address* of your Wi-Fi or Ethernet adapter.
2. **Reserve it in your router** so it never changes. In the router's admin page, look for **DHCP reservation**, *Address reservation* or *Static lease*, and reserve that IP for your PC. Every router is different; search for "*your router model* DHCP reservation" if you can't find it.

## 2. Make sure your network is "Private"
Windows treats *Public* networks more strictly.

1. Open **Settings › Network & internet**, then **Wi-Fi** or **Ethernet**, then your network.
2. Set **Network profile type** to **Private network**.

## 3. Allow the port through Windows Firewall
Open **PowerShell as administrator** (right-click Start, then *Terminal (Admin)*) and run:
```powershell
New-NetFirewallRule -DisplayName "FM26 Analyst phone" -Direction Inbound -Protocol TCP -LocalPort 8766 -RemoteAddress LocalSubnet -Profile Private -Action Allow
```
`LocalSubnet` means only devices on your own network can connect. More detail, and how to undo it: [Windows Firewall](firewall.md).

> When you turn on phone access, Windows may also ask whether Python can use the network. Allow it for **Private networks** only.

## 4. Turn on phone access
In **Settings › Phone**:

1. Leave **Public address** **blank**. The pairing QR code then uses your PC's IP and port.
2. Leave **Only accept connections from** blank, or put your network's devices there if you want to limit it.
3. Switch on **Allow phone access**, and check it says *Listening on 0.0.0.0:8766*.

## 5. Set a password
Google sign-in needs an HTTPS address, so on the local network you sign in with a password. Under **Password (backup)**, set a username and a password of at least 10 characters, then click **Save**. See [Signing in and pairing](phone-sign-in.md#password).

## 6. Pair your phone
1. On the PC, click **Show pairing code**.
2. On the phone (on the same Wi-Fi), scan the QR code with the camera, or open `http://<PC IP>:8766` and type the code.
3. Sign in with your username and password.

Done. Bookmark the page, or add it to your home screen as a shortcut.

## Checking it works
- **From the PC itself:** open `http://<PC IP>:8766/login` in a browser. It should show the sign-in page.
- **From the phone:**
  - **The sign-in page opens:** it works.
  - **It times out:** check the [firewall rule](firewall.md#checking-it-works), that the network is *Private*, and that the phone isn't on a guest Wi-Fi network (guest networks usually can't see other devices).
  - **"Not allowed from this address":** clear **Only accept connections from**.

## Security notes
- **Unencrypted:** plain `http://` traffic on your Wi-Fi isn't encrypted. That's fine on a home network you trust, but don't use it on public Wi-Fi.
- **No internet exposure:** keep the firewall rule at `LocalSubnet`, and don't forward port 8766 on your router.
- **Sign-in is still needed:** every device still has to sign in and pair, even on your own network.

---
[← Phone app](phone.md) · [Tailscale →](phone-tailscale.md)
