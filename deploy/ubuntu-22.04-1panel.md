# VPS Deploy (Ubuntu 22.04 + 1Panel)

This guide deploys `local_scraper` as a Docker app managed by 1Panel.

## 0. Prereqs

- Ubuntu 22.04
- 1Panel installed with Docker support
- A GitHub repo containing the `local_scraper/` directory

## 1. Prepare secrets

In 1Panel, set environment variables (recommended) or create an `.env` file in the app directory on the VPS.

Required:
- `WEBUI_USERNAME`
- `WEBUI_PASSWORD`
- `AI_API_KEY`

Optional:
- `FEISHU_WEBHOOK_URL`

## 2. Deploy via docker-compose

1) In 1Panel -> Apps/Projects -> create a new project from Git.
2) Set the project root to `local_scraper/`.
3) Choose `docker-compose.yml` and start.

By default it exposes port `8000`.

## 3. Reverse proxy (recommended)

Use 1Panel's website reverse proxy to map a domain to `http://127.0.0.1:8000`.

Notes:
- Keep `WEBUI_HOST=0.0.0.0` inside container.
- Protect the site with HTTPS.

## 4. Data persistence

SQLite and logs are persisted via bind mounts:
- `local_scraper/data/` -> `/app/data/`
- `local_scraper/logs/` -> `/app/logs/`

## 5. Upgrade

1) In 1Panel, pull latest Git commit/tag.
2) Rebuild/restart the container.
