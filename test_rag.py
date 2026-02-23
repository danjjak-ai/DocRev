import requests
import time

def test_rag():
    # 1. Upload a PDF (you need a small test pdf)
    # Since I don't have one handy, I'll assume the user will upload one.
    # 2. Test the /ask endpoint
    query = "What is the main topic of the document?"
    print(f"Testing RAG with query: {query}")
    try:
        response = requests.post("http://localhost:5000/ask", json={"query": query})
        if response.status_code == 200:
            print("Successfully retrieved context:")
            print(response.json())
        else:
            print(f"Error: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"Failed to connect: {e}")

if __name__ == "__main__":
    test_rag()
