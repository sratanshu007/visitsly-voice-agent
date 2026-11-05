# Visitsly AI Outbound Voice Agent 🎙️🏢

Production-ready, bi-directional conversational AI Outbound Voice Agent designed for real estate site-visit confirmations, rescheduling, and lead qualification in natural **Hindi & Hinglish** over **Plivo Telephony**.

Directly compatible with **[Visitsly-Backend](https://github.com/mohsin6388/Visitsly-Backend)** and any real estate CRM / SaaS webhook.

---

## 📑 Table of Contents
1. [Core Features](#-core-features)
2. [Architecture & Pipeline](#-architecture--pipeline)
3. [Zero-Cost Free Stack vs Paid Stack](#-zero-cost-free-stack-vs-paid-stack)
4. [Quick Start & Setup](#-quick-start--setup)
5. [Local Call Simulator (No Plivo Needed)](#-local-call-simulator-no-plivo-needed)
6. [Plivo Telephony Setup & Configuration](#-plivo-telephony-setup--configuration)
7. [Connecting with Visitsly-Backend](#-connecting-with-visitsly-backend)
8. [API Endpoints Reference](#-api-endpoints-reference)
9. [Compliance, Legal & Safety](#-compliance-legal--safety)
10. [Production VPS Deployment (HTTPS + WSS)](#-production-vps-deployment-https--wss)
11. [Performance & Latency Tuning](#-performance--latency-tuning)

---

## 🌟 Core Features

- **Real Two-Way Conversational Voice AI**: Bidirectional audio streaming over WebSockets (`audio/x-mulaw;rate=8000`).
- **Natural Hindi & Hinglish Persona**: Polite assistant of your company disclosing automated AI identity, keeping sentences short (max 2 per turn) and spoken style.
- **Ultra-Low Latency Pipeline (<1.2s)**: Sentence-level token chunking from streaming LLM to streaming TTS for instant speech delivery.
- **Instant Barge-In**: Flushes Plivo playback buffer with `clearAudio` event, cancels LLM/TTS generation tasks immediately when caller interrupts.
- **Smart Silence Handling**: Prompts *"Hello, kya aap mujhe sun pa rahe hain?"* after 6 seconds of silence; terminates politely after 2 silence prompts.
- **Indian Relative Date Parser**: Understands *"kal shaam 5 baje"*, *"parso dopahar 2 baje"*, *"sunday ko 4 pm"*, *"dhai baje"*, *"dedh baje"* in `Asia/Kolkata` timezone.
- **100% Legal & Compliant**:
  - Requires customer consent record (IP, timestamp, consent text, booking_id).
  - Calling window enforced strictly to **09:00 - 21:00 IST** (schedules for next morning if booked after 21:00).
  - SHA-256 hashed phone opt-out registry; immediate DND trigger on caller request ("call mat karo", "don't call me").
  - 3-minute hard call duration limit to prevent bill overruns.
  - Auto-retries for `busy`/`no-answer` up to 2 times, at least 2 hours apart, within calling hours.
- **HMAC-SHA256 Webhook**: Sends outcome (`CONFIRMED`, `RESCHEDULED`, `CANCELLED`, `CALLBACK_REQUESTED`, `NOT_INTERESTED`) back to SaaS with signature verification and exponential backoff retry.

---

## 🏗 Architecture & Pipeline

```
  SaaS Webhook (POST /api/bookings/confirmed)
       │
       ▼
 [Consent & Window Check] ──(Within 09:00-21:00 IST)──► [Plivo REST Dial API]
       │                                                         │
       │                                                         ▼
       │                                                  Customer Phone
       │                                                         │
       ▼                                                         ▼
  Plivo Media Server ◄──── Bi-directional WebSocket ────► Plivo Answer XML
                         (WS /plivo/stream)
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
      Incoming Audio (Mu-law)               Outgoing Audio (Mu-law)
            │                                     ▲
            ▼                                     │
   [Streaming STT]                          [Streaming TTS]
 (Deepgram / Groq Whisper)                 (Edge-TTS / Sarvam)
            │                                     ▲
            ▼                                     │
   [Turn State Machine] ───► [Streaming LLM] ────┘ (Sentence Chunking)
   (Silence / Barge-In)       (Groq / Claude)
            │
            ▼
   [Finalize Outcome] ───► POST SAAS_WEBHOOK_URL (HMAC Signed)
```

---

## ⚡ Zero-Cost Free Stack vs Paid Stack

You can run this entire service **100% Free** without spending a single rupee:

| Component | 🆓 Free Option (Default) | 💳 Paid Option |
| :--- | :--- | :--- |
| **LLM** | **Groq** (`llama-3.3-70b-versatile` / `qwen/qwen3.8-27b`)<br>• Free tier: 30 RPM, ~200ms TTFT | Anthropic Claude 3.5 Sonnet |
| **TTS** | **Edge-TTS** (`hi-IN-SwaraNeural`, `hi-IN-MadhurNeural`)<br>• 100% Free, zero quota limits, natural Hindi neural audio | Sarvam Bulbul / ElevenLabs |
| **STT** | **Groq Whisper** (`whisper-large-v3-turbo`)<br>• Free tier on Groq with high accuracy | Deepgram Nova-2 (`hi`) |
| **Database** | SQLite (`sqlite+aiosqlite:///./voice_agent.db`) | PostgreSQL + asyncpg |

To switch any provider, simply change `LLM_PROVIDER`, `STT_PROVIDER`, or `TTS_PROVIDER` in `.env`!

---

## 🚀 Quick Start & Setup

### Prerequisites
- Python 3.11+
- Virtual environment tool (`venv`)

### 1. Clone & Install
```bash
cd visitsly-voice-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Open `.env` and configure your credentials:
```ini
# Server configuration
PORT=8000
PUBLIC_HOST=your-ngrok-subdomain.ngrok-free.app  # (Do NOT add http:// or wss://)
API_KEY=visitsly_secret_booking_key_2026
ADMIN_API_KEY=visitsly_admin_secret_key_2026

# Telephony (Get from console.plivo.com)
PLIVO_AUTH_ID=your_plivo_auth_id
PLIVO_AUTH_TOKEN=your_plivo_auth_token
PLIVO_CALLER_ID=+918047289335

# Free LLM & STT via Groq
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_your_groq_key_here
GROQ_MODEL=llama-3.3-70b-versatile
STT_PROVIDER=groq

# 100% Free Indian Hindi TTS
TTS_PROVIDER=edge_tts
EDGE_TTS_VOICE=hi-IN-SwaraNeural

# SaaS Webhook URL (Visitsly-Backend or CRM)
SAAS_WEBHOOK_URL=http://localhost:3000/api/webhooks/voice/result
SAAS_WEBHOOK_SECRET=visitsly_webhook_hmac_secret_key_32chars
```

### 3. Run the Service
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Check health: `http://localhost:8000/health`  
Interactive Swagger docs: `http://localhost:8000/docs`

### 4. Dispatch Outbound Call via API
To queue an outbound confirmation call for a lead:
```bash
curl -X POST "http://localhost:8000/api/bookings/confirmed" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: visitsly_secret_booking_key_2026" \
  -d '{
    "booking_id": "booking-test-101",
    "customer_name": "Rahul Sharma",
    "phone": "+919876543210",
    "property_name": "Godrej Woods Sector 43",
    "visit_datetime": "2026-11-08 16:00",
    "language": "hi",
    "consent": {
      "given": true,
      "text": "User consented to receive site-visit confirmation call"
    }
  }'
```
This validates consent, checks the calling window (09:00 - 21:00 IST), and automatically initiates the live AI voice call via Plivo!

---

## 📞 Plivo Telephony Setup & Configuration

### 1. Expose Local Server via ngrok
For Plivo to hit your local server, expose port 8000:
```bash
ngrok http 8000
```
Copy the Forwarding HTTPS domain, e.g.: `d123-103-21-244.ngrok-free.app`.

In your `.env`, update:
```ini
PUBLIC_HOST=d123-103-21-244.ngrok-free.app
```
Restart the server.

### 2. Configure Plivo XML Application
1. Log in to [Plivo Console](https://console.plivo.com/).
2. Navigate to **Voice** $\rightarrow$ **XML Applications** $\rightarrow$ **Add Application**.
3. Fill details:
   - **Application Name**: `Visitsly Voice Agent`
   - **Answer URL**: `https://<PUBLIC_HOST>/plivo/answer` (Method: `POST`)
   - **Hangup URL**: `https://<PUBLIC_HOST>/plivo/hangup` (Method: `POST`)
   - **Fallback URL**: `https://<PUBLIC_HOST>/plivo/hangup` (Method: `POST`)
4. Attach this XML Application to your purchased Plivo phone number.

> [!IMPORTANT]
> **India Calling & Telephony KYC Requirements**:
> Under TRAI (Telecom Regulatory Authority of India) and Indian DoT regulations, outbound calling requires enterprise DLT/KYC registration and registered CLI / sender headers. Contact **Plivo Support** (`support@plivo.com` or via console ticket) to complete enterprise entity verification for Indian (+91) outbound routes before dialing Indian mobile numbers. For testing outside India or with sandbox numbers, no additional KYC is needed.

---

## 🔗 Connecting with Visitsly-Backend

In your [Visitsly-Backend](https://github.com/mohsin6388/Visitsly-Backend) Node.js server, trigger a call when a lead books a visit:

### 1. Trigger Booking Webhook from Visitsly-Backend
```javascript
// In Visitsly-Backend (Node.js)
const axios = require('axios');

async function triggerVoiceAgent(lead, booking) {
  const response = await axios.post(
    'http://localhost:8000/api/bookings/confirmed',
    {
      booking_id: String(booking._id),
      customer_name: lead.name,
      phone: lead.phone, // E.164 (+919876543210)
      property_name: lead.project || 'Visitsly Luxury Residency',
      visit_datetime: booking.preferredDate + ' ' + booking.preferredTime,
      language: 'hi',
      consent: {
        given: true,
        timestamp: new Date().toISOString(),
        ip: lead.ip || '127.0.0.1',
        text: 'User checked consent box on booking form to verify visit via phone call.',
      },
    },
    {
      headers: {
        'X-API-Key': process.env.VOICE_AGENT_API_KEY || 'visitsly_secret_booking_key_2026',
      },
    }
  );
  return response.data;
}
```

### 2. Receiving Outbound Result Webhook in Visitsly-Backend
When the call completes, this service automatically posts the outcome back to `SAAS_WEBHOOK_URL` (`POST /api/webhooks/voice/:captureKey`):

```json
{
  "booking_id": "67290a1f81...",
  "outcome": "CONFIRMED",
  "new_datetime": null,
  "attempts": 1,
  "duration": 48,
  "transcript_summary": "Customer confirmed visit for tomorrow at 11 AM.",
  "execution_id": "93b2a8f1-...",
  "status": "completed",
  "summary": "Customer confirmed visit for tomorrow at 11 AM.",
  "transcript": "Assistant: Namaste Rahul ji...\nCaller: Haan main kal aa raha hoon...",
  "extracted_data": {
    "interested": true,
    "visit_date": "2026-11-06",
    "visit_time": "11:00",
    "outcome": "CONFIRMED"
  },
  "user_data": {
    "propai_call_id": "67290a1f81...",
    "booking_id": "67290a1f81..."
  }
}
```
Header: `X-Signature-SHA256: <hex_digest_hmac>`

---

## 📡 API Endpoints Reference

### 1. `POST /api/bookings/confirmed`
- **Header**: `X-API-Key: visitsly_secret_booking_key_2026`
- **Body**:
  ```json
  {
    "booking_id": "bk-1001",
    "customer_name": "Pooja Verma",
    "phone": "+919876543210",
    "property_name": "DLF Magnolias",
    "visit_datetime": "Kal shaam 5 baje",
    "language": "hi",
    "consent": {
      "given": true,
      "timestamp": "2026-11-05T12:00:00Z",
      "ip": "203.0.113.195",
      "text": "User explicitly accepted calling terms on website."
    }
  }
  ```
- **Returns**: `202 Accepted`
  ```json
  {
    "status": "CALL_INITIATED",
    "message": "Call placed successfully via Plivo.",
    "booking_id": "bk-1001",
    "call_id": "e4299b61-41e3-463e-9ea1-e374528d9c28"
  }
  ```

### 2. `POST /plivo/answer`
- Called by Plivo when call is picked up. Returns Plivo XML `<Stream>`.

### 3. `WS /plivo/stream?call_id=...&booking_id=...`
- Plivo Bidirectional audio WebSocket.

### 4. `POST /plivo/hangup`
- Call status callback. Automatically schedules 2-hour retry if busy/unanswered within 09:00 - 21:00 IST.

### 5. `POST /plivo/machine`
- Answering Machine Detection (AMD) callback.

### 6. Admin Opt-Out Endpoints
- `POST /api/admin/opt-out`: Add number to DND (header: `X-Admin-API-Key`).
- `DELETE /api/admin/opt-out/{phone}`: Remove number from DND.
- `GET /api/admin/opt-out`: List opted-out hashes.

---

## 🔒 Compliance, Legal & Safety

1. **Explicit Consent Gate**: Rejects any request with `consent.given == false`. Full consent audit trail stored in DB (`consents` table).
2. **Calling Window (09:00 - 21:00 IST)**: If a booking arrives at 21:30, the call is queued and automatically scheduled for 09:00 AM IST next day.
3. **Data Minimization & Masking**: Application logs mask phone numbers (`+91 98**** 1234`). Transcripts are persisted only in the database.
4. **Instant DND / Opt-Out**: If customer says *"call mat karo"* or *"stop calling"*, the agent immediately apologizes, adds the SHA-256 hashed phone number to `opt_outs` table, and hangs up. Future calls to this number are blocked automatically.
5. **3-Minute Duration Cap**: Hard hangup after 180 seconds prevents runaway calls and unexpected telephony bills.

---

## 🚢 Production VPS Deployment (HTTPS + WSS)

### Option A: Docker Compose (Recommended)
```bash
docker compose up -d --build
```
This runs the FastAPI Voice Agent service along with PostgreSQL 16.

### Option B: Caddy Reverse Proxy (Automatic SSL & WebSockets)
Install Caddy on Ubuntu/Debian:
```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install caddy
```

Add `/etc/caddy/Caddyfile`:
```caddy
voice.yourdomain.com {
    reverse_proxy localhost:8000
}
```
Reload Caddy:
```bash
sudo systemctl reload caddy
```
Caddy automatically provisions free Let's Encrypt SSL certificates with native support for both HTTPS and WSS (WebSocket Secure)!

### Option C: Systemd Service
Create `/etc/systemd/system/voice-agent.service`:
```ini
[Unit]
Description=Visitsly AI Outbound Voice Agent
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/visitsly-voice-agent
ExecStart=/home/ubuntu/visitsly-voice-agent/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always

[Install]
WantedBy=multi-user.target
```
Enable & Start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable voice-agent
sudo systemctl start voice-agent
```

---

## ⚡ Performance & Latency Tuning

The service logs detailed per-turn latencies to help tune performance:
```
[Turn 1 Latency] Total: 412ms | STT: 85ms | LLM TTFT: 198ms | TTS TTFB: 129ms
```

To achieve sub-second turnaround:
1. **Sentence-level chunking**: The agent splits LLM streaming tokens on `.`, `?`, `!`, `।`, `\n` and streams each sentence to TTS without waiting for the whole response.
2. **Groq Llama 3.3 70B**: Provides ~180-250ms Time-To-First-Token (TTFT).
3. **Edge-TTS**: Local audio decoding via `miniaudio` and pure-Python G.711 conversion executes in under 20 milliseconds per chunk.
4. **WebSocket buffering**: Streams 160-byte chunks (20ms frames) for zero jitter on mobile networks.

