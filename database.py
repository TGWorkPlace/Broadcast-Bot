"""
database.py — Async MongoDB layer using Motor.
Collections:
  - users         : {user_id, username, first_name, joined_at}
  - channels      : {user_id, channel_id, channel_name, added_at}
                     Channels are scoped per-user: each user only ever
                     sees/manages the channels they personally added.
  - posts         : {post_id, user_id, created_at, messages: [{channel_id, message_id}]}
  - counters      : internal auto-increment for post_id
"""

import motor.motor_asyncio
from datetime import datetime, timezone
import os

MONGO_URI   = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME     = os.environ.get("MONGO_DB_NAME", "broadcast_bot")

_client: motor.motor_asyncio.AsyncIOMotorClient = None
_db = None


def get_db():
    return _db


async def init_db():
    global _client, _db
    _client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    _db = _client[DB_NAME]

    # Unique indexes
    await _db.users.create_index("user_id", unique=True)
    # A channel is unique per-owner, not globally — two different users
    # are each allowed to independently connect the same channel_id.
    await _db.channels.create_index([("user_id", 1), ("channel_id", 1)], unique=True)
    await _db.posts.create_index("post_id", unique=True)
    await _db.posts.create_index("user_id")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Users ───────────────────────────────────

async def add_user(user_id: int, username: str, first_name: str):
    await _db.users.update_one(
        {"user_id": user_id},
        {"$setOnInsert": {
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "joined_at": _now()
        }},
        upsert=True
    )


async def count_users() -> int:
    return await _db.users.count_documents({})


# ─── Channels (scoped per user_id) ───────────

async def add_channel(user_id: int, channel_id: int, channel_name: str):
    await _db.channels.update_one(
        {"user_id": user_id, "channel_id": channel_id},
        {"$set": {
            "user_id": user_id,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "added_at": _now()
        }},
        upsert=True
    )


async def get_channel(user_id: int, channel_id: int) -> dict | None:
    return await _db.channels.find_one(
        {"user_id": user_id, "channel_id": channel_id}, {"_id": 0}
    )


async def get_all_channels(user_id: int) -> list[dict]:
    """Returns only the channels that belong to this specific user."""
    cursor = _db.channels.find({"user_id": user_id}, {"_id": 0}).sort("channel_name", 1)
    return await cursor.to_list(length=None)


async def update_channel_name(user_id: int, channel_id: int, new_name: str):
    await _db.channels.update_one(
        {"user_id": user_id, "channel_id": channel_id},
        {"$set": {"channel_name": new_name}}
    )


async def remove_channel(user_id: int, channel_id: int):
    await _db.channels.delete_one({"user_id": user_id, "channel_id": channel_id})


async def count_channels(user_id: int | None = None) -> int:
    """Total channel count, or a single user's channel count if user_id is given."""
    query = {"user_id": user_id} if user_id is not None else {}
    return await _db.channels.count_documents(query)


# ─── Posts (scoped per user_id) ──────────────

async def _next_post_id() -> int:
    """Auto-increment post_id using a counters collection."""
    result = await _db.counters.find_one_and_update(
        {"_id": "post_id"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True
    )
    return result["seq"]


async def create_post(user_id: int) -> int:
    """Creates a post document owned by user_id and returns its post_id."""
    post_id = await _next_post_id()
    await _db.posts.insert_one({
        "post_id": post_id,
        "user_id": user_id,
        "created_at": _now(),
        "messages": []   # [{channel_id, message_id}, ...]
    })
    return post_id


async def save_post_message(post_id: int, channel_id: int, message_id: int):
    """Append a {channel_id, message_id} entry to the post's messages array."""
    await _db.posts.update_one(
        {"post_id": post_id},
        {"$push": {"messages": {"channel_id": channel_id, "message_id": message_id}}}
    )


async def get_post_messages(post_id: int) -> list[dict]:
    doc = await _db.posts.find_one({"post_id": post_id}, {"_id": 0})
    return doc.get("messages", []) if doc else []


async def get_post(post_id: int) -> dict | None:
    return await _db.posts.find_one({"post_id": post_id}, {"_id": 0})


async def get_all_posts(user_id: int) -> list[dict]:
    """Returns only the posts created by this specific user."""
    cursor = _db.posts.find({"user_id": user_id}, {"_id": 0}).sort("post_id", -1)
    return await cursor.to_list(length=None)


async def delete_post(post_id: int):
    await _db.posts.delete_one({"post_id": post_id})


async def count_posts(user_id: int | None = None) -> int:
    """Total post count, or a single user's post count if user_id is given."""
    query = {"user_id": user_id} if user_id is not None else {}
    return await _db.posts.count_documents(query)
