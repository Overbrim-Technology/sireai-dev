import whisper
from telegram import Update, ContextTypes
from telegram.ext import CommandHandler, MessageHandler, Filters
import requests
import tempfile
import os
from urllib.parse import urlparse

async def handle_audio(update, context):
    message = update.message
    user_id = message.from_user.id

    # Detect file type
    if message.voice:
        file_id = message.voice.file_id
        file_name = f"{file_id}.ogg"
    elif message.audio:
        file_id = message.audio.file_id
        file_name = message.audio.file_name or f"{file_id}.mp3"
    else:
        await message.reply_text("Please send a valid audio or voice message.")
        return

    # Download file to temp location
    file = await context.bot.get_file(file_id)
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        audio_path = tmp.name

    await message.reply_text("Processing your audio...")

    # Transcribe audio
    result = model.transcribe(audio_path)
    transcription_text = result["text"]

    # Store in SQLite
    save_transcription_to_db(user_id, file_name, transcription_text)

    await message.reply_text("✅ Transcription saved to database.")
    os.remove(audio_path)

# Load Whisper model (use "base", "small", "medium", "large", "turbo" as needed)
model = whisper.load_model("large-v3")

# Your audio file URL (local or remote)
url = '1754398967885.m4a'  # Can be .mp3, .wav, .ogg, etc.

# Detect file extension
parsed_url = urlparse(url)
ext = os.path.splitext(parsed_url.path)[1].lower()
print(f"Detected file extension: {ext}")
print(f"parsed_url: {parsed_url.path}")
if ext not in [".mp3", ".wav", ".m4a", ".flac", ".ogg"]:
    ext = ".wav"  # Fallback

# Open as local file if it's a path, else download
# if os.path.exists(url):
audio_path = url
# else:
    # with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
    #     response = requests.get(url, stream=True)
    #     if response.status_code == 200:
    #         for chunk in response.iter_content(chunk_size=8192):
    #             tmp.write(chunk)
    #         tmp.flush()
    #         audio_path = tmp.name
    #     else:
    #         raise RuntimeError(f"Failed to download audio. Status: {response.status_code}")

# Transcribe
result = model.transcribe(audio_path)
print(result["text"])

# Clean up temp file if downloaded
if not os.path.exists(url) and os.path.exists(audio_path):
    os.remove(audio_path)
