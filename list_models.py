import os
from dotenv import load_dotenv
from google import genai

# Load variables from .env
load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ GEMINI_API_KEY not found")
    print("Make sure your .env file contains:")
    print("GEMINI_API_KEY=your_key_here")
    exit()

print("✅ Gemini API key loaded")

client = genai.Client(api_key=api_key)

print("\nAvailable models:\n")

for model in client.models.list():
    print("NAME:", model.name)
    print("DISPLAY:", model.display_name)
    print("METHODS:", model.supported_actions)
    print("-" * 60)