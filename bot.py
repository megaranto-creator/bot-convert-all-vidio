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
    return re.sub(r'[*_`[\]]', '', str(text))[:200]

# === MEDIA INFO ===
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

def is_slideshow(info):
    if info.get("extractor_key") != "TikTok":
        return False
    if "entries" in info and len(info.get("entries", [])) > 1:
        return True
    formats = info.get("formats", [])
    has_video = any(f.get("vcodec") != "none" for f in formats if f.get("vcodec"))
    has_image = any(f.get("ext") in ("jpg", "jpeg", "png", "webp") for f in formats)
    return has_image and not has_video

# === DOWNLOAD FUNCTIONS ===
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
    filepath = os.path.join(output_dir, files[0])
    file_size = os.path.getsize(filepath) / (1024 * 1024)

    return {
        "filepath": filepath,
        "title": info.get("title", "Video"),
        "file_size_mb": round(file_size, 2),
        "uploader": info.get("uploader", "Unknown"),
    }

async def download_audio(url, output_dir):
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(output_dir, "%(title).80s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extract_audio": True,
        "audio_format": "mp3",
        "audio_quality": "0",
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

    files = [f for f in os.listdir(output_dir) if f.endswith(('.mp3', '.m4a'))]
    filepath = os.path.join(output_dir, files[0])
    file_size = os.path.getsize(filepath) / (1024 * 1024)

    return {
        "filepath": filepath,
        "title": info.get("title", "Audio"),
        "file_size_mb": round(file_size, 2),
        "uploader": info.get("uploader", "Unknown"),
    }

async def download_images(url, output_dir):
    info = await get_media_info(url)
    images = []

    if "entries" in info:
        for entry in info["entries"]:
            formats = entry.get("formats", [entry])
            img_formats = [f for f in formats if f.get("ext") in ("jpg", "jpeg", "png", "webp")]
            if img_formats:
                best = max(img_formats, key=lambda x: x.get("width", 0) * x.get("height", 0))
                images.append(best.get("url"))
    else:
        formats = info.get("formats", [])
        img_formats = [f for f in formats if f.get("ext") in ("jpg", "jpeg", "png", "webp")]
        if img_formats:
            best = max(img_formats, key=lambda x: x.get("width", 0) * x.get("height", 0))
            images.append(best.get("url"))
        elif info.get("url"):
            images.append(info["url"])

    if not images:
        raise Exception("Tidak ada gambar ditemukan")

    downloaded = []
    headers = {"User-Agent": "Mozilla/5.0"}

    for i, img_url in enumerate(images[:10]):
        try:
            resp = requests.get(img_url, headers=headers, timeout=20)
            resp.raise_for_status()
            ext = "png" if "png" in resp.headers.get("content-type", "") else "jpg"
            filepath = os.path.join(output_dir, f"image_{i+1}.{ext}")
            with open(filepath, "wb") as f:
                f.write(resp.content)
            downloaded.append(filepath)
        except Exception as e:
            logger.warning(f"Gagal download gambar {i+1}: {e}")

    if not downloaded:
        raise Exception("Gagal mendownload semua gambar")

    return {
        "files": downloaded,
        "title": info.get("title", "TikTok Slideshow"),
        "uploader": info.get("uploader", "Unknown"),
        "count": len(downloaded),
    }

# === COMMANDS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = "✅ Aktif" if cookies_exist() else "❌ Belum diset"
    text = (
        "👋 *Bot Media Downloader*\n\n"
        "📥 Platform yang didukung:\n"
        "• TikTok (Video + Slideshow Foto + Audio)\n"
        "• Instagram, Facebook, YouTube, Twitter/X\n\n"
        "Cara Pakai:\n"
        "→ Kirim link → Video atau Gambar otomatis\n"
        "→ `/audio link` → Audio MP3\n\n"
        f"🍪 Cookies: {status}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def audio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Gunakan:\n`/audio https://vm.tiktok.com/xxxx/`", parse_mode="Markdown")
        return

    url = context.args[0].strip()
    if not is_valid_url(url):
        await update.message.reply_text("⚠️ Link tidak valid.")
        return

    msg = await update.message.reply_text("🎧 Mendownload audio...")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = await download_audio(url, tmpdir)
            caption = f"🎵 {clean_text(result['title'])}\n👤 {clean_text(result['uploader'])}\n📦 {result['file_size_mb']} MB"
            with open(result["filepath"], "rb") as f:
                await context.bot.send_audio(
                    chat_id=update.message.chat_id,
                    audio=f,
                    caption=caption,
                )
            await msg.edit_text("✅ Audio berhasil dikirim!")
    except Exception as e:
        await msg.edit_text(f"❌ Gagal download audio:\n{str(e)[:250]}")

async def set_cookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["waiting_cookies"] = True
    await update.message.reply_text(
        "🍪 *Upload Cookies*\n\n"
        "Kirim file `cookies.txt` sekarang.\n\n"
        "Cara export:\n"
        "1. Install ekstensi *Get cookies.txt LOCALLY* di Chrome\n"
        "2. Login ke TikTok/Instagram di browser\n"
        "3. Klik ekstensi → Export\n"
        "4. Kirim file .txt ke bot ini",
        parse_mode="Markdown"
    )

async def cookies_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if cookies_exist():
        size = os.path.getsize(COOKIES_FILE)
        await update.message.reply_text(f"🍪 Cookies aktif\n📦 Ukuran: {size} bytes")
    else:
        await update.message.reply_text("❌ Cookies belum diset.\nGunakan /setcookies")

async def delete_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if cookies_exist():
        os.remove(COOKIES_FILE)
        await update.message.reply_text("🗑️ Cookies berhasil dihapus.")
    else:
        await update.message.reply_text("❌ Tidak ada cookies yang tersimpan.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("waiting_cookies"):
        await update.message.reply_text("⚠️ Ketik /setcookies dulu sebelum upload file.")
        return

    doc = update.message.document
    if not doc.file_name.endswith(".txt"):
        await update.message.reply_text("❌ File harus berformat .txt")
        return

    msg = await update.message.reply_text("⏳ Menyimpan cookies...")
    try:
        file = await context.bot.get_file(doc.file_id)
        os.makedirs(os.path.dirname(COOKIES_FILE), exist_ok=True)
        await file.download_to_drive(COOKIES_FILE)
        context.user_data["waiting_cookies"] = False
        await msg.edit_text("✅ Cookies berhasil disimpan!\nSekarang konten private bisa didownload.")
    except Exception as e:
        await msg.edit_text(f"❌ Gagal menyimpan cookies: {str(e)}")

# === HANDLER URL ===
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not is_valid_url(url):
        await update.message.reply_text("⚠️ Bukan link valid.")
        return

    platform = detect_platform(url)
    msg = await update.message.reply_text(f"🔄 Memproses link {platform.capitalize()}...")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            info = await get_media_info(url)

            # TikTok Slideshow
            if platform == "tiktok" and is_slideshow(info):
                await msg.edit_text("🖼️ Mendownload slideshow gambar...")
                result = await download_images(url, tmpdir)
                caption = f"🖼️ {clean_text(result['title'])}\n👤 {clean_text(result['uploader'])}"
                
                if len(result["files"]) == 1:
                    with open(result["files"][0], "rb") as f:
                        await context.bot.send_photo(chat_id=update.message.chat_id, photo=f, caption=caption)
                else:
                    media = []
                    for i, fp in enumerate(result["files"]):
                        with open(fp, "rb") as f:
                            media.append(InputMediaPhoto(media=f.read(), caption=caption if i == 0 else None))
                    await context.bot.send_media_group(chat_id=update.message.chat_id, media=media)
                await msg.edit_text(f"✅ {result['count']} gambar slideshow dikirim!")

            else:
                # Video biasa
                await msg.edit_text("🎥 Mendownload video...")
                video_info = await download_video(url, tmpdir)
                caption = f"📹 {clean_text(video_info['title'])}\n👤 {clean_text(video_info['uploader'])}\n📦 {video_info['file_size_mb']} MB"
                with open(video_info["filepath"], "rb") as f:
                    await context.bot.send_video(
                        chat_id=update.message.chat_id,
                        video=f,
                        caption=caption,
                        supports_streaming=True,
                    )
                await msg.edit_text("✅ Video berhasil dikirim!")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await msg.edit_text(f"❌ Gagal memproses link:\n{str(e)[:250]}")

# === MAIN ===
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Semua handler
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("audio", audio_command))
    app.add_handler(CommandHandler("setcookies", set_cookies_command))
    app.add_handler(CommandHandler("cookiesstatus", cookies_status))
    app.add_handler(CommandHandler("deletecookies", delete_cookies))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

    logger.info("✅ Bot Media Downloader berjalan dengan fitur TikTok lengkap!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
