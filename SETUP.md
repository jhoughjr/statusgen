# Setup: from a bare box to hosting

This is the full stack under `statusgen` and any other static or dynamic site:

```
Internet ─▶ Cloudflare ─▶ cloudflared tunnel ─▶ nginx :80 ─▶ Dokku app containers
                          (dials OUT, so it works behind CGNAT / no public IP)
```

Everything below is CLI and works on any Cloudflare plan. It deliberately uses a
**locally-managed tunnel with a catch-all to nginx** ("dumb pipe"): the tunnel
forwards *everything* to nginx on :80, and **Dokku routes by hostname**. That
one decision avoids the dashboard entirely and sidesteps the two nastiest traps
(dashboard-managed ingress you can't edit from the CLI, and proxied *wildcard
DNS* being Enterprise-only).

Target OS: Debian/Ubuntu (Dokku's supported base). Works great on an ARM64 SBC
(Orange Pi / Raspberry Pi) or any VPS. You need: the host, a domain on
Cloudflare, and a Cloudflare login.

---

## 1. Host prep

```sh
sudo apt update && sudo apt -y upgrade
sudo apt -y install curl git
# give the box a stable name; you'll see it as the tunnel connector hostname
sudo hostnamectl set-hostname mybox
```

If it's headless, enable SSH now (`sudo systemctl enable --now ssh`) so you're
never locked out — and if it's a Mac being repurposed, turn on Remote Login.

---

## 2. Install Dokku

Check <https://dokku.com/docs/getting-started/installation/> for the current
version, then:

```sh
wget -NP . https://dokku.com/install/v0.35.20/bootstrap.sh
sudo DOKKU_TAG=v0.35.20 bash bootstrap.sh
```

Configure it:

```sh
# global domain — apps get <app>.<this> by default
sudo dokku domains:set-global example.net

# authorize the machine(s) that will `git push` deploys (paste your PUBLIC key)
cat ~/.ssh/id_ed25519.pub | sudo dokku ssh-keys:add laptop
```

Dokku installs nginx and listens on :80. `dokku` commands are also reachable
over SSH from your laptop: `ssh dokku@mybox apps:list`.

Sanity check:
```sh
dokku apps:create hello && ssh dokku@mybox apps:list
```

---

## 3. Install cloudflared

ARM64 (SBC) — grab the static binary; on x86 use `amd64`:

```sh
ARCH=arm64   # or amd64
curl -fsSL -o /tmp/cloudflared "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$ARCH"
sudo install /tmp/cloudflared /usr/local/bin/cloudflared
cloudflared --version
```

---

## 4. Create the tunnel (locally-managed, catch-all → nginx)

```sh
# browser auth → writes ~/.cloudflared/cert.pem (authorizes tunnel + DNS ops)
cloudflared tunnel login

# create the tunnel → prints a UUID and writes ~/.cloudflared/<UUID>.json (creds)
cloudflared tunnel create mybox
```

Write the config. The **catch-all `service: http://localhost:80`** is the whole
trick — every request the tunnel receives goes to nginx, and Dokku sorts it out
by `Host`:

```sh
sudo mkdir -p /etc/cloudflared
TUNNEL=<your-UUID>
sudo tee /etc/cloudflared/config.yml >/dev/null <<EOF
tunnel: $TUNNEL
credentials-file: /root/.cloudflared/$TUNNEL.json
ingress:
  - service: http://localhost:80
EOF
# move the creds where root's service can read them
sudo mkdir -p /root/.cloudflared
sudo cp ~/.cloudflared/$TUNNEL.json /root/.cloudflared/
```

> **Credentials file must be the `<UUID>.json`, never `cert.pem`.** `cert.pem`
> authorizes *managing* tunnels/DNS; `<UUID>.json` is what *runs* this tunnel.
> Mixing them up is the #1 cloudflared crash-loop.

Install it as a service so it survives reboots:

```sh
sudo cloudflared --config /etc/cloudflared/config.yml service install
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared     # want: "Registered tunnel connection"
```

---

## 5. Point DNS at the tunnel (per subdomain, CLI)

Proxied *wildcard* DNS is Enterprise-only, so add a record per hostname — one
line each, any plan:

```sh
cloudflared tunnel route dns $TUNNEL example.net
cloudflared tunnel route dns $TUNNEL status.example.net
```

Each creates a proxied CNAME → the tunnel. Because the tunnel's catch-all sends
everything to nginx, and Dokku has a vhost for the hostname, it just works — you
**never touch the Cloudflare dashboard**.

---

## 6. Prove it + make it durable

Deploy any app and hit it:
```sh
# from your laptop, in any Dokku-ready repo (has a Dockerfile/buildpack):
git remote add dokku dokku@mybox:hello && git push dokku main
ssh dokku@mybox domains:add hello hello.example.net
cloudflared tunnel route dns $TUNNEL hello.example.net
curl -I https://hello.example.net      # 200
```

Then the test that actually matters — **reboot and confirm it comes back
untouched:**
```sh
sudo reboot
# ~60s later:
curl -I https://hello.example.net
```

Durability checklist (each of these bit us once):
- **cloudflared**: `systemctl is-enabled cloudflared` → `enabled`.
- **Dokku app containers**: come back on their own (Dokku sets restart policies);
  any hand-run `docker run` containers you add → `--restart unless-stopped`.
- **DNS resolver**: if `/etc/resolv.conf` keeps resetting to a dead value on
  reboot (which breaks cloudflared reaching the edge), pin it:
  `sudo rm -f /etc/resolv.conf; printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' | sudo tee /etc/resolv.conf; sudo chattr +i /etc/resolv.conf`
- **One tunnel, one connector**: don't leave stray `cloudflare/cloudflared`
  containers running the same (or a deleted) tunnel — `docker ps | grep cloudflared`.

---

## 7. Now use statusgen

Infra's up. Point the tool at it and follow the [README](README.md) quickstart:

```sh
export DOKKU_HOST=mybox CF_TUNNEL=$TUNNEL BASE_DOMAIN=example.net
bin/new-site.sh status
cloudflared tunnel route dns $CF_TUNNEL status.example.net   # (run on the host)
bin/new-board.sh status-site demo "Demo" "…"
bin/update.sh status-site demo
```

---

## Troubleshooting (hard-won)

| Symptom | Cause → fix |
|---|---|
| cloudflared crash-loops instantly | `credentials-file` points at `cert.pem` → point it at `<UUID>.json`. |
| Tunnel connects but every site is 502 | Origin problem, not the tunnel. Check nginx: `curl -sI -H 'Host: your.host' http://localhost:80`. |
| A hostname 502s / empty reply | nginx has no vhost for it → the Dokku app/domain isn't set, or (Dokku) the app's nginx config isn't loaded. `dokku domains:report <app>`; ensure nginx includes `/home/dokku/*/nginx.conf`. |
| `dig` resolves but `curl`/browser says "can't resolve" | Stale negative DNS cache on your client. macOS: `sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder`. |
| Edited `config.yml` but ingress didn't change | The tunnel is **dashboard-managed**, so it ignores local `config.yml`. Either manage it in the dashboard, or recreate it locally-managed as in §4. |
| `route dns` says record exists | A leftover/wildcard record is shadowing it — delete that record in the DNS panel and re-run. |

## Scheduled refresh (keep "last status = current state")

A status push happens when something changes, so the board gets older between pushes. To keep it current, run `roost status "scheduled refresh"` on a timer from a machine that is always on. The Dokku host only builds and serves the site. It runs no collector. In the house, the mini runs the refresh every hour, and the opi only deploys.

The scheduled pusher needs:

1. Clones of `roost`, `statusgen`, the status site repo, and each repo that a collector measures.
2. `~/.roostrc`. The shell reads this file, so put quotes around a value with spaces, for example `ROOST_STATS_TEST_CMD="npm run test:coverage"`.
3. Its SSH key registered with Dokku (`sudo dokku ssh-keys:add <name>` on the host) and with your git forge for pulls.
4. On macOS, a LaunchAgent, for example `~/Library/LaunchAgents/<label>.plist` with `StartInterval` 3600 that runs `roost status "scheduled refresh"`. Make sure that its `PATH` includes your node and npm install, because launchd does not read your shell profile. Send `StandardOutPath` and `StandardErrorPath` to `~/Library/Logs/`.
5. On macOS, Remote Login on, and the machine's own key in its `authorized_keys`. macOS Local Network Privacy can stop a launchd agent from reaching the LAN, and the grant changes without warning. `roost status` runs itself again through `ssh localhost`, because a process that sshd starts is exempt. Without the loopback hop, the run continues in place, and the Dokku push can fail with `EHOSTUNREACH`.

More than one machine can push the site, for example the scheduled pusher and a laptop. `roost status` rebases the site on the `origin` mirror before it deploys. On a conflict, it adopts the mirror and regenerates the boards one time. If it cannot fetch the mirror, it stops and does not push. Then it force-pushes to the Dokku remote and pushes to `origin`, so every machine sees the current history. After the push, it reads Dokku's deploy output and fails if Dokku did not serve `status.<domain>`.

Optional: run `gh auth login` on the pusher to keep the GitHub-backed sections current. Without it, those collectors keep their last values, and the push continues.
