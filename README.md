# VirgoZone

VirgoZone is a local-only social wall for one Jetson and the people connected to
the same LAN. It provides live chat, photo/video posts, media comments, a shared
schedule, and a small Ollama-backed LAN fairy. The browser loads no CDN assets
and no feature requires WAN access.

## Current device configuration

- Python 3.10 with an isolated `.venv`
- FastAPI and one Uvicorn worker on `0.0.0.0:8080`
- SQLite WAL database at `data/app.db`
- Originals under `data/uploads/YYYY/MM`
- Feed and vision derivatives under `data/thumbnails/YYYY/MM`
- Ollama only through `http://127.0.0.1:11434`
- Text model: `qwen2.5:0.5b`
- Vision model installed: `moondream:1.8b`, but disabled in configuration

Vision is disabled because live benchmarking on this 8 GB Orin Nano showed that
the CUDA runner could not allocate enough unified memory while the workstation's
other services were active. CPU-only vision took 57.5 seconds and returned an
empty result. Photo fairy actions therefore use captions and media metadata and
never claim to see details that were not provided. Gallery, chat, comments, and
schedule remain independent from Ollama.

## Development run

```bash
cd /home/jetson/fairy_lan
.venv/bin/python -m pytest -q
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 1
```

Open one of:

- `http://192.168.1.188:8080` over Wi-Fi
- `http://192.168.1.190:8080` over Ethernet
- `http://virgozone.local:8080` after the deployment installer configures Avahi

## Deployment

The installer needs root access because it installs ffmpeg, adds systemd and
Avahi files, and changes Avahi's advertised hostname from `hosaka-jetson` to
`virgozone`. It does not change the OS hostname or Ollama's existing network bind.

Run this directly in a terminal so the sudo and new admin passwords do not pass
through chat:

```bash
cd /home/jetson/fairy_lan
sudo ./deploy/install.sh
```

The shared admin password is `neuro`. The installer creates `/etc/virgozone/env`
with mode `0600`. Edit that file to
change limits, models, or `FAIRY_AUTO_COMMENT`, then restart:

```bash
sudo systemctl restart virgozone
sudo journalctl -u virgozone -n 100 --no-pager
```

## Configuration

See `.env.example`. Important settings are:

- `ADMIN_PASSWORD`: enables schedule controls and media deletion.
- `IMAGE_MAX_MB` and `VIDEO_MAX_MB`: enforced while copying each upload.
- `MIN_FREE_MB`: disk reserve below which uploads are rejected.
- `OLLAMA_MODEL`: short text fairy model.
- `OLLAMA_VISION_ENABLED`: keep false until a live image benchmark succeeds.
- `FAIRY_AUTO_COMMENT`: disabled by default; auto jobs skip when inference is busy.

## API

- `GET /api/status`, `GET /api/bootstrap`
- `GET/POST /api/chat`, `POST /api/fairy/chat`
- `GET/POST /api/media`, `DELETE /api/media/{id}`
- `GET/POST /api/media/{id}/comments`, `POST /api/media/{id}/fairy`
- `GET/POST/PATCH/DELETE /api/schedule`
- `GET /api/admin/session`, `POST /api/admin/login`, `POST /api/admin/logout`
- `GET /ws`

WebSocket messages use `{ "type": "...", "payload": { ... } }`. Browsers
connect before bootstrap, buffer events while hydrating, and deduplicate by UUID.

## Hosaka in chat

Every committed human chat message queues one Hosaka response. Calls remain
strictly serialized so Ollama never runs concurrent VirgoZone generations, and
each response is tied to the triggering message's UUID so later chat cannot leak
into its context. Hosaka uses a two-sentence identity distilled from
`Hosaka/identity/AGENT.md` and `SOUL.md`; echoes, role-label leakage, and generic
assistant refusals are suppressed rather than posted. The floating Hosaka status
control has been removed; chat keeps a compact listening/thinking/offline status
and a visible temporary thinking row while Ollama works. Capped sparkles appear
at every primary touch/click location and remain disabled under reduced motion.
Hosaka chooses response length from context: casual turns can stay short, while
explanations, reassurance, and stories may use several sentences.
Ollama has no configured output-token ceiling for chat. Distinct paragraphs are
stored and broadcast as separate HOSAKA messages, with long paragraphs split
only at SQLite's per-message boundary. The finite model context and 120-second
failure timeout remain so a stalled generation cannot block the social queue forever.

## Recovery

The database and media directory are all that must be backed up. Stop the service
before taking a strict point-in-time copy, or use SQLite's online backup command.

```bash
sudo systemctl stop virgozone
cp -a data /path/to/backup/
sudo systemctl start virgozone
```

The pre-VirgoZone Avahi configuration is retained at
`/etc/avahi/avahi-daemon.conf.before-virgozone`.

## Weekend schedule

`virgo_boys_schedule_web.csv` is imported idempotently as the weekend beginning
Friday, September 4, 2026 in `America/Los_Angeles`. Rows after midnight roll
into the following calendar day, and adjacent identical hourly slots are shown
as one time range. Re-run the import after editing the CSV with:

```bash
.venv/bin/python scripts/import_schedule.py
```
