import os
import json
import threading
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify
from flask_cors import CORS
import fitz  # PyMuPDF
import google.generativeai as genai
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
import unicodedata
import re
import uuid
from langchain_community.retrievers import BM25Retriever

app = Flask(__name__)
# Enable CORS for all domains
CORS(app)

# Configure Gemini API
# Load environment variables from .env file
load_dotenv()

# Load API Key with standard fallback for error handling
api_key = os.environ.get("GEMINI_API_KEY", "").strip('"').strip("'")

if not api_key:
    print("WARNING: GEMINI_API_KEY is not set. AI features will fail. Please check your .env file.")
else:
    print("INFO: GEMINI_API_KEY loaded from environment.")

genai.configure(api_key=api_key)
# gemini-2.5-flash is supported according to local tests
model = genai.GenerativeModel('gemini-2.5-flash')

# Global variable for NG words
NG_WORDS = []
# Global variable for Prompts
PROMPTS = {}

# --- Async Job Infrastructure ---
analysis_jobs = {}
analysis_lock = threading.Lock()

def update_job_status(job_id, status, results=None, error=None):
    with analysis_lock:
        if job_id not in analysis_jobs:
            analysis_jobs[job_id] = {"id": job_id, "status": "pending", "results": [], "error": None}
        analysis_jobs[job_id]["status"] = status
        if results is not None:
            analysis_jobs[job_id]["results"] = results
        if error:
            analysis_jobs[job_id]["error"] = error

@app.route('/api/analysis-status/<job_id>', methods=['GET'])
def get_analysis_status(job_id):
    with analysis_lock:
        job = analysis_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)

def perform_analysis_logic(doc, mode, lang):
    """Core analysis logic separated to be runnable in background."""
    lang_prompts = PROMPTS.get(lang, PROMPTS.get('ko', {}))
    results = []
    
    # Extract text for RAG and LLM
    all_text = ""
    pages_text_list = []
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        text = page.get_text()
        all_text += f"--- Page {page_num + 1} ---\n{text}\n\n"
        pages_text_list.append((page_num + 1, text))

    # Trigger indexing in background (as it was)
    doc_id = str(uuid.uuid4())
    threading.Thread(target=index_pdf_text, args=(doc_id, pages_text_list), daemon=True).start()

    # --- Level 1: Keyword Analysis ---
    if mode in ['level1', 'both']:
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            ng_meta = lang_prompts.get('ng_violation', PROMPTS.get('ko', {}).get('ng_violation', {}))
            for ng_item in NG_WORDS:
                word = ng_item.get("word")
                rule = ng_item.get("rule", "")
                suggestion = ng_item.get("suggestion", "")
                if not word: continue
                
                text_instances = page.search_for(word)
                for inst in text_instances:
                    results.append({
                        "page": page_num + 1,
                        "quote": word,
                        "category": ng_meta.get("category", "금지어"),
                        "type": "critical",
                        "clause": rule,
                        "reason": ng_meta.get("reason", "금지어가 발견되었습니다.").format(word=word),
                        "suggestion": suggestion,
                        "rect": [inst.x0, inst.y0, inst.x1, inst.y1],
                        "rects": [[inst.x0, inst.y0, inst.x1, inst.y1]],
                        "ai_review_label": lang_prompts.get("ai_review_label", "AI 리뷰"),
                        "suggestion_label": lang_prompts.get("suggestion_label", "제안")
                    })

    # --- Level 2: AI Review (Gemini + RAG) ---
    if mode in ['level2', 'both'] and api_key:
        try:
            # 1. 문서에서 관련 컨텍스트 검색 (Query Expansion 적용)
            base_query = "판매정보제공 가이드라인 허위 과장 비방 금지"
            expanded_query = expand_query_with_gemini(base_query, lang=lang)
            relevant_docs = retrieve_relevant_context(expanded_query, k=7)
            retrieved_context = "\n\n".join([f"[Context]: {d.page_content}" for d in relevant_docs])

            # 2. Gemini에게 문서 분석 요청
            review_prompt_template = lang_prompts.get('review', "")
            if not review_prompt_template:
                review_prompt_template = PROMPTS.get('en', {}).get('review', "")
            
            if review_prompt_template:
                prompt = f"""
                {review_prompt_template}

                [Retrieved Guideline Context]:
                {retrieved_context}

                Whole Document Text:
                {all_text}
                """
                
                response = model.generate_content(prompt)
                ai_response_text = response.text.strip()
                
                # Strip markdown blocks if present
                if ai_response_text.startswith("```json"):
                    ai_response_text = ai_response_text.split("```json")[1].split("```")[0].strip()
                elif ai_response_text.startswith("```"):
                     ai_response_text = ai_response_text.split("```")[1].split("```")[0].strip()

                parsed_results = json.loads(ai_response_text)
                if isinstance(parsed_results, list):
                    for ann in parsed_results:
                        # Robust page parsing
                        try:
                            page_val = ann.get("page", 1)
                            if isinstance(page_val, str):
                                import re
                                match = re.search(r'\d+', page_val)
                                page_val = int(match.group()) if match else 1
                            page_num_actual = int(page_val)
                            ann["page"] = page_num_actual
                        except:
                            ann["page"] = 1

                        page_idx = ann["page"] - 1
                        quote = ann.get("quote", "").strip()
                        
                        if 0 <= page_idx < len(doc) and quote:
                            page = doc.load_page(page_idx)
                            rects = robust_search_for_quote(page, quote)
                            if rects:
                                ann["rects"] = [[r.x0, r.y0, r.x1, r.y1] for r in rects]
                                ann["rect"] = ann["rects"][0]
                        
                        # Fallbacks...
                        if quote and "rects" not in ann:
                            for p_idx in range(len(doc)):
                                pg = doc.load_page(p_idx)
                                rects = robust_search_for_quote(pg, quote)
                                if rects:
                                    ann["rects"] = [[r.x0, r.y0, r.x1, r.y1] for r in rects]
                                    ann["rect"] = ann["rects"][0]
                                    ann["page"] = p_idx + 1
                                    break
                                    
                        ann["ai_review_label"] = lang_prompts.get("ai_review_label", "AI 리뷰")
                        ann["suggestion_label"] = lang_prompts.get("suggestion_label", "제안")
                        if not ann.get("category"):
                            ann["category"] = ann["ai_review_label"]
                        results.append(ann)
            else:
                print(f"No review prompt template for lang {lang}")
        except Exception as e:
            print(f"AI Review Error: {e}")
            import traceback
            traceback.print_exc()

    return results

def background_analysis_task(job_id, pdf_bytes, mode, lang):
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        results = perform_analysis_logic(doc, mode, lang)
        update_job_status(job_id, "completed", results=results)
    except Exception as e:
        import traceback
        traceback.print_exc()
        update_job_status(job_id, "failed", error=str(e))

def load_ng_words():
    """
    Loads NG words from config/ng_words_dataset.json.
    Creates the file with default values if it doesn't exist.
    """
    global NG_WORDS
    config_dir = "config"
    config_file = os.path.join(config_dir, "ng_words_dataset.json")
    
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)
        print(f"Created directory: {config_dir}")
        
    if not os.path.exists(config_file):
        default_ng_words = [
            {"word": "最高", "rule": "ガイド라인 第1의3-(2)-① (最上級表現の禁止)", "suggestion": "「最高」などの主観的な最上級表現を避け、客観的なデータに基づいた表現に改めてください。"},
            {"word": "No.1", "rule": "ガイド라인 第1의3-(2)-① (最上級表現の禁止)", "suggestion": "根拠なし에 順位를 強調하는 表現은 控え、公平한 比較데이터를 示してください。"},
            {"word": "副作用なし", "rule": "ガイド라인 第1의3-(1)-② (安全性の過信・副作用の否定)", "suggestion": "副作用이 없는 것과 같은 表現은 禁止되어 있습니다. 適切한 副作用情報와 安全性데이터를 併記해 주세요."}
        ]
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(default_ng_words, f, ensure_ascii=False, indent=4)
            print(f"Created default NG words file: {config_file}")
        except Exception as e:
            print(f"Error creating default NG words file: {e}")
    
    try:
        if os.path.exists(config_file):
            with open(config_file, "r", encoding="utf-8") as f:
                NG_WORDS = json.load(f)
            print(f"Loaded {len(NG_WORDS)} NG words.")
        else:
            NG_WORDS = []
    except Exception as e:
        print(f"Error loading NG words: {e}")
        NG_WORDS = [] # Fallback

# Initial load
load_ng_words()

def load_prompts():
    """
    Loads prompts from config/prompts.json.
    """
    global PROMPTS
    config_file = os.path.join("config", "prompts.json")
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                PROMPTS = json.load(f)
            print(f"Loaded prompts for languages: {list(PROMPTS.keys())}")
        except Exception as e:
            print(f"Error loading prompts: {e}")
            PROMPTS = {}
    else:
        print("WARNING: config/prompts.json not found.")
        PROMPTS = {}

def save_prompts():
    """
    Saves the global PROMPTS dictionary back to config/prompts.json.
    """
    config_file = os.path.join("config", "prompts.json")
    try:
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(PROMPTS, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"Error saving prompts: {e}")
        return False

load_prompts()

def save_ng_words():
    """
    Saves the global NG_WORDS list back to config/ng_words_dataset.json.
    """
    config_file = os.path.join("config", "ng_words_dataset.json")
    try:
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(NG_WORDS, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"Error saving NG words: {e}")
        return False

@app.route('/api/ng-words', methods=['GET'])
def get_ng_words():
    return jsonify(NG_WORDS)

@app.route('/api/ng-words', methods=['POST'])
def add_ng_word():
    data = request.get_json()
    word = data.get("word")
    rule = data.get("rule", "")
    suggestion = data.get("suggestion", "")
    
    if not word:
        return jsonify({"error": "No word provided"}), 400
        
    # Check if word already exists in the list of objects
    if any(item.get("word") == word for item in NG_WORDS):
        return jsonify({"error": "Word already exists"}), 400
        
    NG_WORDS.append({
        "word": word,
        "rule": rule,
        "suggestion": suggestion
    })
    
    if save_ng_words():
        return jsonify({"message": "Word added successfully", "words": NG_WORDS}), 201
    return jsonify({"error": "Failed to save changes"}), 500

@app.route('/api/ng-words', methods=['PUT'])
def update_ng_word():
    data = request.get_json()
    old_word = data.get("old_word")
    new_word = data.get("new_word")
    new_rule = data.get("rule", "")
    new_suggestion = data.get("suggestion", "")
    
    if not old_word or not new_word:
        return jsonify({"error": "Both old_word and new_word are required"}), 400
        
    # Find the index of the object with old_word
    target_idx = -1
    for i, item in enumerate(NG_WORDS):
        if item.get("word") == old_word:
            target_idx = i
            break
            
    if target_idx == -1:
        return jsonify({"error": "Old word not found"}), 404
        
    # Check if new_word already exists (if it's changing)
    if new_word != old_word and any(item.get("word") == new_word for item in NG_WORDS):
        return jsonify({"error": "New word already exists"}), 400
    
    NG_WORDS[target_idx] = {
        "word": new_word,
        "rule": new_rule,
        "suggestion": new_suggestion
    }
    
    if save_ng_words():
        return jsonify({"message": "Word updated successfully", "words": NG_WORDS}), 200
    return jsonify({"error": "Failed to save changes"}), 500

@app.route('/api/ng-words', methods=['DELETE'])
def delete_ng_word():
    data = request.get_json()
    word = data.get("word")
    if not word:
        return jsonify({"error": "No word provided"}), 400
        
    global NG_WORDS
    initial_len = len(NG_WORDS)
    NG_WORDS = [item for item in NG_WORDS if item.get("word") != word]
    
    if len(NG_WORDS) == initial_len:
        return jsonify({"error": "Word not found"}), 404
        
    if save_ng_words():
        return jsonify({"message": "Word deleted successfully", "words": NG_WORDS}), 200
    return jsonify({"error": "Failed to save changes"}), 500

@app.route('/api/prompts', methods=['GET'])
def get_prompts():
    return jsonify(PROMPTS)

@app.route('/api/prompts', methods=['POST'])
def update_prompts():
    global PROMPTS
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    PROMPTS = data
    if save_prompts():
        return jsonify({"message": "Prompts updated successfully"}), 200
    return jsonify({"error": "Failed to save prompts"}), 500

# Initialize RAG components
# Use pkshatech/GLuCoSE-base-ja for superior Japanese support
embeddings = HuggingFaceEmbeddings(model_name="pkshatech/GLuCoSE-base-ja")
# Use persistent ChromaDB
PERSIST_DIR = os.path.join(os.path.dirname(__file__), "config", "vector_store")
vector_store = None
bm25_retriever = None

# Reference Document Configuration and State
REF_DOCS_DIR = os.path.join(os.path.dirname(__file__), "config", "ReferenceDoc")
os.makedirs(REF_DOCS_DIR, exist_ok=True)
RAG_STATUS = {"is_running": False, "message": "", "files_processed": []}

def normalize_japanese_text(text):
    """Normalizes Japanese text to NFC and handles full-width/half-width conversions."""
    return unicodedata.normalize('NFKC', text)

def tokenize_japanese_simple(text):
    """Simple tokenizer for Japanese BM25 (splitting by whitespace and non-alphanumeric)."""
    # Using a simple regex to match words/characters for BM25
    return re.findall(r'[a-zA-Z0-9]+|[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', text)

def robust_search_for_quote(page, quote):
    """
    Finds text instances of a quote in a PyMuPDF page with robustness to whitespace/newline differences.
    Returns a list of fitz.Rect objects that match parts of the quote.
    """
    if not quote or not quote.strip():
        return []

    # 1. Normalize the quote: Remove all whitespace/newlines and handle character normalization
    # NFKC/NFC normalization is applied (especially needed for Japanese/Korean character forms)
    norm_quote = unicodedata.normalize('NFKC', quote)
    norm_quote = re.sub(r'\s+', '', norm_quote)

    if not norm_quote:
        return []

    # 2. Extract words with their bounding boxes and line/block metadata
    # page.get_text("words") returns: (x0, y0, x1, y1, "text", block_no, line_no, word_no)
    words = page.get_text("words")
    
    # 3. Build a mapping of characters from words back to their BBoxes and line identifiers
    char_map = [] # List of (normalized_char, rect, line_id)
    
    for word in words:
        x0, y0, x1, y1, text, block_no, line_no, word_no = word
        # Normalize each word
        norm_word = unicodedata.normalize('NFKC', text)
        
        char_count = len(norm_word)
        if char_count == 0: continue
        
        # Distribute word width approximately per character for visualization
        char_width = (x1 - x0) / char_count
        line_id = (block_no, line_no) # Composite key for line
        
        for i, char in enumerate(norm_word):
            char_rect = fitz.Rect(x0 + i * char_width, y0, x0 + (i + 1) * char_width, y1)
            char_map.append((char, char_rect, line_id))

    # 4. Search for normalized quote in concatenated text
    full_norm_text = "".join([c[0] for c in char_map])
    match_index = full_norm_text.find(norm_quote)
    
    if match_index == -1:
        return []

    # 5. Aggregate rects for matching character range, merging rects on the same line
    results = []
    current_rect = None
    last_line_id = None
    
    for i in range(match_index, match_index + len(norm_quote)):
        char, char_rect, line_id = char_map[i]
        
        if current_rect is None:
            current_rect = fitz.Rect(char_rect)
            last_line_id = line_id
        else:
            # If same line (same block_no and line_no), union the rects
            if line_id == last_line_id:
                current_rect = current_rect | char_rect
            else:
                # Line change: push finished rect and start new one
                results.append(current_rect)
                current_rect = fitz.Rect(char_rect)
                last_line_id = line_id
                
    if current_rect:
        results.append(current_rect)

    return results

@app.route('/api/reference-docs', methods=['GET'])
def list_reference_docs():
    files = []
    if os.path.exists(REF_DOCS_DIR):
        for f in os.listdir(REF_DOCS_DIR):
            if f.lower().endswith('.pdf'):
                files.append(f)
    return jsonify(files)

@app.route('/api/reference-docs/upload', methods=['POST'])
def upload_reference_doc():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({"error": "Only PDF files are allowed"}), 400
    
    filename = secure_filename(file.filename)
    file_path = os.path.join(REF_DOCS_DIR, filename)
    file.save(file_path)
    return jsonify({"message": f"Successfully uploaded {filename}", "filename": filename}), 200

@app.route('/api/reference-docs/<filename>', methods=['DELETE'])
def delete_reference_doc(filename):
    safe_filename = secure_filename(filename)
    file_path = os.path.join(REF_DOCS_DIR, safe_filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        return jsonify({"message": f"Successfully deleted {safe_filename}"}), 200
    return jsonify({"error": "File not found"}), 404

@app.route('/api/rag/status', methods=['GET'])
def get_rag_status():
    global RAG_STATUS
    return jsonify(RAG_STATUS)

def reconstruct_rag_task():
    global vector_store, bm25_retriever, RAG_STATUS
    try:
        documents = []
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
            separators=["\n\n", "\n", "。", "！", "？", " ", ""]
        )
        files_processed = []

        if os.path.exists(REF_DOCS_DIR):
            for filename in os.listdir(REF_DOCS_DIR):
                if filename.lower().endswith('.pdf'):
                    file_path = os.path.join(REF_DOCS_DIR, filename)
                    doc = fitz.open(file_path)
                    for page_num in range(len(doc)):
                        page = doc.load_page(page_num)
                        text = page.get_text()
                        chunks = text_splitter.split_text(text)
                        for chunk in chunks:
                            documents.append(Document(
                                page_content=chunk,
                                metadata={"page": page_num + 1, "doc_id": filename}
                            ))
                    files_processed.append(filename)
        
        if documents:
            vector_store = Chroma.from_documents(
                documents=documents, 
                embedding=embeddings,
                persist_directory=PERSIST_DIR
            )
            # Initialize BM25 for hybrid search
            bm25_retriever = BM25Retriever.from_documents(
                documents,
                preprocess_func=tokenize_japanese_simple
            )
            RAG_STATUS["message"] = f"RAG 재구성이 완료되었습니다. (총 {len(documents)}개 청크 생성)"
        else:
            vector_store = None
            bm25_retriever = None
            RAG_STATUS["message"] = "참조 문서가 없어 RAG 데이터베이스를 초기화했습니다."
            
        RAG_STATUS["files_processed"] = files_processed
    except Exception as e:
        RAG_STATUS["message"] = f"RAG 재구성 중 오류 발생: {str(e)}"
    finally:
        RAG_STATUS["is_running"] = False

@app.route('/api/rag/reconstruct', methods=['POST'])
def trigger_rag_reconstruction():
    global RAG_STATUS
    if RAG_STATUS["is_running"]:
        return jsonify({"error": "RAG reconstruction is already running"}), 409
    
    RAG_STATUS["is_running"] = True
    RAG_STATUS["message"] = "RAG 재구성을 시작했습니다..."
    RAG_STATUS["files_processed"] = []
    
    thread = threading.Thread(target=reconstruct_rag_task)
    thread.daemon = True
    thread.start()
    
    return jsonify({"message": "RAG reconstruction started"}), 202


EXPERT_REVIEW_GUIDELINE = """
1. 논리적 일관성: 문서 내의 주장들이 서로 상충되지 않는지 확인.
2. 근거의 명확성: 제시된 데이터나 사례가 주장을 충분히 뒷받침하는지 검토.
3. 가독성 및 표현: 문장이 간결하고 명확하며, 전문 용어가 적절하게 사용되었는지 확인.
4. 개선 제안: 보완이 필요한 부분에 대해 구체적인 수정 방향 제시.
5. 수치 및 통계: 언급된 수치가 정확한지, 계산에 오류가 없는지 확인.
"""

def index_pdf_text(doc_id, pages_text_list):
    """
    Chunks the extracted text and stores it in the vector database.
    pages_text_list: list of tuples (page_num, text)
    """
    global vector_store
    
    documents = []
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len,
    )
    
    for page_num, text in pages_text_list:
        chunks = text_splitter.split_text(text)
        for chunk in chunks:
            documents.append(Document(
                page_content=chunk,
                metadata={"page": page_num, "doc_id": doc_id}
            ))
            
    if vector_store is None:
        vector_store = Chroma.from_documents(
            documents=documents,
            embedding=embeddings
        )
    else:
        vector_store.add_documents(documents)
    
    print(f"Indexed {len(documents)} chunks from document {doc_id}.")

def retrieve_relevant_context(query, k=5):
    """
    Retrieves the most relevant chunks using Hybrid Search (Vector + BM25).
    """
    if vector_store is None:
        return []
        
    # Vector search
    vector_results = vector_store.similarity_search(query, k=k)
    
    # BM25 search
    bm25_results = []
    if bm25_retriever:
        bm25_retriever.k = k
        bm25_results = bm25_retriever.get_relevant_documents(query)
    
    # Simple Reciprocal Rank Fusion or duplicate removal
    seen = set()
    combined = []
    
    # Combine results, prioritizing vector search for now
    for doc in vector_results:
        content_hash = hash(doc.page_content)
        if content_hash not in seen:
            combined.append(doc)
            seen.add(content_hash)
            
    for doc in bm25_results:
        content_hash = hash(doc.page_content)
        if content_hash not in seen:
            combined.append(doc)
            seen.add(content_hash)
            
    return combined[:k]

def expand_query_with_gemini(query, lang='ko'):
    """Uses Gemini to expand the search query for better RAG retrieval."""
    if not api_key:
        return query
        
    expansion_prompt = f"""
    You are an AI assistant specialized in document retrieval. 
    Expand the following user question into a better search query for a RAG system.
    Focus on relevant keywords, especially in Japanese if applicable.
    Respond ONLY with the expanded query string, no explanation.
    
    User Question: {query}
    Language: {lang}
    """
    try:
        response = model.generate_content(expansion_prompt)
        expanded = response.text.strip()
        print(f"Original Query: {query} -> Expanded: {expanded}")
        return expanded
    except:
        return query

@app.route('/upload', methods=['POST'])
def upload_pdf():
    if 'file' not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if not file.filename.lower().endswith('.pdf'):
        return jsonify({"error": "File must be a PDF"}), 400

    job_id = str(uuid.uuid4())
    mode = request.form.get('mode', 'both')
    lang = request.form.get('lang', 'ko')
    
    # Store bytes in memory for the background thread
    pdf_bytes = file.read()
    
    # Start background thread
    update_job_status(job_id, "pending")
    threading.Thread(
        target=background_analysis_task, 
        args=(job_id, pdf_bytes, mode, lang), 
        daemon=True
    ).start()

    return jsonify({"job_id": job_id, "status": "pending"})

@app.route('/chat', methods=['POST'])
def chat_with_document():
    """
    RAG-기반 문서 Q&A 챗봇 엔드포인트.
    """
    data = request.get_json()
    query = data.get("query")
    if not query:
        return jsonify({"error": "No query provided"}), 400
        
    try:
        lang = data.get("lang", "ko")
        lang_prompts = PROMPTS.get(lang, PROMPTS.get('ko', {}))
        chat_prompt_template = lang_prompts.get('chat', "")

        if not chat_prompt_template:
             return jsonify({"error": f"No chat prompt found for language: {lang}"}), 500

        # 1. 문서에서 관련 컨텍스트 검색 (Query Expansion 적용)
        expanded_query = expand_query_with_gemini(query, lang=lang)
        relevant_docs = retrieve_relevant_context(expanded_query, k=7)
        context = "\n\n".join([f"[Context]: {d.page_content}" for d in relevant_docs])

        # 2. Gemini에게 문서 기반 답변 요청
        prompt = f"""
        {chat_prompt_template}

        [Document Context]:
        {context}

        [User Question]:
        {query}
        """

        response = model.generate_content(prompt)
        return jsonify({"answer": response.text.strip()}), 200
    except Exception as e:
        print(f"Error in chat endpoint: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/search_text', methods=['POST'])
def search_text_in_pdf():
    """
    Search for exact text matches across all pages of the uploaded PDF using PyMuPDF.
    Returns a list of annotation objects with matched bounding boxes.
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    file = request.files['file']
    keyword = request.form.get('keyword', '').strip()
    category = request.form.get('category', '일반')
    comment = request.form.get('comment', '')

    if file.filename == '' or not keyword:
        return jsonify({"error": "File or keyword missing"}), 400

    if not file.filename.lower().endswith('.pdf'):
        return jsonify({"error": "File must be a PDF"}), 400

    try:
        pdf_bytes = file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        results = []
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text_instances = page.search_for(keyword)
            # Each text_instance is a Rect(x0, y0, x1, y1)
            for inst in text_instances:
                ann = {
                    "id": f"text-search-{page_num}-{inst.x0}-{inst.y0}",
                    "page": page_num + 1,
                    "type": "text", # Keep type consistent for frontend
                    "keyword": keyword,
                    "category": category,
                    "comment": comment,
                    "rect": [inst.x0, inst.y0, inst.x1, inst.y1]
                }
                results.append(ann)
                
        doc.close()
        return jsonify(results), 200

    except Exception as e:
        print(f"Error in text search endpoint: {e}")
        if 'doc' in locals(): doc.close()
        return jsonify({"error": str(e)}), 500

@app.route('/ask', methods=['POST'])
def ask_question():
    """
    Endpoint to test the RAG retriever.
    Expects JSON: {"query": "some question"}
    """
    data = request.get_json()
    query = data.get("query")
    if not query:
        return jsonify({"error": "No query provided"}), 400
        
    try:
        relevant_chunks = retrieve_relevant_context(query)
        results = []
        for doc in relevant_chunks:
            results.append({
                "content": doc.page_content,
                "metadata": doc.metadata
            })
        return jsonify(results), 200
    except Exception as e:
        print(f"Error in retriever: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Flask server on http://0.0.0.0:{port}")
    print("Ensure GEMINI_API_KEY environment variable is set.")
    app.run(debug=True, host='0.0.0.0', port=port)
