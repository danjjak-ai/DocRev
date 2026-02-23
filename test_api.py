import os
import google.generativeai as genai
from dotenv import load_dotenv

# Load API Key from .env
load_dotenv()

api_key = os.environ.get("GEMINI_API_KEY", "")
genai.configure(api_key=api_key)

try:
    print("Listing models...")
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name}")
    
    model_name = 'gemini-2.5-flash'
    print(f"\nTesting model: {model_name}")
    model = genai.GenerativeModel(model_name)
    response = model.generate_content("Hello, are you working?")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"\nError: {e}")
