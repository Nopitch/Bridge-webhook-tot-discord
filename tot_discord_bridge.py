# -*- coding: utf-8 -*-
"""
Tot! Chat → Discord Bridge (Production Version)
Receives messages from the Tot! Roleplay Redux mod and sends them to Discord

Optimized for:
- 60 players at peak evening hours
- Messages up to 1000 characters
- Discord limit: 5 requests / 2 seconds
"""

import sys
import io
import requests
import threading
import queue
import time
import logging
import statistics
from datetime import datetime
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from logging.handlers import RotatingFileHandler
from flask import Flask, request

# =============================================================================
# WINDOWS CONSOLE ENCODING
# Forces UTF-8 encoding to avoid display errors in the console
# =============================================================================
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# =============================================================================
# CONFIGURATION
# Modify these values according to your needs
# =============================================================================

# Discord webhook URL (get it from your Discord channel settings)
DISCORD_WEBHOOK_URL = "PASTE_YOUR_WEBHOOK"

# Server listening port (must match Tot! config)
PORT = 3000

# Name and avatar displayed in Discord for messages
BOT_NAME = "CONAN_CHAT"
BOT_AVATAR = ""

# =============================================================================
# BATCHING - Optimized for 60 players
# Capacity calculation:
#   - Discord limit: 5 requests / 2 seconds = 150 req/min (burst)
#   - Discord limit: 30 requests / minute (sustained)
#   - Our config: 1 request / 2.5 seconds = 24 req/min (very safe)
#   - With 10 msg/batch: 240 messages/minute
#   - 60 players × 2 msg/min = 120 msg/min
#   - Margin: 240/120 = 2× (100% margin)
# =============================================================================

BATCH_DELAY = 2.5       # Seconds between each send (avoids rate limits)
MAX_BATCH_SIZE = 20     # Maximum 20 messages per send

# =============================================================================
# RATE LIMIT PROTECTION - Prevents hitting Discord limits
# Discord has TWO limits:
#   - Burst: 5 requests / 2 seconds (instant spam protection)
#   - Sustained: ~30 requests / minute (long-term protection)
#
# INTER_REQUEST_DELAY: Time to wait between each Discord request within a batch
#   - 0.5s = max 4 requests/2s (safe under burst limit of 5/2s)
#   - Prevents "machine gun" requests when processing long messages
#
# MAX_DISCORD_REQUESTS: Maximum requests per batch cycle
#   - Limits how many Discord API calls we make per BATCH_DELAY cycle
#   - Remaining messages are queued for next cycle (not lost!)
#   - Set to 0 for unlimited (old behavior, reactive to rate limits)
# =============================================================================

INTER_REQUEST_DELAY = 0.5   # Seconds between requests (0.5 = safe for burst limit)
MAX_DISCORD_REQUESTS = 1    # Max requests per cycle (0 = unlimited, reactive mode)

# =============================================================================
# QUEUE CONFIGURATION
# =============================================================================

MAX_QUEUE_SIZE = 500    # Buffer for activity spikes (increased for 60 players)
MAX_FAILED_RETRY = 200  # Messages waiting for retry

# =============================================================================
# CHARACTER LIMIT
# Discord limits messages to 2000 characters
# Tot! limits player messages to 1000 characters
# We keep a safety margin for formatting (timestamp, name, etc.)
# =============================================================================

DISCORD_MAX_CHARS = 2000
SAFE_BATCH_CHARS = 1900  # Safety margin for formatting

# =============================================================================
# LOG CONFIGURATION
# =============================================================================

LOG_FILE = "bridge.log"
LOG_MAX_SIZE = 5 * 1024 * 1024    # 5 MB per file
LOG_BACKUP_COUNT = 3              # 3 backup files

# =============================================================================
# MONITORING CONFIGURATION
# Interval between each statistics log (in seconds)
# =============================================================================

STATS_LOG_INTERVAL = 300  # 5 minutes

# =============================================================================
# CHANNEL FILTERING
# Empty list = accepts all channels
# Examples:
#   ALLOWED_CHANNELS = []           → All channels
#   ALLOWED_CHANNELS = ["1", "2"]   → Only channels 1 and 2
# =============================================================================

ALLOWED_CHANNELS = []

# =============================================================================
# TIME FORMAT
# Discord formats (adapts to each user's timezone):
#   "t" = 14:30
#   "T" = 14:30:00
#   "d" = 02/21/2026
#   "D" = February 21, 2026
#   "f" = February 21, 2026 14:30
#   "F" = Saturday, February 21, 2026 14:30
#   "R" = 5 minutes ago
#   ""  = disabled (no time displayed)
# =============================================================================

TIMESTAMP_FORMAT = "T"

# =============================================================================
# DISCORD DISPLAY CUSTOMIZATION
# =============================================================================

SHOW_CHARACTER_NAME = True   # Displays character name in parentheses
SHOW_RADIUS = True           # Displays message type [Say], [Shout], etc.
SHOW_LOCATION = False        # Displays player coordinates
SHOW_CHANNEL = True          # Displays channel number

# =============================================================================
# LOG SYSTEM CONFIGURATION
# Uses RotatingFileHandler to prevent logs from growing indefinitely
# =============================================================================

log_handlers = [logging.StreamHandler(sys.stdout)]

if LOG_FILE:
    rotating_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_SIZE,
        backupCount=LOG_BACKUP_COUNT,
        encoding='utf-8'
    )
    log_handlers.append(rotating_handler)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=log_handlers
)
logger = logging.getLogger(__name__)

# =============================================================================
# FLASK AND QUEUE INITIALIZATION
# =============================================================================

app = Flask(__name__)
message_queue = queue.Queue()


# =============================================================================
# STATISTICS AND MONITORING SYSTEM
# Collects metrics for:
#   - Diagnosing performance issues
#   - Adjusting configuration (queue, batch delay, etc.)
#   - Detecting message loss
# =============================================================================

@dataclass
class BridgeStats:
    """
    Thread-safe statistics for bridge monitoring.

    Collected metrics:
    - Global counters (received, sent, lost, rate limits)
    - Historical peaks (queue, messages/min)
    - 5-minute sliding history for throughput calculations
    - Processing latencies
    - Rate limit breakdown by type (global, shared, user)
    """

    # Global counters since startup
    total_received: int = 0         # Messages received from Tot!
    total_sent: int = 0             # Messages sent to Discord
    total_dropped: int = 0          # Messages lost (queue full)
    total_failed: int = 0           # Messages abandoned (Discord errors)
    total_rate_limits: int = 0      # Number of rate limits encountered
    total_requests: int = 0         # Total Discord API requests made

    # Rate limit breakdown by scope (for diagnostics)
    rate_limits_global: int = 0     # Global rate limits (very bad, reduce traffic!)
    rate_limits_shared: int = 0     # Shared rate limits (channel/webhook shared with others)
    rate_limits_user: int = 0       # User/endpoint rate limits (our fault, too fast)

    # Historical peaks for sizing
    peak_queue_size: int = 0        # Maximum queue size observed
    peak_queue_time: datetime = None
    peak_messages_per_minute: float = 0

    # Startup timestamp for uptime calculation
    start_time: datetime = field(default_factory=datetime.now)

    # Sliding history (last 5 minutes, in 10s intervals)
    # Allows calculating recent average throughput
    _received_history: deque = field(default_factory=lambda: deque(maxlen=30))
    _sent_history: deque = field(default_factory=lambda: deque(maxlen=30))
    _latencies: deque = field(default_factory=lambda: deque(maxlen=100))

    # Thread safety - all operations are protected by this lock
    _lock: Lock = field(default_factory=Lock)

    # Current time slot for sliding history
    _current_slot: int = 0
    _slot_received: int = 0
    _slot_sent: int = 0

    def _get_slot(self) -> int:
        """Returns the current time slot (10-second intervals)."""
        return int(time.time() // 10)

    def _rotate_slot(self):
        """
        Changes slot if necessary and archives data.
        Called automatically by record_* methods.
        """
        current = self._get_slot()
        if current != self._current_slot:
            # Archive the previous slot in history
            self._received_history.append(self._slot_received)
            self._sent_history.append(self._slot_sent)

            # Reset for the new slot
            self._slot_received = 0
            self._slot_sent = 0
            self._current_slot = current

    def record_received(self):
        """Records a message received from Tot!."""
        with self._lock:
            self._rotate_slot()
            self.total_received += 1
            self._slot_received += 1

    def record_sent(self, count: int = 1):
        """Records messages successfully sent to Discord."""
        with self._lock:
            self._rotate_slot()
            self.total_sent += count
            self._slot_sent += count

    def record_dropped(self, count: int = 1):
        """Records lost messages (queue full or retry overflow)."""
        with self._lock:
            self.total_dropped += count

    def record_failed(self, count: int = 1):
        """Records abandoned messages (Discord 4xx errors)."""
        with self._lock:
            self.total_failed += count

    def record_request(self):
        """Records a Discord API request."""
        with self._lock:
            self.total_requests += 1

    def record_rate_limit(self, scope: str = "unknown"):
        """
        Records a Discord rate limit with its scope.

        Scope types:
        - "global": Global rate limit (50 req/s) - VERY BAD, reduce traffic!
        - "shared": Shared resource (channel/webhook) - might not be our fault
        - "user": Per-endpoint limit - we're sending too fast
        """
        with self._lock:
            self.total_rate_limits += 1
            if scope == "global":
                self.rate_limits_global += 1
            elif scope == "shared":
                self.rate_limits_shared += 1
            else:
                self.rate_limits_user += 1

    def record_latency(self, latency_seconds: float):
        """
        Records a latency (time between reception and sending).
        Keeps the last 100 values for average calculation.
        """
        with self._lock:
            self._latencies.append(latency_seconds)

    def update_queue_size(self, size: int):
        """Updates the queue peak if current size is higher."""
        with self._lock:
            if size > self.peak_queue_size:
                self.peak_queue_size = size
                self.peak_queue_time = datetime.now()

    def get_messages_per_minute(self) -> tuple:
        """
        Calculates throughput over the last 5 minutes.

        Returns (received/min, sent/min).
        """
        with self._lock:
            self._rotate_slot()

            # Sum over available history + current slot
            received_sum = sum(self._received_history) + self._slot_received
            sent_sum = sum(self._sent_history) + self._slot_sent

            # Number of slots (each slot = 10 seconds)
            slots = len(self._received_history) + 1
            minutes = (slots * 10) / 60

            if minutes > 0:
                recv_per_min = received_sum / minutes
                sent_per_min = sent_sum / minutes

                # Update peak if necessary
                if recv_per_min > self.peak_messages_per_minute:
                    self.peak_messages_per_minute = recv_per_min

                return recv_per_min, sent_per_min
            return 0.0, 0.0

    def get_average_latency(self) -> float:
        """Returns average latency in seconds (over the last 100 messages)."""
        with self._lock:
            if self._latencies:
                return statistics.mean(self._latencies)
            return 0.0

    def get_uptime(self) -> str:
        """Returns formatted uptime in hours/minutes/seconds."""
        delta = datetime.now() - self.start_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    def get_health_status(self, current_queue: int, max_queue: int) -> tuple:
        """
        Evaluates the bridge's health status.

        Returns (status, hex_color):
        - "CRITICAL": Queue > 80%
        - "WARNING": Queue > 50% or frequent rate limits
        - "OK": Everything is fine
        """
        queue_percent = (current_queue / max_queue) * 100 if max_queue > 0 else 0

        if queue_percent > 80:
            return "CRITICAL", "#f04747"
        elif queue_percent > 50:
            return "WARNING", "#faa61a"
        elif self.total_rate_limits > 0 and self.total_sent > 0:
            rate_limit_percent = (self.total_rate_limits / self.total_sent) * 100
            if rate_limit_percent > 10:
                return "RATE LIMITED", "#faa61a"
        return "OK", "#43b581"

    def get_requests_per_minute(self) -> float:
        """Returns average Discord API requests per minute since startup."""
        uptime_seconds = (datetime.now() - self.start_time).total_seconds()
        if uptime_seconds > 0:
            return (self.total_requests / uptime_seconds) * 60
        return 0.0

    def to_dict(self, current_queue: int) -> dict:
        """
        Exports stats as dictionary (for JSON /stats endpoint).
        Useful for external monitoring (Grafana, scripts, etc.).
        """
        recv_min, sent_min = self.get_messages_per_minute()
        status, _ = self.get_health_status(current_queue, MAX_QUEUE_SIZE)

        return {
            "status": status,
            "uptime": self.get_uptime(),
            "uptime_seconds": int((datetime.now() - self.start_time).total_seconds()),
            "queue": {
                "current": current_queue,
                "max": MAX_QUEUE_SIZE,
                "percent": round((current_queue / MAX_QUEUE_SIZE) * 100, 1) if MAX_QUEUE_SIZE > 0 else 0,
                "peak": self.peak_queue_size,
                "peak_time": self.peak_queue_time.isoformat() if self.peak_queue_time else None,
            },
            "messages": {
                "total_received": self.total_received,
                "total_sent": self.total_sent,
                "total_dropped": self.total_dropped,
                "total_failed": self.total_failed,
                "received_per_minute": round(recv_min, 1),
                "sent_per_minute": round(sent_min, 1),
                "peak_per_minute": round(self.peak_messages_per_minute, 1),
            },
            "performance": {
                "total_requests": self.total_requests,
                "requests_per_minute": round(self.get_requests_per_minute(), 1),
                "rate_limits": self.total_rate_limits,
                "rate_limits_global": self.rate_limits_global,
                "rate_limits_shared": self.rate_limits_shared,
                "rate_limits_user": self.rate_limits_user,
                "average_latency_ms": round(self.get_average_latency() * 1000, 1),
            },
            "config": {
                "batch_delay": BATCH_DELAY,
                "max_batch_size": MAX_BATCH_SIZE,
                "inter_request_delay": INTER_REQUEST_DELAY,
                "max_discord_requests": MAX_DISCORD_REQUESTS,
                "theoretical_capacity": int((60 / BATCH_DELAY) * MAX_BATCH_SIZE),
            }
        }


# Initialize global stats
stats = BridgeStats()


# =============================================================================
# MESSAGE FORMATTING FOR DISCORD
# =============================================================================

def format_discord_message(data):
    """
    Transforms raw Tot! data into a formatted message for Discord.
    Uses the RECEPTION time of the message (not the send time).
    """
    sender = data.get('sender', 'Unknown') or 'Unknown'
    character = data.get('character', '')
    message = data.get('message', '')
    radius = (data.get('radius', 'say') or 'say').lower()
    location = data.get('location', '')
    channel = data.get('channel', '')

    # Uses reception time for timestamp (more accurate)
    received_at = data.get('received_at') or datetime.now()

    if not message:
        return None

    # Generates Discord timestamp based on RECEPTION time
    if TIMESTAMP_FORMAT:
        unix_timestamp = int(received_at.timestamp())
        timestamp_str = f"<t:{unix_timestamp}:{TIMESTAMP_FORMAT}> "
    else:
        timestamp_str = ""

    # Builds name display
    if SHOW_CHARACTER_NAME and character and character != sender:
        name_display = f"**{sender}** ({character})"
    else:
        name_display = f"**{sender}**"

    # Builds main message
    if SHOW_RADIUS:
        content = f"{timestamp_str}{name_display} [{radius.capitalize()}]: {message}"
    else:
        content = f"{timestamp_str}{name_display}: {message}"

    # Adds optional info in small text
    footer_parts = []
    if SHOW_LOCATION and location:
        footer_parts.append(f"Location: {location}")
    if SHOW_CHANNEL and channel:
        footer_parts.append(f"Channel: {channel}")

    if footer_parts:
        content += f"\n-# {' | '.join(footer_parts)}"

    return content


# =============================================================================
# SENDING CONTENT TO DISCORD
# =============================================================================

def send_to_discord(content):
    """
    Sends text content to Discord.

    Returns (success, retry_after, scope):
    - success: True if sent successfully
    - retry_after: seconds to wait if rate limited (0 otherwise)
    - scope: rate limit scope if rate limited ("global", "shared", "user", or None)

    Rate limit scopes (from Discord API):
    - "global": Global rate limit (50 req/s) - CRITICAL, reduce all traffic!
    - "shared": Shared resource limit - channel/webhook shared with other bots
    - "user": Per-endpoint limit - we're sending too fast on this endpoint

    IMPORTANT: This function does NOT call time.sleep()!
    The worker handles waiting to remain non-blocking.
    """
    if not content:
        return True, 0, None

    # Truncate if necessary (shouldn't happen with our splitting)
    if len(content) > DISCORD_MAX_CHARS:
        content = content[:DISCORD_MAX_CHARS - 3] + "..."
        logger.warning(f"Message truncated to {DISCORD_MAX_CHARS} characters")

    payload = {
        "username": BOT_NAME,
        "content": content,
        "allowed_mentions": {"parse": []}  # Blocks ALL pings
    }

    if BOT_AVATAR and BOT_AVATAR.strip():
        payload["avatar_url"] = BOT_AVATAR

    try:
        # Record that we're making a request
        stats.record_request()

        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)

        if response.status_code == 204:
            # Success
            return True, 0, None

        elif response.status_code == 429:
            # Rate limit - extract detailed information
            retry_after = response.json().get('retry_after', 2)

            # Get rate limit scope from headers (tells us WHY we're rate limited)
            scope = response.headers.get('X-RateLimit-Scope', 'user')
            remaining = response.headers.get('X-RateLimit-Remaining', '?')
            reset_after = response.headers.get('X-RateLimit-Reset-After', '?')

            # Log with appropriate severity based on scope
            if scope == "global":
                logger.error(f"⚠️ GLOBAL RATE LIMIT! Wait {retry_after}s - REDUCE TRAFFIC IMMEDIATELY!")
            elif scope == "shared":
                logger.warning(f"Rate limit (shared resource) - {retry_after}s - May be other bots on this channel")
            else:
                logger.warning(f"Rate limit (endpoint) - {retry_after}s (remaining: {remaining}, reset: {reset_after}s)")

            return False, retry_after, scope

        elif response.status_code in (404, 401):
            # Invalid or deleted webhook
            logger.error("=" * 60)
            logger.error("CRITICAL ERROR: Discord webhook invalid or deleted!")
            logger.error("Check the webhook URL in the configuration.")
            logger.error("=" * 60)
            return False, 0, None

        else:
            logger.error(f"Discord error {response.status_code}: {response.text}")
            # 5xx error = can retry, others = no
            return False, 2 if response.status_code >= 500 else 0, None

    except requests.exceptions.Timeout:
        logger.error("Timeout sending to Discord (10s)")
        return False, 2, None

    except Exception as e:
        logger.error(f"Send error: {e}")
        return False, 2, None


# =============================================================================
# SENDING A BATCH OF MESSAGES
# =============================================================================

def send_batch_to_discord(messages):
    """
    Sends a group of messages to Discord.
    Intelligently splits messages to:
    - Respect the 2000 character limit
    - Preserve chronological order (IMPORTANT for RP!)
    - Handle long messages (up to 1000 chars)
    - Respect Discord rate limits with INTER_REQUEST_DELAY
    - Optionally limit requests per cycle with MAX_DISCORD_REQUESTS

    Returns (success, retry_after, unsent_messages)

    Rate limit protection:
    - INTER_REQUEST_DELAY: Waits between each request to avoid burst limit (5 req/2s)
    - MAX_DISCORD_REQUESTS: Limits requests per cycle, excess messages go to next cycle
    """
    if not messages:
        return True, 0, []

    # Format all messages preserving chronological order
    formatted_messages = []
    for data in messages:
        formatted = format_discord_message(data)
        if formatted:
            formatted_messages.append((data, formatted))

    if not formatted_messages:
        return True, 0, []

    # Split into batches that respect character limit
    # WITHOUT changing chronological order
    unsent_messages = []
    current_batch_data = []
    current_batch_lines = []
    current_length = 0
    requests_sent = 0  # Track requests in this cycle

    for idx, (data, formatted) in enumerate(formatted_messages):
        line_length = len(formatted) + 1  # +1 for \n

        # If adding this message exceeds limit, send current batch first
        if current_length + line_length > SAFE_BATCH_CHARS and current_batch_lines:

            # Check if we've hit the request limit for this cycle
            if MAX_DISCORD_REQUESTS > 0 and requests_sent >= MAX_DISCORD_REQUESTS:
                # Limit reached: queue remaining messages for next cycle
                unsent_messages.extend(current_batch_data)
                for d, _ in formatted_messages[idx:]:
                    if d not in unsent_messages:
                        unsent_messages.append(d)
                logger.info(f"Request limit ({MAX_DISCORD_REQUESTS}/cycle) reached, {len(unsent_messages)} msg deferred to next cycle")
                return True, 0, unsent_messages  # True = not an error, just deferred

            # Wait between requests to respect burst limit (5 req / 2s)
            if requests_sent > 0 and INTER_REQUEST_DELAY > 0:
                time.sleep(INTER_REQUEST_DELAY)

            # Send current batch
            content = "\n".join(current_batch_lines)
            success, retry_after, scope = send_to_discord(content)
            requests_sent += 1

            if success:
                stats.record_sent(len(current_batch_data))
                logger.info(f"Sent {len(current_batch_lines)} message(s) [req {requests_sent}] | Queue: {message_queue.qsize()}")
            else:
                # Failure: keep all remaining messages for retry
                if retry_after > 0:
                    stats.record_rate_limit(scope or "user")
                unsent_messages.extend(current_batch_data)
                # Also add unprocessed messages (use idx instead of .index())
                for d, _ in formatted_messages[idx:]:
                    if d not in unsent_messages:
                        unsent_messages.append(d)
                return False, retry_after, unsent_messages

            # Reset for next batch
            current_batch_data = []
            current_batch_lines = []
            current_length = 0

        # Add message to current batch
        current_batch_data.append(data)
        current_batch_lines.append(formatted)
        current_length += line_length

    # Send the last batch
    if current_batch_lines:
        # Check request limit
        if MAX_DISCORD_REQUESTS > 0 and requests_sent >= MAX_DISCORD_REQUESTS:
            unsent_messages.extend(current_batch_data)
            logger.info(f"Request limit ({MAX_DISCORD_REQUESTS}/cycle) reached, {len(unsent_messages)} msg deferred")
            return True, 0, unsent_messages

        # Wait between requests
        if requests_sent > 0 and INTER_REQUEST_DELAY > 0:
            time.sleep(INTER_REQUEST_DELAY)

        content = "\n".join(current_batch_lines)
        success, retry_after, scope = send_to_discord(content)
        requests_sent += 1

        if success:
            stats.record_sent(len(current_batch_data))
            logger.info(f"Sent {len(current_batch_lines)} message(s) [req {requests_sent}] | Queue: {message_queue.qsize()}")
        else:
            if retry_after > 0:
                stats.record_rate_limit(scope or "user")
            unsent_messages.extend(current_batch_data)
            return False, retry_after, unsent_messages

    return True, 0, []


# =============================================================================
# WORKER: THREAD THAT PROCESSES THE QUEUE IN THE BACKGROUND
# =============================================================================

def discord_worker():
    """
    Thread that runs continuously and processes messages from the queue.
    NON-BLOCKING VERSION:
    - Continues collecting messages even during rate limit
    - Never does long sleep that would block collection
    - Preserves chronological order of messages
    - Collects statistics for monitoring
    """
    failed_messages = []
    rate_limit_until = 0  # Timestamp until which we must wait
    last_stats_log = time.time()  # For periodic stats logs

    while True:
        try:
            # Retrieve failed messages from previous cycle
            batch = failed_messages.copy()
            failed_messages.clear()

            # Collect new messages for BATCH_DELAY seconds
            deadline = time.time() + BATCH_DELAY

            while time.time() < deadline and len(batch) < MAX_BATCH_SIZE:
                try:
                    remaining = deadline - time.time()
                    if remaining > 0:
                        msg = message_queue.get(timeout=remaining)
                        batch.append(msg)
                except queue.Empty:
                    break

            # Update queue peak
            stats.update_queue_size(message_queue.qsize())

            # Check if we're still rate limited
            now = time.time()
            if now < rate_limit_until:
                # Still rate limited
                # Keep messages but continue collecting
                failed_messages.extend(batch)
                wait_time = rate_limit_until - now
                logger.debug(f"Rate limit active, waiting {wait_time:.1f}s (queue: {len(failed_messages)})")
                time.sleep(min(0.5, wait_time))  # Small sleep, not the entire rate limit
                continue

            # Send the batch
            if batch:
                success, retry_after, unsent = send_batch_to_discord(batch)

                if success:
                    # Record sent messages (already done in send_batch_to_discord)
                    # Calculate and record average batch latency
                    sent_count = len(batch) - len(unsent)
                    for msg in batch[:sent_count]:
                        if 'received_at' in msg:
                            latency = (datetime.now() - msg['received_at']).total_seconds()
                            stats.record_latency(latency)

                    # Handle deferred messages (from request limit, not errors)
                    if unsent:
                        failed_messages.extend(unsent)
                else:
                    if retry_after > 0:
                        # Rate limit: note until when to wait
                        rate_limit_until = time.time() + retry_after
                        failed_messages.extend(unsent)
                        logger.warning(f"Discord rate limit, resuming in {retry_after:.1f}s | Queue: {message_queue.qsize()}")
                    else:
                        # 400/403 error: Message is corrupted or illegal. DESTROY IT.
                        stats.record_failed(len(unsent))
                        logger.error("Message permanently rejected by Discord (4xx Error). Message abandoned.")
                        # We do NOT put unsent back in failed_messages

                    # Limit number of pending messages
                    if len(failed_messages) > MAX_FAILED_RETRY:
                        dropped = len(failed_messages) - MAX_FAILED_RETRY
                        failed_messages = failed_messages[-MAX_FAILED_RETRY:]
                        stats.record_dropped(dropped)
                        logger.warning(f"Retry queue full, {dropped} message(s) abandoned")

            # Periodic statistics log
            if time.time() - last_stats_log > STATS_LOG_INTERVAL:
                recv_min, sent_min = stats.get_messages_per_minute()
                req_min = stats.get_requests_per_minute()
                logger.info(
                    f"[STATS] Received: {recv_min:.1f}/min | Sent: {sent_min:.1f}/min | "
                    f"Requests: {req_min:.1f}/min | "
                    f"Queue: {message_queue.qsize()}/{MAX_QUEUE_SIZE} | "
                    f"Peak queue: {stats.peak_queue_size} | "
                    f"Lost: {stats.total_dropped} | "
                    f"Rate limits: {stats.total_rate_limits} (G:{stats.rate_limits_global}/S:{stats.rate_limits_shared}/U:{stats.rate_limits_user})"
                )
                last_stats_log = time.time()

            # Avoid spinning if nothing to do
            if not batch and not failed_messages:
                time.sleep(0.1)

        except Exception as e:
            logger.error(f"Worker error: {e}")
            time.sleep(1)


# =============================================================================
# FLASK ROUTES (HTTP ENDPOINTS)
# =============================================================================

@app.route('/message', methods=['GET', 'POST'])
def receive_message():
    """
    Endpoint that receives messages from Tot!

    Captures reception time IMMEDIATELY for accurate timestamp.
    Filters messages according to ALLOWED_CHANNELS if configured.
    Collects reception statistics.
    """
    try:
        # Capture reception time IMMEDIATELY
        # This time will be displayed in Discord, not the send time
        received_at = datetime.now()

        data = {
            'message': request.args.get('message', ''),
            'sender': request.args.get('sender', 'Unknown'),
            'character': request.args.get('character', ''),
            'radius': request.args.get('radius', 'say'),
            'location': request.args.get('location', ''),
            'channel': request.args.get('channel', ''),
            'received_at': received_at,  # Store reception time
        }

        # Filter by channel if configured
        if ALLOWED_CHANNELS and data['channel'] not in ALLOWED_CHANNELS:
            logger.info(f"[Channel {data['channel']} ignored] {data['sender']}: {data['message'][:50] if data['message'] else '(empty)'}")
            return {"status": "ignored"}, 200

        # Record reception in stats
        stats.record_received()

        # Update queue peak
        current_size = message_queue.qsize()
        stats.update_queue_size(current_size)

        logger.info(f"[{data['radius']}] {data['sender']}: {data['message'][:80] if data['message'] else '(empty)'}")

        # Check if queue is not full
        if current_size >= MAX_QUEUE_SIZE:
            stats.record_dropped()
            logger.warning(f"Queue full ({MAX_QUEUE_SIZE}), message ignored")
            return {"status": "queue_full"}, 503

        if data['message'] and data['message'].strip():
            message_queue.put(data)

        return {"status": "ok"}, 200

    except Exception as e:
        # Log detailed error server-side but return a generic message to the client
        logger.error(f"Error in /message endpoint: {e}", exc_info=True)
        return {"error": "Internal server error"}, 500


@app.route('/', methods=['GET'])
def health_check():
    """
    Monitoring page with detailed statistics.
    Displays bridge health status and real-time metrics.
    Auto-refresh every 5 seconds.
    """
    queue_size = message_queue.qsize()
    recv_min, sent_min = stats.get_messages_per_minute()
    req_min = stats.get_requests_per_minute()
    avg_latency = stats.get_average_latency()
    status, status_color = stats.get_health_status(queue_size, MAX_QUEUE_SIZE)
    channels_info = ", ".join(ALLOWED_CHANNELS) if ALLOWED_CHANNELS else "All"

    # Colors for gauges
    queue_percent = (queue_size / MAX_QUEUE_SIZE) * 100 if MAX_QUEUE_SIZE > 0 else 0
    queue_color = "#43b581" if queue_percent < 50 else "#faa61a" if queue_percent < 80 else "#f04747"

    # ASCII progress bar for queue
    bar_length = 20
    filled = int(bar_length * queue_percent / 100)
    queue_bar = "█" * filled + "░" * (bar_length - filled)

    # Rate limit breakdown display
    rate_limit_breakdown = f"Global: {stats.rate_limits_global} | Shared: {stats.rate_limits_shared} | User: {stats.rate_limits_user}"

    # Alert if problem detected
    alert_html = ""
    if status == "CRITICAL":
        alert_html = """
        <div style="background: #f04747; padding: 15px; border-radius: 8px; margin: 10px 0;">
            <strong>⚠️ ALERT:</strong> Queue almost full! Risk of message loss.
            <br>→ Increase MAX_QUEUE_SIZE or reduce BATCH_DELAY
        </div>
        """
    elif stats.rate_limits_global > 0:
        alert_html = f"""
        <div style="background: #f04747; padding: 15px; border-radius: 8px; margin: 10px 0;">
            <strong>🚨 CRITICAL:</strong> {stats.rate_limits_global} GLOBAL rate limit(s) hit!
            <br>→ Reduce traffic immediately or risk being banned
        </div>
        """
    elif stats.total_dropped > 0:
        alert_html = f"""
        <div style="background: #faa61a; padding: 15px; border-radius: 8px; margin: 10px 0;">
            <strong>⚠️ WARNING:</strong> {stats.total_dropped} message(s) lost since startup.
        </div>
        """

    return f"""
    <html>
    <head>
        <title>Tot Discord Bridge - Monitoring</title>
        <meta charset="utf-8">
        <meta http-equiv="refresh" content="5">
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; padding: 20px; background: #2c2f33; color: white; }}
            .card {{ background: #23272a; padding: 15px; border-radius: 8px; margin: 10px 0; }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }}
            .stat {{ text-align: center; }}
            .stat-value {{ font-size: 2em; font-weight: bold; }}
            .stat-label {{ color: #72767d; font-size: 0.9em; }}
            code {{ background: #1e2124; padding: 8px; display: block; border-radius: 4px; }}
            .bar {{ font-family: monospace; letter-spacing: 2px; }}
            h3 {{ margin-top: 0; color: #7289da; }}
        </style>
    </head>
    <body>
        <h1>🎮 Tot Discord Bridge</h1>

        <div class="card" style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <strong>Status:</strong> <span style="color: {status_color};">● {status}</span>
            </div>
            <div style="color: #72767d;">
                Uptime: {stats.get_uptime()}
            </div>
        </div>

        {alert_html}

        <div class="grid">
            <div class="card stat">
                <div class="stat-value" style="color: #7289da;">{recv_min:.1f}</div>
                <div class="stat-label">Messages received/min</div>
            </div>
            <div class="card stat">
                <div class="stat-value" style="color: #43b581;">{sent_min:.1f}</div>
                <div class="stat-label">Messages sent/min</div>
            </div>
            <div class="card stat">
                <div class="stat-value" style="color: #faa61a;">{req_min:.1f}</div>
                <div class="stat-label">Discord requests/min</div>
            </div>
            <div class="card stat">
                <div class="stat-value" style="color: {queue_color};">{queue_size}</div>
                <div class="stat-label">Current queue</div>
            </div>
            <div class="card stat">
                <div class="stat-value">{avg_latency*1000:.0f}ms</div>
                <div class="stat-label">Average latency</div>
            </div>
        </div>

        <div class="card">
            <h3>📊 Queue</h3>
            <p class="bar" style="font-size: 1.2em;">[{queue_bar}] {queue_percent:.1f}%</p>
            <p><strong>Current:</strong> {queue_size} / {MAX_QUEUE_SIZE}</p>
            <p><strong>Historical peak:</strong> {stats.peak_queue_size} {f"(at {stats.peak_queue_time.strftime('%H:%M:%S')})" if stats.peak_queue_time else ""}</p>
            <p><strong>Peak messages/min:</strong> {stats.peak_messages_per_minute:.1f}</p>
        </div>

        <div class="card">
            <h3>📈 Totals since startup</h3>
            <div class="grid">
                <p><strong>Received:</strong> {stats.total_received}</p>
                <p><strong>Sent:</strong> {stats.total_sent}</p>
                <p><strong>Requests:</strong> {stats.total_requests}</p>
                <p><strong style="color: #f04747;">Lost:</strong> {stats.total_dropped}</p>
            </div>
        </div>

        <div class="card">
            <h3>⏱️ Rate Limits</h3>
            <p><strong>Total:</strong> {stats.total_rate_limits}</p>
            <p><strong>Breakdown:</strong> {rate_limit_breakdown}</p>
            <p style="color: #72767d; font-size: 0.85em;">
                Global = critical (reduce traffic!) | Shared = channel congestion | User = too fast
            </p>
        </div>

        <div class="card">
            <h3>⚙️ Configuration</h3>
            <p><strong>Channels:</strong> {channels_info}</p>
            <p><strong>Batch:</strong> {BATCH_DELAY}s / {MAX_BATCH_SIZE} msg</p>
            <p><strong>Rate limit protection:</strong> {INTER_REQUEST_DELAY}s between requests{f", max {MAX_DISCORD_REQUESTS} req/cycle" if MAX_DISCORD_REQUESTS > 0 else ""}</p>
            <p><strong>Theoretical capacity:</strong> {int((60/BATCH_DELAY) * MAX_BATCH_SIZE)} msg/min</p>
        </div>

        <div class="card">
            <p><strong>URL for Tot!:</strong></p>
            <code>http://localhost:{PORT}/message</code>
            <p style="margin-top: 10px;"><strong>Stats API (JSON):</strong></p>
            <code>http://localhost:{PORT}/stats</code>
        </div>

        <p style="color: #72767d; font-size: 12px;">Auto-refresh every 5 seconds</p>
    </body>
    </html>
    """


@app.route('/stats', methods=['GET'])
def get_stats():
    """
    JSON endpoint for external monitoring.
    Useful for Grafana, monitoring scripts, alerts, etc.
    """
    return stats.to_dict(message_queue.qsize()), 200


# =============================================================================
# MAIN FUNCTION
# =============================================================================

def main():
    """
    Program entry point.
    """
    if not DISCORD_WEBHOOK_URL or "PASTE_YOUR_WEBHOOK" in DISCORD_WEBHOOK_URL:
        print("\n" + "=" * 50)
        print("  ERROR: Configure your Discord webhook!")
        print("  Open the script and modify DISCORD_WEBHOOK_URL")
        print("=" * 50 + "\n")
        input("Press Enter to exit...")
        return

    print("")
    print("=" * 50)
    print("   Tot! Chat -> Discord Bridge")
    print("   Optimized for 60 players")
    print("=" * 50)
    print(f"   Server    : http://localhost:{PORT}")
    print(f"   Tot URL   : http://localhost:{PORT}/message")
    print(f"   Monitoring: http://localhost:{PORT}/")
    print(f"   Stats JSON: http://localhost:{PORT}/stats")
    print(f"   Batch     : {BATCH_DELAY}s / {MAX_BATCH_SIZE} msg")
    print(f"   Rate limit: {INTER_REQUEST_DELAY}s delay{f', max {MAX_DISCORD_REQUESTS} req/cycle' if MAX_DISCORD_REQUESTS > 0 else ''}")
    print(f"   Max queue : {MAX_QUEUE_SIZE}")
    if ALLOWED_CHANNELS:
        print(f"   Channels  : {', '.join(ALLOWED_CHANNELS)}")
    else:
        print("   Channels  : All")
    print("=" * 50)
    print("")

    # Start worker in separate thread
    worker = threading.Thread(target=discord_worker, daemon=True)
    worker.start()
    logger.info("Discord worker started")

    # Start server
    try:
        from waitress import serve
        logger.info("Starting in production mode (Waitress)")
        serve(app, host='127.0.0.1', port=PORT, threads=8)  # 8 threads for 60 players
    except ImportError:
        logger.warning("Waitress not found, development mode (pip install waitress)")
        app.run(host='127.0.0.1', port=PORT, debug=False, threaded=True)


if __name__ == '__main__':
    main()
