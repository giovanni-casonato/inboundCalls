# services/stt/deepgram.py
import os, re, json, asyncio
from typing import List
from fastapi import WebSocket
from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType
from deepgram.extensions.types.sockets import (
    ListenV1MediaMessage,
    ListenV1ControlMessage,
    ListenV1SocketClientResponse,
)
from services.llm.openai_async import LargeLanguageModel

TWILIO_SAMPLE_RATE = 8000
ENCODING = "mulaw"

class DeepgramTranscriber:
    def __init__(self, llm_instance: LargeLanguageModel, websocket: WebSocket, stream_sid: str):
        self.llm = llm_instance
        self.ws = websocket
        self.stream_sid = stream_sid
        self.dg = AsyncDeepgramClient(api_key=os.environ["DEEPGRAM_API_KEY"])
        self._buf: List[str] = []
        self.conn = None
        self._keepalive_task: asyncio.Task | None = None
        self._listening = False
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
        try:
            async with self.dg.listen.v1.connect(**self._opts) as self.conn:
                def on_message(msg: ListenV1SocketClientResponse):
                    t = getattr(msg, "type", None)
                    if t == "Results":
                        try:
                            text = msg.channel.alternatives[0].transcript or ""
                        except Exception:
                            return
                        if not text:
                            return
                        if getattr(msg, "is_final", False):
                            self._buf.append(text)
                            if re.search(r"[.!?]$", text):
                                asyncio.create_task(self._flush_to_llm())
                    elif t == "UtteranceEnd":
                        if self._buf:
                            asyncio.create_task(self._flush_to_llm())

                self.conn.on(EventType.OPEN, lambda *_: print("Deepgram connection opened"))
                self.conn.on(EventType.MESSAGE, on_message)
                self.conn.on(EventType.CLOSE, lambda *_: print("Deepgram connection closed"))
                self.conn.on(EventType.ERROR, lambda error: print(f"Deepgram error: {error}"))

                self._listening = True

                # keepalive loop
                async def keepalive():
                    while self._listening:
                        await asyncio.sleep(5)
                        try:
                            await self.conn.send_control(ListenV1ControlMessage(type="KeepAlive"))
                        except Exception:
                            break
                self._keepalive_task = asyncio.create_task(keepalive())
                await self.conn.start_listening()
        except Exception as e:
            print(f"Deepgram connection error: {e}")
        finally:
            self._listening = False
            self.conn = None

    async def send_audio(self, audio_bytes: bytes):
        if self.conn and audio_bytes and self._listening:
            try:
                # Use typed media message for Listen V1
                await self.conn.send_media(ListenV1MediaMessage(audio_bytes))
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
        self._listening = False
        if self._keepalive_task:
            self._keepalive_task.cancel()

        if self._buf:
            self._buf.clear()
