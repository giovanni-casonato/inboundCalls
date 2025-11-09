import os
import json
from functools import partial
from fastapi import WebSocket
from services.llm.openai_async import LargeLanguageModel
import re

# Deepgram SDK imports for Flux v2
-from deepgram import DeepgramClient, LiveOptions
+from deepgram import DeepgramClient, LiveOptions
+try:
+    from deepgram.core.events import EventType
+except Exception:
+    EventType = None

# Audio format constants for telephony compatibility with Flux
# Flux supports mulaw at 8000Hz for telephony applications
TWILIO_SAMPLE_RATE = 8000  # Standard telephony sample rate
ENCODING = "mulaw"  # Telephony encoding format, compatible with Flux

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

        # Flux-specific parameters from environment or defaults
        self.eot_threshold = float(os.getenv("DEEPGRAM_EOT_THRESHOLD", "0.7"))
        self.eager_eot_threshold = float(os.getenv("DEEPGRAM_EAGER_EOT_THRESHOLD", "0.6"))
        self.eot_timeout_ms = int(os.getenv("DEEPGRAM_EOT_TIMEOUT_MS", "2000"))

        # Build options for Flux v2 LiveOptions
        self.options: LiveOptions = LiveOptions(
            model="flux-general-en",
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
        
        # Create Flux v2 connection
        try:
            if hasattr(self.deepgram.listen, 'v2'):
                self.dg_connection = self.deepgram.listen.v2.connect(
                    model="flux-general-en",
                    encoding=ENCODING,
                    sample_rate=TWILIO_SAMPLE_RATE,
                    channels=1,
                    smart_format=True,
                    interim_results=True,
                    eot_threshold=self.eot_threshold,
                    eager_eot_threshold=self.eager_eot_threshold,
                    eot_timeout_ms=self.eot_timeout_ms,
                )
            else:
                raise AttributeError("ListenClient has no attribute 'v2'")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Deepgram Flux connection: {e}")

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
        try:
            self.dg_connection.on('Transcript', on_transcript_kwargs)
            self.dg_connection.on('EndOfTurn', on_end_of_turn_kwargs)
            self.dg_connection.on('EagerEndOfTurn', on_eager_end_of_turn_kwargs)
            self.dg_connection.on('TurnResumed', on_turn_resumed_kwargs)
        except Exception:
            pass
        # Generic event stream fallback if EventType is available
        if EventType is not None:
            try:
                async def on_message(event):
                    etype = getattr(event, 'type', None) or getattr(event, 'event', None)
                    payload = getattr(event, 'payload', None) or event
                    if etype == 'Transcript':
                        await on_transcript_kwargs(payload)
                    elif etype == 'EndOfTurn':
                        await on_end_of_turn_kwargs(payload)
                    elif etype == 'EagerEndOfTurn':
                        await on_eager_end_of_turn_kwargs(payload)
                    elif etype == 'TurnResumed':
                        await on_turn_resumed_kwargs(payload)
                self.dg_connection.on(EventType.MESSAGE, on_message)
            except Exception:
                pass

        # Start Flux connection with smart turn detection parameters
        try:
            # v5 typically uses start_listening; attempt that first
            start_listening = getattr(self.dg_connection, 'start_listening', None)
            if callable(start_listening):
                start_listening()
            else:
                # Fall back to start with parameters if supported
                start_fn = getattr(self.dg_connection, 'start', None)
                if start_fn is not None:
                    res = start_fn(self.options)
                    if hasattr(res, '__await__'):
                        await res
                else:
                    # As last resort, try without params
                    res2 = self.dg_connection.start(self.options)
                    if hasattr(res2, '__await__'):
                        await res2
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
           


    async def send_audio(self, audio_bytes: bytes):
        """Send audio buffer to Deepgram connection, supporting async/sync send methods."""
        if not (self.dg_connection and self.started):
            return
        try:
            send_fn = getattr(self.dg_connection, 'send', None)
            if send_fn is None:
                return
            res = send_fn(audio_bytes)
            if hasattr(res, '__await__'):
                await res
        except Exception as e:
            # Log and continue; audio drops rather than crash
            print(f"Deepgram send_audio error: {e}")
           

