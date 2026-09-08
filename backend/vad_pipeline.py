"""
Voice Activity Detection pipeline.

Design
------
We use webrtcvad, the VAD engine shipped inside Chromium's WebRTC stack.
It classifies short fixed-length audio frames (here: 20ms) as speech or
non-speech using a Gaussian Mixture Model over frame energy/spectral
features. It's lightweight (no GPU, no torch), which matters because it
runs on every 20ms frame for every open connection.

webrtcvad requires 16-bit mono PCM at 8/16/32/48 kHz, in frames of
exactly 10/20/30 ms. The frontend is responsible for resampling the
browser's mic audio to 16kHz mono PCM16 before it ever reaches this code
(see frontend/app.js). This module assumes that contract is already met.

State machine
-------------
A single boolean "is this frame speech" is too noisy to gate on directly
(a cough, a page turn, or a short pause mid-sentence would fragment the
utterance). Instead we track a rolling window of the last N frame
decisions and use hysteresis:

  SILENCE --[>= START_RATIO speech frames in window]--> SPEAKING
  SPEAKING --[>= END_RATIO silence frames in window]--> SILENCE (flush)

While SPEAKING, raw PCM bytes are appended to an utterance buffer. A
small amount of "pre-roll" audio (captured just before speech onset) is
prepended so the first phoneme of a word isn't clipped. When we
transition back to SILENCE, the buffered utterance is handed off to the
ASR step and the buffer is cleared.
"""

import collections
from dataclasses import dataclass, field
from typing import Callable, Deque, List, Optional

import webrtcvad

SAMPLE_RATE = 16000
FRAME_MS = 20
FRAME_BYTES = int(SAMPLE_RATE * (FRAME_MS / 1000.0)) * 2  # 16-bit samples

WINDOW_FRAMES = 15          # ~300ms rolling window for the hysteresis decision
START_RATIO = 0.6           # fraction of speech frames in window to trigger START
END_SILENCE_MS = 700        # sustained silence to consider an utterance finished
END_SILENCE_FRAMES = END_SILENCE_MS // FRAME_MS
PREROLL_FRAMES = 8          # ~160ms of audio kept before detected onset


@dataclass
class VadSession:
    """Per-WebSocket-connection VAD state. One of these per active mic stream."""

    vad: webrtcvad.Vad = field(default_factory=lambda: webrtcvad.Vad(2))
    ring_window: Deque[bool] = field(
        default_factory=lambda: collections.deque(maxlen=WINDOW_FRAMES)
    )
    preroll: Deque[bytes] = field(
        default_factory=lambda: collections.deque(maxlen=PREROLL_FRAMES)
    )
    speaking: bool = False
    silence_run: int = 0
    utterance: bytearray = field(default_factory=bytearray)
    _leftover: bytes = b""  # partial frame carried over between calls

    def push_audio(self, chunk: bytes, on_utterance: Callable[[bytes], None]) -> None:
        """
        Feed raw PCM16 bytes (any length) into the pipeline. Internally
        splits into exact FRAME_BYTES frames. Calls on_utterance(pcm_bytes)
        each time a complete speech utterance is detected.
        """
        data = self._leftover + chunk
        n_frames = len(data) // FRAME_BYTES
        for i in range(n_frames):
            frame = data[i * FRAME_BYTES:(i + 1) * FRAME_BYTES]
            self._process_frame(frame, on_utterance)
        self._leftover = data[n_frames * FRAME_BYTES:]

    def _process_frame(self, frame: bytes, on_utterance: Callable[[bytes], None]) -> None:
        is_speech = self.vad.is_speech(frame, SAMPLE_RATE)
        self.ring_window.append(is_speech)

        if not self.speaking:
            self.preroll.append(frame)
            speech_ratio = sum(self.ring_window) / len(self.ring_window)
            if speech_ratio >= START_RATIO:
                self.speaking = True
                self.silence_run = 0
                self.utterance = bytearray(b"".join(self.preroll))
        else:
            self.utterance.extend(frame)
            if is_speech:
                self.silence_run = 0
            else:
                self.silence_run += 1
                if self.silence_run >= END_SILENCE_FRAMES:
                    finished = bytes(self.utterance)
                    self.speaking = False
                    self.silence_run = 0
                    self.utterance = bytearray()
                    self.ring_window.clear()
                    self.preroll.clear()
                    if len(finished) > FRAME_BYTES * 5:  # ignore blips < ~100ms
                        on_utterance(finished)

    def flush(self) -> Optional[bytes]:
        """Call when the session ends (mic stopped) to emit any tail utterance."""
        if self.speaking and len(self.utterance) > FRAME_BYTES * 5:
            finished = bytes(self.utterance)
            self.speaking = False
            self.utterance = bytearray()
            return finished
        return None
