# Phone app through Cloudflare Tunnel (untested suggestion)

[← Phone app](phone.md) · [Guide index](../../README.md#guide)

> ⚠️ **Untested suggestion.** This setup hasn't been tested with FM26 Analyst yet. It's written from how Cloudflare Tunnel normally works, so treat it as a starting point; the commands and dashboard menus may differ slightly. The tested routes are the [local network](phone-local-network.md) and a [reverse proxy with NGINX Proxy Manager](phone-reverse-proxy.md). If you try this, please [report how it went](https://github.com/lastrider04/FM26-Analyst/issues).

[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) gives FM26 Analyst a public HTTPS address on your domain without opening any ports on your router. A small program on your PC (`cloudflared`) connects out to Cloudflare, and Cloudflare passes requests back through that connection.

| ✓ | ✗ |
|---|---|
| Real HTTPS, any browser, anywhere | You need a domain whose DNS is on Cloudflare (the free plan is fine) |
| No router port forwarding, no proxy server | Traffic passes through Cloudflare |
| Optional extra login wall with Cloudflare Access | |

## 1. Add your domain to Cloudflare
If your domain isn't on Cloudflare yet:
1. Sign up at [cloudflare.com](https://dash.cloudflare.com/sign-up) and add your domain.
2. Change the domain's nameservers at your registrar to the two Cloudflare gives you.
3. Wait until Cloudflare shows the domain as **Active**.

## 2. Create the tunnel
1. In the Cloudflare dashboard, open **Zero Trust**, then **Networks › Tunnels** (it may be under *Access* in older layouts), and click **Create a tunnel**.
2. Choose **Cloudflared**, and name it, e.g. `fm26-pc`.
3. Under **Install and run a connector**, choose **Windows**, and copy the command it shows. It looks like `cloudflared.exe service install <long token>`.
4. Install `cloudflared` on the PC. Either run `winget install Cloudflare.cloudflared`, or download it from the page. Then run the copied command in **PowerShell as administrator**. This installs it as a Windows service, so it starts with your PC.
5. Back in the dashboard, the connector should show as **Healthy**. Click **Next**.

## 3. Route your subdomain to FM26 Analyst
Add a **Public hostname** (also called a *published application route*):

| Field | Value |
|---|---|
| Subdomain | `fm26` |
| Domain | `example.com` |
| Service type | **HTTP** |
| URL | `localhost:8766` |

Save. Cloudflare creates the DNS record and certificate for `https://fm26.example.com` by itself.

## 4. Settings in FM26 Analyst
In **Settings › Phone**:

1. **Public address:** `https://fm26.example.com`.
2. **Only accept connections from:** `127.0.0.1, ::1`. `cloudflared` connects from the PC itself, so this blocks anything else on your network.
3. **Allow phone access:** on.

**No firewall rule is needed**, because `cloudflared` connects locally. If Windows asks whether Python can use the network, you can choose **Cancel**.

## 5. Sign-in and pairing
1. Set up [Google sign-in](phone-sign-in.md#google-sign-in) with the redirect URI `https://fm26.example.com/auth/google/callback`, or a [password](phone-sign-in.md#password).
2. On the phone, open `https://fm26.example.com`, sign in, and enter the pairing code from the PC.
3. Add it to the home screen ([how](phone.md#installing-it-on-your-phone)).

## Optional: Cloudflare Access
For an extra layer, put a **Cloudflare Access** application in front of the hostname. Cloudflare then asks for your email (one-time code) before anything reaches your PC. FM26 Analyst's own pairing still applies after that.

> If you use Access, add a **Bypass** policy for the path `/auth/google/callback` if Google sign-in fails. Or simply use the password sign-in.

## Cloudflare problems

| Problem | What to do |
|---|---|
| *Error 1033* or "tunnel not found" | `cloudflared` isn't running on the PC. In *Services* (`services.msc`), start **Cloudflared agent**. |
| *502 Bad Gateway* | Phone access is off, or the service URL is wrong. It must be `HTTP` and `localhost:8766`. |
| *"Not allowed from this address"* | Clear **Only accept connections from**, then try `127.0.0.1, ::1` again. |
| Coach answers arrive all at once | Usually fine through Cloudflare. If not, check that nothing else (e.g. another proxy) is in between. |

---
[← Reverse proxy](phone-reverse-proxy.md) · [Phone app](phone.md) · [Signing in and pairing →](phone-sign-in.md)
