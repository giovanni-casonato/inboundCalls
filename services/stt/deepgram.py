import os
import re
import json
from typing import List
from fastapi import WebSocket

from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType
from services.llm.openai_async import LargeLanguageModel

TWILIO_SAMPLE_RATE = 8000
ENCODING = "mulaw"


class DeepgramTranscriber:
    """Real-time speech transcription using Deepgram API"""
    
    def __init__(self, llm_instance: LargeLanguageModel, websocket: WebSocket, stream_sid: str):
        self.llm = llm_instance
        self.ws = websocket
        self.stream_sid = stream_sid

        api_key = os.getenv("DEEPGRAM_API_KEY")
        if not api_key:
            raise RuntimeError("Missing DEEPGRAM_API_KEY")
        self.deepgram = AsyncDeepgramClient(api_key=api_key)

        self.dg_connection = None 
        self._transcripts: List[str] = []

        # Live connection options (pass as kwargs to connect)
        self._connect_kwargs = {
            "model": "nova-3",
            "language": "en-US",
            "smart_format": True,
            "encoding": ENCODING,
            "channels": 1,
            "sample_rate": TWILIO_SAMPLE_RATE,
            "interim_results": True,     # needed to get timely partials
            "utterance_end_ms": 2000,    # silence that finalizes an utterance
            "punctuate": True,
        }

    async def deepgram_connect(self):
        """Open the Nova-3 websocket and register event handlers."""
        if self.dg_connection:
            return

        self.dg_connection = self.deepgram.listen.v1.connect(**self._connect_kwargs)

        async def on_transcript(msg):
            """
            Handle Transcript events: collect finalized sentences; on sentence end,
            flush to LLM and clear transcripts.
            """
            # Defensive guards: not all events carry the same payload shape
            try:
                sentence: str = msg.channel.alternatives[0].transcript or ""
            except Exception:
                return

            if not sentence:
                return

            if getattr(msg, "is_final", False):
                self._transcripts.append(sentence)

                # Flush on sentence boundary to keep latency low
                if re.search(r"[.!?]$", sentence):
                    user_final = " ".join(self._transcripts).strip()
                    if user_final:
                        # Clear any assistant audio on the Twilio side
                        try:
                            await self.ws.send_text(json.dumps({
                                "event": "clear",
                                "streamSid": self.stream_sid
                            }))
                        except Exception:
                            pass

                        # Kick the LLM (your openai_async.py implements run_chat)
                        await self.llm.run_chat(user_final)

                    self._transcripts.clear()

        async def on_utterance_end(_msg):
            """
            If DG finalizes an utterance (silence), flush whatever we buffered,
            even if it didn't end with punctuation.
            """
            if not self._transcripts:
                return

            user_final = " ".join(self._transcripts).strip()
            self._transcripts.clear()
            if not user_final:
                return

            try:
                await self.ws.send_text(json.dumps({
                    "event": "clear",
                    "streamSid": self.stream_sid
                }))
            except Exception:
                pass

            await self.llm.run_chat(user_final)

        # Hook up events
        self.dg_connection.on(EventType.TRANSCRIPT, on_transcript)
        self.dg_connection.on(EventType.UTTERANCE_END, on_utterance_end)

        # Start listening
        await self.dg_connection.start_listening()
        print("Deepgram Transcriber Connected (Nova-3)")

    async def send_audio(self, audio_bytes: bytes):
        """Forward raw μ-law 8k chunks to Deepgram (e.g., every ~80 ms)."""
        if not self.dg_connection or not audio_bytes:
            return
        try:
            await self.dg_connection.send(audio_bytes)
        except Exception as e:
            print(f"Deepgram send_audio error: {e}")

    async def deepgram_close(self):
        """Finish the stream gracefully; flush any pending text."""
        # Flush remaining transcript if any
        if self._transcripts:
            user_final = " ".join(self._transcripts).strip()
            self._transcripts.clear()
            if user_final:
                try:
                    await self.ws.send_text(json.dumps({
                        "event": "clear",
                        "streamSid": self.stream_sid
                    }))
                except Exception:
                    pass
                await self.llm.run_chat(user_final)

        if self.dg_connection:
            try:
                await self.dg_connection.finish()
            finally:
                self.dg_connection = None
        print("Deepgram Transcriber Closed")