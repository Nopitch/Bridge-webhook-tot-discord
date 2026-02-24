# Tot! Chat -> Discord Bridge

A Python bridge that forwards messages from the Tot! Roleplay Redux mod (Conan Exiles) to a Discord channel in real-time via webhook.

**Topics:** ![Conan Exiles](https://img.shields.io/badge/Conan_Exiles-Modding-brown.svg) ![Discord Webhook](https://img.shields.io/badge/Discord-Webhook-5865F2.svg) ![Tot! Redux](https://img.shields.io/badge/Tot!-Redux-ff69b4.svg) ![Python](https://img.shields.io/badge/Python-3.8+-blue.svg) ![Flask](https://img.shields.io/badge/Flask-2.0+-green.svg) ![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## ✨ Features

- **Real-time transmission** of chat messages to Discord.
- **Optimized for 60 players** with a smart batching system.
- **Dynamic Discord timestamps** (adapts to each user's timezone).
- **Discord rate limits management** with automatic retry.
- **Advanced monitoring page** with real-time statistics.
- **JSON API** for external monitoring (Grafana, scripts, etc.).
- **Highly configurable** (channels, display, delays...).
- **Rotating logs** to prevent disk saturation.
- **Anti-ping protection** (blocks `@everyone`, `@here`, etc.).

---

## 📋 Prerequisites

- Python 3.8 or higher.
- The [Tot! Roleplay Redux mod](https://steamcommunity.com/sharedfiles/filedetails/?id=2400073656) configured to send HTTP messages.
- A Discord Webhook URL.

---

## 🚀 Installation & Usage

### 1. Download the project

```bash
git clone [https://github.com/your-repo/tot-discord-bridge.git](https://github.com/your-repo/tot-discord-bridge.git)
cd tot-discord-bridge
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```
> *Note: `waitress` is included and recommended for production (high-performance WSGI server).*

### 3. Configure the script

1. Open your Discord channel settings -> Integrations -> Webhooks -> Copy Webhook URL.
2. Open `tot_discord_bridge.py` and modify the core variables:

```python
DISCORD_WEBHOOK_URL = "[https://discord.com/api/webhooks/](https://discord.com/api/webhooks/)..."  # Your webhook
PORT = 3000  # Listening port (must match Tot!)
```

### 4. Start the bridge

Use the provided startup scripts depending on your OS:
- **Windows:** Double-click `start.bat`
- **Linux/macOS:** Run `./start.sh`

### 5. Configure the Mod (in-game)

In the Tot! mod configuration panel, set the HTTP URL to:
```text
http://localhost:3000/message
```

---

## ⚙️ Configuration

Open `tot_discord_bridge.py` to adjust the following settings. They are grouped by category for easier tweaking.

### Main Options
| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_WEBHOOK_URL` | - | Discord webhook URL (required) |
| `PORT` | `3000` | HTTP server listening port |
| `BOT_NAME` | `"CHAT_CONAN"` | Name displayed in Discord |
| `BOT_AVATAR` | Image URL | Bot avatar in Discord |

### Performance & Rate Limits
| Variable | Default | Description |
|----------|---------|-------------|
| `BATCH_DELAY` | `2.5` | Seconds between batch cycles |
| `MAX_BATCH_SIZE` | `20` | Maximum messages collected per cycle |
| `MAX_QUEUE_SIZE` | `500` | Buffer for activity spikes |
| `MAX_FAILED_RETRY` | `200` | Maximum messages waiting for retry |
| `INTER_REQUEST_DELAY` | `0.5` | Seconds between Discord requests |
| `MAX_DISCORD_REQUESTS` | `1` | Max requests per batch cycle (0 = unlimited) |

**Recommended Flow Settings:**
| Mode | `INTER_REQUEST_DELAY` | `MAX_DISCORD_REQUESTS` | Behavior |
|------|-----------------------|------------------------|----------|
| **Safe** (Rec.)| `0.5` | `1` | Zero rate limits, ~24 req/min |
| **Balanced** | `0.5` | `2` | Occasional rate limits, faster throughput |
| **Reactive** | `0.5` | `0` | Unlimited, relies on Discord's 429 errors to pause |

### Message Display & Formatting
| Variable | Default | Description |
|----------|---------|-------------|
| `SHOW_CHARACTER_NAME` | `True` | Displays the character's name |
| `SHOW_RADIUS` | `True` | Displays the type [Say], [Shout], etc. |
| `SHOW_LOCATION` | `False` | Displays the coordinates |
| `SHOW_CHANNEL` | `True` | Displays the channel number |
| `TIMESTAMP_FORMAT` | `"T"` | Discord time format (`t`, `T`, `d`, `D`, `f`, `F`, `R`, or `""` to disable) |
| `ALLOWED_CHANNELS` | `[]` | Accept all channels. Use `["1", "2"]` to filter. |

---

## 📊 Monitoring & API Endpoints

### Web Dashboard
Access `http://localhost:3000/` for a real-time HTML dashboard showing:
- Messages received/sent per minute
- Discord requests per minute
- Current queue size and historical peak
- Average latency & Rate limit breakdowns

### JSON API (`GET /stats`)
Returns application health and metrics for integration with tools like Grafana.
```json
{
  "status": "OK",
  "uptime": "2h 15m 30s",
  "queue": { "current": 5, "max": 500, "peak": 42 },
  "messages": { "total_received": 5000, "total_sent": 4998 },
  "performance": { "total_requests": 1250, "requests_per_minute": 23.5, "rate_limits": 0 }
}
```

### Inbound Endpoint (`GET/POST /message`)
Receives messages from Tot! Roleplay Redux. Accepts `message`, `sender`, `character`, `radius`, `location`, and `channel`.
Returns `200 ok`, `200 ignored` (if filtered), `503 queue_full`, or `500 error`.

---

## 🏗️ Architecture & Data Flow

### System Topology
```text
┌─────────────┐     HTTP      ┌──────────────┐     Queue     ┌────────────┐
│  Tot! Mod   │ ───────────▶  │ Flask Server │ ───────────▶  │   Worker   │
│  (Conan)    │   /message    │   (Port 3000)│               │  (Thread)  │
└─────────────┘               └──────────────┘               └─────┬──────┘
                                     │                             │
                                     ▼                             ▼
                              ┌──────────────┐               ┌──────────────┐
                              │    Stats     │               │   Discord    │
                              │  Dashboard   │               │   Webhook    │
                              └──────────────┘               └──────────────┘
```

### Background Worker Logic
> **Note on Message Order:** Messages are *always delivered in chronological order*. Deferred messages (due to rate limits) are prioritized and sent before new messages in the next cycle.

```text
Queue (FIFO)
     ↓
┌─────────────────────────┐
│ For each batch cycle:   │
│ 1. Get deferred msgs    │
│ 2. Collect new msgs     │
│ 3. Send (with delay)    │
│ 4. Defer remaining      │
└─────────────────────────┘
     ↓
Discord Webhook
```

**Capacity Calculation Example:**
`60 / BATCH_DELAY (2.5) = 24 cycles/min`. 
`24 × MAX_DISCORD_REQUESTS (1) = 24 req/min`.
Discord's sustained limit is ~30 req/min, giving this configuration a **25% safety margin**.

---

## 🔧 Troubleshooting

| Symptom / Error | Cause | Solution |
|-----------------|-------|----------|
| **High `Shared` Rate Limits** | Exceeding ~30 requests/minute on the webhook. | Set `MAX_DISCORD_REQUESTS = 1` |
| **High `User` Rate Limits** | Sending too fast (burst limit: 5 req/2s). | Set `INTER_REQUEST_DELAY = 0.5` |
| **Queue Growing constantly** | Output throughput is too low for the server load. | Increase `MAX_DISCORD_REQUESTS` to `2` or decrease `BATCH_DELAY` to `2.0`. |
| **Windows encoding errors** | Terminal doesn't support UTF-8 natively. | The script forces UTF-8, but ensure your terminal font supports special characters. |

---

## 📁 Files Overview

| File | Description |
|------|-------------|
| `tot_discord_bridge.py` | Core application script |
| `start.bat` | Startup script for Windows |
| `start.sh` | Startup script for Linux and macOS |
| `requirements.txt` | Python dependencies list |
| `bridge.log` | Rotating application logs (5 MB max) |

---
*MIT License - Free to use and modify.* **Developed for the Conan Exiles RP community.**
