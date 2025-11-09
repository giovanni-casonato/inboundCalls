import os
import json
from functools import partial
from fastapi import WebSocket
from services.llm.openai_async import LargeLanguageModel
import re

# Deepgram SDK imports aligned to v3
from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions

TWILIO_SAMPLE_RATE = 8000
ENCODING = "mulaw"

class DeepgramTranscriber:
    def __init__(self, assistant: LargeLanguageModel, ws: WebSocket, stream_sid):
        self.assistant = assistant
        # Initialize Deepgram client with API key from environment
        self.api_key = os.getenv("DEEPGRAM_API_KEY")
        if not self.api_key:
            raise ValueError("Deepgram API key not found. Set DEEPGRAM_API_KEY env var.")
        self.deepgram: DeepgramClient = DeepgramClient(self.api_key)
        self.dg_connection = None 
        self.transcripts = []
        self.ws = ws
        self.stream_sid = stream_sid
        self.started = False
        self.closed = False
        self.utterance_end_ms = os.getenv("DEEPGRAM_UTTERANCE_END_MS", "2000")

        # Build options for v3 LiveOptions
        self.options: LiveOptions = LiveOptions(
            model="nova-3",
            language="en-US",
            smart_format=True,
            encoding=ENCODING,
            channels=1,
            sample_rate=TWILIO_SAMPLE_RATE,
            interim_results=True,
            punctuate=True,
        )
    
    async def deepgram_connect(self):
        # If already started, do not reinitialize or restart
        if self.dg_connection is not None and self.started:
            print("socket is already initialized")
            return
        # Create live connection using asyncwebsocket (v3)
        conn = None
        try:
            conn = self.deepgram.listen.asyncwebsocket.v("1")
        except Exception:
            try:
                conn = self.deepgram.listen.websocket.v("1")
            except Exception:
                try:
                    conn = self.deepgram.listen.live.v("1")
                except Exception:
                    conn = None
        self.dg_connection = conn
        if not self.dg_connection:
            raise RuntimeError("Failed to initialize Deepgram live connection; SDK version mismatch")

        async def on_message(result, **kwargs):
            "Receive text from deepgram_ws"
            transcripts = kwargs.get('transcripts')
            assistant: LargeLanguageModel = kwargs.get('assistant')
            ws: WebSocket = kwargs.get('websocket')
            stream_sid = kwargs.get('stream_sid')

            sentence = result.channel.alternatives[0].transcript if result and getattr(result, 'channel', None) and result.channel.alternatives else ""

            if getattr(result, 'is_final', False):
                # collect final transcripts:
                if len(sentence) > 0:
                    transcripts.append(sentence)

                if len(transcripts) > 0 and re.search(r'[.!?]$', sentence):
                    user_message_final = " ".join(transcripts)
                    print(f'\nUser: {user_message_final}')

                    # clear audio from assistant on user response
                    await ws.send_text(json.dumps({'event': 'clear', 'streamSid': f"{stream_sid}"}))

                    await assistant.run_chat(user_message_final)
                    transcripts.clear()

        async def on_utterance_end(utterance_end, **kwargs):
            transcripts = kwargs.get('transcripts')
            assistant: LargeLanguageModel = kwargs.get('assistant')
            if transcripts and len(transcripts) > 0 and re.search(r'[.!?]$', transcripts[-1]):
                user_message_final = " ".join(transcripts)
                print(f'\nUser: {user_message_final}')

                await assistant.run_chat(user_message_final)
                transcripts.clear()
    
        on_message_with_kwargs = partial(on_message, transcripts=self.transcripts, assistant=self.assistant, websocket=self.ws, stream_sid=self.stream_sid)
        on_utterance_end_kwargs = partial(on_utterance_end, transcripts=self.transcripts, assistant=self.assistant)
        
        # Register event handlers using enums (v3)
        try:
            self.dg_connection.on(LiveTranscriptionEvents.Transcript, on_message_with_kwargs)
            self.dg_connection.on(LiveTranscriptionEvents.UtteranceEnd, on_utterance_end_kwargs)
        except Exception:
            # Fallback to string event names for older variants
            self.dg_connection.on('Transcript', on_message_with_kwargs)
            self.dg_connection.on('UtteranceEnd', on_utterance_end_kwargs)

        # Start connection with utterance_end_ms as request param per SDK
        try:
            await self.dg_connection.start(self.options, {'utterance_end_ms': str(self.utterance_end_ms)})
        except Exception as e:
            msg = str(e).lower()
            if 'already started' in msg:
                print('Deepgram websocket already started; using existing connection')
                self.started = True
            elif isinstance(e, TypeError):
                # Some SDK variants expect kwargs instead of a dict
                try:
                    await self.dg_connection.start(self.options, utterance_end_ms=str(self.utterance_end_ms))
                except Exception as e2:
                    msg2 = str(e2).lower()
                    if 'already started' in msg2:
                        print('Deepgram websocket already started; using existing connection')
                        self.started = True
                    else:
                        raise
            else:
                raise
        else:
            self.started = True
        print('Deepgram Transcriber Connected')
    
    async def deepgram_close(self):
        "Close Deepgram Connection"
        try:
            if self.dg_connection is not None and self.started and not self.closed:
                # Finish gracefully; some SDKs have finish() as coroutine
                finish_fn = getattr(self.dg_connection, 'finish', None)
                if finish_fn is not None:
                    res = finish_fn()
                    if hasattr(res, '__await__'):
                        await res
                self.closed = True
                self.started = False
                self.dg_connection = None
                print(f'\nDeepgram Transcriber Closed\n')
            else:
                # Already closed or never started
                print('Deepgram connection not active; skip close')
        except Exception as e:
            # Swallow errors during shutdown to avoid crashing ASGI
            print(f'Deepgram close error: {e}')
           

