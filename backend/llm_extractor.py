"""
LLM-based structured extraction.

On session completion, the full transcript is sent once to Gemini with
a system prompt that defines the exact JSON structure we want back.
The response is validated through Pydantic so malformed data is not
silently passed to the frontend.

The model is instructed to extract ONLY information explicitly stated
in the transcript and never hallucinate or infer missing clinical facts.
"""

import json
import os

from dotenv import load_dotenv
from google import genai

from schemas import ClinicalSummary

load_dotenv()

MODEL = "gemini-3.6-flash"

SYSTEM_PROMPT = """You are a clinical scribe assistant. You will be given a raw \
transcript of a doctor-patient consultation, produced by an automatic speech \
recognition system (it may contain minor transcription errors, filler words, \
or misattributed speaker turns).

Extract ONLY information that is actually stated in the transcript. Never \
invent, infer, or guess a value that is not present — leave it empty instead. \
Keep patient-reported positive symptoms and explicitly denied (negative) \
symptoms in separate lists. Preserve clinical terminology where the speaker \
used it, but you may lightly normalize phrasing for clarity.

Respond with ONLY a single JSON object matching this exact shape, and nothing \
else — no markdown fences, no commentary:

{schema}
"""

def _client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to the .env file before starting the server."
        )

    return genai.Client(api_key=api_key)


def extract_clinical_summary(transcript: str) -> ClinicalSummary:
    if not transcript.strip():
        raise ValueError("Cannot analyze an empty transcript.")

    schema_json = json.dumps(
        ClinicalSummary.model_json_schema(),
        indent=2
    )

    system_prompt = SYSTEM_PROMPT.format(
        schema=schema_json
    )

    client = _client()

    response = client.models.generate_content(
        model=MODEL,
        contents=f"{system_prompt}\n\nTranscript:\n\n{transcript}",
        config={
            "response_mime_type": "application/json",
            "response_schema": ClinicalSummary,
            "max_output_tokens": 2000,
        },
    )

    raw_text = response.text.strip()
    data = json.loads(raw_text)

    return ClinicalSummary.model_validate(data)