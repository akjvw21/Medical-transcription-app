# Live Medical Transcription & Clinical Summary

A live-transcription tool: capture mic audio, gate it with Voice Activity
Detection, transcribe with Whisper, show the transcript live, then run one
LLM pass at the end to extract a structured clinical summary.



## Why these specific choices

**webrtcvad over energy-threshold silence detection.** A naive
"RMS below X = silence" approach breaks on background noise and doesn't
generalize across mics. webrtcvad runs a small pretrained model over
each 20ms frame and is the same VAD used inside Chrome's WebRTC stack —
battle-tested, CPU-only, no extra dependency weight.

**Hysteresis state machine instead of frame-by-frame gating.** A single
frame's speech/silence decision is noisy — a half-second pause
mid-sentence would otherwise fragment one utterance into three ASR
calls. We track a rolling window and require a ratio of frames to agree
before flipping state (see `vad_pipeline.py`), plus a fixed silence
duration (700ms) before considering an utterance "done". Pre-roll
frames are kept so the first phoneme isn't clipped at onset.

**faster-whisper (local) over the OpenAI Whisper API.** Per your
choice: no per-request cost, no network dependency for the ASR step,
and CTranslate2's int8 CPU inference is fast enough for short
(2-10 second) utterances. Trade-off: first request pays model load
time, and accuracy/speed depends on which model size you pick
(`asr.py` defaults to `small`; drop to `base` for speed or go to
`medium`/`large-v3` for accuracy on a stronger machine).

**One LLM call per session, not per utterance.** Structured medical
extraction (e.g. distinguishing "denies fever" from "reports fever")
needs the full conversation for context — a running per-line extraction
would constantly contradict itself as new information arrives. Running
it once, on completion, against the full transcript is both cheaper and
more accurate.

**Pydantic schema as the LLM/frontend contract.** The extraction prompt
literally includes `ClinicalSummary.model_json_schema()` so the model
sees the exact shape we expect, and the response is validated through
the same model before it's returned — if Claude ever returns malformed
JSON, the backend raises instead of shipping broken data to the UI.

**Two-endpoint split (WebSocket + REST).** Streaming needs a persistent
connection (WebSocket); the one-shot analysis is a plain stateless
request/response, so it's a normal REST POST. No reason to force both
through the same transport.

## Setup

```bash
cd backend
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

export GEMINI_API_KEY=your-gemini-api-key
uvicorn main:app --reload --port 8000
```

On Windows PowerShell, set the key for the current terminal with:

```powershell
$env:GEMINI_API_KEY = "your-gemini-api-key"
```

You can instead put `GEMINI_API_KEY=your-gemini-api-key` in
`backend/.env`. Do not commit that file.

Then serve the frontend (any static server works, e.g.):

```bash
cd frontend
python -m http.server 5500
```

Open `http://localhost:5500`, click **Start microphone**, allow mic
permission, and speak. Click **Stop**, then **Process transcript with
AI** to run the extraction.

## Known limitations / next steps

- `ScriptProcessorNode` is used for mic capture for simplicity; it's
  deprecated in favor of `AudioWorkletNode`, which runs off the main
  thread — worth migrating to before shipping.
- ASR runs synchronously inside the WebSocket handler; under real
  concurrent load you'd move it to a task queue (e.g. `asyncio` queue
  worker or Celery) so one connection's transcription can't block
  another's audio frames.
- No persistence layer — the transcript lives only in the browser tab
  for the session. A real deployment would persist sessions (with
  proper PHI handling / encryption) rather than losing everything on
  refresh.
- No auth on the WebSocket or REST endpoints — fine for a local demo,
  not for handling real patient data.
