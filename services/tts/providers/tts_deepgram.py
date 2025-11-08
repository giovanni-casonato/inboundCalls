import os
import base64
import json
from fastapi import WebSocket
from deepgram import DeepgramClient
from ..tts_provider import TTSProvider

class DeepgramTTS(TTSProvider):
    def __init__(self, ws: WebSocket, stream_sid):
        super().__init__(ws, stream_sid)
        self.api_key = os.getenv("DEEPGRAM_API_KEY")
        if not self.api_key:
            raise ValueError("Deepgram API key not found.")
        
        self.deepgram = DeepgramClient(self.api_key)

    async def get_audio_from_text(self, text: str) -> bool:
        try:
            # Use dictionary options for SDK compatibility across versions
            options = {
                "model": "aura-2-amalthea-en",
                "encoding": "mulaw",
                "sample_rate": 8000,
            }
            
            # Get audio stream directly
            audio_stream = self.deepgram.speak.rest.v("1").stream(
                {"text": text}, 
                options
            )
            
            # Process audio chunks
            for chunk in audio_stream:
                if chunk:
                    # Encode to base64 for Twilio
                    payload_b64 = base64.b64encode(chunk).decode('utf-8')
                    
                    # Send to Twilio WebSocket
                    await self.ws.send_text(json.dumps({
                        'event': 'media',
                        'streamSid': self.stream_sid,
                        'media': {'payload': payload_b64}
                    }))
            
            return True
                    
        except Exception as e:
            print(f"Error in Deepgram TTS: {str(e)}")
            return False