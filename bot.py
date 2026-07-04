"""
Telegram Broadcast Bot - Pyrogram / Kurigram
Bot(Client) subclass pattern — handlers live in this file,
started via bot.run() which calls start() then idles.

This is a PUBLIC bot: every user manages their own private set of
channels and posts. Users never see or touch each other's channels —
everything is scoped by the user's own Telegram user_id.
"""

import asyncio
import logging
from datetime import datetime

import pytz
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from pyrogram.errors import FloodWait
from pyrogram.enums import ParseMode, ButtonStyle

import database as db
from config import API_ID, API_HASH, BOT_TOKEN, LOG_CHANNEL
from webserver import run_webserver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# In-memory session state per user
# ─────────────────────────────────────────────
user_states: dict = {}

# ─────────────────────────────────────────────
# Bot class
# ─────────────────────────────────────────────

class BroadcastBot(Client):

    def __init__(self):
        super().__init__(
            name="broadcast_bot",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
        )

    async def start(self, *args, **kwargs):
        # Newer kurigram versions call app.run() -> self.start(use_qr=..., except_ids=...).
        # Accept and forward any such kwargs to the base Client.start().
        await db.init_db()
        logger.info("Database initialized.")

        await super().start(*args, **kwargs)

        me = await self.get_me()
        logger.info(f"Bot started: @{me.username}")

        self._web_runner = await run_webserver()

        tz = pytz.timezone("Asia/Kolkata")
        now = datetime.now(tz).strftime("%d/%m/%Y %H:%M:%S")
        if LOG_CHANNEL:
            try:
                await self.send_message(LOG_CHANNEL, f"🚀 Bot restarted\n📅 {now} IST")
            except Exception as e:
                logger.warning(f"Startup log failed: {e}")

    async def stop(self, *args, **kwargs):
        if hasattr(self, "_web_runner"):
            await self._web_runner.cleanup()
        await super().stop(*args, **kwargs)
        logger.info("Bot stopped.")


app = BroadcastBot()

# ─────────────────────────────────────────────
# Button colour support (Bot API 9.4 / kurigram)
# ButtonStyle.PRIMARY -> blue, SUCCESS -> green, DANGER -> red
# ─────────────────────────────────────────────

COLOR_MAP = {
    "blue":    "primary",
    "primary": "primary",
    "green":   "success",
    "success": "success",
    "red":     "danger",
    "danger":  "danger",
}


def parse_buttons(text: str):
    """
    Parses one button per line.

    Formats supported:
      Name - https://link.com                -> normal (no colour) button
      Name - https://link.com - blue          -> coloured button (blue/green/red)

    Returns a list of dicts: {"name": ..., "url": ..., "style": <str|None>}
    """
    buttons = []
    for line in text.strip().splitlines():
        if " - " not in line:
            continue
        parts = [p.strip() for p in line.split(" - ")]
        if len(parts) < 2:
            continue

        name = parts[0]
        url = parts[1]
        style = None

        if len(parts) >= 3 and parts[2]:
            color_key = parts[2].lower()
            style = COLOR_MAP.get(color_key)  # unrecognised colour -> normal button

        if name and url.startswith("http"):
            buttons.append({"name": name, "url": url, "style": style})
    return buttons


def build_inline_keyboard(buttons: list):
    if not buttons:
        return None
    rows = []
    for b in buttons:
        kwargs = {"url": b["url"]}
        style = b.get("style")
        if style:
            # "style" is the Bot API 9.4 / kurigram field for button colour.
            # Requires a recent kurigram build; older clients simply ignore it.
            kwargs["style"] = style
        rows.append([InlineKeyboardButton(b["name"], **kwargs)])
    return InlineKeyboardMarkup(rows)


def build_channel_keyboard(channels: list, page: int, selected: set):
    """Keyboard for broadcast channel selection."""
    per_page = 10
    total = len(channels)
    total_pages = max(1, (total + per_page - 1) // per_page)
    start = page * per_page
    page_channels = channels[start:start + per_page]

    rows = []
    for ch in page_channels:
        ch_id = ch["channel_id"]
        tick = "✅ " if ch_id in selected else ""
        rows.append([InlineKeyboardButton(
            f"{tick}{ch['channel_name']}",
            callback_data=f"sel_ch:{ch_id}:{page}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"ch_page:{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"ch_page:{page+1}"))
    if nav:
        rows.append(nav)

    rows.append([
        InlineKeyboardButton("📤 Send Selected", callback_data="broadcast:selected"),
        InlineKeyboardButton("📢 Send to All",   callback_data="broadcast:all"),
    ])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="broadcast:cancel")])
    return InlineKeyboardMarkup(rows)


def build_del_channel_keyboard(channels: list, page: int, selected: set):
    """Keyboard for /del_channel — paginated multi-select with Delete button."""
    per_page = 10
    total = len(channels)
    total_pages = max(1, (total + per_page - 1) // per_page)
    start = page * per_page
    page_channels = channels[start:start + per_page]

    rows = []
    for ch in page_channels:
        ch_id = ch["channel_id"]
        tick = "🗑 " if ch_id in selected else ""
        rows.append([InlineKeyboardButton(
            f"{tick}{ch['channel_name']}",
            callback_data=f"dch_sel:{ch_id}:{page}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"dch_page:{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"dch_page:{page+1}"))
    if nav:
        rows.append(nav)

    selected_count = len(selected)
    delete_label = f"🗑 Delete ({selected_count} selected)" if selected_count else "🗑 Delete"
    rows.append([InlineKeyboardButton(delete_label, callback_data="dch_confirm")])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="dch_cancel")])
    return InlineKeyboardMarkup(rows)


async def log(client: Client, text: str):
    if LOG_CHANNEL:
        try:
            await client.send_message(LOG_CHANNEL, text)
        except Exception as e:
            logger.warning(f"Log failed: {e}")


async def send_post_to_chat(client: Client, chat_id, state: dict):
    text = state.get("post_text") or ""
    media = state.get("post_media")
    media_type = state.get("post_media_type")
    buttons = state.get("post_buttons", [])
    reply_markup = build_inline_keyboard(buttons)

    if media and media_type == "photo":
        msg = await client.send_photo(
            chat_id, media,
            caption=text or None,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=reply_markup
        )
    else:
        msg = await client.send_message(
            chat_id, text,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=False
        )
    return msg.id


# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────

@app.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    user = message.from_user
    await db.add_user(user.id, user.username or "", user.first_name or "")
    await message.reply(
        f"👋 Hello <b>{user.first_name}</b>!\n\n"
        "I am a <b>Broadcast Bot</b>.\n\n"
        "Connect your own channels and I'll help you post and broadcast "
        "to them — your channels are private to you and no other user can "
        "see them.\n\n"
        "Use /help to see what I can do.",
        parse_mode=enums.ParseMode.HTML
    )


# ─────────────────────────────────────────────
# /help
# ─────────────────────────────────────────────

@app.on_message(filters.command("help") & filters.private)
async def help_handler(client: Client, message: Message):
    await message.reply(
        "<b>📖 Commands</b>\n\n"
        "/post — Create and broadcast a post\n"
        "/add_channels — Add channels to the bot\n"
        "/list_channels — View your connected channels\n"
        "/del_channel — Remove channel(s) from the bot\n"
        "/refresh_chnl — Refresh channel names from Telegram\n"
        "/delete_post — Delete a broadcast post from your channels\n"
        "/stats — Your usage statistics\n"
        "/cancel — Cancel current operation\n\n"
        "<i>Your channels and posts are private — only you can see or manage them.</i>",
        parse_mode=enums.ParseMode.HTML
    )


# ─────────────────────────────────────────────
# /stats
# ─────────────────────────────────────────────

@app.on_message(filters.command("stats") & filters.private)
async def stats_handler(client: Client, message: Message):
    uid = message.from_user.id
    my_channels = await db.count_channels(uid)
    my_posts = await db.count_posts(uid)
    await message.reply(
        f"📊 <b>Your Statistics</b>\n\n"
        f"📡 Your channels: <b>{my_channels}</b>\n"
        f"📝 Your posts: <b>{my_posts}</b>",
        parse_mode=enums.ParseMode.HTML
    )


# ─────────────────────────────────────────────
# /cancel
# ─────────────────────────────────────────────

@app.on_message(filters.command("cancel") & filters.private)
async def cancel_handler(client: Client, message: Message):
    user_states.pop(message.from_user.id, None)
    await message.reply("✅ Operation cancelled.")


# ─────────────────────────────────────────────
# /skip  (used during post button step)
# ─────────────────────────────────────────────

@app.on_message(filters.command("skip") & filters.private)
async def skip_handler(client: Client, message: Message):
    uid = message.from_user.id
    state = user_states.get(uid)
    if not state or state.get("step") != "post_await_buttons":
        return await message.reply("⚠️ Nothing to skip right now.")
    state["post_buttons"] = []
    state["step"] = "post_preview"
    user_states[uid] = state
    await show_post_preview(client, message.chat.id, uid, state)


# ─────────────────────────────────────────────
# /add_channels
# ─────────────────────────────────────────────

@app.on_message(filters.command("add_channels") & filters.private)
async def add_channels_start(client: Client, message: Message):
    user_states[message.from_user.id] = {"step": "add_channel_await_forward"}
    await message.reply(
        "📡 <b>Add Channels</b>\n\n"
        "Please <b>forward any message</b> from the channel you want to add.\n\n"
        "<i>Make sure the bot is an admin in that channel first!</i>",
        parse_mode=enums.ParseMode.HTML
    )


# ─────────────────────────────────────────────
# /list_channels
# ─────────────────────────────────────────────

@app.on_message(filters.command("list_channels") & filters.private)
async def list_channels_handler(client: Client, message: Message):
    uid = message.from_user.id
    channels = await db.get_all_channels(uid)
    if not channels:
        return await message.reply("You haven't added any channels yet. Use /add_channels to add some.")
    lines = [
        f"<b>{i+1}.</b> {ch['channel_name']} — <code>{ch['channel_id']}</code>"
        for i, ch in enumerate(channels)
    ]
    await message.reply(
        "📡 <b>Your Connected Channels:</b>\n\n" + "\n".join(lines),
        parse_mode=enums.ParseMode.HTML
    )


# ─────────────────────────────────────────────
# /del_channel
# ─────────────────────────────────────────────

@app.on_message(filters.command("del_channel") & filters.private)
async def del_channel_start(client: Client, message: Message):
    uid = message.from_user.id
    channels = await db.get_all_channels(uid)
    if not channels:
        return await message.reply("You have no channels to remove. Use /add_channels to add some.")

    user_states[uid] = {
        "step": "del_channel_selecting",
        "del_ch_selected": set(),
        "del_ch_page": 0,
    }
    kb = build_del_channel_keyboard(channels, 0, set())
    await message.reply(
        "🗑 <b>Remove Channels</b>\n\n"
        "Tap a channel to select it for removal (🗑 = selected).\n"
        "You can select multiple. Then press <b>Delete</b>.",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=kb
    )


# ─────────────────────────────────────────────
# /refresh_chnl
# ─────────────────────────────────────────────

@app.on_message(filters.command("refresh_chnl") & filters.private)
async def refresh_channels_handler(client: Client, message: Message):
    uid = message.from_user.id
    channels = await db.get_all_channels(uid)
    if not channels:
        return await message.reply("You have no channels to refresh.")
    msg = await message.reply("🔄 Refreshing channel names...")
    updated = 0
    for ch in channels:
        try:
            chat = await client.get_chat(ch["channel_id"])
            if chat.title != ch["channel_name"]:
                await db.update_channel_name(uid, ch["channel_id"], chat.title)
                updated += 1
        except Exception as e:
            logger.warning(f"Refresh failed for {ch['channel_id']}: {e}")
    await msg.edit(
        f"✅ Refreshed. <b>{updated}</b> channel name(s) updated.",
        parse_mode=enums.ParseMode.HTML
    )


# ─────────────────────────────────────────────
# /post
# ─────────────────────────────────────────────

@app.on_message(filters.command("post") & filters.private)
async def post_start(client: Client, message: Message):
    user_states[message.from_user.id] = {
        "step": "post_await_content",
        "post_media": None,
        "post_media_type": None,
        "post_text": "",
        "post_buttons": [],
        "selected_channels": set(),
        "channel_page": 0,
        "preview_msg_id": None,
    }
    await message.reply(
        "✍️ <b>Create Post</b>\n\n"
        "Send the post content:\n"
        "• Text (HTML supported: <b>bold</b>, <i>italic</i>, <a href='...'>links</a>)\n"
        "• Photo\n"
        "• Photo with caption\n\n"
        "<i>Use /cancel to abort.</i>",
        parse_mode=enums.ParseMode.HTML
    )


# ─────────────────────────────────────────────
# /delete_post
# ─────────────────────────────────────────────

@app.on_message(filters.command("delete_post") & filters.private)
async def delete_post_start(client: Client, message: Message):
    uid = message.from_user.id
    posts = await db.get_all_posts(uid)
    if not posts:
        return await message.reply("You have no posts in the database.")
    rows = []
    for p in posts[:20]:
        ts = p.get("created_at", "")[:10]
        rows.append([InlineKeyboardButton(
            f"🗑 Post #{p['post_id']} ({ts})",
            callback_data=f"del_post:{p['post_id']}"
        )])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="del_cancel")])
    await message.reply(
        "🗑 <b>Delete Post</b>\n\nSelect a post to delete from your channels:",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(rows)
    )


# ─────────────────────────────────────────────
# General message handler (state machine)
# ─────────────────────────────────────────────

COMMANDS = [
    "start", "help", "post", "add_channels", "del_channel",
    "list_channels", "refresh_chnl", "delete_post",
    "stats", "cancel", "skip",
]

@app.on_message(filters.private & ~filters.command(COMMANDS))
async def message_state_handler(client: Client, message: Message):
    uid = message.from_user.id
    state = user_states.get(uid)
    if not state:
        return

    step = state.get("step")

    # ── Add channel: await forward ──
    if step == "add_channel_await_forward":
        if not message.forward_from_chat:
            return await message.reply(
                "⚠️ Please forward a message from a channel, not a user or group."
            )
        chat = message.forward_from_chat
        if chat.type.value != "channel":
            return await message.reply("⚠️ That doesn't seem to be a channel.")

        ch_id = chat.id
        ch_name = chat.title

        existing = await db.get_channel(uid, ch_id)
        if existing:
            return await message.reply(
                f"⚠️ <b>{ch_name}</b> is already added.",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("➕ Add More", callback_data="add_more_channel"),
                    InlineKeyboardButton("✅ Done",     callback_data="add_channel_done")
                ]])
            )

        try:
            member = await client.get_chat_member(ch_id, "me")
            if member.status.value not in ("administrator", "creator"):
                return await message.reply(
                    "⚠️ I'm not an admin in that channel. Please add me as admin first."
                )
        except Exception as e:
            return await message.reply(f"⚠️ Could not verify bot membership: {e}")

        await db.add_channel(uid, ch_id, ch_name)
        await log(client, f"📡 Channel added by {uid}: {ch_name} ({ch_id})")
        await message.reply(
            f"✅ <b>{ch_name}</b> added successfully!",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("➕ Add More", callback_data="add_more_channel"),
                InlineKeyboardButton("✅ Done",     callback_data="add_channel_done")
            ]])
        )

    # ── Post: await content ──
    elif step == "post_await_content":
        if message.photo:
            state["post_media"] = message.photo.file_id
            state["post_media_type"] = "photo"
            state["post_text"] = message.caption.html if message.caption else ""
        elif message.text:
            state["post_text"] = message.text.html
        else:
            return await message.reply("⚠️ Please send text or a photo (with optional caption).")

        state["step"] = "post_await_buttons"
        user_states[uid] = state
        await message.reply(
            "🔘 <b>Add Buttons</b>\n\n"
            "Send button links one per line:\n"
            "<code>Button Name - https://link.com</code>\n"
            "or with an optional colour (blue/green/red):\n"
            "<code>Button Name - https://link.com - blue</code>\n\n"
            "Example:\n"
            "<code>Visit Website - https://example.com - blue\n"
            "Join Channel - https://t.me/yourchannel - green\n"
            "My id - https://t.me/username - red\n"
            "Join - https://t.me/channel</code>\n\n"
            "Buttons with no colour given are shown as normal buttons.\n"
            "Send /skip to add no buttons.",
            parse_mode=enums.ParseMode.HTML
        )

    # ── Post: await buttons ──
    elif step == "post_await_buttons":
        if message.text:
            buttons = parse_buttons(message.text)
            if not buttons:
                return await message.reply(
                    "⚠️ Could not parse buttons. Use format:\n"
                    "<code>Button Name - https://link.com</code>\n"
                    "or\n"
                    "<code>Button Name - https://link.com - blue</code>\n\n"
                    "Or send /skip to add no buttons.",
                    parse_mode=enums.ParseMode.HTML
                )
            state["post_buttons"] = buttons

        state["step"] = "post_preview"
        user_states[uid] = state
        await show_post_preview(client, message.chat.id, uid, state)


async def show_post_preview(client: Client, chat_id: int, uid: int, state: dict):
    text = state.get("post_text") or ""
    media = state.get("post_media")
    media_type = state.get("post_media_type")
    buttons = state.get("post_buttons", [])
    post_markup = build_inline_keyboard(buttons)

    await client.send_message(chat_id, "👁 <b>Post Preview:</b>", parse_mode=enums.ParseMode.HTML)

    if media and media_type == "photo":
        await client.send_photo(
            chat_id, media,
            caption=text or None,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=post_markup
        )
    else:
        await client.send_message(
            chat_id, text,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=post_markup,
            disable_web_page_preview=False
        )

    await client.send_message(
        chat_id,
        "Ready to send? Press <b>Send</b> to choose channels.",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📤 Send",   callback_data="post_send"),
            InlineKeyboardButton("❌ Cancel", callback_data="post_cancel")
        ]])
    )
    user_states[uid] = state


# ─────────────────────────────────────────────
# Callback Query Handler
# NOTE: No filters.private — CallbackQuery has no .chat attribute
# ─────────────────────────────────────────────

@app.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    data = query.data
    state = user_states.get(uid, {})

    # ════════════════════════════════════════
    # del_channel callbacks
    # ════════════════════════════════════════

    if data.startswith("dch_sel:"):
        # Toggle selection of a channel for deletion
        parts = data.split(":")
        ch_id = int(parts[1])
        page  = int(parts[2])
        selected = state.get("del_ch_selected", set())
        if ch_id in selected:
            selected.discard(ch_id)
            await query.answer("Deselected")
        else:
            selected.add(ch_id)
            await query.answer("🗑 Selected for removal")
        state["del_ch_selected"] = selected
        state["del_ch_page"] = page
        user_states[uid] = state
        channels = await db.get_all_channels(uid)
        kb = build_del_channel_keyboard(channels, page, selected)
        await query.message.edit_reply_markup(kb)

    elif data.startswith("dch_page:"):
        page = int(data.split(":")[1])
        state["del_ch_page"] = page
        user_states[uid] = state
        channels = await db.get_all_channels(uid)
        kb = build_del_channel_keyboard(channels, page, state.get("del_ch_selected", set()))
        await query.message.edit_reply_markup(kb)
        await query.answer()

    elif data == "dch_confirm":
        selected = state.get("del_ch_selected", set())
        if not selected:
            await query.answer("⚠️ No channels selected!", show_alert=True)
            return

        deleted_names = []
        for ch_id in selected:
            ch = await db.get_channel(uid, ch_id)
            name = ch["channel_name"] if ch else str(ch_id)
            await db.remove_channel(uid, ch_id)
            deleted_names.append(name)

        user_states.pop(uid, None)
        names_text = "\n".join(f"• {n}" for n in deleted_names)
        await query.message.edit_text(
            f"✅ <b>{len(deleted_names)}</b> channel(s) removed:\n\n{names_text}",
            parse_mode=enums.ParseMode.HTML
        )
        await log(client, f"🗑 Channels removed by {uid}:\n{names_text}")
        await query.answer("Done!")

    elif data == "dch_cancel":
        user_states.pop(uid, None)
        await query.message.edit_text("❌ Channel removal cancelled.")
        await query.answer()

    # ════════════════════════════════════════
    # add_channel callbacks
    # ════════════════════════════════════════

    elif data == "add_more_channel":
        user_states[uid] = {"step": "add_channel_await_forward"}
        await query.message.edit_text(
            "📡 Forward a message from the next channel you want to add:"
        )
        await query.answer()

    elif data == "add_channel_done":
        user_states.pop(uid, None)
        channels = await db.get_all_channels(uid)
        await query.message.edit_text(
            f"✅ Done! <b>{len(channels)}</b> channel(s) connected.",
            parse_mode=enums.ParseMode.HTML
        )
        await query.answer()

    # ════════════════════════════════════════
    # Post flow callbacks
    # ════════════════════════════════════════

    elif data == "post_cancel":
        user_states.pop(uid, None)
        await query.message.edit_text("❌ Post creation cancelled.")
        await query.answer()

    elif data == "post_send":
        channels = await db.get_all_channels(uid)
        if not channels:
            await query.answer("No channels added! Use /add_channels first.", show_alert=True)
            return
        state["selected_channels"] = set()
        state["channel_page"] = 0
        state["step"] = "selecting_channels"
        user_states[uid] = state
        kb = build_channel_keyboard(channels, 0, set())
        await query.message.edit_text(
            "📡 <b>Select Channels</b>\n\nTap to select/deselect (✅ = selected):",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=kb
        )
        await query.answer()

    elif data.startswith("ch_page:"):
        page = int(data.split(":")[1])
        state["channel_page"] = page
        user_states[uid] = state
        channels = await db.get_all_channels(uid)
        kb = build_channel_keyboard(channels, page, state.get("selected_channels", set()))
        await query.message.edit_reply_markup(kb)
        await query.answer()

    elif data.startswith("sel_ch:"):
        parts = data.split(":")
        ch_id = int(parts[1])
        page  = int(parts[2])
        selected = state.get("selected_channels", set())
        if ch_id in selected:
            selected.discard(ch_id)
            await query.answer("❌ Deselected")
        else:
            selected.add(ch_id)
            await query.answer("✅ Selected")
        state["selected_channels"] = selected
        user_states[uid] = state
        channels = await db.get_all_channels(uid)
        kb = build_channel_keyboard(channels, page, selected)
        await query.message.edit_reply_markup(kb)

    # ════════════════════════════════════════
    # Broadcast callbacks
    # ════════════════════════════════════════

    elif data.startswith("broadcast:"):
        action = data.split(":")[1]
        channels = await db.get_all_channels(uid)

        if action == "cancel":
            user_states.pop(uid, None)
            await query.message.edit_text("❌ Broadcast cancelled.")
            await query.answer()
            return

        if action == "selected":
            targets = [ch for ch in channels if ch["channel_id"] in state.get("selected_channels", set())]
        else:
            targets = channels

        if not targets:
            await query.answer("No channels selected!", show_alert=True)
            return

        await query.message.edit_text(
            f"📤 Sending to <b>{len(targets)}</b> channel(s)...",
            parse_mode=enums.ParseMode.HTML
        )

        post_id = await db.create_post(uid)
        success, failed = 0, 0

        for ch in targets:
            try:
                msg_id = await send_post_to_chat(client, ch["channel_id"], state)
                await db.save_post_message(post_id, ch["channel_id"], msg_id)
                success += 1
                await asyncio.sleep(0.5)
            except FloodWait as e:
                await asyncio.sleep(e.value)
                try:
                    msg_id = await send_post_to_chat(client, ch["channel_id"], state)
                    await db.save_post_message(post_id, ch["channel_id"], msg_id)
                    success += 1
                except Exception as ex:
                    logger.error(f"Retry failed: {ex}")
                    failed += 1
            except Exception as e:
                logger.error(f"Broadcast to {ch['channel_id']} failed: {e}")
                failed += 1

        user_states.pop(uid, None)
        await query.message.edit_text(
            f"✅ <b>Broadcast Complete!</b>\n\n"
            f"📤 Sent: <b>{success}</b>\n"
            f"❌ Failed: <b>{failed}</b>\n"
            f"🆔 Post ID: <code>{post_id}</code>\n\n"
            f"<i>Use /delete_post to remove from channels.</i>",
            parse_mode=enums.ParseMode.HTML
        )
        await log(client, f"📢 Broadcast by {uid} | Post #{post_id} | ✅{success} ❌{failed}")
        await query.answer("Done!")

    # ════════════════════════════════════════
    # Delete post callbacks
    # ════════════════════════════════════════

    elif data.startswith("del_post:"):
        post_id = int(data.split(":")[1])

        # Ownership check — a user may only delete their own posts.
        post = await db.get_post(post_id)
        if not post or post.get("user_id") != uid:
            await query.answer("⛔ This isn't your post.", show_alert=True)
            return

        records = await db.get_post_messages(post_id)
        if not records:
            await query.answer("No message records found for this post.", show_alert=True)
            return
        await query.message.edit_text(
            f"🗑 Deleting Post #{post_id} from {len(records)} channel(s)..."
        )
        deleted, failed = 0, 0
        for rec in records:
            try:
                await client.delete_messages(rec["channel_id"], rec["message_id"])
                deleted += 1
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.warning(f"Delete failed {rec}: {e}")
                failed += 1
        await db.delete_post(post_id)
        await query.message.edit_text(
            f"✅ Deleted <b>{deleted}</b> message(s). Failed: <b>{failed}</b>.",
            parse_mode=enums.ParseMode.HTML
        )
        await log(client, f"🗑 Post #{post_id} deleted by {uid} | ✅{deleted} ❌{failed}")
        await query.answer()

    elif data == "del_cancel":
        await query.message.edit_text("❌ Deletion cancelled.")
        await query.answer()

    else:
        await query.answer()


# ─────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app.run()
