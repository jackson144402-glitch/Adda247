import logging
import os
import time
import httpx

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("LioBot")

app = Client(
    "lio_interactive_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
)

USER_DATA = {}
TIMEOUT = 30

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://www.adda247.com",
    "Referer": "https://www.adda247.com/",
    "X-Auth-Token": "fpoa43edty5",
    "x-app-id": "adda247",
    "client-id": "adda247",
    "appVersion": "2.0",
}


def safe_get(obj, *keys, default=None):
    try:
        for key in keys:
            if obj is None:
                return default
            obj = obj.get(key)
        return default if obj is None else obj
    except (AttributeError, KeyError, TypeError):
        return default


def authorized(message: Message) -> bool:
    return not config.OWNER_ID or message.from_user.id == config.OWNER_ID


async def get_json(url, headers):
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=True,
        ) as client:
            response = await client.get(url, headers=headers)

            logger.info(
                "GET %s -> %s",
                url,
                response.status_code,
            )

            if response.status_code != 200:
                logger.error(
                    "API response: %s",
                    response.text[:500],
                )
                return None

            return response.json()

    except httpx.HTTPError as exc:
        logger.error("HTTP error: %s", exc)
        return None
    except ValueError:
        logger.error("Server returned non-JSON data")
        return None
    except Exception:
        logger.exception("Unexpected request error")
        return None


def batches_keyboard(packages, page=0):
    per_page = 8
    start = page * per_page
    items = packages[start:start + per_page]

    rows = []

    for index, package in enumerate(items, start=start):
        title = (
            safe_get(package, "title")
            or safe_get(package, "packageName")
            or safe_get(package, "name")
            or "Untitled Batch"
        )
        title = str(title)[:45]

        rows.append([
            InlineKeyboardButton(
                f"📚 {title}",
                callback_data=f"batch:{index}",
            )
        ])

    navigation = []

    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                "⬅️ Prev",
                callback_data=f"batchpage:{page - 1}",
            )
        )

    if (page + 1) * per_page < len(packages):
        navigation.append(
            InlineKeyboardButton(
                "Next ➡️",
                callback_data=f"batchpage:{page + 1}",
            )
        )

    if navigation:
        rows.append(navigation)

    rows.append([
        InlineKeyboardButton("❌ Close", callback_data="close")
    ])

    return InlineKeyboardMarkup(rows)


@app.on_message(filters.command("start"))
async def start_handler(_, message: Message):
    await message.reply_text(
        "🦁 <b>Lio Interactive Bot</b>\n\n"
        "Use <code>/adda</code> to authenticate and view "
        "authorized purchased-batch metadata.",
        parse_mode=ParseMode.HTML,
    )


@app.on_message(filters.command("cancel"))
async def cancel_handler(_, message: Message):
    USER_DATA.pop(message.from_user.id, None)
    await message.reply_text("❌ Current session cancelled.")


@app.on_message(filters.command("adda"))
async def adda_handler(_, message: Message):
    if not authorized(message):
        await message.reply_text("❌ You are not authorized.")
        return

    user_id = message.from_user.id

    USER_DATA[user_id] = {
        "state": "WAITING_LOGIN",
        "packages": [],
        "headers": None,
        "jwt": None,
    }

    status = await message.reply_text(
        "🔐 <b>ADDA247 LOGIN</b>\n\n"
        "Send your credentials in this format:\n"
        "<code>email*password</code>\n\n"
        "Your credential message will be deleted after processing "
        "and will NOT be forwarded to a log channel.\n\n"
        "Use /cancel to stop.",
        parse_mode=ParseMode.HTML,
    )

    USER_DATA[user_id]["status_message_id"] = status.id


@app.on_message(
    filters.text & ~filters.command(["start", "adda", "cancel"])
)
async def login_handler(_, message: Message):
    user_id = message.from_user.id
    data = USER_DATA.get(user_id)

    if not data or data.get("state") != "WAITING_LOGIN":
        return

    if "*" not in message.text:
        await message.reply_text(
            "❌ Invalid format.\n\n"
            "Use: <code>email*password</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    email, password = message.text.strip().split("*", 1)

    try:
        await message.delete()
    except Exception:
        pass

    try:
        status = await app.get_messages(
            message.chat.id,
            data["status_message_id"],
        )
        await status.edit_text("🔄 <b>Logging in...</b>", parse_mode=ParseMode.HTML)
    except Exception:
        status = await message.reply_text("🔄 Logging in...")

    headers = BASE_HEADERS.copy()

    login_payload = {
        "email": email,
        "providerName": "email",
        "sec": password,
    }

    # Do not retain credentials after this request.
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(
                "https://userapi.adda247.com/login?src=aweb",
                headers=headers,
                json=login_payload,
            )

            logger.info(
                "Login response status: %s",
                response.status_code,
            )

            if response.status_code != 200:
                logger.error(
                    "Login response: %s",
                    response.text[:500],
                )
                await status.edit_text(
                    "❌ <b>Login failed.</b>\n\n"
                    "The provider rejected the authentication request.",
                    parse_mode=ParseMode.HTML,
                )
                USER_DATA.pop(user_id, None)
                return

            login_data = response.json()

    except Exception:
        logger.exception("Login error")
        await status.edit_text(
            "❌ <b>Login failed.</b>\n\n"
            "Please try again.",
            parse_mode=ParseMode.HTML,
        )
        USER_DATA.pop(user_id, None)
        return
    finally:
        del email
        del password
        del login_payload

    jwt = safe_get(login_data, "jwtToken")

    if not jwt:
        await status.edit_text(
            "❌ <b>Login failed.</b>\n\n"
            "No authentication token was returned.",
            parse_mode=ParseMode.HTML,
        )
        USER_DATA.pop(user_id, None)
        return

    headers["X-Jwt-Token"] = jwt

    data["headers"] = headers
    data["jwt"] = jwt

    await status.edit_text(
        "🔄 <b>Loading purchased batches...</b>",
        parse_mode=ParseMode.HTML,
    )

    # Only use the valid purchased-package endpoint.
    # The old /api/v1/my/purchase fallback that returned HTTP 400
    # is intentionally removed.
    url = (
        "https://store.adda247.com/api/v2/ppc/package/purchased"
        "?pageNumber=0&pageSize=100&src=aweb"
    )

    package_data = await get_json(url, headers)

    if not package_data:
        await status.edit_text(
            "❌ <b>Could not load purchased batches.</b>\n\n"
            "Check the server response in your terminal logs.",
            parse_mode=ParseMode.HTML,
        )
        USER_DATA.pop(user_id, None)
        return

    packages = (
        safe_get(package_data, "data", "packages")
        or safe_get(package_data, "data", "items")
        or safe_get(package_data, "data")
        or safe_get(package_data, "packages")
        or []
    )

    if not isinstance(packages, list) or not packages:
        await status.edit_text(
            "📦 <b>No purchased batches returned.</b>",
            parse_mode=ParseMode.HTML,
        )
        USER_DATA.pop(user_id, None)
        return

    data["packages"] = packages
    data["state"] = "BATCH_SELECTION"

    await status.edit_text(
        "📚 <b>YOUR PURCHASED BATCHES</b>\n\n"
        f"Total batches: <b>{len(packages)}</b>\n\n"
        "Select a batch:",
        parse_mode=ParseMode.HTML,
        reply_markup=batches_keyboard(packages),
    )


@app.on_callback_query()
async def callback_handler(_, query: CallbackQuery):
    user_id = query.from_user.id
    data = USER_DATA.get(user_id)

    if not data:
        await query.answer("Session expired. Use /adda again.", show_alert=True)
        return

    try:
        action = query.data

        if action == "close":
            USER_DATA.pop(user_id, None)
            await query.message.edit_text("✅ Session closed.")
            await query.answer()
            return

        if action.startswith("batchpage:"):
            page = int(action.split(":", 1)[1])
            await query.message.edit_reply_markup(
                batches_keyboard(data["packages"], page)
            )
            await query.answer()
            return

        if action.startswith("batch:"):
            index = int(action.split(":", 1)[1])
            package = data["packages"][index]

            title = (
                safe_get(package, "title")
                or safe_get(package, "packageName")
                or safe_get(package, "name")
                or "Untitled Batch"
            )

            package_id = (
                safe_get(package, "packageId")
                or safe_get(package, "id")
            )

            data["selected_package"] = package

            await query.message.edit_text(
                "📚 <b>SELECTED BATCH</b>\n\n"
                f"<b>{title}</b>\n\n"
                f"Package ID: <code>{package_id or 'N/A'}</code>\n\n"
                "The authenticated package metadata was loaded.\n"
                "Protected file/stream URLs are not exported by this version.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "⬅️ Batches",
                            callback_data="back:batches",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "❌ Close",
                            callback_data="close",
                        )
                    ],
                ]),
            )
            await query.answer()
            return

        if action == "back:batches":
            await query.message.edit_text(
                "📚 <b>YOUR PURCHASED BATCHES</b>\n\nSelect a batch:",
                parse_mode=ParseMode.HTML,
                reply_markup=batches_keyboard(data["packages"]),
            )
            await query.answer()
            return

        await query.answer()

    except Exception:
        logger.exception("Callback error")
        await query.answer(
            "Something went wrong.",
            show_alert=True,
        )


print("🚀 Lio Interactive Bot Started...")
app.run()
