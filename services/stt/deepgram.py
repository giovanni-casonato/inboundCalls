import os
import json
from fastapi import WebSocket
from services.llm.openai_async import LargeLanguageModel
import re

from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType


TWILIO_SAMPLE_RATE = 8000  # Flux mulaw sample rate
ENCODING = "mulaw"  # Flux-supported PCM encoding

class DeepgramTranscriber:
    def __init__(self, assistant: LargeLanguageModel, ws: WebSocket, stream_sid):
        self.assistant = assistant
        self.ws = ws
        self.stream_sid = stream_sid

        # Client & socket
        api_key = os.getenv("DEEPGRAM_API_KEY")
        if not api_key:
            raise RuntimeError("Missing DEEPGRAM_API_KEY")
        self.deepgram = AsyncDeepgramClient(api_key=api_key)
        self.dg_connection = None 
        self._buf_text: List[str] = []
        self._sentence_flush_regex = re.compile(r"[.!?]$")

        self._closed = False

        # Flux-specific parameters from environment or defaults
        self.eot_threshold = float(os.getenv("DEEPGRAM_EOT_THRESHOLD", "0.7"))
        self.eager_eot_threshold = float(os.getenv("DEEPGRAM_EAGER_EOT_THRESHOLD", "0.6"))
        self.eot_timeout_ms = int(os.getenv("DEEPGRAM_EOT_TIMEOUT_MS", "2000"))
    

    async def deepgram_connect(self):
        """Open a Flux v2 listen socket and start receiving events."""
        if self.dg_connection:
            print("socket is already initialized")
            return
        
        # Create Flux v2 connection
        self.dg_connection = await self.deepgram.listen.v2.connect(
            model="flux-general-en",
            encoding=ENCODING,
            sample_rate=TWILIO_SAMPLE_RATE,
        )

        # Single message handler for all server events
        async def on_message(msg):
            # msg.type is a string like "Transcript", "EagerEndOfTurn", "EndOfTurn", "TurnResumed"
            t = getattr(msg, "type", None)

            if t == "Transcript":
                # SDK sends a flattened object on v2 with .transcript and .is_final
                text = getattr(msg, "transcript", "") or ""
                if not text:
                    return

                if getattr(msg, "is_final", False):
                    self._buf_text.append(text)

                    # Optional early flush when a final segment ends with punctuation
                    if self._sentence_flush_regex.search(text):
                        await self._flush_to_llm(speculative=False)

            # elif t == "EagerEndOfTurn":
            #     # Start LLM fast; your LLM should support speculative or cancellable output
            #     if self._buf_text:
            #         await self._flush_to_llm(speculative=True)

            # elif t == "TurnResumed":
            #     # User kept talking -> cancel speculative TTS/LLM if supported
            #     cancel = getattr(self.assistant, "cancel", None)
            #     if callable(cancel):
            #         try:
            #             await cancel()
            #         except Exception:
            #             pass  # swallow cancel errors; transcript continues

            # elif t == "EndOfTurn":
            #     if self._buf_text:
            #         await self._flush_to_llm(speculative=False)


        # Register Flux event handlers
        self.dg_connection.on(EventType.MESSAGE, on_message)

        await self.dg_connection.start_listening()


    async def send_audio(self, audio_data: bytes):
        """
        Send Twilio mulaw 8k audio directly to Deepgram Flux.
        Twilio yields 160-byte mulaw frames (20ms at 8kHz). We buffer upstream to ~80ms.
        """
        if not self.dg_connection or self.c:
            return

        try:
            await self.dg_connection.send(audio_data)
        except Exception as e:
            print(f"Deepgram send_audio error: {e}")
    

    async def deepgram_close(self):
        """Finish the stream gracefully; safe to call multiple times."""
        if self._closed:
            return
        self._closed = True

        try:
            if self._buf_text:
                await self._flush_to_llm(speculative=False)
        except Exception:
            pass

        try:
            if self.dg_connection:
                await self.dg_connection.finish()
        finally:
            self.dg_connection = None

    # HELPERS
    async def _flush_to_llm(self, speculative: bool):
        """
        Clear Twilio's playback buffer, dispatch buffered ASR text to LLM,
        and reset the local transcript buffer.
        """
        text = " ".join(self._buf_text).strip()
        self._buf_text.clear()
        if not text:
            return

        # Interrupt any audio currently queued to caller for fast barge-in
        try:
            await self.ws.send_text(json.dumps({"event": "clear", "streamSid": self.stream_sid}))
        except Exception:
            # If the WS is gone, we still try to run the LLM (no-op for TTS)
            pass

        # Your LLM driver should stream TTS back to Twilio through your TTS provider
        await self.assistant.run_chat(text, speculative=speculative)