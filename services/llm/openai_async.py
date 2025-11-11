from openai import AsyncOpenAI
from services.tts.tts_factory import TTSFactory
from services.calendar.google_calendar import GoogleCalendarService
import os
import datetime

class LargeLanguageModel:
    def __init__(self, tts_provider: TTSFactory):
        self.client = AsyncOpenAI()
        self.tts_provider = tts_provider
        self.conversation = []
        # Calendar service (optional, enabled when env vars are present)
        self.calendar = None
        try:
            self.calendar = GoogleCalendarService()
        except Exception as e:
            print(f"Calendar not initialized: {e}")

    def init_chat(self):
        with open('services/llm/instructions.txt', "r") as f:
            instructions = f.read()
        # Add a note about scheduling capability if calendar is available
        if self.calendar:
            instructions += "\n\nScheduling capability: I can check availability and book appointments in Google Calendar."
        self.conversation.append({"role": "system", "content": instructions})

    async def run_chat(self, message):
        self.conversation.append({"role":"user", "content": message})

        # Simple intent detection for scheduling
        lower = message.lower()
        if self.calendar and any(k in lower for k in ["book", "schedule", "appointment", "meeting", "calendar"]):
            try:
                # naive example: schedule 30 min from now for 30 minutes
                start = datetime.datetime.utcnow() + datetime.timedelta(minutes=30)
                end = start + datetime.timedelta(minutes=30)
                created = self.calendar.create_appointment(
                    summary="Investor Call",
                    description=f"Scheduled via voice assistant: '{message}'",
                    start_iso=start.isoformat() + "Z",
                    end_iso=end.isoformat() + "Z",
                    attendees=[os.getenv("BOOKING_ATTENDEE_EMAIL")] if os.getenv("BOOKING_ATTENDEE_EMAIL") else None,
                )
                assistant_response = (
                    f"I've scheduled a meeting on your calendar for {start.isoformat()} UTC. "
                    f"Event ID: {created.get('id')}"
                )
                print(f"Assistant: {assistant_response}")
                self.conversation.append({"role": "assistant", "content": assistant_response})
                await self.tts_provider.get_audio_from_text(assistant_response)
                return
            except Exception as e:
                err_msg = f"I tried to schedule a meeting but hit an error: {str(e)}"
                print(f"Assistant: {err_msg}")
                self.conversation.append({"role": "assistant", "content": err_msg})
                await self.tts_provider.get_audio_from_text(err_msg)
                return

        # Otherwise, regular chat
        response = await self.client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=self.conversation,
        )

        assistant_response = response.choices[0].message.content
        print(f"Assistant: {assistant_response}")
        self.conversation.append({"role": "assistant", "content": assistant_response})

        await self.tts_provider.get_audio_from_text(assistant_response)
    
