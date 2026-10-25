# Windows Firewall for the phone app

[← Phone app](phone.md) · [Guide index](../../README.md#guide)

Windows Firewall blocks incoming connections by default. Whether you need a rule depends on how your phone connects:

| Connection method | Firewall rule needed? | Rule should allow |
|---|---|---|
| [Local network](phone-local-network.md) | **Yes** | Your local network (`LocalSubnet`) |
| [Reverse proxy](phone-reverse-proxy.md) on **another** machine | **Yes** | Only the proxy machine's IP |
| Reverse proxy on **this** PC | No | – |
| [Tailscale](phone-tailscale.md) | No (Tailscale Serve connects locally) | – |
| [Cloudflare Tunnel](phone-cloudflare-tunnel.md) | No (`cloudflared` connects locally) | – |

The desktop dashboard (port 8765) never needs a rule. It only listens on `127.0.0.1`.

## The "allow access" prompt
The first time you turn on phone access, Windows may show *"Windows Defender Firewall has blocked some features of Python"*:
- **Local network or a proxy on another machine:** tick **Private networks** only, then **Allow access**. It's still better to add the specific rule below.
- **Tailscale, Cloudflare Tunnel or a proxy on the same PC:** click **Cancel**. Nothing from outside the PC needs to reach it.

## Adding the rule
Open **PowerShell as administrator** (right-click Start, then **Terminal (Admin)**). Run **one** of these:

**Local network:**
```powershell
New-NetFirewallRule -DisplayName "FM26 Analyst phone" -Direction Inbound -Protocol TCP -LocalPort 8766 -RemoteAddress LocalSubnet -Profile Private -Action Allow
```

**Reverse proxy on another machine** (put in your proxy's IP):
```powershell
New-NetFirewallRule -DisplayName "FM26 Analyst phone" -Direction Inbound -Protocol TCP -LocalPort 8766 -RemoteAddress 192.168.1.20 -Action Allow
```

If you changed the **Port** in Settings › Phone, use that number instead of 8766.

### Using the Windows interface instead
1. Press **Win + R**, type `wf.msc`, and press Enter.
2. **Inbound Rules › New Rule… › Port › TCP**, specific local port **8766**, then **Allow the connection**.
3. **Profile:** tick **Private**. Also tick *Domain* and *Public* only if your network is set as one of those.
4. **Name:** `FM26 Analyst phone`, then **Finish**.
5. *(Optional, recommended)* Open the new rule's **Properties › Scope**. Under *Remote IP address*, choose **These IP addresses** and add your proxy's IP, or *Local subnet*.

## Checking it works
In PowerShell:
```powershell
Get-NetFirewallRule -DisplayName "FM26 Analyst phone" | Get-NetFirewallAddressFilter
```
```powershell
Get-NetTCPConnection -LocalPort 8766 -State Listen
```
- **First command:** shows which addresses the rule allows.
- **Second command:** shows that the app is listening. If it shows nothing, turn on **Allow phone access** in Settings › Phone.

From another device on your network, open `http://<PC IP>:8766/login`. For a proxy setup, run `curl -I http://<PC IP>:8766/login` on the proxy machine. You should get the sign-in page, or `200 OK`.

**Network profile:** if your network shows as **Public** in *Settings › Network & internet*, Windows applies stricter rules, and a *Private*-only rule won't apply. Switch your home network to **Private**.

## Removing the rule
```powershell
Remove-NetFirewallRule -DisplayName "FM26 Analyst phone"
```

---
[← Signing in and pairing](phone-sign-in.md) · [Phone app](phone.md) · [Guide index](../../README.md#guide)
