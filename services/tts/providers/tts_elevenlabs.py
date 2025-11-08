# services/tts/providers/tts_elevenlabs.py
import os
import json
import base64
from fastapi import WebSocket
from ..tts_provider import TTSProvider
from elevenlabs.client import ElevenLabs

class ElevenLabsTTS(TTSProvider):
    def __init__(self, ws: WebSocket, stream_sid: str):
        super().__init__(ws, stream_sid)
        self.api_key = os.getenv("ELEVENLABS_API_KEY")
        if not self.api_key:
            raise ValueError("ElevenLabs API key not found.")

        # Ensure SDK-compatible env var name exists
        os.environ.setdefault("ELEVEN_API_KEY", self.api_key)

        # Initialize client robustly across SDK versions
        try:
            # Newer SDKs may read API key from env and take no args
            self.client = ElevenLabs()
        except TypeError:
            # Older SDKs allow explicit api_key kwarg
            self.client = ElevenLabs(api_key=self.api_key)

        # Configure your voice (voice ID expected by stream API)
        self.voice_id = "UgBBYS2sOqTuMpoF3BR0"
        
    async def get_audio_from_text(self, text: str) -> bool:
        try:
            stream = None
            # Preferred streaming API
            if hasattr(self.client, "text_to_speech") and hasattr(self.client.text_to_speech, "stream"):
                stream = self.client.text_to_speech.stream(
                    text=text,
                    voice_id=self.voice_id,
                    model_id="eleven_turbo_v2_5",
                    output_format="ulaw_8000"  # μ-law 8kHz for Twilio
                )
            # Fallback: alternate API naming in some SDK versions
            elif hasattr(self.client, "generate_stream"):
                stream = self.client.generate_stream(
                    text=text,
                    voice=self.voice_id,
                    model_id="eleven_turbo_v2_5",
                    output_format="ulaw_8000"
                )
            else:
                raise RuntimeError("ElevenLabs streaming API not found in installed SDK")
            
            # Iterate over audio chunks and send to Twilio WebSocket
            for chunk in stream:
                if not chunk:
                    continue
                if isinstance(chunk, bytes):
                    payload_b64 = base64.b64encode(chunk).decode('utf-8')
                    await self.ws.send_text(json.dumps({
                        'event': 'media',
                        'streamSid': f"{self.stream_sid}",
                        'media': {'payload': payload_b64}
                    }))
                else:
                    # Some SDKs may yield dicts with 'audio'
                    if isinstance(chunk, dict) and 'audio' in chunk:
                        audio_bytes = chunk['audio']
                        payload_b64 = base64.b64encode(audio_bytes).decode('utf-8')
                        await self.ws.send_text(json.dumps({
                            'event': 'media',
                            'streamSid': f"{self.stream_sid}",
                            'media': {'payload': payload_b64}
                        }))
                    else:
                        print(f"Unexpected ElevenLabs stream chunk type: {type(chunk)}")
            
            return True
                
        except Exception as e:
            print(f"ElevenLabs TTS error: {e}")
            return False