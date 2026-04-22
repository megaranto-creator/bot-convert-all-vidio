import os
import re
import logging
import asyncio
import tempfile
import requests
from telegram import Update, InputMediaPhoto
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)
import yt_dlp

# === KONFIGURASI ===
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ISI_TOKEN_BOT_KAMU_DISINI")
COOKIES_FILE = "/app/data/cookies.txt"
MAX_FILE_SIZE_MB = 1000

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === HELPER ===
def detect_platform(url):
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

def is_valid_url(url):
    return bool(re.match(r"https?://", url, re.IGNORECASE))

def cookies_exist():
    return os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 0

def clean_text(text):
    return text.replace('*','').replace('_','').replace('`','').replace('[','').replace(']','')

# === DOWNLOAD VIDEO (tetap sama seperti sebelumnya) ===
async def download_video(url, output_dir):
    ydl_opts = {
        "format": "best[height<=1080][ext=mp4]/best[height<=1080]/best[ext=mp4]/best",
        "outtmpl": os.path.join(output_dir, "%(title).50s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": MAX_FILE_SIZE_MB * 1024 * 1024,
    }
    if cookies_exist():
        ydl_opts["cookiefile"] = COOKIES_FILE

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
        "is_image": info.get("ext") in ["jpg", "jpeg", "png", "webp"],
    }

# === DOWNLOAD AUDIO BARU ===
async def download_audio(url, output_dir):
    ydl_opts = {
        "format": "bestaudio/best",           # ambil audio terbaik
        "outtmpl": os.path.join(output_dir, "%(title).80s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extract_audio": True,                # ekstrak audio
        "audio_format": "mp3",                # convert ke MP3
        "audio_quality": "0",                 # 0 = terbaik
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "0",
        }],
    }
    if cookies_exist():
        ydl_opts["cookiefile"] = COOKIES_FILE

    loop = asyncio.get_event_loop()
    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return info

    info = await loop.run_in_executor(None, _download)

    files = [f for f in os.listdir(output_dir) if f.endswith(('.mp3', '.m4a', '.opus', '.wav'))]
    if not files:
        raise Exception("File audio tidak ditemukan")

    filepath = os.path.join(output_dir, files[0])
    file_size = os.path.getsize(filepath) / (1024 * 1024)

    return {
        "filepath": filepath,
        "title": info.get("title", "Audio"),
        "file_size_mb": round(file_size, 2),
        "uploader": info.get("uploader", "Unknown"),
        "duration": info.get("duration"),
    }

# === CEK MEDIA INFO & DOWNLOAD GAMBAR (tetap sama) ===
async def get_media_info(url):
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
    }
    if cookies_exist():
        ydl_opts["cookiefile"] = COOKIES_FILE

    loop = asyncio.get_event_loop()
    def _get_info():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)
    return await loop.run_in_executor(None, _get_info)

async def download_images(url, output_dir):
    # ... (kode download_images kamu tetap sama, saya tidak ubah supaya ringkas)
    # Silakan copy-paste fungsi download_images dari kode lama kamu di sini
    pass  # ← ganti dengan kode download_images kamu yang lama

# === COMMANDS ===
async def start(update, context):
    status = "✅ Aktif" if cookies_exist() else "❌ Belum diset"
    text = (
        "👋 *Bot Media Downloader*\n\n"
        "📥 Platform yang didukung:\n"
        "• 📸 Instagram (Video & Foto)\n"
        "• 🎵 TikTok (Video, Foto, & **Audio**)\n"
        "• 📘 Facebook\n"
        "• 🎬 YouTube\n"
        "• 🐦 Twitter / X\n\n"
        "⚡ Kirim link biasa → Video/Foto otomatis\n"
        "🎧 Kirim `/audio` + link → Download **Audio Only** (MP3)\n\n"
        f"🍪 Cookies: {status}\n\n"
        "⚙️ Commands:\n"
        "/start - Pesan ini\n"
        "/audio - Download audio (contoh: /audio https://tiktok.com/...)\n"
        "/setcookies - Upload cookies (konten private)\n"
        "/cookiesstatus - Cek status cookies\n"
        "/deletecookies - Hapus cookies"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def audio_command(update, context):
    if not context.args:
        await update.message.reply_text("⚠️ Cara pakai:\n`/audio https://vm.tiktok.com/xxxxxx/`", parse_mode="Markdown")
        return

    url = context.args[0].strip()
    if not is_valid_url(url):
        await update.message.reply_text("⚠️ Link tidak valid.")
        return

    msg = await update.message.reply_text("🎧 Mendownload audio...")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = await download_audio(url, tmpdir)
            safe_title = clean_text(result["title"][:80])
            safe_uploader = clean_text(result["uploader"])
            caption = f"🎵 {safe_title}\n👤 {safe_uploader}\n📦 {result['file_size_mb']} MB"

            await msg.edit_text("📤 Mengirim audio...")
            with open(result["filepath"], "rb") as f:
                await context.bot.send_audio(
                    chat_id=update.message.chat_id,
                    audio=f,
                    caption=caption,
                    title=safe_title,
                    performer=safe_uploader,
                )
            await msg.edit_text("✅ Audio berhasil dikirim!")
    except Exception as e:
        logger.error(f"Error download audio: {e}", exc_info=True)
        await msg.edit_text(f"❌ Gagal download audio:\n{str(e)[:300]}")

# ... (fungsi cookies_status, set_cookies_command, delete_cookies, handle_document tetap sama)

async def handle_url(update, context):
    url = update.message.text.strip()
    if not is_valid_url(url):
        await update.message.reply_text("⚠️ Bukan link yang valid.")
        return

    platform = detect_platform(url)
    emoji = {"instagram": "📸", "tiktok": "🎵", "facebook": "📘", "youtube": "🎬", "twitter": "🐦", "unknown": "🌐"}.get(platform, "🌐")

    msg = await update.message.reply_text(f"{emoji} Mendownload dari {platform.capitalize()}...")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Coba download sebagai video dulu
            try:
                info = await download_video(url, tmpdir)
                # ... (kode send_video kamu yang lama tetap sama)
                # (saya skip bagian ini supaya tidak terlalu panjang, copy dari kode lama kamu)

            except yt_dlp.utils.DownloadError as e:
                err = str(e).lower()
                if "no video" in err or "image" in err or "photo" in err:
                    # ... (kode download gambar kamu yang lama)
                    pass
                elif any(x in err for x in ["private", "login", "sign in"]):
                    await msg.edit_text("🔒 Konten private! Setup cookies dulu: /setcookies")
                else:
                    await msg.edit_text(f"❌ Gagal: {str(e)[:200]}")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await msg.edit_text(f"❌ Terjadi kesalahan:\n{str(e)[:200]}")

# === MAIN ===
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("audio", audio_command))          # ← BARU
    app.add_handler(CommandHandler("setcookies", set_cookies_command))
    app.add_handler(CommandHandler("cookiesstatus", cookies_status))
    app.add_handler(CommandHandler("deletecookies", delete_cookies))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

    logger.info("Bot Media Downloader berjalan... (dengan fitur Audio TikTok)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
