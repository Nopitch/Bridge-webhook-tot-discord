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
| `BOT_NAME` | `"CHAT_CONAN"` | Name displayed in Discord |
| `BOT_AVATAR` | Image URL | Bot avatar in Discord |

### Rate Limit Protection

| Variable | Default | Description |
|----------|---------|-------------|
| `INTER_REQUEST_DELAY` | `0.5` | Seconds between Discord requests (prevents burst limit of 5 req/2s) |
| `MAX_DISCORD_REQUESTS` | `1` | Max requests per batch cycle (0 = unlimited, reactive mode) |

**Recommended settings:**

| Mode | INTER_REQUEST_DELAY | MAX_DISCORD_REQUESTS | Behavior |
|------|---------------------|----------------------|----------|
| Safe (recommended) | `0.5` | `1` | Zero rate limits, 24 req/min |
| Balanced | `0.5` | `2` | Occasional rate limits, faster |
| Reactive | `0.5` | `0` | Unlimited, handles rate limits reactively |

### Batching

| Variable | Default | Description |
|----------|---------|-------------|
| `BATCH_DELAY` | `2.5` | Seconds between batch cycles |
| `MAX_BATCH_SIZE` | `20` | Maximum messages collected per cycle |
| `MAX_QUEUE_SIZE` | `500` | Buffer for activity spikes |
| `MAX_FAILED_RETRY` | `200` | Maximum messages waiting for retry |

### Capacity Calculation
```
Cycles per minute: 60 / BATCH_DELAY = 24 cycles/min
Requests per minute: 24 × MAX_DISCORD_REQUESTS = 24 req/min
Discord limit: ~30 req/min (sustained)
Margin: 30 / 24 = 1.25× (25% safety margin)
```
### Log Stats
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

### Web Dashboard

Access `http://localhost:3000/` for real-time monitoring:

- Messages received/sent per minute
- **Discord requests per minute** (new!)
- Current queue size and peak
- Average latency
- **Rate limit breakdown by type** (new!)

### Rate Limit Types

| Type | Meaning | Action |
|------|---------|--------|
| **Global** | Discord-wide limit (50 req/s) | CRITICAL - reduce traffic immediately! |
| **Shared** | Channel/webhook limit (~30 req/min) | Reduce `MAX_DISCORD_REQUESTS` |
| **User** | Burst limit (5 req/2s) | Increase `INTER_REQUEST_DELAY` |

### JSON API

`GET /stats` returns:

```json
{
  "status": "OK",
  "uptime": "2h 15m 30s",
  "queue": {
    "current": 5,
    "max": 500,
    "peak": 42
  },
  "messages": {
    "total_received": 5000,
    "total_sent": 4998,
    "total_dropped": 0,
    "total_failed": 2,
    "received_per_minute": 45.2,
    "sent_per_minute": 44.8
  },
  "performance": {
    "total_requests": 1250,
    "requests_per_minute": 23.5,
    "rate_limits": 0,
    "rate_limits_global": 0,
    "rate_limits_shared": 0,
    "rate_limits_user": 0,
    "average_latency_ms": 125.3
  },
  "config": {
    "batch_delay": 2.5,
    "max_batch_size": 20,
    "inter_request_delay": 0.5,
    "max_discord_requests": 1
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
## Architecture

```
Tot! Mod → HTTP GET → Flask /message → Queue (FIFO)
                                           ↓
                              Discord Worker (background thread)
                                           ↓
                              ┌─────────────────────────┐
                              │ For each batch cycle:   │
                              │ 1. Get deferred msgs    │
                              │ 2. Collect new msgs     │
                              │ 3. Send (with delay)    │
                              │ 4. Defer remaining      │
                              └─────────────────────────┘
                                           ↓
                              Discord Webhook (rate limited)
```
## Troubleshooting

### High "Shared" Rate Limits

**Symptom:** `rate_limits_shared` increasing in stats

**Cause:** Exceeding ~30 requests/minute on the webhook

**Solution:**
```python
MAX_DISCORD_REQUESTS = 1  # Limit to 24 req/min
```

### High "User" Rate Limits

**Symptom:** `rate_limits_user` increasing in stats

**Cause:** Sending too fast (burst limit: 5 req/2s)

**Solution:**
```python
INTER_REQUEST_DELAY = 0.5  # 500ms between requests
```

### Queue Growing / Messages Delayed

**Symptom:** Queue size increasing, messages arriving late

**Cause:** `MAX_DISCORD_REQUESTS = 1` limits throughput to ~24 req/min

**Solutions:**
1. Increase `MAX_DISCORD_REQUESTS` to `2` (accept some rate limits)
2. Decrease `BATCH_DELAY` to `2.0` (30 cycles/min)
3. Filter unnecessary channels with `ALLOWED_CHANNELS`

### Message Order

Messages are **always delivered in chronological order**. Deferred messages (due to rate limits or request limits) are sent before new messages in the next cycle.

### Discord rate limit

```text
Discord rate limit, resuming in X.Xs
```
-> Normal during activity spikes. The system automatically handles retries. If frequent, increase `BATCH_DELAY`.


### Windows encoding errors

The script forces UTF-8 encoding for the Windows console. If you experience display issues, ensure your terminal supports UTF-8.

## Files

| File | Description |
|------|-------------|
| `tot_discord_bridge.py` | Main script |
| `start.bat` | Startup script for Windows |
| `start.sh` | Startup script for Linux and macOS |
| `bridge.log` | Logs (automatic rotation, 5 MB max) |
| `bridge.log.1`, `.2`, `.3` | Log backups |

## License

MIT License - Free to use and modify.

---

Developed for the Conan Exiles RP community
