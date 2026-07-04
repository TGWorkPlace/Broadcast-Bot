# 📡 Telegram Broadcast Bot

A feature-rich Pyrogram/Kurigram-based Telegram broadcast bot. **Public bot** — any user can use it, and every user's channels and posts are private to them; nobody can see or manage another user's channels. Supports channel management, post creation with coloured inline buttons, paginated channel selection, and post deletion from all channels.

---

## 🗂 File Structure

```
.
├── main.py           # Entrypoint: runs bot + webserver together
├── bot.py            # All bot logic and handlers
├── database.py       # Async MongoDB layer (Motor), scoped per-user
├── config.py         # Reads env vars
├── webserver.py      # Aiohttp health-check server (port 8080)
├── requirements.txt
├── Dockerfile
└── .env.example
```

---

## ⚙️ Environment Variables

Copy `.env.example` to `.env` and fill in:

| Variable      | Description                                      |
|---------------|--------------------------------------------------|
| `API_ID`      | Telegram API ID (from my.telegram.org)           |
| `API_HASH`    | Telegram API Hash                                |
| `BOT_TOKEN`   | Bot token from @BotFather                        |
| `LOG_CHANNEL` | Channel ID for logs (e.g. `-1001234567890`)      |
| `MONGO_URI`   | MongoDB connection string                        |
| `MONGO_DB_NAME` | MongoDB database name                          |

There is no admin allowlist — this bot is public. Every user gets their own
private space for channels and posts.

---

## 🚀 Running Locally

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in your .env values
python main.py
```

---

## 🐳 Docker

```bash
docker build -t broadcast-bot .
docker run -d \
  -e API_ID=... \
  -e API_HASH=... \
  -e BOT_TOKEN=... \
  -e LOG_CHANNEL=... \
  -e MONGO_URI=... \
  -p 8080:8080 \
  broadcast-bot
```

---

## ☁️ Koyeb Deployment

1. Push to GitHub
2. Create a new Koyeb service → **Docker** or **Git** deployment
3. Set environment variables in Koyeb dashboard
4. Health check path: `/health` on port `8080`
5. Deploy!

---

## 📖 Commands (available to every user)

| Command          | Description                                      |
|------------------|--------------------------------------------------|
| `/post`          | Create and broadcast a post to your own channels |
| `/add_channels`  | Add channels (forward a message from the channel)|
| `/list_channels` | View your connected channels                     |
| `/del_channel`   | Remove one or more of your channels              |
| `/refresh_chnl`  | Re-fetch and update your channel names           |
| `/delete_post`   | Delete one of your posts from all its channels   |
| `/stats`         | View your own usage statistics                   |
| `/cancel`        | Cancel current operation                         |

---

## 🔄 Workflow

### Creating a Post
1. `/post` → Send image/text/image+caption
2. Send buttons, one per line, in either format:
   - `Button Name - https://url` (normal button)
   - `Button Name - https://url - blue` (coloured button)
   - or `/skip` for no buttons
3. Preview shown → Press **Send**
4. Paginated channel list appears — tap to select ✅
5. **Send Selected** or **Send to All** (both are limited to *your own* channels)

### Coloured Buttons
Uses Bot API 9.4 / kurigram's `style` field on `InlineKeyboardButton`. Add an
optional third field after the URL, separated by ` - `:

| Colour keyword     | Rendered as     |
|---------------------|-----------------|
| `blue` / `primary`  | Blue (Primary)  |
| `green` / `success` | Green (Success) |
| `red` / `danger`    | Red (Danger)    |
| *(omitted)*          | Normal button   |

Example:
```
Visit Website - https://example.com - blue
Join Channel - https://t.me/yourchannel - green
My id - https://t.me/username - red
Join - https://t.me/channel
```
The last line has no colour, so it renders as a normal button.

> Note: button colours require Bot API 9.4 support in your `kurigram`
> version and a recent Telegram client. Older clients just show a normal
> button and ignore the colour.

### Adding Channels
1. `/add_channels`
2. Forward any message from the target channel
3. Bot verifies it's an admin, saves the channel under your user ID
4. **Add More** or **Done**

### Deleting Posts
1. `/delete_post`
2. Select a post from *your* list
3. Bot deletes the message from every channel it was sent to

---

## 🗄 Database Schema (MongoDB)

| Collection | Fields                                                     |
|------------|-------------------------------------------------------------|
| `users`    | user_id, username, first_name, joined_at                    |
| `channels` | user_id, channel_id, channel_name, added_at (unique per user+channel) |
| `posts`    | post_id, user_id, created_at, messages: [{channel_id, message_id}] |
| `counters` | internal auto-increment for post_id                          |

Channels and posts are always scoped to `user_id` in every query, so one
user's data is never visible or editable by another user.
