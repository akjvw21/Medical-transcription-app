"""
Automatic Speech Recognition using faster-whisper.

faster-whisper is a CTranslate2 reimplementation of OpenAI's Whisper —
same model weights, much faster CPU inference (int8 quantization),
lower memory footprint. We load the model once at process start and
reuse it for every utterance, since model load is the expensive part
(the transcription call itself is fast for short 2-10s utterances).
"""

import numpy as np
from faster_whisper import WhisperModel

MODEL_SIZE = "small"       # tiny/base/small/medium/large-v3 — speed vs accuracy tradeoff
DEVICE = "cpu"
COMPUTE_TYPE = "int8"      # quantized for CPU speed; use "float16" if running on GPU

_model: WhisperModel | None = None


def get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
    return _model


def pcm16_bytes_to_float32(pcm_bytes: bytes) -> np.ndarray:
    """faster-whisper expects float32 samples in [-1, 1], mono, 16kHz."""
    audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
    return audio_int16.astype(np.float32) / 32768.0


def transcribe_utterance(pcm_bytes: bytes, language: str = "en") -> str:
    """
    Transcribe a single VAD-delimited utterance.
    Returns the joined text of all segments (usually just one for a short utterance).
    """
    audio = pcm16_bytes_to_float32(pcm_bytes)
    model = get_model()
    segments, _info = model.transcribe(
        audio,
        language=language,
        vad_filter=False,  # we already gated with our own VAD upstream
        beam_size=5,
    )
    return " ".join(seg.text.strip() for seg in segments).strip()
