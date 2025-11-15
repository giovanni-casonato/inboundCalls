# services/stt/deepgram.py
import os
import re
import json
import asyncio
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
        self.conn_context = None
        self.keepalive_task = None
        self.listening_task = None
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
        )

    async def deepgram_connect(self):   
        try:
            print("Starting Deepgram connection...")

            self.conn_context = self.dg.listen.v1.connect(**self._opts)
            self.conn = await self.conn_context.__aenter__()

            def on_message(msg: ListenV1SocketClientResponse) -> None:
                t = getattr(msg, "type", None)
                print(f"Deepgram message type: {t}")
                if t == "Results":
                    try:
                        text = msg.channel.alternatives[0].transcript or ""
                        print(f"Deepgram transcript: {text}")
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

            self.conn.on(EventType.OPEN, lambda _: print("Deepgram connection opened"))
            self.conn.on(EventType.MESSAGE, on_message)
            self.conn.on(EventType.CLOSE, lambda _: print("Deepgram connection closed"))
            self.conn.on(EventType.ERROR, lambda error: print(f"Deepgram error: {error}"))

            # Run start_listening as a background task so it doesn't block
            # This allows the connection to listen for events while main code continues
            self.listening_task = asyncio.create_task(self.conn.start_listening())
            self._listening = True

            self.keepalive_task = asyncio.create_task(self._keepalive())

        except Exception as e:
            print(f"Deepgram connection error: {e}")

    async def _keepalive(self):
        """Send periodic keepalive messages to maintain the connection"""
        while self._listening:
            await asyncio.sleep(5)
            try:
                if self.conn:
                    await self.conn.send_control(ListenV1ControlMessage(type="KeepAlive"))
            except Exception as e:
                print(f"Keepalive error: {e}")
                break

    async def send_audio(self, audio_bytes: bytes):
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
        print(f"Flushing to LLM: {text}")
        try:
            await self.ws.send_text(json.dumps({"event":"clear","streamSid": self.stream_sid}))
        except Exception as e:
            print(f"Error sending clear event: {e}")
        await self.llm.run_chat(text)

    async def _cancel_task(self, task):
        """Helper to safely cancel and await an asyncio task"""
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        return None

    async def deepgram_close(self):
        self._listening = False
        
        # Cancel background tasks
        self.listening_task = await self._cancel_task(self.listening_task)
        self.keepalive_task = await self._cancel_task(self.keepalive_task)
        
        # Close the connection properly
        if self.conn_context:
            try:
                await self.conn_context.__aexit__(None, None, None)
            except Exception as e:
                print(f"Error closing Deepgram connection: {e}")
            finally:
                self.conn = None
                self.conn_context = None

        if self._buf:
            self._buf.clear()
