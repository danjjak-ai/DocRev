import os
import json
import threading
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import fitz  # PyMuPDF
from google import genai
from google.genai import types
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
import unicodedata
import re
import uuid
import base64
import io
from langchain_community.retrievers import BM25Retriever

app = Flask(__name__)
# Enable CORS with configured origins
allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*")
CORS(app, resources={r"/*": {"origins": allowed_origins}})

# --- Static File Serving ---
@app.route('/')
def serve_index():
    return send_from_directory('.', 'pdf_comment_workspace.html')

@app.route('/<path:path>')
def serve_static(path):
    if os.path.exists(os.path.join('.', path)):
        return send_from_directory('.', path)
    return jsonify({"error": "File not found"}), 404

# Configure Gemini API
# Load environment variables from .env file
load_dotenv()

# Load API Key with standard fallback for error handling
api_key = os.environ.get("GEMINI_API_KEY", "").strip('"').strip("'")

if not api_key:
    print("WARNING: GEMINI_API_KEY is not set. AI features will fail. Please check your .env file.")
else:
    print("INFO: GEMINI_API_KEY loaded from environment.")

# Initialize Gemini Client
client = genai.Client(api_key=api_key)
# Using Gemini Model from environment
MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")

# NG word list is now handled per-group via load_ng_words()
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

def perform_analysis_logic(doc, mode, lang, ng_group_id="default", prompt_group_id="default", rag_group_id="default"):
    """Core analysis logic separated to be runnable in background."""
    prompts_data = load_prompts_for_group(prompt_group_id)
    lang_prompts = prompts_data.get(lang, prompts_data.get('ko', {}))
    results = []
    
    # Extract text and images for multimodal analysis
    all_text = ""
    pages_text_list = []
    gemini_input_parts = []
    
    # Base instructions for multimodal analysis
    comp_context = """
    [Multimodal Analysis Instructions]:
    1. Identify all tables and charts/graphs in the images.
    2. Extract 'Table' data as structured Markdown format.
    3. Perform 'Visual Verification': Check if graph trends (e.g. slopes) match text claims (e.g. "sudden improvement").
    4. Detect 'Absolute Expressions' (e.g. '최고', '최상', '유일', '완치') in both text and images/charts.
    5. Search for Guideline violations based on the provided [Retrieved Guideline Context].
    """

    MAX_PAGES = 10
    total_pages = len(doc)
    processing_pages = min(total_pages, MAX_PAGES)
    
    for page_num in range(processing_pages):
        page = doc.load_page(page_num)
        text = page.get_text()
        all_text += f"--- Page {page_num + 1} ---\n{text}\n\n"
        pages_text_list.append((page_num + 1, text))


    if total_pages > MAX_PAGES:
        trunc_msg = {
            'ko': 'Light Demo에서는 10장 까지만 처리되며, 완전한 처리를 위해서는 프로덕션모드 데모를 요청하세요.',
            'ja': 'Light Demoでは10ページまで処理されます。完全な処理のためにはプロダクションモードのデモをリクエストしてください。',
            'en': 'The Light Demo only processes up to 10 pages. Please request a production mode demo for full processing.'
        }
        msg = trunc_msg.get(lang, trunc_msg['ko'])
        results.append({
            "page": -1,
            "category": "Notice",
            "type": "suggestion",
            "comment": msg,
            "ai_review_label": "INFO",
            "suggestion_label": "System"
        })

    # Prevent OpenMP Deadlock: Removed unauthorized background indexing of uploaded docs
    # doc_id = str(uuid.uuid4())
    # threading.Thread(target=index_pdf_text, args=(doc_id, pages_text_list), daemon=True).start()

    # --- Level 1: Keyword Analysis (OCR + Text Search) ---
    if mode in ['level1', 'both']:
        # Load NG words for the specific group
        ng_words_list = load_ng_words(ng_group_id)
        
        for page_num in range(processing_pages):
            page = doc.load_page(page_num)
            ng_meta = lang_prompts.get('ng_violation', PROMPTS.get('ko', {}).get('ng_violation', {}))
            for ng_item in ng_words_list:
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

    # --- Level 2: Multimodal AI Review (Gemini 1.5 Pro + RAG) ---
    if mode in ['level2', 'both'] and api_key:
        try:
            for page_num in range(processing_pages):
                page = doc.load_page(page_num)
                # Convert page to high-res image (300 DPI)
                pix = page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72))
                img_bytes = pix.tobytes("png")
                gemini_input_parts.append({
                    "mime_type": "image/png",
                    "data": img_bytes
                })

            # 1. 문서에서 관련 컨텍스트 검색 (Query Expansion 적용)
            base_query = "제약 광고 심의 가이드라인 판매정보제공 가이드라인 허위 과장 비방 금지"
            expanded_query = expand_query_with_gemini(base_query, lang=lang)
            relevant_docs = retrieve_relevant_context(expanded_query, k=10)
            retrieved_context = "\n\n".join([f"[Context]: {d.page_content}" for d in relevant_docs])

            # 2. Gemini에게 문서 분석 요청
            review_prompt_template = lang_prompts.get('review', "")
            if not review_prompt_template:
                review_prompt_template = PROMPTS.get('en', {}).get('review', "")
            
            if review_prompt_template:
                # Add multimodal context to prompt
                final_prompt = f"""
                {review_prompt_template}

                {comp_context}

                [Retrieved Guideline Context]:
                {retrieved_context}

                Whole Document Text:
                {all_text}
                
                Analyze the provided images and text carefully. 
                Especially, detect if any absolute expressions or prohibited words (e.g., '최고', '최상', '유일', '완치', 'No.1', '副作用なし') appear inside images or graphs.
                If you find a 'Table' or 'Chart', extract its data as Markdown and include it in the 'reason' or 'suggestion' field.
                
                Return results as a JSON list. 
                Each object MUST contain these exact keys:
                - "page": integer
                - "quote": exact text verbatim (for images, use a short descriptive phrase of the visual finding)
                - "category": string (e.g., "Guideline Violation")
                - "type": "critical" or "suggestion"
                - "clause": title of the related rule
                - "reason": detailed explanation
                - "suggestion": how to fix
                """
                
                # Combine prompt with image parts
                # The new SDK uses a different content structure
                contents = [final_prompt]
                for img_part in gemini_input_parts:
                    contents.append(types.Part.from_bytes(
                        data=img_part["data"],
                        mime_type=img_part["mime_type"]
                    ))
                
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=contents
                )
                ai_response_text = response.text.strip()
                print(f"AI Response Raw: {ai_response_text[:200]}...")
                
                # Strip markdown blocks if present
                if ai_response_text.startswith("```json"):
                    ai_response_text = ai_response_text.split("```json")[1].split("```")[0].strip()
                elif ai_response_text.startswith("```"):
                     ai_response_text = ai_response_text.split("```")[1].split("```")[0].strip()

                # Robust JSON Parsing
                try:
                    parsed_results = json.loads(ai_response_text)
                except json.JSONDecodeError:
                    # Try to extract JSON if there's surrounding text
                    match = re.search(r'\[.*\]', ai_response_text, re.DOTALL)
                    if match:
                        parsed_results = json.loads(match.group())
                    else:
                        raise ValueError(f"Failed to parse AI response as JSON: {ai_response_text[:100]}...")

                # Handle if AI returns a dictionary instead of a list
                if isinstance(parsed_results, dict):
                    # Look for list-like keys (results, violations, annotations, analysis, data, etc.)
                    for key in ["results", "violations", "annotations", "analysis", "data"]:
                        if key in parsed_results and isinstance(parsed_results[key], list):
                            parsed_results = parsed_results[key]
                            break
                    else:
                        # Otherwise, treat as a single result in a list
                        parsed_results = [parsed_results]

                if isinstance(parsed_results, list):
                    print(f"AI Review: Parsed {len(parsed_results)} annotation candidates.")
                    for ann in parsed_results:
                        # Robust page parsing
                        try:
                            page_val = ann.get("page", 1)
                            if isinstance(page_val, str):
                                match = re.search(r'\d+', page_val)
                                page_val = int(match.group()) if match else 1
                            page_num_actual = int(page_val)
                            ann["page"] = page_num_actual
                        except:
                            ann["page"] = 1

                        page_idx = ann["page"] - 1
                        
                        # Handle alternate keys (keyword vs quote)
                        if "keyword" in ann and not ann.get("quote"):
                            ann["quote"] = ann["keyword"]
                        
                        quote = ann.get("quote", "").strip()
                        
                        # Match bounding boxes for quotes detected by AI
                        if 0 <= page_idx < len(doc) and quote:
                            page = doc.load_page(page_idx)
                            rects = robust_search_for_quote(page, quote)
                            if rects:
                                ann["rects"] = [[r.x0, r.y0, r.x1, r.y1] for r in rects]
                                ann["rect"] = ann["rects"][0]
                        
                        # High-probability word search fallback
                        if quote and "rects" not in ann:
                            for p_idx in range(processing_pages):
                                pg = doc.load_page(p_idx)
                                rects = robust_search_for_quote(pg, quote)
                                if rects:
                                    ann["rects"] = [[r.x0, r.y0, r.x1, r.y1] for r in rects]
                                    ann["rect"] = ann["rects"][0]
                                    ann["page"] = p_idx + 1
                                    break
                                    
                        ann["ai_review_label"] = lang_prompts.get("ai_review_label", "AI 리뷰")
                        ann["suggestion_label"] = lang_prompts.get("suggestion_label", "제안")
                        
                        # Use provided category if available, else default to ai_review_label
                        if not ann.get("category"):
                            ann["category"] = ann.get("ai_review_label", "AI 리뷰")
                        
                        # Ensure fields exist for frontend processing
                        # Deep Review results should keep reason and suggestion separate for UI flexibility
                        if not ann.get("clause"): 
                            ann["clause"] = ann.get("category", "")
                        
                        # If 'comment' exists but not 'reason', map it.
                        if not ann.get("reason"):
                            ann["reason"] = ann.get("comment", "상세 내용 없음")
                        
                        # Ensure 'suggestion' is at least an empty string
                        if "suggestion" not in ann:
                            ann["suggestion"] = ""
                            
                        results.append(ann)
                
                print(f"Level 2 Analysis Complete: Found {len(results)} total violations.")
            else:
                print(f"No review prompt template for lang {lang}")
        except Exception as e:
            print(f"AI Review Error: {e}")
            import traceback
            traceback.print_exc()

    return results

def background_analysis_task(job_id, pdf_bytes, mode, lang, ng_group_id="default", prompt_group_id="default", rag_group_id="default"):
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        results = perform_analysis_logic(doc, mode, lang, ng_group_id, prompt_group_id, rag_group_id)
        update_job_status(job_id, "completed", results=results)
    except Exception as e:
        import traceback
        traceback.print_exc()
        update_job_status(job_id, "failed", error=str(e))

# Global Variables and Configurations
CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")
PROMPTS_FILE = os.path.join(CONFIG_DIR, "prompts.json") # Legacy fallback
NG_GROUPS_FILE = os.path.join(CONFIG_DIR, "ng_groups.json")
NG_WORDS_BASE_DIR = os.path.join(CONFIG_DIR, "ng_words")
PROMPT_GROUPS_FILE = os.path.join(CONFIG_DIR, "prompt_groups.json")
PROMPTS_BASE_DIR = os.path.join(CONFIG_DIR, "prompts")

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(NG_WORDS_BASE_DIR, exist_ok=True)
os.makedirs(PROMPTS_BASE_DIR, exist_ok=True)

# --- Initial setup for default group ---
def init_default_config():
    get_ng_groups() # Ensures ng_groups.json and default folder/file exist
    get_rag_groups() # For RAG
    get_prompt_groups() # For Prompts

def get_prompt_groups():
    groups = {}
    if os.path.exists(PROMPT_GROUPS_FILE):
        try:
            with open(PROMPT_GROUPS_FILE, "r", encoding="utf-8") as f:
                groups = json.load(f)
        except:
            pass
    
    if "default" not in groups:
        groups["default"] = {"id": "default", "name": "기본 프롬프트 (Default)"}
        save_prompt_groups(groups)
    
    # Ensure default is first
    ordered = {"default": groups.pop("default")}
    ordered.update(groups)
    return ordered

def save_prompt_groups(groups):
    with open(PROMPT_GROUPS_FILE, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=4)

def get_prompts_file(group_id):
    return os.path.join(PROMPTS_BASE_DIR, f"{group_id}.json")

def load_prompts_for_group(group_id="default"):
    file_path = get_prompts_file(group_id)
    if not os.path.exists(file_path):
        # Migrate old global file to default group if it exists
        if group_id == "default" and os.path.exists(PROMPTS_FILE):
            import shutil
            shutil.copy(PROMPTS_FILE, file_path)
        else:
            return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_prompts_for_group(group_id, data):
    file_path = get_prompts_file(group_id)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# PROMPTS is now loaded per-group when needed
PROMPTS = {} # Still keep as global cache if needed, but per-group is preferred

def get_ng_groups():
    groups = {}
    if os.path.exists(NG_GROUPS_FILE):
        try:
            with open(NG_GROUPS_FILE, "r", encoding="utf-8") as f:
                groups = json.load(f)
        except:
            pass
    
    if "default" not in groups:
        groups["default"] = {"id": "default", "name": "기본 금지어 (Default)"}
        save_ng_groups(groups)
        
    # Ensure default is first
    ordered = {"default": groups.pop("default")}
    ordered.update(groups)
    return ordered

def save_ng_groups(groups):
    with open(NG_GROUPS_FILE, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=4)

def get_ng_words_file(group_id):
    return os.path.join(NG_WORDS_BASE_DIR, f"{group_id}.json")

def load_ng_words(group_id="default"):
    file_path = get_ng_words_file(group_id)
    if not os.path.exists(file_path):
        # Migrate old global file to default group if it exists
        old_file = os.path.join(CONFIG_DIR, "ng_words_dataset.json")
        if group_id == "default" and os.path.exists(old_file):
            import shutil
            shutil.move(old_file, file_path)
        else:
            return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_ng_words(group_id, words):
    file_path = get_ng_words_file(group_id)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False, indent=4)

@app.route('/api/ng-words/groups', methods=['GET'])
def list_ng_groups():
    return jsonify(list(get_ng_groups().values()))

@app.route('/api/ng-words/groups', methods=['POST'])
def create_ng_group():
    data = request.get_json()
    name = data.get("name")
    if not name:
        return jsonify({"error": "Group name is required"}), 400
    
    groups = get_ng_groups()
    group_id = str(uuid.uuid4())[:8]
    groups[group_id] = {"id": group_id, "name": name}
    save_ng_groups(groups)
    
    # Init empty file
    save_ng_words(group_id, [])
    
    return jsonify(groups[group_id]), 201

@app.route('/api/ng-words/groups/<group_id>', methods=['PATCH'])
def rename_ng_group(group_id):
    data = request.get_json()
    new_name = data.get("name")
    if not new_name:
        return jsonify({"error": "New name is required"}), 400
    
    groups = get_ng_groups()
    if group_id not in groups:
        return jsonify({"error": "Group not found"}), 404
    
    groups[group_id]["name"] = new_name
    save_ng_groups(groups)
    return jsonify(groups[group_id])

@app.route('/api/ng-words/groups/<group_id>', methods=['DELETE'])
def delete_ng_group(group_id):
    groups = get_ng_groups()
    if group_id not in groups:
        return jsonify({"error": "Group not found"}), 404
    
    if group_id == "default":
        return jsonify({"error": "Cannot delete default group"}), 400

    del groups[group_id]
    save_ng_groups(groups)

    # Clean up file
    file_path = get_ng_words_file(group_id)
    if os.path.exists(file_path): os.remove(file_path)

    return jsonify({"message": "Group deleted successfully"})

@app.route('/api/ng-words', methods=['GET'])
def get_ng_words_api():
    group_id = request.args.get("group_id", "default")
    return jsonify(load_ng_words(group_id))

@app.route('/api/ng-words', methods=['POST'])
def add_ng_word_api():
    data = request.get_json()
    group_id = data.get("group_id", "default")
    word = data.get("word")
    rule = data.get("rule", "")
    suggestion = data.get("suggestion", "")
    
    if not word:
        return jsonify({"error": "No word provided"}), 400
    
    words = load_ng_words(group_id)
    if any(item.get("word") == word for item in words):
        return jsonify({"error": "Word already exists"}), 400
        
    words.append({
        "word": word,
        "rule": rule,
        "suggestion": suggestion
    })
    
    save_ng_words(group_id, words)
    return jsonify({"message": "Word added successfully", "words": words}), 201

@app.route('/api/ng-words', methods=['PUT'])
def update_ng_word_api():
    data = request.get_json()
    group_id = data.get("group_id", "default")
    old_word = data.get("old_word")
    new_word = data.get("new_word")
    new_rule = data.get("rule", "")
    new_suggestion = data.get("suggestion", "")
    
    if not old_word or not new_word:
        return jsonify({"error": "Both old_word and new_word are required"}), 400
        
    words = load_ng_words(group_id)
    target_idx = -1
    for i, item in enumerate(words):
        if item.get("word") == old_word:
            target_idx = i
            break
            
    if target_idx == -1:
        return jsonify({"error": "Old word not found"}), 404
        
    if new_word != old_word and any(item.get("word") == new_word for item in words):
        return jsonify({"error": "New word already exists"}), 400
    
    words[target_idx] = {
        "word": new_word,
        "rule": new_rule,
        "suggestion": new_suggestion
    }
    
    save_ng_words(group_id, words)
    return jsonify({"message": "Word updated successfully", "words": words}), 200

@app.route('/api/ng-words', methods=['DELETE'])
def delete_ng_word_api():
    data = request.get_json()
    group_id = data.get("group_id", "default")
    word = data.get("word")
    if not word:
        return jsonify({"error": "No word provided"}), 400
        
    words = load_ng_words(group_id)
    initial_len = len(words)
    words = [item for item in words if item.get("word") != word]
    
    if len(words) == initial_len:
        return jsonify({"error": "Word not found"}), 404
        
    save_ng_words(group_id, words)
    return jsonify({"message": "Word deleted successfully", "words": words}), 200

@app.route('/api/prompts/groups', methods=['GET'])
def list_prompt_groups():
    return jsonify(list(get_prompt_groups().values()))

@app.route('/api/prompts/groups', methods=['POST'])
def create_prompt_group():
    data = request.get_json()
    name = data.get("name")
    if not name:
        return jsonify({"error": "Group name is required"}), 400
    
    groups = get_prompt_groups()
    group_id = str(uuid.uuid4())[:8]
    groups[group_id] = {"id": group_id, "name": name}
    save_prompt_groups(groups)
    
    # Init empty file or default prompts
    save_prompts_for_group(group_id, {})
    
    return jsonify(groups[group_id]), 201

@app.route('/api/prompts/groups/<group_id>', methods=['PATCH'])
def rename_prompt_group(group_id):
    data = request.get_json()
    new_name = data.get("name")
    if not new_name:
        return jsonify({"error": "New name is required"}), 400
    
    groups = get_prompt_groups()
    if group_id not in groups:
        return jsonify({"error": "Group not found"}), 404
    
    groups[group_id]["name"] = new_name
    save_prompt_groups(groups)
    return jsonify(groups[group_id])

@app.route('/api/prompts/groups/<group_id>', methods=['DELETE'])
def delete_prompt_group(group_id):
    groups = get_prompt_groups()
    if group_id not in groups:
        return jsonify({"error": "Group not found"}), 404
    
    if group_id == "default":
        return jsonify({"error": "Cannot delete default group"}), 400

    del groups[group_id]
    save_prompt_groups(groups)

    # Clean up file
    file_path = get_prompts_file(group_id)
    if os.path.exists(file_path): os.remove(file_path)

    return jsonify({"message": "Group deleted successfully"})

@app.route('/api/prompts', methods=['GET'])
def get_prompts_api():
    group_id = request.args.get("group_id", "default")
    return jsonify(load_prompts_for_group(group_id))

@app.route('/api/prompts', methods=['POST'])
def update_prompts_api():
    data = request.get_json()
    group_id = data.get("group_id", "default")
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    # Remove group_id from actual prompts data before saving
    # data_to_save = {k: v for k, v in data.items() if k != "group_id"}
    # Note: frontend sends { "group_id": "...", "ko": {...}, "en": {...} }
    # but we want to store it in a way load_prompts_for_group expects.
    # Actually current frontend sends promptsData which is a dict of langs.
    # Let's handle it carefully.
    
    save_prompts_for_group(group_id, data)
    return jsonify({"message": "Prompts updated successfully"}), 200

# Lazy load embeddings only when needed to speed up startup for group listing API
_embeddings_instance = None
def get_embeddings():
    global _embeddings_instance
    if _embeddings_instance is None:
        print("INFO: Loading HuggingFaceEmbeddings model (this may take a few seconds)...")
        _embeddings_instance = HuggingFaceEmbeddings(model_name="pkshatech/GLuCoSE-base-ja")
        print("INFO: HuggingFaceEmbeddings model loaded.")
    return _embeddings_instance

# Use persistent ChromaDB
PERSIST_DIR = os.path.join(os.path.dirname(__file__), "config", "vector_store")
vector_store = None
bm25_retriever = None

# Reference Document Configuration and State
RAG_GROUPS_FILE = os.path.join(CONFIG_DIR, "rag_groups.json")
REF_DOCS_BASE_DIR = os.path.join(CONFIG_DIR, "ReferenceDoc")
PERSIST_BASE_DIR = os.path.join(CONFIG_DIR, "vector_store")

os.makedirs(REF_DOCS_BASE_DIR, exist_ok=True)
os.makedirs(PERSIST_BASE_DIR, exist_ok=True)

# Format: { "group_id": { "is_running": False, "message": "", "files_processed": [] } }
RAG_STATUS_MAP = {}

def get_rag_groups():
    groups = {}
    if os.path.exists(RAG_GROUPS_FILE):
        try:
            with open(RAG_GROUPS_FILE, "r", encoding="utf-8") as f:
                groups = json.load(f)
        except:
            pass
    
    if "default" not in groups:
        groups["default"] = {"id": "default", "name": "기본 그룹 (Default)"}
        save_rag_groups(groups)
        
    # Ensure default is first
    ordered = {"default": groups.pop("default")}
    ordered.update(groups)
    return ordered

def save_rag_groups(groups):
    with open(RAG_GROUPS_FILE, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=4)

def get_group_dir(group_id):
    path = os.path.join(REF_DOCS_BASE_DIR, group_id)
    os.makedirs(path, exist_ok=True)
    return path

def get_persist_dir(group_id):
    path = os.path.join(PERSIST_BASE_DIR, group_id)
    os.makedirs(path, exist_ok=True)
    return path

def get_group_status(group_id):
    if group_id not in RAG_STATUS_MAP:
        RAG_STATUS_MAP[group_id] = {"is_running": False, "message": "", "files_processed": []}
    return RAG_STATUS_MAP[group_id]

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

@app.route('/api/rag/groups', methods=['GET'])
def list_rag_groups():
    return jsonify(list(get_rag_groups().values()))

@app.route('/api/rag/groups', methods=['POST'])
def create_rag_group():
    data = request.get_json()
    name = data.get("name")
    if not name:
        return jsonify({"error": "Group name is required"}), 400
    
    groups = get_rag_groups()
    group_id = str(uuid.uuid4())[:8]
    groups[group_id] = {"id": group_id, "name": name}
    save_rag_groups(groups)
    
    # Pre-create directories
    get_group_dir(group_id)
    get_persist_dir(group_id)
    
    return jsonify(groups[group_id]), 201

@app.route('/api/rag/groups/<group_id>', methods=['PATCH'])
def rename_rag_group(group_id):
    data = request.get_json()
    new_name = data.get("name")
    if not new_name:
        return jsonify({"error": "New name is required"}), 400
    
    groups = get_rag_groups()
    if group_id not in groups:
        return jsonify({"error": "Group not found"}), 404
    
    groups[group_id]["name"] = new_name
    save_rag_groups(groups)
    return jsonify(groups[group_id])

@app.route('/api/rag/groups/<group_id>', methods=['DELETE'])
def delete_rag_group(group_id):
    groups = get_rag_groups()
    if group_id not in groups:
        return jsonify({"error": "Group not found"}), 404
    
    if group_id == "default":
        return jsonify({"error": "Cannot delete default group"}), 400

    del groups[group_id]
    save_rag_groups(groups)

    # Clean up files
    import shutil
    group_dir = os.path.join(REF_DOCS_BASE_DIR, group_id)
    persist_dir = os.path.join(PERSIST_BASE_DIR, group_id)
    if os.path.exists(group_dir): shutil.rmtree(group_dir)
    if os.path.exists(persist_dir): shutil.rmtree(persist_dir)

    return jsonify({"message": "Group deleted successfully"})

@app.route('/api/reference-docs', methods=['GET'])
def list_reference_docs():
    group_id = request.args.get("group_id", "default")
    group_dir = get_group_dir(group_id)
    files = []
    if os.path.exists(group_dir):
        for f in os.listdir(group_dir):
            if f.lower().endswith(('.pdf', '.txt', '.md', '.xml')):
                files.append(f)
    return jsonify(files)

@app.route('/api/reference-docs/upload', methods=['POST'])
def upload_reference_doc():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    files = request.files.getlist('file')
    group_id = request.form.get("group_id", "default")
    group_dir = get_group_dir(group_id)

    if not files:
        return jsonify({"error": "No selected files"}), 400
    
    uploaded_files = []
    errors = []
    for file in files:
        if file.filename == '': continue
        
        filename = secure_filename(file.filename)
        file_path = os.path.join(group_dir, filename)
        file.save(file_path)
        uploaded_files.append(filename)
    
    return jsonify({
        "message": f"Successfully uploaded {len(uploaded_files)} files", 
        "filenames": uploaded_files,
        "errors": errors if errors else None
    }), 200

@app.route('/api/reference-docs/<filename>', methods=['DELETE'])
def delete_reference_doc(filename):
    group_id = request.args.get("group_id", "default")
    group_dir = get_group_dir(group_id)
    safe_filename = secure_filename(filename)
    file_path = os.path.join(group_dir, safe_filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        return jsonify({"message": f"Successfully deleted {safe_filename}"}), 200
    return jsonify({"error": "File not found"}), 404

@app.route('/api/rag/status', methods=['GET'])
def get_rag_status():
    group_id = request.args.get("group_id", "default")
    return jsonify(get_group_status(group_id))

def reconstruct_rag_task(group_id):
    global RAG_STATUS_MAP
    status = get_group_status(group_id)
    try:
        documents = []
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
            separators=["\n\n", "\n", "。", "！", "？", " ", ""]
        )
        files_processed = []
        group_dir = get_group_dir(group_id)
        persist_dir = get_persist_dir(group_id)

        if os.path.exists(group_dir):
            for root, dirs, files in os.walk(group_dir):
                for filename in files:
                    file_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(file_path, group_dir)
                    
                    if filename.lower().endswith('.pdf'):
                        doc = fitz.open(file_path)
                        for page_num in range(len(doc)):
                            page = doc.load_page(page_num)
                            text = page.get_text()
                            chunks = text_splitter.split_text(text)
                            for chunk in chunks:
                                documents.append(Document(
                                    page_content=chunk,
                                    metadata={"page": page_num + 1, "doc_id": rel_path, "group_id": group_id}
                                ))
                        files_processed.append(rel_path)
                    
                    elif filename.lower().endswith(('.xml', '.txt', '.md')):
                        try:
                            with open(file_path, "r", encoding="utf-8") as f:
                                text = f.read()
                                chunks = text_splitter.split_text(text)
                                for chunk in chunks:
                                    documents.append(Document(
                                        page_content=chunk,
                                        metadata={"doc_id": rel_path, "group_id": group_id}
                                    ))
                            files_processed.append(rel_path)
                        except Exception as read_err:
                            print(f"Error reading {file_path}: {read_err}")
        
        if documents:
            # Create group-specific vector store
            Chroma.from_documents(
                documents=documents, 
                embedding=get_embeddings(),
                persist_directory=persist_dir
            )
            status["message"] = f"RAG 재구성이 완료되었습니다. (그룹: {group_id}, 총 {len(documents)}개 청크)"
        else:
            status["message"] = f"참조 문서가 없어 RAG 데이터베이스를 초기화했습니다. (그룹: {group_id})"
            
        status["files_processed"] = files_processed
    except Exception as e:
        status["message"] = f"RAG 재구성 중 오류 발생: {str(e)}"
    finally:
        status["is_running"] = False

@app.route('/api/rag/reconstruct', methods=['POST'])
def trigger_rag_reconstruction():
    data = request.get_json() or {}
    group_id = data.get("group_id", "default")
    status = get_group_status(group_id)
    
    if status["is_running"]:
        return jsonify({"error": f"RAG reconstruction for group {group_id} is already running"}), 409
    
    status["is_running"] = True
    status["message"] = f"RAG 재구성을 시작했습니다... (그룹: {group_id})"
    status["files_processed"] = []
    
    thread = threading.Thread(target=reconstruct_rag_task, args=(group_id,))
    thread.daemon = True
    thread.start()
    
    return jsonify({"message": "RAG reconstruction started", "group_id": group_id}), 202


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
            embedding=get_embeddings()
        )
    else:
        vector_store.add_documents(documents)
    
    print(f"Indexed {len(documents)} chunks from document {doc_id}.")

def retrieve_relevant_context(query, group_id="default", k=5):
    """
    Retrieves the most relevant chunks from a specific group's vector store.
    """
    persist_dir = get_persist_dir(group_id)
    if not os.path.exists(persist_dir) or not os.listdir(persist_dir):
        return []

    try:
        # Load the store for this specific group
        group_store = Chroma(
            persist_directory=persist_dir,
            embedding_function=get_embeddings()
        )
        
        # Vector search
        vector_results = group_store.similarity_search(query, k=k)
        
        # BM25 search
        bm25_results = []
        if bm25_retriever:
            bm25_retriever.k = k
            bm25_results = bm25_retriever.get_relevant_documents(query)
        
        # Simple Reciprocal Rank Fusion or duplicate removal
        seen = set()
        combined = []
        
        # Combine results, prioritizing vector search
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
                
        return combined[:int(k)]
    except Exception as e:
        print(f"Error retrieving from group {group_id}: {e}")
        return []

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
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=expansion_prompt
        )
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
    ng_group_id = request.form.get('ng_group_id', 'default')
    prompt_group_id = request.form.get('prompt_group_id', 'default')
    rag_group_id = request.form.get('rag_group_id', 'default')
    
    # Store bytes in memory for the background thread
    pdf_bytes = file.read()
    
    # Start background thread
    update_job_status(job_id, "pending")
    threading.Thread(
        target=background_analysis_task, 
        args=(job_id, pdf_bytes, mode, lang, ng_group_id, prompt_group_id, rag_group_id), 
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
        prompt_group_id = data.get("prompt_group_id", "default")
        rag_group_id = data.get("rag_group_id", "default")
        
        prompts_data = load_prompts_for_group(prompt_group_id)
        lang_prompts = prompts_data.get(lang, prompts_data.get('ko', {}))
        chat_prompt_template = lang_prompts.get('chat', "")

        if not chat_prompt_template:
             return jsonify({"error": f"No chat prompt found for language: {lang}"}), 500

        # 1. 문서에서 관련 컨텍스트 검색 (Query Expansion 적용)
        expanded_query = expand_query_with_gemini(query, lang=lang)
        relevant_docs = retrieve_relevant_context(expanded_query, group_id=rag_group_id, k=7)
        context = "\n\n".join([f"[Context]: {d.page_content}" for d in relevant_docs])

        # 2. Gemini에게 문서 기반 답변 요청
        prompt = f"""
        {chat_prompt_template}

        [Document Context]:
        {context}

        [User Question]:
        {query}
        """

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
        )
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

init_default_config()

if __name__ == '__main__':
    port = int(os.environ.get("FLASK_PORT", 5000))
    print(f"Starting Flask server on http://0.0.0.0:{port}")
    print("Ensure GEMINI_API_KEY environment variable is set.")
    app.run(debug=True, host='0.0.0.0', port=port)
