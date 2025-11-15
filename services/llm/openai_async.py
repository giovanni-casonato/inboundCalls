import json
from datetime import datetime
from openai import AsyncOpenAI
from services.tts.tts_factory import TTSFactory
from services.calendar.google_calendar import GoogleCalendarService

class LargeLanguageModel:
    def __init__(self, tts_provider: TTSFactory):
        self.client = AsyncOpenAI()
        self.tts_provider = tts_provider
        self.conversation = []
        self.calendar_service = GoogleCalendarService()
        self.tools = self._define_tools()

    def _define_tools(self):
        """Define available function tools for the LLM"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "check_availability",
                    "description": "Check available appointment slots for a specific date. Returns list of available time slots.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date": {
                                "type": "string",
                                "description": "The date to check availability for in YYYY-MM-DD format"
                            },
                            "duration_minutes": {
                                "type": "integer",
                                "description": "Duration of the appointment in minutes (default: 30)",
                                "default": 30
                            }
                        },
                        "required": ["date"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "schedule_appointment",
                    "description": "Schedule an appointment in the calendar",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date": {
                                "type": "string",
                                "description": "The date in YYYY-MM-DD format"
                            },
                            "time": {
                                "type": "string",
                                "description": "The time in HH:MM format (24-hour)"
                            },
                            "duration_minutes": {
                                "type": "integer",
                                "description": "Duration in minutes (default: 30)",
                                "default": 30
                            },
                            "customer_name": {
                                "type": "string",
                                "description": "Customer's full name"
                            },
                            "customer_email": {
                                "type": "string",
                                "description": "Customer's email address (optional)"
                            },
                            "customer_phone": {
                                "type": "string",
                                "description": "Customer's phone number (optional)"
                            },
                            "notes": {
                                "type": "string",
                                "description": "Additional notes about the appointment (optional)"
                            }
                        },
                        "required": ["date", "time", "customer_name"]
                    }
                }
            }
        ]
    
    def init_chat(self):
        with open('services/llm/instructions.txt', "r") as f:
            instructions = f.read()
        
        # Get current date for context
        today = datetime.now().strftime("%B %d, %Y")
        
        # Add calendar capabilities to instructions
        calendar_instructions = f"""

IMPORTANT: Today's date is {today}. Use this when interpreting relative dates like "tomorrow", "next week", etc.

You have access to calendar management tools:
1. check_availability - Check available time slots for a specific date
2. schedule_appointment - Schedule an appointment

When a customer wants to schedule an appointment:
1. Ask for their preferred date
2. Use check_availability to show available slots
3. Once they choose a time, collect their name, email (optional), and phone (optional)
4. Use schedule_appointment to book it
5. Confirm the appointment details clearly

Always be helpful and guide the customer through the scheduling process naturally.
"""
        
        self.conversation.append({"role": "system", "content": instructions + calendar_instructions})

    async def run_chat(self, message):
        self.conversation.append({"role": "user", "content": message})

        # Make initial API call with tools
        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=self.conversation,
            tools=self.tools,
            tool_choice="auto"
        )

        response_message = response.choices[0].message
        
        # Handle tool calls
        if response_message.tool_calls:
            # Add assistant's response to conversation
            self.conversation.append(response_message)
            
            # Process each tool call
            for tool_call in response_message.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                
                print(f"Calling function: {function_name} with args: {function_args}")
                
                # Execute the function
                if function_name == "check_availability":
                    function_response = await self.calendar_service.get_available_slots(
                        date=function_args.get("date"),
                        duration_minutes=function_args.get("duration_minutes", 30)
                    )
                elif function_name == "schedule_appointment":
                    function_response = await self.calendar_service.create_appointment(
                        date=function_args.get("date"),
                        time=function_args.get("time"),
                        duration_minutes=function_args.get("duration_minutes", 30),
                        customer_name=function_args.get("customer_name"),
                        customer_email=function_args.get("customer_email"),
                        customer_phone=function_args.get("customer_phone"),
                        notes=function_args.get("notes")
                    )
                else:
                    function_response = {"error": "Unknown function"}
                
                # Add function response to conversation
                self.conversation.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps(function_response)
                })
            
            # Get final response from model with function results
            final_response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=self.conversation,
            )
            
            assistant_response = final_response.choices[0].message.content
        else:
            # No tool calls, just regular response
            assistant_response = response_message.content
            self.conversation.append({"role": "assistant", "content": assistant_response})
        
        print(f"Assistant: {assistant_response}")
        
        # Send response to caller via TTS
        await self.tts_provider.get_audio_from_text(assistant_response)
    
