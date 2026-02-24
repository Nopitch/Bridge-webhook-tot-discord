# Tot! Chat -> Discord Bridge

A Python bridge that forwards messages from the Tot! Roleplay Redux mod (Conan Exiles) to a Discord channel in real-time via webhook.

**Topics:** ![Conan Exiles](https://img.shields.io/badge/Conan_Exiles-Modding-brown.svg)
![Discord Webhook](https://img.shields.io/badge/Discord-Webhook-5865F2.svg)
![Tot! Redux](https://img.shields.io/badge/Tot!-Redux-ff69b4.svg)
![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-2.0+-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Features

- Real-time transmission of chat messages to Discord
- Optimized for 60 players with a smart batching system
- Dynamic Discord timestamps (adapt to each user's timezone)
- Discord rate limits management with automatic retry
- Advanced monitoring page with real-time statistics
- JSON API for external monitoring (Grafana, scripts, etc.)
- Highly configurable (channels, display, delays...)
- Rotating logs to prevent disk saturation
- Anti-ping protection (blocks @everyone, @here, etc. mentions)

## Prerequisites

- Python 3.8 or higher
- The Tot! Roleplay Redux mod (https://steamcommunity.com/sharedfiles/filedetails/?id=2400073656) configured to send HTTP messages
- A Discord webhook

## Installation

### 1. Clone or download the project

```bash
git clone [https://github.com/your-repo/tot-discord-bridge.git](https://github.com/your-repo/tot-discord-bridge.git)
cd tot-discord-bridge
```

### 2. Install dependencies

```bash
pip install flask requests waitress
```

> Note: waitress is optional but recommended for production (high-performance WSGI server).

### 3. Create a Discord webhook

1. Open your Discord channel settings
2. Go to Integrations -> Webhooks
3. Click on New webhook
4. Copy the webhook URL

### 4. Configure the script

Open tot_discord_bridge.py and modify the configuration variables:

```python
DISCORD_WEBHOOK_URL = "[https://discord.com/api/webhooks/](https://discord.com/api/webhooks/)..."  # Your webhook
PORT = 3000  # Listening port (must match Tot!)
```

## Configuration

### Main options

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_WEBHOOK_URL` | - | Discord webhook URL (required) |
| `PORT` | `3000` | HTTP server listening port |
| `BOT_NAME` | `"La Poukave"` | Name displayed in Discord |
| `BOT_AVATAR` | Image URL | Bot avatar in Discord |

### Batching & Performance

| Variable | Default | Description |
|----------|---------|-------------|
| `BATCH_DELAY` | `2.5` | Seconds between each Discord dispatch |
| `MAX_BATCH_SIZE` | `10` | Max number of messages per batch |
| `MAX_QUEUE_SIZE` | `500` | Max size of the waiting queue |
| `MAX_FAILED_RETRY` | `200` | Max messages waiting for retry |

### Monitoring

| Variable | Default | Description |
|----------|---------|-------------|
| `STATS_LOG_INTERVAL` | `300` | Interval for stats logs (seconds) |

### Message display

| Variable | Default | Description |
|----------|---------|-------------|
| `SHOW_CHARACTER_NAME` | `True` | Displays the character's name |
| `SHOW_RADIUS` | `True` | Displays the type [Say], [Shout], etc. |
| `SHOW_LOCATION` | `False` | Displays the coordinates |
| `SHOW_CHANNEL` | `True` | Displays the channel number |
| `TIMESTAMP_FORMAT` | `"T"` | Discord time format |

### Discord timestamp formats

| Format | Example |
|--------|---------|
| `"t"` | 14:30 |
| `"T"` | 14:30:00 |
| `"d"` | 02/21/2026 |
| `"D"` | February 21, 2026 |
| `"f"` | February 21, 2026 14:30 |
| `"F"` | Saturday, February 21, 2026 14:30 |
| `"R"` | 5 minutes ago |
| `""` | Disabled |

### Channel filtering

```python
# Accept all channels
ALLOWED_CHANNELS = []

# Accept only channels 1 and 2
ALLOWED_CHANNELS = ["1", "2"]
```

## Usage

### Start the bridge

```bash
python tot_discord_bridge.py
```

Expected output:
```text
==================================================
   Tot ! Chat -> Discord Bridge
   Optimized for 60 players
==================================================
   Server     : http://localhost:3000
   Tot URL    : http://localhost:3000/message
   Monitoring : http://localhost:3000/
   Stats JSON : http://localhost:3000/stats
   Batch      : 2.5s / 10 msg
   Max queue  : 500
   Channels   : All
==================================================
```

### Configure Tot! Roleplay Redux

In the Tot! mod configuration, set the HTTP URL:
```text
http://localhost:3000/message
```

## Monitoring

### Web monitoring page

Access `http://localhost:3000/` to view the real-time dashboard.

Displayed metrics:

| Metric | Description |
|--------|-------------|
| Received messages/min | Inbound rate from Tot! |
| Sent messages/min | Outbound rate to Discord |
| Current queue | Number of pending messages |
| Average latency | Time between reception and dispatch |
| Queue peak | Historical maximum (with timestamp) |
| Messages/min peak | Maximum observed load |
| Dropped messages | Total of unsent messages |
| Rate limits | Number of Discord blocks |

### JSON API (/stats)

For integration with external monitoring tools:

```bash
curl http://localhost:3000/stats
```

Response:
```json
{
  "status": "OK",
  "uptime": "2h 15m 30s",
  "uptime_seconds": 8130,
  "queue": {
    "current": 5,
    "max": 500,
    "percent": 1.0,
    "peak": 45,
    "peak_time": "2026-02-24T20:30:15"
  },
  "messages": {
    "total_received": 1250,
    "total_sent": 1248,
    "total_dropped": 0,
    "total_failed": 2,
    "received_per_minute": 12.5,
    "sent_per_minute": 12.3,
    "peak_per_minute": 85.0
  },
  "performance": {
    "rate_limits": 3,
    "average_latency_ms": 2450.5
  },
  "config": {
    "batch_delay": 2.5,
    "max_batch_size": 10,
    "theoretical_capacity": 240
  }
}
```

### Periodic logs

Every 5 minutes (configurable via `STATS_LOG_INTERVAL`), a summary is logged:

```text
[2026-02-24 20:30:00] INFO: [STATS] Received: 45.2/min | Sent: 44.8/min | Queue: 12/500 | Queue peak: 67 | Dropped: 0 | Rate limits: 2
```

## API Endpoints

### GET/POST /message

Receives messages from Tot! Roleplay Redux.

Parameters (query string):

| Parameter | Type | Description |
|-----------|------|-------------|
| `message` | string | Message content |
| `sender` | string | Player name |
| `character` | string | RP Character name |
| `radius` | string | Message type (say, shout, whisper...) |
| `location` | string | Player coordinates |
| `channel` | string | Channel number |

Responses:

| Code | Status | Description |
|------|--------|-------------|
| 200 | `ok` | Message accepted |
| 200 | `ignored` | Channel filtered |
| 503 | `queue_full` | Queue is full |
| 500 | `error` | Server error |

### GET /

HTML monitoring page with real-time statistics (5s auto-refresh).

### GET /stats

JSON endpoint with all metrics for external monitoring.

## Technical Architecture

```text
┌─────────────┐     HTTP      ┌──────────────┐     Queue     ┌────────────┐
│  Tot! Mod   │ ───────────▶  │ Flask Server │ ───────────▶  │   Worker   │
│  (Conan)    │   /message    │   (Port 3000)│               │  (Thread)  │
└─────────────┘               └──────────────┘               └─────┬──────┘
                                     │                             │
                                     │                             │
                                     ▼                             │
                              ┌──────────────┐                  Batching
                              │    Stats     │                     │
                              │  (Metrics)   │                     ▼
                              └──────────────┘               ┌──────────────┐
                                     │                       │   Discord    │
                                     ▼                       │   Webhook    │
                              ┌──────────────┐               └──────────────┘
                              │  /stats JSON │
                              │  / Dashboard │
                              └──────────────┘
```

### Calculated capacity

- Discord limit: 5 requests / 2 seconds = 150 req/min
- Safe configuration: 1 request / 2.5 seconds = 24 req/min
- With batching: 10 msg/batch x 24 = 240 messages/minute
- 60 players x 2 msg/min: 120 msg/min -> 100% margin

## Troubleshooting

### The webhook is not working

```text
CRITICAL ERROR: Discord webhook invalid or deleted!
```
-> Verify that the webhook URL is correct and that the webhook has not been deleted.

### Dropped messages / Full queue

```text
Queue full (500), message ignored
```
-> Check the dashboard to see the queue peak. If the peak approaches `MAX_QUEUE_SIZE`, increase this value or reduce `BATCH_DELAY`.

Diagnosis via `/stats`:
```bash
curl -s http://localhost:3000/stats | jq '.queue'
```

### Discord rate limit

```text
Discord rate limit, resuming in X.Xs
```
-> Normal during activity spikes. The system automatically handles retries. If frequent, increase `BATCH_DELAY`.

Check frequency:
```bash
curl -s http://localhost:3000/stats | jq '.performance.rate_limits'
```

### High latency

If the average latency exceeds 5 seconds:
1. Verify that the queue is not filling up faster than it empties
2. Reduce `BATCH_DELAY` (watch out for rate limits)
3. Increase `MAX_BATCH_SIZE`

### Windows encoding errors

The script forces UTF-8 encoding for the Windows console. If you experience display issues, ensure your terminal supports UTF-8.

## Files

| File | Description |
|------|-------------|
| `tot_discord_bridge.py` | Main script |
| `bridge.log` | Logs (automatic rotation, 5 MB max) |
| `bridge.log.1`, `.2`, `.3` | Log backups |

## License

MIT License - Free to use and modify.

---

Developed for the Conan Exiles RP community
