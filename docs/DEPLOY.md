# Deploying Encaixe

One Linux server, two containers: the app (FastAPI serving the API and the built front, SQLite and the embedding model on a volume) and [Caddy](https://caddyserver.com/) in front of it, which gets and renews the HTTPS certificate on its own. Nothing else to run: no separate database, queue or front-end server.

## 1. What you need

- **A Linux VM (x86_64)** with **at least 2 GB of RAM plus 2 GB of swap**; 4 GB is comfortable. The server uses about 470 MB with the model loaded and the daily job collection peaks at about 550 MB while it runs next to it.
- **A domain** (for example a `.com.br`) with an `A` record pointing to the VM, and ports **80 and 443** open.
- **An SMTP account** to send login links (there are no passwords): Brevo, Resend or similar with SPF and DKIM set on your domain, or, for a small beta, a dedicated Gmail account with an App Password. Use port 587 (or 2525); several clouds block 25 and 465.
- Optional: a Groq API key, used only when a person ticks "Usar IA para ler meu CV".

## 2. Prepare the server

```bash
# Docker Engine + the compose plugin: https://docs.docker.com/engine/install/
# 2 GB of swap, if the VM has none
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Before going further, send a test e-mail **from the VM** with your SMTP settings: some providers block outgoing mail ports on new accounts.

## 3. Install

```bash
git clone https://github.com/FG-SC/encaixe.git && cd encaixe
cp deploy/env.prod.example .env.prod      # then edit: DOMAIN, BASE_URL, SMTP_*, optional GROQ_API_KEY
docker compose build
docker compose run --rm app encaixe embed           # downloads the embedding model (~250 MB) into the volume
docker compose run --rm app encaixe ingest --all    # first job collection (a few minutes)
docker compose up -d
```

Check it:

```bash
docker compose ps                                   # app "healthy", caddy "running"
curl https://YOUR_DOMAIN/api/health
docker compose exec app encaixe status              # counts, embeddings, LLM, last collection runs
```

Open `https://YOUR_DOMAIN`, ask for a login link and make sure it reaches the inbox (not spam) on Gmail and Outlook.

The production database starts **empty of people**: no fictional jobs, no synthetic candidates, no dev panel (`ENCAIXE_ENV=prod` is set in the image; the demo commands refuse to run there).

## 4. Daily jobs (cron on the host)

`crontab -e`, times in UTC:

```cron
30 6 * * *  cd /path/to/encaixe && docker compose exec -T app encaixe backup        >> /var/log/encaixe-backup.log 2>&1
0 7 * * *   cd /path/to/encaixe && docker compose exec -T app encaixe ingest --all  >> /var/log/encaixe-ingest.log 2>&1
```

The collection runs at 04:00 in Brasília, off-peak: each job board is fetched at most once a day, serially, at least 1 s apart. The server notices the new jobs by itself.

## 5. Backups and restore

`encaixe backup` writes a consistent copy of the database (`VACUUM INTO`, safe while the server writes) to `/data/backups` inside the volume and keeps the 7 newest. They sit on the same disk as the database, so also turn on the provider's VM snapshots or copy them off the server, for example:

```bash
docker compose cp app:/data/backups ./backups-$(date +%F)
```

Restore:

```bash
docker compose stop app
docker compose cp ./encaixe-YYYYMMDD-HHMMSS.db app:/data/encaixe.db
docker compose run --rm --entrypoint sh app -c 'rm -f /data/encaixe.db-wal /data/encaixe.db-shm'
docker compose start app
```

## 6. Updating

```bash
git pull && docker compose up -d --build
```

Tables are created on start. A change to an existing table needs a written `ALTER` (there is no migration framework yet); the release notes will say so.

## 7. Where things are

| what | where |
|---|---|
| database, models, HTTP cache, backups | volume `encaixe-data`, mounted at `/data` in the app container |
| certificates | volume `caddy-data` |
| configuration and secrets | `.env.prod` next to `docker-compose.yml` (never committed) |
| logs | `docker compose logs -f app` (rotated at 10 MB × 3) |

## 8. Troubleshooting

- **The app restarts at boot:** `docker compose logs app`. In production it refuses to start without an https `BASE_URL`, `SMTP_HOST`/`SMTP_FROM`, or the embedding model; the message says which.
- **Login e-mails don't arrive:** check the spam folder, the SPF/DKIM records of the sender's domain, and the SMTP port (587 or 2525).
- **Out of memory during the collection:** add swap or move to a 4 GB VM; the collection and the server share the machine at 04:00 for a few minutes.
- **The model download failed on first start:** run `docker compose run --rm app encaixe embed` again; the server needs it to start in production.
