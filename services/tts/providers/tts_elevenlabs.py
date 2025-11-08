# services/tts/providers/tts_elevenlabs.py
import os
import json
import base64
from fastapi import WebSocket
from ..tts_provider import TTSProvider
# Use top-level import to match newer SDKs
from elevenlabs import ElevenLabs

class ElevenLabsTTS(TTSProvider):
    def __init__(self, ws: WebSocket, stream_sid: str):
        super().__init__(ws, stream_sid)
        # Support both env var names
        self.api_key = os.getenv("ELEVENLABS_API_KEY") or os.getenv("ELEVEN_API_KEY")
        if not self.api_key:
            raise ValueError("ElevenLabs API key not found. Set ELEVENLABS_API_KEY or ELEVEN_API_KEY.")
        # Ensure SDK reads expected env var
        os.environ["ELEVEN_API_KEY"] = self.api_key
        # Newer SDKs read API key from env and take no args
        self.client = ElevenLabs()
        self.voice_id = "UgBBYS2sOqTuMpoF3BR0"
        
    async def get_audio_from_text(self, text: str) -> bool:
        try:
            # Stream audio directly in μ-law 8kHz format
            audio_stream = None
            if hasattr(self.client, "text_to_speech") and hasattr(self.client.text_to_speech, "stream"):
                audio_stream = self.client.text_to_speech.stream(
                    text=text,
                    voice_id=self.voice_id,
                    model_id="eleven_turbo_v2_5",
                    output_format="ulaw_8000"
                )
            elif hasattr(self.client, "text_to_speech") and hasattr(self.client.text_to_speech, "convert"):
                audio_stream = self.client.text_to_speech.convert(
                    text=text,
                    voice_id=self.voice_id,
                    model_id="eleven_turbo_v2_5",
                    output_format="ulaw_8000"
                )
            else:
                # Last resort: older naming
                generate_stream = getattr(self.client, "generate_stream", None)
                if callable(generate_stream):
                    audio_stream = generate_stream(
                        text=text,
                        voice=self.voice_id,
                        model_id="eleven_turbo_v2_5",
                        output_format="ulaw_8000"
                    )
                else:
                    raise RuntimeError("ElevenLabs streaming API not found; check SDK version")
            
            for chunk in audio_stream:
                if not chunk:
                    continue
                if isinstance(chunk, bytes):
                    payload_b64 = base64.b64encode(chunk).decode('utf-8')
                    await self.ws.send_text(json.dumps({
                        'event': 'media',
                        'streamSid': f"{self.stream_sid}",
                        'media': {'payload': payload_b64}
                    }))
                elif isinstance(chunk, dict) and 'audio' in chunk:
                    audio_bytes = chunk['audio']
                    payload_b64 = base64.b64encode(audio_bytes).decode('utf-8')
                    await self.ws.send_text(json.dumps({
                        'event': 'media',
                        'streamSid': f"{self.stream_sid}",
                        'media': {'payload': payload_b64}
                    }))
                else:
                    # Unexpected type, log and continue
                    print(f"Unexpected ElevenLabs stream chunk type: {type(chunk)}")
            
            return True
                
        except Exception as e:
            print(f"ElevenLabs TTS error: {e}")
            return False