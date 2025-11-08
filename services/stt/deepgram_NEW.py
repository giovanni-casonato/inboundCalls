import os
import asyncio
import json
from fastapi import WebSocket
from typing import Optional
from deepgram import (
    DeepgramClient,
    LiveTranscriptionEvents,
    LiveOptions
)
from services.llm.openai_async import LargeLanguageModel


class DeepgramTranscriber:
    """Real-time speech transcription using Deepgram API"""
    
    def __init__(self, llm_instance: LargeLanguageModel, websocket: WebSocket, stream_sid: str):
        self.llm = llm_instance
        self.websocket = websocket
        self.stream_sid = stream_sid
        self.dg_connection = None
        self.deepgram_client = None
        self.is_connected = False
        
        # deepgram websocket options
        self.options: LiveOptions = LiveOptions(
            model="nova-3",
            language="en-US",
            # Apply smart formatting to the output
            smart_format=True,
            # Raw audio format details
            encoding="mulaw",
            channels=1,
            sample_rate=8000,
            # To get UtteranceEnd, the following must be set:
            interim_results=True,
            punctuate=True
        )

    async def deepgram_connect(self):
        """Initialize connection to Deepgram"""
        try:
            # Initialize Deepgram client using API key from environment
            api_key = os.getenv("DEEPGRAM_API_KEY")
            if not api_key:
                raise ValueError("Deepgram API key not found. Set DEEPGRAM_API_KEY env var.")

            self.deepgram_client = DeepgramClient(api_key)
            
            # Create live transcription connection
            self.dg_connection = self.deepgram_client.listen.asyncwebsocket.v("1")
            
            # Set up event handlers
            self.dg_connection.on(LiveTranscriptionEvents.Open, self._on_open)
            self.dg_connection.on(LiveTranscriptionEvents.Transcript, self._on_message)
            self.dg_connection.on(LiveTranscriptionEvents.Error, self._on_error)
            self.dg_connection.on(LiveTranscriptionEvents.Close, self._on_close)
            self.dg_connection.on(LiveTranscriptionEvents.Warning, self._on_warning)
            
            # Start the connection
            if await self.dg_connection.start(self.options, utterance_end_ms="2000"):
                print(f"🎤 Connected to Deepgram for stream {self.stream_sid}")
                self.is_connected = True
                
                # Start keepalive task
                asyncio.create_task(self._send_keepalive())
            else:
                print("❌ Failed to start Deepgram connection")
                
        except Exception as e:
            print(f"❌ Error connecting to Deepgram: {e}")
            
    async def _on_open(self, *args, **kwargs):
        """Called when Deepgram connection opens"""
        print("✅ Deepgram WebSocket opened")
        
    async def _on_message(self, *args, **kwargs):
        """Handle incoming transcription results"""
        try:
            result = kwargs.get("result")
            if not result:
                return
                
            # Extract transcript
            if result.channel and result.channel.alternatives:
                alternative = result.channel.alternatives[0]
                transcript = alternative.transcript
                
                if transcript:
                    confidence = alternative.confidence if hasattr(alternative, 'confidence') else 0.0
                    is_final = result.is_final
                    
                    print(f"📝 Transcript ({'FINAL' if is_final else 'interim'}): {transcript}")
                    
                    # Process the transcript
                    await self._handle_transcript(transcript, is_final, confidence)
                    
        except Exception as e:
            print(f"❌ Error processing Deepgram message: {e}")
            
    async def _on_error(self, *args, **kwargs):
        """Handle Deepgram errors"""
        error = kwargs.get("error")
        print(f"❌ Deepgram error: {error}")
        
    async def _on_close(self, *args, **kwargs):
        """Handle Deepgram connection close"""
        print(f"🔌 Deepgram connection closed for stream {self.stream_sid}")
        self.is_connected = False
        
    async def _on_warning(self, *args, **kwargs):
        """Handle Deepgram warnings"""
        warning = kwargs.get("warning")
        print(f"⚠️ Deepgram warning: {warning}")
        
    async def _handle_transcript(self, transcript: str, is_final: bool, confidence: float):
        """Process transcript and send to LLM if final"""
        if is_final and transcript.strip():
            print(f"🤖 Sending to LLM: '{transcript}' (confidence: {confidence:.2f})")
            
            # Send to your LLM for processing
            try:
                await self.llm.run_chat(transcript)
            except Exception as e:
                print(f"❌ Error sending to LLM: {e}")
        elif not is_final:
            # You can handle interim results here if needed
            # For example, show typing indicators, real-time feedback, etc.
            pass
            
    async def _send_keepalive(self):
        """Send periodic keepalive messages to maintain connection"""
        while self.is_connected:
            try:
                await asyncio.sleep(5)  # Send every 5 seconds
                if self.dg_connection and self.is_connected:
                    keepalive_msg = {"type": "KeepAlive"}
                    await self.dg_connection.send(json.dumps(keepalive_msg))
            except Exception as e:
                print(f"❌ Keepalive error: {e}")
                break
                
    async def send_audio(self, audio_data: bytes):
        """Send audio data to Deepgram (alternative to using dg_connection.send directly)"""
        if self.dg_connection and self.is_connected:
            try:
                await self.dg_connection.send(audio_data)
            except Exception as e:
                print(f"❌ Error sending audio to Deepgram: {e}")
                
    async def deepgram_close(self):
        """Close Deepgram connection"""
        self.is_connected = False
        if self.dg_connection:
            try:
                await self.dg_connection.finish()
                print(f"🔌 Deepgram connection closed for stream {self.stream_sid}")
            except Exception as e:
                print(f"❌ Error closing Deepgram connection: {e}")
