# services/stt/deepgram.py
import os, re, json
from typing import List
from fastapi import WebSocket
from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType
from services.llm.openai_async import LargeLanguageModel

TWILIO_SAMPLE_RATE = 8000
ENCODING = "mulaw"

class DeepgramTranscriber:
    def __init__(self, llm_instance: LargeLanguageModel, websocket: WebSocket, stream_sid: str):
        self.llm = llm_instance
        self.ws = websocket
        self.stream_sid = stream_sid
        self.dg = AsyncDeepgramClient(api_key=os.environ["DEEPGRAM_API_KEY"])
        self._cm = None        # async context manager
        self.socket = None     # live socket
        self._buf: List[str] = []
        self._opts = dict(
            model="nova-3",
            language="en-US",
            smart_format=True,
            encoding=ENCODING,
            channels=1,
            sample_rate=TWILIO_SAMPLE_RATE,
            interim_results=True,
            utterance_end_ms=2000,
            punctuate=True,
        )

    async def deepgram_connect(self):
        if self.socket:
            return
        # 1) get context manager
        self._cm = self.dg.listen.v1.connect(**self._opts)
        # 2) enter it to get the SOCKET
        self.socket = await self._cm.__aenter__()

        async def on_message(msg):
            t = getattr(msg, "type", None)
            if t == "Transcript":
                try:
                    text = msg.channel.alternatives[0].transcript or ""
                except Exception:
                    return
                if not text:
                    return
                if getattr(msg, "is_final", False):
                    self._buf.append(text)
                    if re.search(r"[.!?]$", text):
                        await self._flush_to_llm()
            elif t == "UtteranceEnd":
                if self._buf:
                    await self._flush_to_llm()

        # IMPORTANT: attach handlers to the SOCKET, not the context manager
        self.socket.on(EventType.MESSAGE, on_message)

        # start read loop on the SOCKET
        await self.socket.start_listening()
        print("Deepgram Transcriber Connected (Nova-3)")

    async def send_audio(self, audio_bytes: bytes):
        if self.socket and audio_bytes:
            try:
                await self.socket.send(audio_bytes)
            except Exception as e:
                print(f"Deepgram send_audio error: {e}")

    async def _flush_to_llm(self):
        text = " ".join(self._buf).strip()
        self._buf.clear()
        if not text:
            return
        try:
            await self.ws.send_text(json.dumps({"event":"clear","streamSid": self.stream_sid}))
        except Exception:
            pass
        await self.llm.run_chat(text)

    async def deepgram_close(self):
        # flush remaining
        if self._buf:
            await self._flush_to_llm()
        # stop read loop, then exit context
        if self.socket:
            try:
                try:
                    await self.socket.stop_listening()
                except Exception:
                    pass
                if self._cm:
                    await self._cm.__aexit__(None, None, None)
            finally:
                self.socket = None
                self._cm = None
        print("Deepgram Transcriber Closed")
