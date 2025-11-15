import os
import json
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class GoogleCalendarService:
    """Service for managing Google Calendar appointments"""
    
    def __init__(self):
        """Initialize Google Calendar service with service account credentials"""
        self.service = None
        self._initialize_service()
    
    def _initialize_service(self):
        """Initialize the Google Calendar API service"""
        try:
            # Load service account credentials from environment variable or file
            credentials_json = os.getenv('GOOGLE_CALENDAR_CREDENTIALS_JSON')
            print(f"Credentials JSON: {credentials_json}")
            if credentials_json:
                # Parse JSON from environment variable
                credentials_info = json.loads(credentials_json)
                credentials = service_account.Credentials.from_service_account_info(
                    credentials_info,
                    scopes=['https://www.googleapis.com/auth/calendar']
                )
            else:
                # Load from file (for local development)
                credentials_file = os.getenv('GOOGLE_CALENDAR_CREDENTIALS_FILE', 'credentials.json')
                credentials = service_account.Credentials.from_service_account_file(
                    credentials_file,
                    scopes=['https://www.googleapis.com/auth/calendar']
                )
            
            self.service = build('calendar', 'v3', credentials=credentials)
            self.calendar_id = os.getenv('GOOGLE_CALENDAR_ID', 'primary')
            print("Google Calendar service initialized successfully")
            
        except Exception as e:
            print(f"Error initializing Google Calendar service: {e}")
            self.service = None
    
    async def get_available_slots(self, date: str, duration_minutes: int = 30) -> list:
        """
        Get available time slots for a specific date
        
        Args:
            date: Date in YYYY-MM-DD format
            duration_minutes: Duration of the appointment in minutes
            
        Returns:
            List of available time slots
        """
        if not self.service:
            return []
        
        try:
            # Parse the date
            target_date = datetime.strptime(date, "%Y-%m-%d")
            
            # Define business hours (9 AM to 5 PM)
            start_time = target_date.replace(hour=9, minute=0, second=0, microsecond=0)
            end_time = target_date.replace(hour=17, minute=0, second=0, microsecond=0)
            
            # Get existing events for the day
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=start_time.isoformat() + 'Z',
                timeMax=end_time.isoformat() + 'Z',
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            # Generate all possible slots
            available_slots = []
            current_time = start_time
            
            while current_time + timedelta(minutes=duration_minutes) <= end_time:
                slot_end = current_time + timedelta(minutes=duration_minutes)
                
                # Check if slot conflicts with existing events
                is_available = True
                for event in events:
                    event_start = datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')).replace('Z', '+00:00'))
                    event_end = datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')).replace('Z', '+00:00'))
                    
                    # Remove timezone info for comparison
                    event_start = event_start.replace(tzinfo=None)
                    event_end = event_end.replace(tzinfo=None)
                    
                    # Check for overlap
                    if (current_time < event_end and slot_end > event_start):
                        is_available = False
                        break
                
                if is_available:
                    available_slots.append({
                        'start': current_time.strftime("%I:%M %p"),
                        'end': slot_end.strftime("%I:%M %p"),
                        'datetime': current_time.isoformat()
                    })
                
                # Move to next slot (30 minute intervals)
                current_time += timedelta(minutes=30)
            
            return available_slots
            
        except Exception as e:
            print(f"Error getting available slots: {e}")
            return []
    
    async def create_appointment(
        self, 
        date: str, 
        time: str, 
        duration_minutes: int,
        customer_name: str,
        customer_email: str = None,
        customer_phone: str = None,
        notes: str = None
    ) -> dict:
        """
        Create a calendar appointment
        
        Args:
            date: Date in YYYY-MM-DD format
            time: Time in HH:MM format (24-hour)
            duration_minutes: Duration of the appointment
            customer_name: Name of the customer
            customer_email: Customer's email (optional)
            customer_phone: Customer's phone (optional)
            notes: Additional notes (optional)
            
        Returns:
            Dictionary with appointment details or error
        """
        if not self.service:
            return {"success": False, "error": "Calendar service not initialized"}
        
        try:
            # Parse date and time
            start_datetime = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
            end_datetime = start_datetime + timedelta(minutes=duration_minutes)
            
            # Create event description
            description_parts = [f"Customer: {customer_name}"]
            if customer_email:
                description_parts.append(f"Email: {customer_email}")
            if customer_phone:
                description_parts.append(f"Phone: {customer_phone}")
            if notes:
                description_parts.append(f"\nNotes: {notes}")
            
            description = "\n".join(description_parts)
            
            # Create the event
            event = {
                'summary': f"Appointment - {customer_name}",
                'description': description,
                'start': {
                    'dateTime': start_datetime.isoformat(),
                    'timeZone': 'America/New_York',  # Update to your timezone
                },
                'end': {
                    'dateTime': end_datetime.isoformat(),
                    'timeZone': 'America/New_York',  # Update to your timezone
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'email', 'minutes': 24 * 60},  # 1 day before
                        {'method': 'popup', 'minutes': 30},  # 30 minutes before
                    ],
                },
            }
            
            # Add attendee if email provided
            if customer_email:
                event['attendees'] = [{'email': customer_email}]
            
            # Insert the event
            created_event = self.service.events().insert(
                calendarId=self.calendar_id, 
                body=event,
                sendUpdates='all' if customer_email else 'none'
            ).execute()
            
            return {
                "success": True,
                "event_id": created_event['id'],
                "event_link": created_event.get('htmlLink'),
                "start_time": start_datetime.strftime("%B %d, %Y at %I:%M %p"),
                "end_time": end_datetime.strftime("%I:%M %p")
            }
            
        except HttpError as e:
            print(f"Google Calendar API error: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            print(f"Error creating appointment: {e}")
            return {"success": False, "error": str(e)}

