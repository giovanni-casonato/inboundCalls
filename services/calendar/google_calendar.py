import os
import datetime
from typing import Optional, List
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]

class GoogleCalendarService:
    def __init__(self, calendar_id: Optional[str] = None):
        self.calendar_id = calendar_id or os.getenv("GOOGLE_CALENDAR_ID")
        if not self.calendar_id:
            raise RuntimeError("Missing GOOGLE_CALENDAR_ID env var")

        creds_path = os.getenv("GOOGLE_CALENDAR_CREDENTIALS")
        if not creds_path or not os.path.exists(creds_path):
            raise RuntimeError("Missing GOOGLE_CALENDAR_CREDENTIALS env var or file not found")

        self.creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        self.service = build("calendar", "v3", credentials=self.creds)

    def list_upcoming_events(self, max_results: int = 10) -> List[dict]:
        now = datetime.datetime.utcnow().isoformat() + "Z"  # 'Z' indicates UTC time
        events_result = self.service.events().list(
            calendarId=self.calendar_id,
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        return events_result.get("items", [])

    def check_availability(self, start_iso: str, end_iso: str) -> bool:
        # Use freebusy query to check availability
        body = {
            "timeMin": start_iso,
            "timeMax": end_iso,
            "items": [{"id": self.calendar_id}],
        }
        fb = self.service.freebusy().query(body=body).execute()
        busy = fb.get("calendars", {}).get(self.calendar_id, {}).get("busy", [])
        return len(busy) == 0

    def create_appointment(
        self,
        summary: str,
        description: str,
        start_iso: str,
        end_iso: str,
        attendees: Optional[List[str]] = None,
        location: Optional[str] = None,
    ) -> dict:
        event = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_iso, "timeZone": "UTC"},
            "end": {"dateTime": end_iso, "timeZone": "UTC"},
        }
        if attendees:
            event["attendees"] = [{"email": a} for a in attendees]
        if location:
            event["location"] = location

        created = self.service.events().insert(calendarId=self.calendar_id, body=event).execute()
        return created
