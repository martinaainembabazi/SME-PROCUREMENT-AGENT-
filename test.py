"""
Simple test script to confirm your Gemini API key works.
Run: pip install google-genai python-dotenv
Then: python test.py
"""

import os
from dotenv import load_dotenv
from google import genai

# Load GEMINI_API_KEY and GEMINI_MODEL from your .env file
load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
model_name = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
if not api_key or api_key == "your_key_here":
    raise SystemExit("GEMINI_API_KEY is missing or still the placeholder — check your .env file.")

client = genai.Client(api_key=api_key)

test_prompt = (
    "You are a procurement-preparation assistant for a small supermarket. "
    "In two sentences, explain how you would compare two supplier quotations "
    "for the same item before drafting a purchase requisition."
)

response = client.models.generate_content(
    model=model_name,
    contents=test_prompt,
)

print("--- Model used ---")
print(model_name)
print("\n--- Prompt sent ---")
print(test_prompt)
print("\n--- Response received ---")
print(response.text)
print("\nIf you see a sensible response above, your key and model access are working.")