/*
 * Frontend responsibilities:
 *  1. Capture mic audio via getUserMedia.
 *  2. Resample it from the device's native rate down to 16kHz mono.
 *  3. Convert Float32 samples to PCM16.
 *  4. Stream PCM16 bytes to the backend over WebSocket.
 *  5. Render returned transcript chunks immediately.
 *  6. Send the completed transcript to /analyze for clinical extraction.
 *
 * ScriptProcessorNode is used for this assignment/demo.
 */

const BACKEND_HTTP = "http://127.0.0.1:8000";
const BACKEND_WS = "ws://127.0.0.1:8000/ws/transcribe";
const TARGET_SAMPLE_RATE = 16000;

const el = (id) => document.getElementById(id);
const startBtn = el("startBtn");
const stopBtn = el("stopBtn");
const clearBtn = el("clearBtn");
const analyzeBtn = el("analyzeBtn");
const copyBtn = el("copyBtn");
const clearRecordBtn = el("clearRecordBtn");
const feedScroll = el("feedScroll");
const feedPlaceholder = el("feedPlaceholder");
const statusDot = el("statusDot");
const statusLabel = el("statusLabel");
const sessionClock = el("sessionClock");
const wordCountEl = el("wordCount");
const chunkCountEl = el("chunkCount");

let audioCtx;
let sourceNode;
let processorNode;
let mediaStream;
let ws;

let transcriptChunks = [];
let clockInterval;
let sessionStartMs;
let isStopping = false;

function fmtClock(ms) {
  const total = Math.floor(ms / 1000);
  const m = String(Math.floor(total / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function downsampleTo16k(float32Data, inputSampleRate) {
  if (inputSampleRate === TARGET_SAMPLE_RATE) {
    return float32Data;
  }

  const ratio = inputSampleRate / TARGET_SAMPLE_RATE;
  const outLength = Math.floor(float32Data.length / ratio);
  const out = new Float32Array(outLength);

  for (let i = 0; i < outLength; i++) {
    out[i] = float32Data[Math.floor(i * ratio)];
  }

  return out;
}

function float32ToPCM16(float32Data) {
  const out = new Int16Array(float32Data.length);

  for (let i = 0; i < float32Data.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Data[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }

  return out.buffer;
}

async function startMic() {
  try {
    console.log("[MIC] Requesting microphone permission...");

    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: true,
    });

    console.log("[MIC] Microphone permission granted");

    audioCtx = new (window.AudioContext || window.webkitAudioContext)();

    await audioCtx.resume();

    console.log("[AUDIO] AudioContext state:", audioCtx.state);
    console.log("[AUDIO] Sample rate:", audioCtx.sampleRate);

    sourceNode = audioCtx.createMediaStreamSource(mediaStream);

    console.log("[AUDIO] MediaStreamSource created");

    processorNode = audioCtx.createScriptProcessor(4096, 1, 1);

    console.log("[AUDIO] ScriptProcessor created");

    ws = new WebSocket(BACKEND_WS);
    ws.binaryType = "arraybuffer";

    console.log("[WS] Connecting to:", BACKEND_WS);

    ws.onerror = (error) => {
      console.error("[WS] WebSocket error:", error);
    };

    ws.onclose = (event) => {
      console.log(
        "[WS] WebSocket closed:",
        event.code,
        event.reason || "(no reason)"
      );
    };

    ws.onmessage = (event) => {
      console.log("[WS] Message received:", event.data);

      try {
        const msg = JSON.parse(event.data);

        if (msg.type === "transcript_chunk") {
          console.log("[TRANSCRIPT] Received:", msg.text);
          appendTranscriptChunk(msg.text);
        }

        if (msg.type === "stopped") {
          console.log("[WS] Backend confirmed stopped");
          isStopping = false;
          analyzeBtn.disabled = transcriptChunks.length === 0;

          // The backend has now sent the final VAD-flushed transcription.
          // Closing earlier can discard that last transcript chunk.
          if (ws && ws.readyState === WebSocket.OPEN) {
            ws.close();
          }
        }
      } catch (err) {
        console.error("[WS] Failed to parse message:", err);
      }
    };

    ws.onopen = () => {
      console.log("[WS] WebSocket connected");

      let audioDebugCount = 0;

      processorNode.onaudioprocess = (e) => {
        const input = e.inputBuffer.getChannelData(0);

        /*
         * Only print the first few callbacks so the console
         * doesn't get flooded with thousands of messages.
         */
        if (audioDebugCount < 10) {
          let maxAmplitude = 0;
          let sumSquares = 0;

          for (let i = 0; i < input.length; i++) {
            const value = input[i];

            maxAmplitude = Math.max(
              maxAmplitude,
              Math.abs(value)
            );

            sumSquares += value * value;
          }

          const rms = Math.sqrt(sumSquares / input.length);

          console.log(
            `[AUDIO] Processing | samples=${input.length} | maxAmplitude=${maxAmplitude.toFixed(
              5
            )} | RMS=${rms.toFixed(5)}`
          );

          audioDebugCount++;
        }

        const resampled = downsampleTo16k(
          input,
          audioCtx.sampleRate
        );

        const pcm16Buffer = float32ToPCM16(resampled);

        if (ws.readyState === WebSocket.OPEN) {
          ws.send(pcm16Buffer);

          if (audioDebugCount <= 10) {
            console.log(
              `[WS] Sent ${pcm16Buffer.byteLength} bytes`
            );
          }
        }
      };

      console.log("[AUDIO] Connecting microphone to processor...");

      sourceNode.connect(processorNode);

      processorNode.connect(audioCtx.destination);

      console.log("[AUDIO] Audio pipeline connected");
    };

    sessionStartMs = Date.now();

    clockInterval = setInterval(() => {
      sessionClock.textContent = fmtClock(
        Date.now() - sessionStartMs
      );
    }, 500);

    statusDot.classList.add("live");
    statusLabel.textContent = "recording";

    startBtn.disabled = true;
    stopBtn.disabled = false;
    analyzeBtn.disabled = true;
    isStopping = false;

    console.log("[SESSION] Recording started");
  } catch (err) {
    console.error("[MIC] Failed to start microphone:", err);

    alert(`Could not start microphone: ${err.message}`);

    if (mediaStream) {
      mediaStream.getTracks().forEach((track) => track.stop());
    }

    if (audioCtx) {
      await audioCtx.close();
    }
  }
}

function stopMic() {
  console.log("[SESSION] Stopping recording...");

  if (ws && ws.readyState === WebSocket.OPEN) {
    console.log("[WS] Sending stop command");

    ws.send("__stop__");
  }

  if (processorNode) {
    processorNode.disconnect();
    processorNode.onaudioprocess = null;
  }

  if (sourceNode) {
    sourceNode.disconnect();
  }

  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
  }

  if (audioCtx) {
    audioCtx.close();
  }

  clearInterval(clockInterval);

  statusDot.classList.remove("live");
  statusLabel.textContent = "stopped";

  startBtn.disabled = false;
  stopBtn.disabled = true;
  // Wait for the backend's "stopped" response, which may include the final
  // transcript chunk produced from the VAD buffer.
  isStopping = true;
  analyzeBtn.disabled = true;

  console.log("[SESSION] Recording stopped");
}

function appendTranscriptChunk(text) {
  feedPlaceholder.style.display = "none";

  transcriptChunks.push(text);

  const line = document.createElement("p");
  line.className = "feed-line";

  const ts = document.createElement("span");
  ts.className = "ts";
  ts.textContent = fmtClock(
    Date.now() - sessionStartMs
  );

  const body = document.createElement("span");
  body.textContent = text;

  line.appendChild(ts);
  line.appendChild(body);

  feedScroll.appendChild(line);

  feedScroll.scrollTop = feedScroll.scrollHeight;

  const totalWords = transcriptChunks
    .join(" ")
    .split(/\s+/)
    .filter(Boolean)
    .length;

  wordCountEl.textContent = `words ${totalWords}`;
  chunkCountEl.textContent =
    `utterances ${transcriptChunks.length}`;

  if (!isStopping) {
    analyzeBtn.disabled = false;
  }
}

function clearFeed() {
  transcriptChunks = [];

  feedScroll.innerHTML = "";
  feedScroll.appendChild(feedPlaceholder);

  feedPlaceholder.style.display = "block";

  wordCountEl.textContent = "words 0";
  chunkCountEl.textContent = "utterances 0";

  analyzeBtn.disabled = true;
}

async function analyzeTranscript() {
  const fullTranscript = transcriptChunks.join(" ");

  analyzeBtn.disabled = true;
  analyzeBtn.textContent = "Analyzing…";

  try {
    const res = await fetch(`${BACKEND_HTTP}/analyze`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        transcript: fullTranscript,
      }),
    });

    if (!res.ok) {
      throw new Error(`Server returned ${res.status}`);
    }

    const summary = await res.json();

    renderClinicalSummary(summary);

    copyBtn.disabled = false;
  } catch (err) {
    console.error("[AI] Analysis failed:", err);
    alert(`Analysis failed: ${err.message}`);
  } finally {
    analyzeBtn.disabled = false;
    analyzeBtn.textContent =
      "Process transcript with AI";
  }
}

function setListField(fieldName, items) {
  const list = document.querySelector(
    `[data-field="${fieldName}"]`
  );

  if (!list) return;

  list.innerHTML = "";

  if (!items || items.length === 0) {
    list.innerHTML =
      `<li class="record-empty">None extracted</li>`;
    return;
  }

  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = item;
    list.appendChild(li);
  }
}

function setTextField(fieldName, text) {
  const node = document.querySelector(
    `p[data-field="${fieldName}"]`
  );

  if (!node) return;

  node.textContent =
    text && text.trim()
      ? text
      : "Not mentioned";

  node.classList.toggle(
    "record-empty",
    !text || !text.trim()
  );
}

function renderClinicalSummary(s) {
  const patient = s.patient_details || {};

  el("patientRow").querySelector(
    ".patient-name"
  ).textContent =
    patient.name || "Patient name not stated";

  el("patientMeta").textContent = [
    patient.age,
    patient.sex,
  ]
    .filter(Boolean)
    .join(" · ");

  setTextField(
    "chief_complaint",
    s.chief_complaint
  );

  const hpi =
    s.history_of_present_illness || {};

  const hpiParts = [];

  if (hpi.onset) {
    hpiParts.push(`Onset: ${hpi.onset}`);
  }

  if (hpi.duration) {
    hpiParts.push(`Duration: ${hpi.duration}`);
  }

  if (hpi.progression) {
    hpiParts.push(
      `Progression: ${hpi.progression}`
    );
  }

  if (hpi.aggravating_factors?.length) {
    hpiParts.push(
      `Aggravating: ${hpi.aggravating_factors.join(", ")}`
    );
  }

  if (hpi.relieving_factors?.length) {
    hpiParts.push(
      `Relieving: ${hpi.relieving_factors.join(", ")}`
    );
  }

  setTextField(
    "hpi",
    hpiParts.join(" — ")
  );

  setListField(
    "symptoms_positive",
    s.symptoms?.positive
  );

  setListField(
    "symptoms_negative",
    s.symptoms?.negative
  );

  setListField(
    "past_history",
    s.past_medical_history
  );

  setListField(
    "medications",
    s.medication_history?.current_medications
  );

  setListField(
    "allergies",
    s.medication_history?.allergies
  );

  const obs =
    s.clinical_observations || {};

  setListField(
    "observations",
    [
      ...(obs.vitals || []),
      ...(obs.examination_findings || []),
    ]
  );

  setListField(
    "assessment",
    s.assessment
  );

  const plan = s.plan || {};

  const planItems = [
    ...(plan.investigations || []).map(
      (x) => `Investigation: ${x}`
    ),

    ...(plan.prescriptions || []).map(
      (x) => `Prescription: ${x}`
    ),

    ...(plan.advice || []).map(
      (x) => `Advice: ${x}`
    ),

    ...(plan.follow_up
      ? [`Follow-up: ${plan.follow_up}`]
      : []),
  ];

  setListField("plan", planItems);

  setTextField(
    "narrative",
    s.narrative_summary
  );
}

function copyRecordAsText() {
  const sheet = el("recordSheet");

  navigator.clipboard
    .writeText(sheet.innerText)
    .then(() => {
      copyBtn.textContent = "Copied";

      setTimeout(
        () => (copyBtn.textContent = "Copy record as text"),
        1500
      );
    });
}

startBtn.addEventListener(
  "click",
  startMic
);

stopBtn.addEventListener(
  "click",
  stopMic
);

clearBtn.addEventListener(
  "click",
  clearFeed
);

analyzeBtn.addEventListener(
  "click",
  analyzeTranscript
);

copyBtn.addEventListener(
  "click",
  copyRecordAsText
);

clearRecordBtn.addEventListener(
  "click",
  () => location.reload()
);
