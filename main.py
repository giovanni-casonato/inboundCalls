import os
import json
import base64
from fastapi import FastAPI, Request, WebSocket, Response
from twilio.twiml.voice_response import VoiceResponse

from services.tts.tts_factory import TTSFactory
from services.llm.openai_async import LargeLanguageModel
from services.stt.deepgram import DeepgramTranscriber

app = FastAPI()

# Twilio setup - only need account credentials for webhook validation if desired
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')

# Twilio sends audio data as 160 byte messages containing 20ms of audio each
# We buffer 4 twilio messages corresponding to 80 ms of audio
BUFFER_SIZE = 4 * 160  # 80ms chunks recommended for Flux
TWILIO_SAMPLE_RATE = 8000


@app.post("/incoming-call")
async def incoming_call(request: Request):
    """
    Webhook endpoint for incoming calls.
    Returns TwiML to connect the call to our WebSocket for AI processing.
    """
    response = VoiceResponse()
    
    # Connect the call to our WebSocket for real-time audio streaming
    response.connect().stream(url=f"wss://{request.url.netloc}/media-stream")
    
    return Response(content=str(response), media_type="application/xml")


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    """
    WebSocket endpoint for handling real-time audio from inbound calls.
    """
    await websocket.accept()
    buffer = bytearray(b'')
    empty_byte_received = False
    transcriber = None
    
    try:
        async for message in websocket.iter_text():
            data = json.loads(message)
            
            match data['event']:
                case "connected":
                    print("Media stream connected")
                    
                case "start":
                    stream_sid = data['streamSid']
                    call_sid = data['start']['callSid']
                    print(f"Inbound call started - Stream SID: {stream_sid}, Call SID: {call_sid}")
                    
                    # Initialize TTS provider for responding to caller
                    text_to_speech = TTSFactory.create_tts_provider("elevenlabs", websocket, stream_sid)
                    
                    print("1. After init tts")
                    # Initialize AI conversation
                    openai_llm = LargeLanguageModel(text_to_speech)
                    openai_llm.init_chat()
                    
                    print("2. After init openai")

                    # Initialize speech transcriber
                    transcriber = DeepgramTranscriber(openai_llm, websocket, stream_sid)
                    await transcriber.deepgram_connect()
                    
                    print("3. After init deepgram")
                    
                    # Send initial greeting to caller
                    await text_to_speech.get_audio_from_text("Hello! Thanks for calling Wholesale Atlas. I'm here to help you with your real estate investment needs. What markets are you interested in buying properties in?")
                    
                case "media":
                    if transcriber:
                        # Send audio to Deepgram for transcription
                        payload_b64 = data['media']['payload']
                        payload_mulaw = base64.b64decode(payload_b64)
                        buffer.extend(payload_mulaw)
                        
                        if payload_mulaw == b'':
                            empty_byte_received = True
                        
                        # Send buffer when it reaches the target size or when silence detected
                        if len(buffer) >= BUFFER_SIZE or empty_byte_received:
                            await transcriber.send_audio(buffer)
                            buffer = bytearray(b'')
                            empty_byte_received = False
                            
                case "stop":
                    print("Call ended")
                    if transcriber:
                        await transcriber.deepgram_close()
                        transcriber = None
                        
                case "mark":
                    # Handle mark events if needed
                    pass
                    
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        # Cleanup
        if transcriber:
            await transcriber.deepgram_close()
            transcriber = None


# Health check endpoint for Railway
@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)