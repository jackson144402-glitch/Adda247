import os

# Telegram API Configuration (my.telegram.org se lein)
API_ID = int(os.environ.get("API_ID", "26754022"))
API_HASH = os.environ.get("API_HASH", "1a0b65e7a4d48e08687c732bdc0f2cc4")

# Telegram Bot Token (@BotFather se lein)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8975478761:AAHr4KgkSsn0NyECvBkLfa8O_eehBTpWmbk")

# Admin Users (Numeric IDs)
ADMINS = [int(x) for x in os.environ.get("ADMINS", "8302836831").split()]

# Log Channel ID (Telegram Channel ID jahan logs jayenge e.g., -1001234567890)
PREMIUM_LOGS = int(os.environ.get("PREMIUM_LOGS", "-1004453613232"))

# Bot Branding & Extras
BOT_TEXT = os.environ.get("BOT_TEXT", "Adda247 Extractor Bot")
THUMB_URL = os.environ.get("THUMB_URL", "https://telegra.ph/file/c083204962660555088f6.jpg")
join = os.environ.get("JOIN_CHANNEL", "https://t.me/your_channel")