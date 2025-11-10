import json
from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveTranscriptionEvents,
    LiveOptions,
)
from functools import partial
from fastapi import WebSocket
from services.llm.openai_async import LargeLanguageModel

TWILIO_SAMPLE_RATE = 8000
ENCODING = "mulaw"

class DeepgramTranscriber:
    """Real-time speech transcription using Deepgram API"""
    
    def __init__(self, llm_instance: LargeLanguageModel, websocket: WebSocket, stream_sid: str):
        self.llm = llm_instance
        self.config: DeepgramClientOptions = DeepgramClientOptions(
            options={"keepalive": "true"}
        )
        self.deepgram: DeepgramClient = DeepgramClient("", self.config)
        self.dg_connection = None 
        self.transcripts = []
        self.ws = ws
        self.stream_sid = stream_sid

        # deepgram websocket options
        self.options: LiveOptions = LiveOptions(
            model="nova-3",
            language="en-US",
            # Apply smart formatting to the output
            smart_format=True,
            # Raw audio format details
            encoding=ENCODING,
            channels=1,
            sample_rate=TWILIO_SAMPLE_RATE,
            # To get UtteranceEnd, the following must be set:
            interim_results=True,
            # Time in milliseconds of silence to wait for before finalizing speech
            utterance_end_ms=2000,
            punctuate=True
        )

    async def deepgram_connect(self):
        self.dg_connection = self.deepgram.listen.asynclive.v("1")

        async def on_message(self, result, **kwargs):
            "Receive text from deepgram_ws"

            transcripts = kwargs.get('transcripts')
            assistant: ChatCompletionAssistant = kwargs.get('assistant')
            ws: WebSocket = kwargs.get('websocket')
            stream_sid = kwargs.get('stream_sid')

            # Useful for Debugging
            # print(f"""
            # Alt Length: {len(result.channel.alternatives)}
            # sentence: '{result.channel.alternatives[0].transcript}'
            # speech_final: {result.speech_final}
            # is_final: {result.is_final}
            # transcript: {" ".join(transcripts)}
            # """)

            sentence = result.channel.alternatives[0].transcript

            if result.is_final:
                # collect final transcripts:
                if len(sentence) > 0:
                    transcripts.append(sentence)

                if len(transcripts) > 0 and re.search(r'[.!?]$', sentence):
                    user_message_final = " ".join(transcripts)
                    print(f'\nUser: {user_message_final}')

                    # clear audio from assistant on user response
                    await ws.send_text(json.dumps({'event': 'clear', 'streamSid': f"{stream_sid}"}))

                    await assistant.run_chat_completion(user_message_final)
                    transcripts.clear()

        async def on_utterance_end(self, utterance_end, **kwargs):
            transcripts = kwargs.get('transcripts')
            assistant: ChatCompletionAssistant = kwargs.get('assistant')
            if len(transcripts) > 0 and re.search(r'[.!?]$', transcripts):
                user_message_final = " ".join(transcripts)
                print(f'\nUser: {user_message_final}')

                await assistant.run_chat_completion(user_message_final)
                transcripts.clear()
    
        on_message_with_kwargs = partial(on_message, transcripts=self.transcripts, assistant=self.assistant, websocket=self.ws, stream_sid = self.stream_sid)
        on_utterance_end_kwargs = partial(on_utterance_end, transcripts=self.transcripts, assistant=self.assistant)
        
        self.dg_connection.on(LiveTranscriptionEvents.Transcript, on_message_with_kwargs)
        self.dg_connection.on(LiveTranscriptionEvents.UtteranceEnd, on_utterance_end_kwargs)

        await self.dg_connection.start(self.options)

        print('Deepgram Transcriber Connected')
    
    async def deepgram_close(self):
        "Close Deepgram Connection"
        await self.dg_connection.finish()
        print(f'\nDeepgram Transcriber Closed\n')
           