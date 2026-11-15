# Deploying Pocket Agent 24/7

The bot is one process that **long-polls** Telegram (it asks Telegram for new
messages, so it needs no public URL, domain or open port). It needs:

- an always-on machine with **at least 1 GB RAM** (Whisper uses about 500 MB),
- a **persistent disk** for `data/` (SQLite DB, run logs, backups, Whisper cache).

> Only ONE copy of the bot may poll Telegram at a time. Stop the one on your
> laptop before starting the server copy, or both will fight over updates.

## Picking a host

| Option | Cost | Notes |
|---|---|---|
| Hetzner Cloud CX22 (2 vCPU, 4 GB) | about €4/month | Recommended: cheap, simple, fast. |
| DigitalOcean Basic droplet (1 GB) | about $6/month | Fine; 1 GB is just enough. |
| Oracle Cloud Always Free (Ampere ARM) | free | Generous, but sign-up and capacity can be fiddly. The image builds on ARM. |

Free tiers on Render, Railway or Fly sleep when idle or lack a permanent disk,
which breaks reminders and the database, so they aren't a good fit.

## 1. Set up the server (Ubuntu 24.04)

```bash
ssh root@YOUR_SERVER_IP
curl -fsSL https://get.docker.com | sh
adduser pocket && usermod -aG docker pocket
su - pocket
```

## 2. Get the code and your `.env`

```bash
git clone https://github.com/jai45/pocket-agent.git
cd pocket-agent
mkdir -p data && sudo chown 1000:1000 data   # the container runs as uid 1000
```

Copy `.env` from your laptop (run this **on your laptop**), so secrets never go
into git:

```bash
scp .env pocket@YOUR_SERVER_IP:~/pocket-agent/.env
```

Don't set `DB_PATH`, `LOG_DIR` or `BACKUP_DIR` in the server's `.env`; the
Dockerfile points them at `/data`. Do set `TIMEZONE` and (recommended)
`DAILY_BUDGET_USD`.

To bring your existing history along, copy the database too (with the laptop
bot stopped): `scp data/pocket.db pocket@YOUR_SERVER_IP:~/pocket-agent/data/`

## 3. Start it

```bash
docker compose up -d --build
docker compose logs -f        # Ctrl+C stops watching, not the bot
```

The first start downloads the Whisper model into `data/hf-cache` (about a minute).
Send the bot `/cost` on Telegram to check it is alive.

## Everyday commands

```bash
docker compose logs --tail 100           # recent text logs
tail -n 5 data/logs/runs-$(date +%F).jsonl  # structured run logs
docker compose restart                   # restart
git pull && docker compose up -d --build # deploy a new version
docker compose down                      # stop
```

`restart: unless-stopped` brings the bot back after a crash or a server reboot.

## Backups

The bot backs up the database itself every night at `BACKUP_TIME` (default
03:00 in your `TIMEZONE`), using SQLite's online backup (safe while running),
into `data/backups/pocket-YYYY-MM-DD.db`, keeping the last 7. Run logs older
than 30 days are deleted at the same time.

These backups sit on the same disk as the database, so also copy them off the
server now and then (on your laptop):

```bash
scp "pocket@YOUR_SERVER_IP:~/pocket-agent/data/backups/*" ./server-backups/
```

### Restoring a backup

```bash
docker compose down
cp data/pocket.db data/pocket.db.broken
cp data/backups/pocket-2026-11-13.db data/pocket.db
docker compose up -d
```

Reminders are rebuilt from the database on startup, so nothing else is needed.
