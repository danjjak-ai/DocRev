import requests
import fitz
import io

def verify_rag_engine():
    # 1. Create a dummy PDF with some specific text
    doc = fitz.open()
    page = doc.new_page()
    text = "The quick brown fox jumps over the lazy dog. This document discusses the importance of local RAG engines for PDF analysis."
    page.insert_text((50, 50), text)
    pdf_bytes = doc.write()
    doc.close()

    # 2. Upload the PDF
    print("Uploading dummy PDF for indexing...")
    files = {'file': ('test.pdf', pdf_bytes, 'application/pdf')}
    try:
        up_response = requests.post("http://localhost:5000/upload", files=files)
        if up_response.status_code == 200:
            print("Upload successful.")
        else:
            print(f"Upload returned status {up_response.status_code}.")
            print(f"Error Body: {up_response.text}")
    except Exception as e:
        print(f"Failed to upload: {e}")

    # 3. Test Retrieval
    query = "What does the document say about fox?"
    print(f"Testing RAG retrieval with query: '{query}'")
    try:
        ask_response = requests.post("http://localhost:5000/ask", json={"query": query})
        if ask_response.status_code == 200:
            results = ask_response.json()
            if results:
                print("Successfully retrieved context:")
                for i, res in enumerate(results):
                    print(f"Result {i+1}: {res['content']} (Page: {res['metadata'].get('page')})")
            else:
                print("No relevant context found. Indexing might have failed.")
        else:
            print(f"Retrieval failed: {ask_response.status_code}")
            print(ask_response.text)
    except Exception as e:
        print(f"Failed to retrieve: {e}")

if __name__ == "__main__":
    verify_rag_engine()
