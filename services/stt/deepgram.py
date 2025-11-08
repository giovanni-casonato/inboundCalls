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

        # Build options for v3 LiveOptions
        self.options: LiveOptions = LiveOptions(
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

        async def on_message(self, result, **kwargs):
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

        async def on_utterance_end(self, utterance_end, **kwargs):
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

        await self.dg_connection.start(self.options)
        print('Deepgram Transcriber Connected')
    
    async def deepgram_close(self):
        "Close Deepgram Connection"
        await self.dg_connection.finish()
        print(f'\nDeepgram Transcriber Closed\n')
           

