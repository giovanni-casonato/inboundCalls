# services/tts/providers/tts_elevenlabs.py
import os
import json
import base64
from fastapi import WebSocket
from ..tts_provider import TTSProvider
from elevenlabs import ElevenLabs

class ElevenLabsTTS(TTSProvider):
    def __init__(self, ws: WebSocket, stream_sid: str):
        super().__init__(ws, stream_sid)
        self.api_key = os.getenv("ELEVENLABS_API_KEY") or os.getenv("ELEVEN_API_KEY")
        if not self.api_key:
            raise ValueError("ElevenLabs API key not found.")
        os.environ["ELEVEN_API_KEY"] = self.api_key
        self.client = ElevenLabs()
        self.voice_id = "UgBBYS2sOqTuMpoF3BR0"
        
    async def get_audio_from_text(self, text: str) -> bool:
        try:
            # Get audio data directly in μ-law 8kHz format
            audio_stream = self.client.text_to_speech.stream(
                text=text,
                voice_id=self.voice_id,
                model_id="eleven_turbo_v2_5",
                output_format="ulaw_8000"  # Request μ-law 8kHz directly
            )
            
            for chunk in audio_stream:
                if isinstance(chunk, bytes):
                    # Encode to base64 for Twilio
                    payload_b64 = base64.b64encode(chunk).decode('utf-8')
                    
                    # Send to Twilio WebSocket
                    await self.ws.send_text(json.dumps({
                        'event': 'media',
                        'streamSid': f"{self.stream_sid}",
                        'media': {'payload': payload_b64}
                    }))
                else:
                    print(f"Unexpected chunk type: {type(chunk)}")
                    
            return True
                
        except Exception as e:
            print(f"ElevenLabs TTS error: {e}")
            return False