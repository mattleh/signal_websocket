"""Assist and STT utilities for Signal Messenger."""
import logging
from homeassistant.components import assist_pipeline, stt
from homeassistant.core import HomeAssistant

# Relative import of your ffmpeg utility
from .ffmpeg import async_transcode_to_wav

_LOGGER = logging.getLogger(__name__)

async def async_transcribe(hass: HomeAssistant, audio_data: bytes) -> str | None:
    """Transcribe audio data using the assist_pipeline's STT engine."""
    
    # 1. Transcode incoming audio (AAC/M4A) to WAV PCM
    wav_data = await async_transcode_to_wav(hass, audio_data)
    if not wav_data:
        return None

    # 2. Get the default pipeline
    pipeline = assist_pipeline.async_get_pipeline(hass, None)
    if not pipeline or not pipeline.stt_engine:
        _LOGGER.error("No STT engine configured in Assist pipeline")
        return None

    # 3. Resolve the engine. For Cloud, we need to handle it via the pipeline logic.
    try:
        # We use the internal engine resolution from the assist_pipeline
        # This is the "magic" that handles CloudProviderEntity correctly.
        engine = stt.async_get_speech_to_text_engine(hass, pipeline.stt_engine)
        if not engine:
             _LOGGER.error("STT engine %s not found", pipeline.stt_engine)
             return None

        metadata = stt.SpeechMetadata(
            language=pipeline.stt_language or hass.config.language,
            format=stt.AudioFormats.WAV,
            codec=stt.AudioCodecs.PCM,
            bit_rate=stt.AudioBitRates.BITRATE_16,
            sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
            channel=stt.AudioChannels.CHANNEL_MONO,
        )

        async def audio_stream(data: bytes):
            """Chunk the audio data for the STT engine."""
            chunk_size = 4096
            for i in range(0, len(data), chunk_size):
                yield data[i : i + chunk_size]

        # WORKAROUND: If it's the CloudProviderEntity, we call its internal 
        # process method which is often hidden but used by the pipeline.
        # Otherwise, we use the standard method.
        if hasattr(engine, "async_process_audio_stream"):
            result = await engine.async_process_audio_stream(metadata, audio_stream(wav_data))
        else:
            result = await engine.async_speech_to_text(metadata, audio_stream(wav_data))
        
        _LOGGER.debug("STT result for Signal message: %s", result)
        if result.result == stt.SpeechResultState.SUCCESS:
            return result.text
            
    except Exception as err:
        _LOGGER.error("Signal STT transcription failed: %s", err)
    
    return None
