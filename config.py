"""
Configuration - reads from environment variables
"""
import os

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", 0)) if os.environ.get("LOG_CHANNEL") else None

# NOTE: This bot is public — every user manages their own set of channels
# and posts, isolated from everyone else. There is no admin allowlist.

# MongoDB
MONGO_URI    = os.environ.get("MONGO_URI", "")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "broadcast_bot")

# URL shortener integration (external API from the Shortener bot project)
# SHORTENER_API_URL should point at the "/api" endpoint, e.g.
# https://domain.app/api
SHORTENER_API_URL = os.environ.get("SHORTENER_API_URL", "").rstrip("/")
SHORTENER_API_KEY = os.environ.get("SHORTENER_API_KEY", "")
