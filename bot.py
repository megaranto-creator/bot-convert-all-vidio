import os
import re
import logging
import asyncio
import tempfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import yt_dlp

# === KONFIGURASI ===
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ISI_TOKEN_BOT_KAMU_DISINI")
COOKIES_FILE = "/app/cookies.txt"
MAX_FILE_SIZE_MB = 50

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === HELPER ===
def detect_platform(url: str) -> str:
    patterns = {
        "instagram": r"(instagram\.com|instagr\.am)",
        "tiktok": r"(tiktok\.com|vm\.tiktok\.com)",
        "facebook": r"(facebook\.com|fb\.watch|fb\.com)",
        "youtube": r"(youtube\.com|youtu\.be)",
        "twitter": r"(twitter\.com|x\.com)",
    }
    for platform, pattern in patterns.items():
        if re.search(pattern, url, re.IGNORECASE):
            return platform
    return "unknown"

def is_valid_url(url: str) -> bool:
    return bool(re.match(r"https?://", url, re.IGNORECASE))

def cookies_exist() -> bool:
    return os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 0

# === DOWNLOAD ===
async def download_video(url: str, output_dir: str, quality: str = "best") -> dict:
    format_map = {
        "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "medium": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]",
        "low": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]",
        "audio": "bestaudio[ext=m4a]/bestaudio",
    }

    ydl_opts = {
        "format": format_map.get(quality, format_map["best"]),
        "outtmpl": os.path.join(output_dir, "%(title).50s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "max_filesize": MAX_FILE_SIZE_MB * 1024 * 1024,
    }

    if cookies_exist():
        ydl_opts["cookiefile"] = COOKIES_FILE
        logger.info("✅ Pakai cookies")
    else:
        logger.info("⚠️ Tanpa cookies")

    if quality == "audio":
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]

    loop = asyncio.get_event_loop()

    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return info

    info = await loop.run_in_executor(None, _download)

    files = os.listdir(output_dir)
    if not files:
        raise Exception("File tidak ditemukan setelah download")

    filepath = os.path.join(output_dir, files[0])
    file_size = os.path.getsize(filepath) / (1024 * 1024)

    return {
        "filepath": filepath,
        "title": info.get("title", "Video"),
        "file_size_mb": round(file_size, 2),
        "uploader": info.get("uploader", "Unknown"),
    }

# === COMMANDS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = "✅ Aktif" if cookies_exist() else "❌ Belum diset"
    text = (
        "👋 *Bot Video Downloader*\n\n"
        "📥 Platform yang didukung:\n"
        "• 📸 Instagram\n"
        "• 🎵 TikTok\n"
        "• 📘 Facebook\n"
        "• 🎬 YouTube\n"
        "• 🐦 Twitter / X\n\n"
        f"🍪 Status Cookies: {status}\n\n"
        "💡 Kirim link video langsung ke sini!\n\n"
        "⚙️ Commands:\n"
        "/start - Pesan ini\n"
        "/setcookies - Upload cookies (untuk video private)\n"
        "/cookiesstatus - Cek status cookies\n"
        "/deletecookies - Hapus cookies"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cookies_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if cookies_exist():
        size = os.path.getsize(COOKIES_FILE)
        await update.message.reply_text(
            f"🍪 *Status Cookies*\n\n"
            f"✅ Cookies aktif\n"
            f"📦 Ukuran: {size} bytes\n\n"
            f"Video private bisa didownload!",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "🍪 *Status Cookies*\n\n"
            "❌ Cookies belum diset\n\n"
            "Kirim /setcookies untuk upload cookies.",
            parse_mode="Markdown"
        )

async def set_cookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["waiting_cookies"] = True
    await update.message.reply_text(
        "🍪 *Upload Cookies*\n\n"
        "Kirim file `cookies.txt` sekarang.\n\n"
        "Cara export cookies:\n"
        "1. Install ekstensi *Get cookies.txt LOCALLY* di Chrome/Firefox\n"
        "2. Login ke Instagram/TikTok/FB di browser\n"
        "3. Buka tab platformnya → klik ekstensi → Export\n"
        "4. Kirim file `.txt` hasil export ke sini\n\n"
        "⚠️ Jangan share cookies ke siapapun!",
        parse_mode="Markdown"
    )

async def delete_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if cookies_exist():
        os.remove(COOKIES_FILE)
        await update.message.reply_text("🗑️ Cookies berhasil dihapus.")
    else:
        await update.message.reply_text("❌ Tidak ada cookies yang perlu dihapus.")

# === HANDLER FILE (COOKIES UPLOAD) ===
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("waiting_cookies"):
        await update.message.reply_text("⚠️ Kirim /setcookies dulu sebelum upload file cookies.")
        return

    doc = update.message.document
    if not doc.file_name.endswith(".txt"):
        await update.message.reply_text("❌ File harus berformat `.txt`")
        return

    msg = await update.message.reply_text("⏳ Menyimpan cookies...")

    try:
        file = await context.bot.get_file(doc.file_id)
        os.makedirs(os.path.dirname(COOKIES_FILE), exist_ok=True)
        await file.download_to_drive(COOKIES_FILE)
        context.user_data["waiting_cookies"] = False
        await msg.edit_text(
            "✅ *Cookies berhasil disimpan!*\n\n"
            "Sekarang bisa download video private.\n"
            "Cek status: /cookiesstatus",
            parse_mode="Markdown"
        )
    except Exception as e:
        await msg.edit_text(f"❌ Gagal simpan cookies: `{str(e)}`", parse_mode="Markdown")

# === HANDLER URL ===
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if not is_valid_url(url):
        await update.message.reply_text(
            "⚠️ Bukan link yang valid.\n"
            "Pastikan diawali `https://`",
            parse_mode="Markdown"
        )
        return

    platform = detect_platform(url)
    emoji = {
        "instagram": "📸", "tiktok": "🎵", "facebook": "📘",
        "youtube": "🎬", "twitter": "🐦", "unknown": "🌐"
    }.get(platform, "🌐")

    context.user_data["pending_url"] = url
    context.user_data["platform"] = platform

    keyboard = [
        [
            InlineKeyboardButton("🔥 Terbaik", callback_data="quality_best"),
            InlineKeyboardButton("📺 720p", callback_data="quality_medium"),
        ],
        [
            InlineKeyboardButton("📱 480p", callback_data="quality_low"),
            InlineKeyboardButton("🎵 Audio MP3", callback_data="quality_audio"),
        ],
        [InlineKeyboardButton("❌ Batal", callback_data="quality_cancel")],
    ]

    await update.message.reply_text(
        f"{emoji} *{platform.capitalize()}* terdeteksi\n\n"
        f"🎚️ Pilih kualitas:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# === CALLBACK KUALITAS ===
async def handle_quality_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "quality_cancel":
        await query.edit_message_text("❌ Download dibatalkan.")
        context.user_data.clear()
        return

    quality = query.data.replace("quality_", "")
    url = context.user_data.get("pending_url")

    if not url:
        await query.edit_message_text("⚠️ Session expired. Kirim ulang linknya ya!")
        return

    quality_label = {
        "best": "Kualitas Terbaik",
        "medium": "720p",
        "low": "480p",
        "audio": "Audio MP3"
    }.get(quality, quality)

    await query.edit_message_text(
        f"⏳ *Memproses...*\n\n"
        f"📥 Kualitas: {quality_label}\n"
        f"🍪 Cookies: {'✅' if cookies_exist() else '❌'}\n\n"
        f"Mohon tunggu...",
        parse_mode="Markdown"
    )

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            info = await download_video(url, tmpdir, quality)

            if info["file_size_mb"] > MAX_FILE_SIZE_MB:
                await query.edit_message_text(
                    f"⚠️ File terlalu besar ({info['file_size_mb']}MB).\n"
                    f"Batas {MAX_FILE_SIZE_MB}MB. Coba kualitas lebih rendah."
                )
                return

            caption = (
                f"✅ *Selesai!*\n\n"
                f"📌 {info['title'][:80]}\n"
                f"👤 {info['uploader']}\n"
                f"📦 {info['file_size_mb']} MB"
            )

            await query.edit_message_text("📤 Mengirim file...")

            if quality == "audio":
                with open(info["filepath"], "rb") as f:
                    await context.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=f,
                        caption=caption,
                        parse_mode="Markdown",
                        title=info["title"][:64],
                    )
            else:
                with open(info["filepath"], "rb") as f:
                    await context.bot.send_video(
                        chat_id=query.message.chat_id,
                        video=f,
                        caption=caption,
                        parse_mode="Markdown",
                        supports_streaming=True,
                    )

            await query.edit_message_text("✅ Video sudah dikirim di atas!")

    except yt_dlp.utils.DownloadError as e:
        err = str(e).lower()
        if "private" in err:
            msg = (
                "🔒 *Video Private!*\n\n"
                "Butuh cookies untuk download.\n"
                "Kirim /setcookies untuk setup."
            )
        elif "unavailable" in err or "removed" in err:
            msg = "❌ Video tidak tersedia atau sudah dihapus."
        elif "login" in err or "sign in" in err:
            msg = (
                "🔐 *Perlu Login!*\n\n"
                "Platform ini butuh cookies.\n"
                "Kirim /setcookies untuk setup."
            )
        else:
            msg = f"❌ Gagal download.\nError: `{str(e)[:200]}`"
        await query.edit_message_text(msg, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await query.edit_message_text(
            f"❌ Terjadi kesalahan:\n`{str(e)[:200]}`",
            parse_mode="Markdown"
        )

    finally:
        context.user_data.clear()

# === MAIN ===
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setcookies", set_cookies_command))
    app.add_handler(CommandHandler("cookiesstatus", cookies_status))
    app.add_handler(CommandHandler("deletecookies", delete_cookies))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(handle_quality_choice, pattern="^quality_"))

    logger.info("🤖 Bot Video Downloader berjalan...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
