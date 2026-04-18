"""FFmpeg utilities for Signal Messenger."""
import asyncio
import logging
from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

async def async_transcode_to_wav(hass: HomeAssistant, audio_data: bytes) -> bytes | None:
    """Transcode AAC/M4A to WAV PCM 16kHz Mono using FFmpeg."""
    manager = get_ffmpeg_manager(hass)
    ffmpeg_bin = manager.binary
    if ffmpeg_bin is None:
        _LOGGER.error("FFmpeg binary not found. Ensure ffmpeg is installed and configured")
        return None

    # Arguments to convert input buffer to WAV PCM 16bit, 16000Hz, Mono
    command = [
        ffmpeg_bin,
        "-vn",                    # Skip any embedded album art/video
        "-i", "pipe:0",           # Read from stdin
        "-acodec", "pcm_s16le",   # Output codec
        "-ar", "16000",           # Audio rate
        "-ac", "1",               # Mono
        "-f", "wav",              # WAV format (with header)
        "pipe:1",                 # Write to stdout
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate(input=audio_data)

        if process.returncode != 0:
            _LOGGER.error("FFmpeg transcoding failed: %s", stderr.decode())
            return None

        return stdout
    except Exception as err:
        _LOGGER.error("Exception during FFmpeg transcoding: %s", err)
        return None