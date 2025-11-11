from openai import AsyncOpenAI
from services.tts.tts_factory import TTSFactory

class LargeLanguageModel:
    def __init__(self, tts_provider: TTSFactory):
        self.client = AsyncOpenAI()
        self.tts_provider = tts_provider
        self.conversation = []

    def init_chat(self):
        with open('services/llm/instructions.txt', "r") as f:
            instructions = f.read()
        self.conversation.append({"role": "system", "content": instructions})

    async def run_chat(self, message):
        self.conversation.append({"role":"user", "content": message})

        response = await self.client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=self.conversation,
        )

        assistant_response = response.choices[0].message.content
        print(f"Assistant: {assistant_response}")
        self.conversation.append({"role": "assistant", "content": assistant_response})

        await self.tts_provider.get_audio_from_text(assistant_response)
    
