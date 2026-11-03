"""
Configuration loader for Telegram Feed Aggregator Bot.
Supports environment variables and .env file loading.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if available
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Telegram API credentials (from https://my.telegram.org)
API_ID_RAW = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not API_ID_RAW or not API_HASH:
    print("[WARNING] API_ID or API_HASH is missing in environment/.env!", file=sys.stderr)
    API_ID = 0
else:
    try:
        API_ID = int(API_ID_RAW)
    except ValueError:
        print("[ERROR] API_ID must be an integer!", file=sys.stderr)
        API_ID = 0

# String session for deployment without interactive prompt (Telethon StringSession)
USER_SESSION_STRING = os.getenv("USER_SESSION_STRING", "").strip()

# Session file paths
USER_SESSION = os.getenv("USER_SESSION", "user_collector.session")
BOT_SESSION = os.getenv("BOT_SESSION", "bot_interface.session")

# Database path
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "feed_bot.db"))

# Admin ID for update management commands (/update, /check_updates)
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "0")
try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    ADMIN_ID = 0

# Target channel for forwarding (e.g. '@my_feed_channel' or '-1001234567890')
# Can also be configured dynamically per-user via /target command
TARGET_CHANNEL_ID = os.getenv("TARGET_CHANNEL_ID", "").strip()

# Auto-update settings
AUTO_UPDATE_CODE = os.getenv("AUTO_UPDATE_CODE", "false").lower() in ("true", "1", "yes")
CODE_CHECK_INTERVAL_HOURS = int(os.getenv("CODE_CHECK_INTERVAL_HOURS", "6"))
FOLDER_CHECK_INTERVAL_HOURS = int(os.getenv("FOLDER_CHECK_INTERVAL_HOURS", "12"))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
