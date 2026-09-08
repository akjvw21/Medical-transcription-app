"""
FastAPI backend for the live medical transcription tool.

Two endpoints:

  WS   /ws/transcribe   Streams raw PCM16 audio frames in, streams
                        transcript text out, as VAD detects each
                        completed utterance.

  POST /analyze         Takes the full accumulated transcript and runs
                        the one-shot LLM extraction into a structured
                        clinical summary.

State management is intentionally simple: each WebSocket connection
owns exactly one VadSession, and the transcript itself is assembled on
the frontend from the stream of "transcript_chunk" messages (no server-
side session store needed, since the /analyze call is stateless and
just receives the transcript text directly in its request body).
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from asr import transcribe_utterance
from llm_extractor import extract_clinical_summary
from vad_pipeline import VadSession

app = FastAPI(title="Live Medical Transcription API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this to your frontend's origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws/transcribe")
async def transcribe_ws(websocket: WebSocket):
    print("[WS] Connection attempt received")

    await websocket.accept()

    print("[WS] WebSocket accepted")

    session = VadSession()
    transcripts: list[str] = []

    def handle_utterance(pcm_bytes: bytes) -> None:
        print(f"[VAD] Speech utterance detected: {len(pcm_bytes)} bytes")

        text = transcribe_utterance(pcm_bytes)

        print(f"[WHISPER] Result: {text!r}")

        if text:
            transcripts.append(text)

    try:
        while True:
            message = await websocket.receive()

            if "bytes" in message and message["bytes"] is not None:
                audio_bytes = message["bytes"]

                print(f"[AUDIO] Received {len(audio_bytes)} bytes")

                session.push_audio(
                    audio_bytes,
                    handle_utterance
                )

                while transcripts:
                    text = transcripts.pop(0)

                    print(f"[WS] Sending transcript: {text!r}")

                    await websocket.send_json(
                        {
                            "type": "transcript_chunk",
                            "text": text,
                        }
                    )

            elif "text" in message and message["text"] == "__stop__":
                print("[WS] Stop command received")

                tail = session.flush()

                if tail:
                    print(f"[VAD] Flushed tail: {len(tail)} bytes")

                    text = transcribe_utterance(tail)

                    print(f"[WHISPER] Tail result: {text!r}")

                    if text:
                        await websocket.send_json(
                            {
                                "type": "transcript_chunk",
                                "text": text,
                            }
                        )

                await websocket.send_json(
                    {
                        "type": "stopped"
                    }
                )

                print("[WS] Stopped")

                break

    except WebSocketDisconnect:
        print("[WS] WebSocket disconnected")


class AnalyzeRequest(BaseModel):
    transcript: str


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    summary = extract_clinical_summary(req.transcript)
    return summary.model_dump()


@app.get("/health")
async def health():
    return {"status": "ok"}
