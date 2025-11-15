# Wholesale Atlas Inbound Calls

This service handles Twilio inbound call WebSocket, TTS, and STT using FastAPI with intelligent appointment scheduling via Google Calendar.

## ✨ Features

- 📞 **Natural phone conversations** - Handles incoming calls via Twilio
- 🎤 **Real-time transcription** - Deepgram speech-to-text with WebSocket streaming
- 🤖 **AI-powered responses** - OpenAI GPT with function calling
- 🗣️ **Human-like voice** - ElevenLabs text-to-speech
- 📅 **Appointment booking** - Integrated Google Calendar scheduling
- 🔄 **Async architecture** - Non-blocking WebSocket handling for low latency

## 📅 Google Calendar Integration

The AI assistant can now:
- Check available appointment slots
- Schedule appointments automatically
- Collect customer information (name, email, phone)
- Send calendar invitations
- Set up automatic reminders

**See [`GOOGLE_CALENDAR_SETUP.md`](GOOGLE_CALENDAR_SETUP.md) for complete setup instructions.**

Quick setup:
1. Create Google Cloud service account
2. Enable Google Calendar API
3. Share your calendar with the service account
4. Set environment variable: `GOOGLE_CALENDAR_CREDENTIALS_JSON`

## 🎯 Use Cases
- Handles incoming sales/support calls with natural conversation
- Books appointments automatically via Google Calendar
- Captures customer preferences and contact information
- Answers questions about your business
- Provides information about markets, services, pricing, etc.
- Runs in real-time with low latency

## 🚀 Quick Start

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set environment variables:**
   ```bash
   export OPENAI_API_KEY=your_openai_key
   export DEEPGRAM_API_KEY=your_deepgram_key
   export ELEVENLABS_API_KEY=your_elevenlabs_key
   export GOOGLE_CALENDAR_CREDENTIALS_JSON='{"type":"service_account",...}'
   ```

3. **Run the server:**
   ```bash
   python main.py
   ```

4. **Set up Twilio webhook** (see below)

## Twilio Setup
- Buy a voice‑enabled Twilio number
- Point Incoming Call webhook to `https://<your-domain>/incoming-call` (use ngrok for local: `ngrok http 8080`)
- Ensure media streams are enabled to use the WebSocket

## Endpoints
- `POST /incoming-call` — Twilio webhook for new calls
- `WS /media-stream` — Real‑time audio stream for STT/LLM/TTS

## 🛠️ Tech Stack
- **FastAPI** - Web server & WebSocket handling
- **Twilio** - Telephony & media streaming
- **Deepgram** - Real-time speech-to-text
- **OpenAI GPT-4o-mini** - LLM with function calling
- **ElevenLabs** - Natural text-to-speech
- **Google Calendar API** - Appointment scheduling

## 📁 Project Structure
```
inboundCalls/
├── main.py                          # FastAPI app & WebSocket handler
├── services/
│   ├── stt/
│   │   └── deepgram.py             # Speech-to-text service
│   ├── tts/
│   │   ├── tts_factory.py          # TTS provider factory
│   │   └── providers/
│   │       └── tts_elevenlabs.py   # ElevenLabs TTS
│   ├── llm/
│   │   ├── openai_async.py         # OpenAI with function calling
│   │   └── instructions.txt        # System prompt
│   └── calendar/
│       └── google_calendar.py      # Google Calendar integration
├── requirements.txt
├── GOOGLE_CALENDAR_SETUP.md        # Calendar setup guide
└── CALENDAR_INTEGRATION_SUMMARY.md # Implementation details
```

## 📚 Documentation
- [`GOOGLE_CALENDAR_SETUP.md`](GOOGLE_CALENDAR_SETUP.md) - Complete Google Calendar setup guide
- [`CALENDAR_INTEGRATION_SUMMARY.md`](CALENDAR_INTEGRATION_SUMMARY.md) - How the calendar integration works

## 🔒 Security Notes
- Keep API keys in environment variables
- Never commit credentials to git
- Add `credentials.json` to `.gitignore`
- Use service accounts for Google Calendar (not OAuth)
- Rotate keys periodically

## 🎨 Customization
- Edit `services/llm/instructions.txt` for custom AI behavior
- Modify business hours in `services/calendar/google_calendar.py`
- Update timezone settings for your location
- Customize TTS voice in `services/tts/providers/tts_elevenlabs.py`