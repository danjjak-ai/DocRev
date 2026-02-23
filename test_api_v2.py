import os
import google.generativeai as genai

# Load API Key from environment
api_key = os.environ.get("GEMINI_API_KEY", "")
if not api_key:
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY", "")

genai.configure(api_key=api_key)

print("--- START OF TEST ---")
try:
    print("Testing API Key connection...")
    models = genai.list_models()
    print("Models found successfully.")
    
    found_models = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
    print(f"Supported models: {found_models}")
    
    # Check if 'gemini-2.5-flash' is in the list
    if any('gemini-2.5-flash' in name for name in found_models):
        print("Model 'gemini-2.5-flash' is supported.")
        model_name = 'gemini-2.5-flash'
    else:
        print("Model 'gemini-2.5-flash' is NOT in the list.")
        # Try to find a fallback
        if any('gemini-1.5-flash' in name for name in found_models):
            model_name = 'gemini-1.5-flash'
        elif any('gemini-2.0-flash' in name for name in found_models):
            model_name = 'gemini-2.0-flash'
        else:
            model_name = found_models[0] if found_models else None
            
    if model_name:
        if 'models/' not in model_name:
            model_id = f"models/{model_name}"
        else:
            model_id = model_name
            
        print(f"Testing generation with: {model_id}")
        model = genai.GenerativeModel(model_id)
        response = model.generate_content("Ping")
        print(f"Response: {response.text}")
    else:
        print("No suitable model found.")

except Exception as e:
    print(f"ERROR: {e}")
print("--- END OF TEST ---")
