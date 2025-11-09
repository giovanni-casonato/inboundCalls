import os
import json
from functools import partial
from fastapi import WebSocket
from services.llm.openai_async import LargeLanguageModel
import re

from deepgram import AsyncDeepgramClient

# Audio format constants for Flux
# Flux supports mulaw at 8000Hz; Twilio sends mulaw at 8000Hz.
# We send Twilio's mulaw 8k audio directly without conversion.
TWILIO_SAMPLE_RATE = 8000  # Flux mulaw sample rate
ENCODING = "mulaw"  # Flux-supported PCM encoding

class DeepgramTranscriber:
    def __init__(self, assistant: LargeLanguageModel, ws: WebSocket, stream_sid):
        self.assistant = assistant
        # Initialize Deepgram client with API key from environment
        self.deepgram = AsyncDeepgramClient(api_key=os.getenv("DEEPGRAM_API_KEY"))
        self.dg_connection = None 
        self.transcripts = []
        self.ws = ws
        self.stream_sid = stream_sid
        self.started = False
        self.closed = False

        # Flux-specific parameters from environment or defaults
        self.eot_threshold = float(os.getenv("DEEPGRAM_EOT_THRESHOLD", "0.7"))
        self.eager_eot_threshold = float(os.getenv("DEEPGRAM_EAGER_EOT_THRESHOLD", "0.6"))
        self.eot_timeout_ms = int(os.getenv("DEEPGRAM_EOT_TIMEOUT_MS", "2000"))
    
    async def deepgram_connect(self):
        # If already started, do not reinitialize or restart
        if self.dg_connection is not None and self.started:
            print("socket is already initialized")
            return
        
        # Create Flux v2 connection
        self.dg_connection = self.deepgram.listen.v2.connect(
            model="flux-general-en",
            # language="en-US",
            # encoding=ENCODING,
            # sample_rate=TWILIO_SAMPLE_RATE,
            # channels=1,
            # interim_results=True,
            # smart_format=True,
            # punctuate=True,
            # Flux turn-taking controls
            eot_threshold=self.eot_threshold,
            eager_eot_threshold=self.eager_eot_threshold,
            eot_timeout_ms=self.eot_timeout_ms,
        )

        async def on_transcript(result, **kwargs):
            "Handle transcript results from Flux"
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

        async def on_end_of_turn(turn_end, **kwargs):
            "Handle Flux EndOfTurn event for smart turn detection"
            transcripts = kwargs.get('transcripts')
            assistant: LargeLanguageModel = kwargs.get('assistant')
            
            if transcripts and len(transcripts) > 0:
                user_message_final = " ".join(transcripts)
                print(f'\nUser (EndOfTurn): {user_message_final}')

                await assistant.run_chat(user_message_final)
                transcripts.clear()

        async def on_eager_end_of_turn(eager_turn_end, **kwargs):
            "Handle Flux EagerEndOfTurn event for ultra-low latency"
            transcripts = kwargs.get('transcripts')
            assistant: LargeLanguageModel = kwargs.get('assistant')
            
            if transcripts and len(transcripts) > 0:
                user_message_final = " ".join(transcripts)
                print(f'\nUser (EagerEndOfTurn): {user_message_final}')

                # Early LLM response for ultra-low latency
                await assistant.run_chat(user_message_final)
                transcripts.clear()

        async def on_turn_resumed(turn_resumed, **kwargs):
            "Handle Flux TurnResumed event when user continues speaking"
            print("User resumed speaking - turn detection reset")
            # Optionally handle turn resumption logic here
    
        # Set up event handlers with kwargs
        on_transcript_kwargs = partial(on_transcript, transcripts=self.transcripts, assistant=self.assistant, websocket=self.ws, stream_sid=self.stream_sid)
        on_end_of_turn_kwargs = partial(on_end_of_turn, transcripts=self.transcripts, assistant=self.assistant)
        on_eager_end_of_turn_kwargs = partial(on_eager_end_of_turn, transcripts=self.transcripts, assistant=self.assistant)
        on_turn_resumed_kwargs = partial(on_turn_resumed)
        
        # Register Flux event handlers
        self.dg_connection.on('Transcript', on_transcript_kwargs)
        self.dg_connection.on('EndOfTurn', on_end_of_turn_kwargs)
        self.dg_connection.on('EagerEndOfTurn', on_eager_end_of_turn_kwargs)
        self.dg_connection.on('TurnResumed', on_turn_resumed_kwargs)

        # Start Flux connection with smart turn detection parameters
        try:
            await self.dg_connection.start(self.options, 
                                         eot_threshold=self.eot_threshold,
                                         eager_eot_threshold=self.eager_eot_threshold,
                                         eot_timeout_ms=self.eot_timeout_ms)
        except Exception as e:
            msg = str(e).lower()
            if 'already started' in msg:
                print('Deepgram Flux connection already started; using existing connection')
                self.started = True
            else:
                raise
        else:
            self.started = True
        print('Deepgram Flux Transcriber Connected')

    async def send_audio(self, audio_data: bytes):
        """
        Send Twilio mulaw 8k audio directly to Deepgram Flux.
        - Twilio yields 160-byte mulaw frames (20ms at 8kHz). We buffer upstream to ~80ms.
        - Flux supports `encoding=mulaw` and `sample_rate=8000`, so no conversion is needed.
        """
        if not self.dg_connection or not self.started:
            return

        try:
            await self.dg_connection.send(audio_data)
        except Exception as e:
            print(f"Deepgram send_audio error: {e}")
    
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
           

