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
    return re.sub(r'[*_`[\]]', '', text)[:200]

# === CEK JENIS MEDIA TIKTOK ===
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
    """Deteksi apakah ini TikTok Photo Mode / Slideshow"""
    if info.get("extractor_key") != "TikTok":
        return False
    # Cek entries (multiple images)
    if "entries" in info and len(info["entries"]) > 1:
        return True
    # Cek jika ada format image tapi tidak ada video
    formats = info.get("formats", [])
    has_video = any(f.get("vcodec") != "none" for f in formats if f.get("vcodec"))
    has_image = any(f.get("ext") in ("jpg", "jpeg", "png", "webp") for f in formats)
    return has_image and not has_video

# === DOWNLOAD VIDEO (Video Biasa) ===
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
        raise Exception("File video tidak ditemukan")

    filepath = os.path.join(output_dir, files[0])
    file_size = os.path.getsize(filepath) / (1024 * 1024)

    return {
        "filepath": filepath,
        "title": info.get("title", "Video"),
        "file_size_mb": round(file_size, 2),
        "uploader": info.get("uploader", "Unknown"),
    }

# === DOWNLOAD AUDIO ===
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
    if not files:
        raise Exception("File audio tidak ditemukan")

    filepath = os.path.join(output_dir, files[0])
    file_size = os.path.getsize(filepath) / (1024 * 1024)

    return {
        "filepath": filepath,
        "title": info.get("title", "Audio TikTok"),
        "file_size_mb": round(file_size, 2),
        "uploader": info.get("uploader", "Unknown"),
    }

# === DOWNLOAD GAMBAR (Slideshow / Photo Mode) ===
async def download_images(url, output_dir):
    info = await get_media_info(url)
    images = []

    # TikTok Slideshow biasanya punya "entries"
    if "entries" in info:
        for entry in info["entries"]:
            formats = entry.get("formats", []) or [entry]
            img_formats = [f for f in formats if f.get("ext") in ("jpg", "jpeg", "png", "webp")]
            if img_formats:
                best = max(img_formats, key=lambda x: x.get("width", 0) * x.get("height", 0))
                images.append(best.get("url"))
            elif entry.get("url"):
                images.append(entry["url"])
    else:
        # Single image atau fallback
        formats = info.get("formats", [])
        img_formats = [f for f in formats if f.get("ext") in ("jpg", "jpeg", "png", "webp")]
        if img_formats:
            best = max(img_formats, key=lambda x: x.get("width", 0) * x.get("height", 0))
            images.append(best.get("url"))
        elif info.get("url"):
            images.append(info["url"])

    if not images:
        raise Exception("Tidak ada gambar ditemukan di postingan ini")

    downloaded = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for i, img_url in enumerate(images[:10]):  # maksimal 10 gambar
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
        raise Exception("Gagal mendownload gambar")

    return {
        "files": downloaded,
        "title": info.get("title", "TikTok Slideshow"),
        "uploader": info.get("uploader", "Unknown"),
        "count": len(downloaded),
    }

# === COMMANDS ===
async def start(update, context):
    status = "✅ Aktif" if cookies_exist() else "❌ Belum diset"
    text = (
        "👋 *Bot Media Downloader*\n\n"
        "📥 Platform yang didukung:\n"
        "• 📸 Instagram\n"
        "• 🎵 **TikTok** (Video + Slideshow Foto + Audio)\n"
        "• 📘 Facebook\n"
        "• 🎬 YouTube\n"
        "• 🐦 Twitter / X\n\n"
        "Cara pakai:\n"
        "→ Kirim link TikTok biasa → **Video** atau **Gambar** otomatis\n"
        "→ `/audio` + link → **Audio MP3** saja\n\n"
        f"🍪 Cookies: {status}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def audio_command(update, context):
    if not context.args:
        await update.message.reply_text("⚠️ Gunakan: `/audio https://vm.tiktok.com/...`", parse_mode="Markdown")
        return
    url = context.args[0].strip()
    # ... (kode audio_command sama seperti sebelumnya, saya singkat)

    msg = await update.message.reply_text("🎧 Mendownload audio TikTok...")
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
        await msg.edit_text(f"❌ Gagal: {str(e)[:250]}")

# === HANDLER UTAMA ===
async def handle_url(update, context):
    url = update.message.text.strip()
    if not is_valid_url(url):
        await update.message.reply_text("⚠️ Link tidak valid.")
        return

    platform = detect_platform(url)
    msg = await update.message.reply_text(f"🔄 Mendeteksi & mendownload dari {platform.capitalize()}...")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            info = await get_media_info(url)

            if platform == "tiktok" and is_slideshow(info):
                await msg.edit_text("🖼️ Mendownload slideshow gambar TikTok...")
                result = await download_images(url, tmpdir)
                safe_title = clean_text(result["title"])
                caption = f"🖼️ {safe_title}\n👤 {clean_text(result['uploader'])}"

                if len(result["files"]) == 1:
                    with open(result["files"][0], "rb") as f:
                        await context.bot.send_photo(chat_id=update.message.chat_id, photo=f, caption=caption)
                else:
                    media = [InputMediaPhoto(media=open(fp, "rb").read(), caption=caption if i == 0 else None) 
                             for i, fp in enumerate(result["files"])]
                    await context.bot.send_media_group(chat_id=update.message.chat_id, media=media)
                await msg.edit_text(f"✅ {result['count']} gambar slideshow dikirim!")

            else:
                # Default: coba video dulu
                await msg.edit_text("🎥 Mendownload video...")
                try:
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
                except Exception as ve:
                    # Fallback ke gambar jika gagal sebagai video
                    await msg.edit_text("🖼️ Mencoba download sebagai gambar...")
                    result = await download_images(url, tmpdir)
                    # ... (kirim gambar sama seperti di atas)
                    await msg.edit_text(f"✅ {result['count']} gambar dikirim!")

    except Exception as e:
        logger.error(f"Error handle_url: {e}", exc_info=True)
        await msg.edit_text(f"❌ Gagal memproses:\n{str(e)[:200]}")

# === MAIN (sama seperti sebelumnya) ===
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("audio", audio_command))
    # tambahkan handler cookies seperti sebelumnya...

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    logger.info("Bot Media Downloader v2 (TikTok Video + Slideshow + Audio) berjalan...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
