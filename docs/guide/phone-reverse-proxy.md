# Phone app through a reverse proxy

[← Phone app](phone.md) · [Guide index](../../README.md#guide)

With a reverse proxy, your phone opens your own domain over HTTPS, for example `https://fm26.example.com`, from any browser, anywhere. The proxy handles the HTTPS certificate and forwards requests to FM26 Analyst on your PC.

| ✓ | ✗ |
|---|---|
| Any browser, anywhere, nothing to install on the phone | You need a domain, a proxy and router port forwarding |
| Real HTTPS: installs as an app, offline copy, Google sign-in | Your proxy is reachable from the internet, so keep it updated |

This page uses **[NGINX Proxy Manager](https://nginxproxymanager.com)** (NPM), the **tested** setup. The [Caddy](#caddy) and [plain nginx](#plain-nginx) examples further down are untested suggestions. The proxy can run on the same PC or on another machine, such as a home server or Raspberry Pi.

```
Phone ──HTTPS──► your router :443 ──► proxy (e.g. 192.168.1.20) ──HTTP──► your PC 192.168.1.10:8766
```

- [1. Domain and DNS](#1-domain-and-dns)
- [2. Router port forwarding](#2-router-port-forwarding)
- [3. Firewall on the proxy machine](#3-firewall-on-the-proxy-machine)
- [4. Firewall on your PC](#4-firewall-on-your-pc)
- [5. NGINX Proxy Manager proxy host](#5-nginx-proxy-manager-proxy-host)
- [6. Settings in FM26 Analyst](#6-settings-in-fm26-analyst)
- [7. Sign-in and pairing](#7-sign-in-and-pairing)
- [Caddy](#caddy) · [Plain nginx](#plain-nginx)
- [Streaming coach answers](#streaming-coach-answers)
- [Home network problems](#home-network-problems)
- [Proxy problems](#proxy-problems)

## 1. Domain and DNS
1. **Domain:** you need a domain or subdomain, e.g. `fm26.example.com`. Any registrar works.
2. **DNS record:** at your DNS provider, create a record pointing it at your home's **public IP**. To find your public IP, search "what is my IP" from home.
   - an **A record**: `fm26 → <your public IP>`, or
   - a **CNAME** to a name that already points home, e.g. `fm26 → example.com`.
3. **If your home IP changes** (most home connections): use your DNS provider's dynamic DNS option, or a dynamic DNS service, to keep the record current.
4. **Cloudflare users:** set the record to **DNS only** (grey cloud) so Let's Encrypt can reach your proxy. Or try [Cloudflare Tunnel](phone-cloudflare-tunnel.md) instead (untested suggestion).

**Check:** `nslookup fm26.example.com 1.1.1.1` should return your public IP.

## 2. Router port forwarding
In your router's admin page, find **Port forwarding** (also called *Virtual server* or *NAT*) and forward these to the **proxy machine's** LAN IP:

| External port | To | Why |
|---|---|---|
| **443** (TCP) | proxy IP : 443 | HTTPS for your phone |
| **80** (TCP) | proxy IP : 80 | Let's Encrypt certificate checks, and redirecting http to https |

Give the proxy machine a fixed IP too (a DHCP reservation). **Don't** forward port 8766; only the proxy should reach FM26 Analyst.

## 3. Firewall on the proxy machine
If the proxy runs on Linux with **ufw**, allow web traffic in:
```bash
sudo ufw allow 80/tcp
```
```bash
sudo ufw allow 443/tcp
```

Notes:
- **NPM's admin page** is on port **81**; keep it closed to the internet.
- **Outgoing connections** to your PC are allowed by default. If you set ufw to deny outgoing traffic, also allow the proxy to reach the PC:
  ```bash
  sudo ufw allow out to 192.168.1.10 port 8766 proto tcp
  ```
- **NPM in Docker:** Docker publishes its ports past ufw, so the rules above mainly matter if NPM runs directly on the host.

## 4. Firewall on your PC
Allow **only the proxy machine** to reach port 8766. Run in **PowerShell as administrator**, using your proxy's IP:
```powershell
New-NetFirewallRule -DisplayName "FM26 Analyst phone" -Direction Inbound -Protocol TCP -LocalPort 8766 -RemoteAddress 192.168.1.20 -Action Allow
```
If the proxy runs **on the same PC**, you don't need a rule. Details: [Windows Firewall](firewall.md).

## 5. NGINX Proxy Manager proxy host
In NPM, go to **Hosts › Proxy Hosts › Add Proxy Host**.

**Details tab:**

| Field | Value |
|---|---|
| Domain Names | `fm26.example.com` |
| **Scheme** | **`http`**. The app speaks plain HTTP behind the proxy; `https` here causes errors. |
| Forward Hostname / IP | your PC's LAN IP, e.g. `192.168.1.10` (or `host.docker.internal` / the host IP if NPM runs in Docker on the same PC) |
| Forward Port | `8766` |
| Block Common Exploits | on |
| Websockets Support | not needed (on is harmless) |

**SSL tab:**
- **SSL Certificate:** *Request a new SSL Certificate* (Let's Encrypt).
- **Force SSL:** on. **HTTP/2 Support:** on.
- Agree to the Let's Encrypt terms and save. The certificate request needs ports 80 and 443 forwarded (step 2) and DNS pointing at your home (step 1).

**Advanced tab:** add this so coach answers stream word by word:
```nginx
proxy_buffering off;
```

Save. Opening `https://fm26.example.com` should now show the FM26 Analyst sign-in page, once phone access is on (next step).

## 6. Settings in FM26 Analyst
In **Settings › Phone**:

1. **Public address:** `https://fm26.example.com`.
2. **Only accept connections from:** your proxy's LAN IP, e.g. `192.168.1.20`. (Use `127.0.0.1, ::1` if the proxy runs on the same PC.)
3. **Allow phone access:** on. It should say *Listening on 0.0.0.0:8766*.

## 7. Sign-in and pairing
1. **Set up sign-in:** Google, a password, or both. See [Signing in and pairing](phone-sign-in.md). For Google, the redirect URI is `https://fm26.example.com/auth/google/callback`.
2. **Pair:** on the phone, open `https://fm26.example.com`, sign in, and enter the code from **Show pairing code** on the PC.
3. **Install:** add it to the home screen ([how](phone.md#installing-it-on-your-phone)).

## Caddy
> ⚠️ **Untested suggestion:** a standard Caddy setup that should work the same way, but it hasn't been tried with FM26 Analyst.

[Caddy](https://caddyserver.com) gets certificates by itself. In your `Caddyfile`:
```caddy
fm26.example.com {
    reverse_proxy 192.168.1.10:8766 {
        flush_interval -1
    }
}
```
`flush_interval -1` streams coach answers. Ports 80 and 443 must be forwarded to the Caddy machine, as above.

## Plain nginx
> ⚠️ **Untested suggestion:** the usual nginx equivalent of the NPM setup above, not tried with FM26 Analyst.

With a certificate from certbot (or similar):
```nginx
server {
    listen 443 ssl http2;
    server_name fm26.example.com;
    ssl_certificate     /etc/letsencrypt/live/fm26.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/fm26.example.com/privkey.pem;

    location / {
        proxy_pass http://192.168.1.10:8766;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;              # stream coach answers
        proxy_read_timeout 300s;          # long coach answers
    }
}
server { listen 80; server_name fm26.example.com; return 301 https://$host$request_uri; }
```

## Streaming coach answers
Coach answers stream as server-sent events. Most proxies hold back ("buffer") responses by default, so the answer appears all at once at the end. Turn buffering off:
- **NPM / nginx:** `proxy_buffering off;`
- **Caddy:** `flush_interval -1`

The app also sends `X-Accel-Buffering: no`, which nginx honours.

## Home network problems
**It works on mobile data but not on your home Wi-Fi.** At home, your phone looks up your domain, gets your **public** IP, and tries to go out and back in through your router. Many routers (including many ISP routers) don't support that loopback, called *NAT hairpinning*.

**Fix:** make your home network resolve the domain to the proxy's **LAN** IP:
- **Pi-hole:** *Local DNS › DNS Records*: `fm26.example.com → 192.168.1.20` (the **proxy's** IP, not the PC's).
- **AdGuard Home:** *Filters › DNS rewrites*.
- **Router:** some routers have a local DNS or hosts option.

Then flush the caches: in Pi-hole run `pihole restartdns`; on Windows run `ipconfig /flushdns`; on the phone, toggle Wi-Fi off and on.

Other symptoms:
- **"DNS address could not be found" only at home:** your local DNS server cached the name from before you created it. Flush its cache, or add the local record above.
- **"Refused to connect" at home after adding a local record:** the record points at the wrong machine. It must be the **proxy's** IP, since that's where port 443 is.

## Proxy problems

| What you see | Cause | Fix |
|---|---|---|
| NPM *"Internal Error"* when saving with SSL | Let's Encrypt couldn't reach your proxy | Check DNS (step 1), forwarding of ports **80** and 443 (step 2), and ufw (step 3). The NPM log (`/data/logs/letsencrypt.log`) has the details. |
| *502 Bad Gateway* | The proxy can't reach the PC | Is phone access on? Check the PC firewall rule (step 4), the forward IP and port, and **Scheme = http**. From the proxy machine, `curl -I http://192.168.1.10:8766/login` should return `200`. |
| *Internal error / 500* and the app log shows `Invalid HTTP request received` | The proxy sends HTTPS to the app | Set the proxy host **Scheme** to `http`. |
| *"Not allowed from this address"* | **Only accept connections from** doesn't match the proxy's IP | Set it to the IP the proxy connects from, or clear it to test. NPM in Docker may connect from its Docker host's IP. |
| Coach answers arrive all at once | Buffering | See [Streaming coach answers](#streaming-coach-answers). |

---
[← Tailscale](phone-tailscale.md) · [Phone app](phone.md) · [Cloudflare Tunnel →](phone-cloudflare-tunnel.md)
