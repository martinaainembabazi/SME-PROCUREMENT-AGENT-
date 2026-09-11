import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

class ModelClient:
    def __init__(self):
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.model = os.getenv("MODEL_NAME", "gemini-2.5-flash")

    def generate(self, prompt: str, system_instruction: str = "") -> str:
        try:
            config = None
            if system_instruction:
                config = {"system_instruction": system_instruction}

            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config
            )
            return response.text
        except Exception as e:
            return f"[MODEL ERROR] {type(e).__name__}: {e}"