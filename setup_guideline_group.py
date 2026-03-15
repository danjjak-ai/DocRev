
import os
import json
import uuid
import shutil

CONFIG_DIR = r"c:\workspace\DocRev\config"
RAG_GROUPS_FILE = os.path.join(CONFIG_DIR, "rag_groups.json")
NG_GROUPS_FILE = os.path.join(CONFIG_DIR, "ng_groups.json")
PROMPT_GROUPS_FILE = os.path.join(CONFIG_DIR, "prompt_groups.json")

NEW_NAME = "医療用医薬品の販売情報提供活動に関するガイドライン"
GROUP_ID = "guideline"

def ensure_group(file_path, new_id, new_name):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            groups = json.load(f)
    else:
        groups = {}
    
    groups[new_id] = {"id": new_id, "name": new_name}
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=4)
    print(f"Registered {new_name} in {file_path}")

def copy_default_data(group_type, new_id):
    if group_type == "ng":
        base_dir = os.path.join(CONFIG_DIR, "ng_words")
    elif group_type == "prompt":
        base_dir = os.path.join(CONFIG_DIR, "prompts")
    elif group_type == "rag_docs":
        base_dir = os.path.join(CONFIG_DIR, "ReferenceDoc")
    elif group_type == "rag_vec":
        base_dir = os.path.join(CONFIG_DIR, "vector_store")
    else:
        return

    src = os.path.join(base_dir, "default")
    if group_type in ["ng", "prompt"]:
        src += ".json"
        dst = os.path.join(base_dir, f"{new_id}.json")
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy(src, dst)
            print(f"Copied {src} to {dst}")
    else:
        dst = os.path.join(base_dir, new_id)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copytree(src, dst)
            print(f"Copied directory {src} to {dst}")

# 1. Register groups
ensure_group(RAG_GROUPS_FILE, GROUP_ID, NEW_NAME)
ensure_group(NG_GROUPS_FILE, GROUP_ID, NEW_NAME)
ensure_group(PROMPT_GROUPS_FILE, GROUP_ID, NEW_NAME)

# 2. Copy default data
copy_default_data("ng", GROUP_ID)
copy_default_data("prompt", GROUP_ID)
copy_default_data("rag_docs", GROUP_ID)
copy_default_data("rag_vec", GROUP_ID)

print("Setup completed successfully.")
