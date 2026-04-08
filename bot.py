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
 
# === DOWNLOAD VIDEO ===
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
 
# === CEK APAKAH POSTINGAN FOTO ===
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
 
# === DOWNLOAD GAMBAR ===
async def download_images(url, output_dir):
    info = await get_media_info(url)

    images = []

    # Coba ambil gambar dari format (ini yang benar untuk TikTok slideshow)
    if "entries" in info:
        for entry in info["entries"]:
            # Cek format gambar dulu
            formats = entry.get("formats", [])
            img_formats = [f for f in formats if f.get("ext") in ("jpg", "jpeg", "png", "webp")]
            if img_formats:
                best = max(img_formats, key=lambda x: x.get("width", 0) * x.get("height", 0))
                images.append(best.get("url"))
            elif entry.get("url"):
                images.append(entry["url"])
            # Fallback ke thumbnail kalau tidak ada format lain
            elif entry.get("thumbnails"):
                best = max(entry["thumbnails"], key=lambda x: x.get("width", 0) * x.get("height", 0))
                images.append(best.get("url"))
    else:
        # Single post - cek format dulu
        formats = info.get("formats", [])
        img_formats = [f for f in formats if f.get("ext") in ("jpg", "jpeg", "png", "webp")]
        if img_formats:
            best = max(img_formats, key=lambda x: x.get("width", 0) * x.get("height", 0))
            images.append(best.get("url"))
        elif info.get("url"):
            images.append(info["url"])
        elif info.get("thumbnails"):
            best = max(info["thumbnails"], key=lambda x: x.get("width", 0) * x.get("height", 0))
            images.append(best.get("url"))

    if not images:
        raise Exception("Tidak ada gambar ditemukan")

    downloaded = []
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.tiktok.com/"  # Penting untuk TikTok!
    }
    for i, img_url in enumerate(images[:10]):
        try:
            resp = requests.get(img_url, headers=headers, timeout=15)
            resp.raise_for_status()

            # Deteksi ekstensi dari content-type
            content_type = resp.headers.get("content-type", "")
            if "png" in content_type:
                ext = "png"
            elif "webp" in content_type:
                ext = "webp"
            else:
                ext = "jpg"

            filepath = os.path.join(output_dir, f"image_{i+1}.{ext}")
            with open(filepath, "wb") as f:
                f.write(resp.content)
            downloaded.append(filepath)
        except Exception as e:
            logger.warning(f"Gagal download gambar {i+1}: {e}")

    if not downloaded:
        raise Exception("Gagal download semua gambar")

    return {
        "files": downloaded,
        "title": info.get("title", "Gambar"),
        "uploader": info.get("uploader", "Unknown"),
        "count": len(downloaded),
    }

 
# === COMMANDS ===
async def start(update, context):
    status = "✅ Aktif" if cookies_exist() else "❌ Belum diset"
    text = (
        "👋 *Bot Media Downloader*\n\n"
        "📥 Platform yang didukung:\n"
        "• 📸 Instagram (Video & Foto)\n"
        "• 🎵 TikTok (Video & Foto)\n"
        "• 📘 Facebook\n"
        "• 🎬 YouTube\n"
        "• 🐦 Twitter / X\n\n"
        "⚡ Langsung HD otomatis — tinggal kirim linknya!\n\n"
        f"🍪 Cookies: {status}\n\n"
        "⚙️ Commands:\n"
        "/start - Pesan ini\n"
        "/setcookies - Upload cookies (konten private)\n"
        "/cookiesstatus - Cek status cookies\n"
        "/deletecookies - Hapus cookies"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
 
async def cookies_status(update, context):
    if cookies_exist():
        size = os.path.getsize(COOKIES_FILE)
        await update.message.reply_text(f"🍪 Cookies aktif\n📦 Ukuran: {size} bytes")
    else:
        await update.message.reply_text("❌ Cookies belum diset\n\nKirim /setcookies untuk upload.")
 
async def set_cookies_command(update, context):
    context.user_data["waiting_cookies"] = True
    await update.message.reply_text(
        "🍪 *Upload Cookies*\n\n"
        "Kirim file `cookies.txt` sekarang.\n\n"
        "Cara export:\n"
        "1. Install ekstensi *Get cookies.txt LOCALLY* di Chrome\n"
        "2. Login ke platform di browser\n"
        "3. Klik ekstensi → Export\n"
        "4. Kirim file .txt ke sini",
        parse_mode="Markdown"
    )
 
async def delete_cookies(update, context):
    if cookies_exist():
        os.remove(COOKIES_FILE)
        await update.message.reply_text("🗑️ Cookies berhasil dihapus.")
    else:
        await update.message.reply_text("❌ Tidak ada cookies.")
 
async def handle_document(update, context):
    if not context.user_data.get("waiting_cookies"):
        await update.message.reply_text("⚠️ Kirim /setcookies dulu sebelum upload file.")
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
        await msg.edit_text("✅ Cookies berhasil disimpan!")
    except Exception as e:
        await msg.edit_text(f"❌ Gagal simpan cookies: {str(e)}")
 
# === HANDLER URL UTAMA ===
async def handle_url(update, context):
    url = update.message.text.strip()
 
    if not is_valid_url(url):
        await update.message.reply_text("⚠️ Bukan link yang valid. Pastikan diawali https://")
        return
 
    platform = detect_platform(url)
    emoji = {
        "instagram": "📸", "tiktok": "🎵", "facebook": "📘",
        "youtube": "🎬", "twitter": "🐦", "unknown": "🌐"
    }.get(platform, "🌐")
 
    msg = await update.message.reply_text(f"{emoji} Mendownload dari {platform.capitalize()}...")
 
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Coba download sebagai video dulu
            try:
                info = await download_video(url, tmpdir)
                file_size = info["file_size_mb"]
 
                if file_size > MAX_FILE_SIZE_MB:
                    await msg.edit_text(f"⚠️ File terlalu besar ({file_size}MB). Maks {MAX_FILE_SIZE_MB}MB.")
                    return
 
                safe_title = clean_text(info["title"][:80])
                safe_uploader = clean_text(info["uploader"])
                caption = f"📌 {safe_title}\n👤 {safe_uploader}\n📦 {file_size} MB"
 
                await msg.edit_text("📤 Mengirim...")
 
                with open(info["filepath"], "rb") as f:
                    await context.bot.send_video(
                        chat_id=update.message.chat_id,
                        video=f,
                        caption=caption,
                        supports_streaming=True,
                    )
                await msg.edit_text("✅ Selesai!")
 
            except yt_dlp.utils.DownloadError as e:
                err = str(e).lower()
 
                # Kalau bukan video (foto/carousel), coba download gambar
                if "no video" in err or "image" in err or "photo" in err:
                    await msg.edit_text("🖼️ Mendownload gambar...")
                    result = await download_images(url, tmpdir)
                    safe_title = clean_text(result["title"][:80])
                    safe_uploader = clean_text(result["uploader"])
                    caption = f"🖼️ {safe_title}\n👤 {safe_uploader}"
 
                    if len(result["files"]) == 1:
                        with open(result["files"][0], "rb") as f:
                            await context.bot.send_photo(
                                chat_id=update.message.chat_id,
                                photo=f,
                                caption=caption,
                            )
                    else:
                        media = []
                        for i, fp in enumerate(result["files"]):
                            with open(fp, "rb") as f:
                                media.append(InputMediaPhoto(
                                    media=f.read(),
                                    caption=caption if i == 0 else None
                                ))
                        await context.bot.send_media_group(
                            chat_id=update.message.chat_id,
                            media=media,
                        )
                    await msg.edit_text(f"✅ {result['count']} gambar dikirim!")
 
                elif "private" in err:
                    await msg.edit_text("🔒 Konten private!\n\nSetup cookies dulu: /setcookies")
                elif "login" in err or "sign in" in err:
                    await msg.edit_text("🔐 Perlu login!\n\nSetup cookies: /setcookies")
                elif "unavailable" in err or "removed" in err:
                    await msg.edit_text("❌ Konten tidak tersedia atau sudah dihapus.")
                else:
                    # Fallback: coba download gambar
                    try:
                        await msg.edit_text("🖼️ Mencoba download sebagai gambar...")
                        result = await download_images(url, tmpdir)
                        safe_title = clean_text(result["title"][:80])
                        safe_uploader = clean_text(result["uploader"])
                        caption = f"🖼️ {safe_title}\n👤 {safe_uploader}"
 
                        if len(result["files"]) == 1:
                            with open(result["files"][0], "rb") as f:
                                await context.bot.send_photo(
                                    chat_id=update.message.chat_id,
                                    photo=f,
                                    caption=caption,
                                )
                        else:
                            media = []
                            for i, fp in enumerate(result["files"]):
                                with open(fp, "rb") as f:
                                    media.append(InputMediaPhoto(
                                        media=f.read(),
                                        caption=caption if i == 0 else None
                                    ))
                            await context.bot.send_media_group(
                                chat_id=update.message.chat_id,
                                media=media,
                            )
                        await msg.edit_text(f"✅ {result['count']} gambar dikirim!")
                    except Exception:
                        await msg.edit_text(f"❌ Gagal download.\n{str(e)[:200]}")
 
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await msg.edit_text(f"❌ Terjadi kesalahan:\n{str(e)[:200]}")
 
# === MAIN ===
def main():
    app = Application.builder().token(BOT_TOKEN).build()
 
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setcookies", set_cookies_command))
    app.add_handler(CommandHandler("cookiesstatus", cookies_status))
    app.add_handler(CommandHandler("deletecookies", delete_cookies))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
 
    logger.info("Bot Media Downloader berjalan...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
 
if __name__ == "__main__":
    main()
