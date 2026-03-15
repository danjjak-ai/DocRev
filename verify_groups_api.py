import requests
import json

BASE_URL = "http://localhost:5000"

def test_add_group(endpoint, name):
    print(f"Testing {endpoint} for group '{name}'...")
    try:
        res = requests.post(f"{BASE_URL}{endpoint}", json={"name": name})
        print(f"Status: {res.status_code}")
        print(f"Response: {res.text}")
        return res.status_code == 201
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    success = True
    success &= test_add_group("/api/ng-words/groups", "Test NG Group")
    success &= test_add_group("/api/prompts/groups", "Test Prompt Group")
    success &= test_add_group("/api/rag/groups", "Test RAG Group")
    
    if success:
        print("\nAll group creation tests passed on backend!")
    else:
        print("\nSome tests failed. Check backend logs.")
