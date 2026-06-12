import json
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set,Any
import os
import time
from dotenv import load_dotenv
from datetime import datetime
from google import genai
from rapidfuzz import fuzz
BEFORE_TOC_DIR = Path("before_toc_txt")
AFTER_TOC_DIR = Path("after_toc_txt")
DEFINITIONS_DIR = Path("json_files")        
METADATA_DIR = Path("document_metadata")      

OUTPUT_DIR = Path("output_files")  
OUTPUT_DIR.mkdir(exist_ok=True)
KEYWORDS = [
    "Title",
    "Lead Arrangers",
    "Borrower",
    "sponsor",
    "Administrative Agent",
    "amendment number",
    "legal issuer",
    "source title",
    "document title",
    "document date"
]
def normalize(text: str) -> str:
    return " ".join(text.lower().split())
def normalize_key(key: str) -> str:
    
    return re.sub(r"[^\w]", "", key).lower()
def estimate_tokens(text: str) -> int:
    """
    Rough token estimator:
    ~4 characters per token (common heuristic)
    """
    if not text:
        return 0
    return max(1, len(text) // 4)
def extract_first_3_digits(name: str) -> str | None:
    match = re.search(r"\d{3}", name)
    return match.group(0) if match else None
def load_json_definitions(path: Path) -> Dict[str, str]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    definitions = {}
    for entry in data:
        term = entry.get("term")
        definition = entry.get("definition")
        if term and definition:
            definitions[normalize(term)] = definition.strip()

    return definitions
def merge_txt_files_by_id() -> dict[str, str]:
    """
    Merge TXT files by first 3 digits in strict order:
    1. BEFORE_TOC
    2. AFTER_TOC
    Returns { pdf_id: merged_text }
    """

    groups_before = defaultdict(list)
    groups_after = defaultdict(list)

    # Collect BEFORE_TOC files
    for file in BEFORE_TOC_DIR.glob("*.txt"):
        pdf_id = extract_first_3_digits(file.name)
        if pdf_id:
            groups_before[pdf_id].append(file)

    # Collect AFTER_TOC files
    for file in AFTER_TOC_DIR.glob("*.txt"):
        pdf_id = extract_first_3_digits(file.name)
        if pdf_id:
            groups_after[pdf_id].append(file)

    merged = {}

    all_ids = set(groups_before.keys()) | set(groups_after.keys())

    for pdf_id in all_ids:
        content = []

        # 1️⃣ BEFORE_TOC first
        for f in sorted(groups_before.get(pdf_id, [])):
            content.append(f.read_text(encoding="utf-8"))

        # 2️⃣ AFTER_TOC second
        for f in sorted(groups_after.get(pdf_id, [])):
            content.append(f.read_text(encoding="utf-8"))

        merged[pdf_id] = "\n\n".join(content)

    return merged

def find_matching_definitions(
    keywords: List[str],
    definitions: Dict[str, str]
) -> List[str]:
    matches = []
    seen: Set[str] = set()

    keyword_norms = [normalize(k) for k in keywords]

    for term_norm, definition in definitions.items():
        for kw in keyword_norms:
            if kw in term_norm and term_norm not in seen:
                matches.append(
                    f"Term: {term_norm}\nDefinition:\n{definition}"
                )
                seen.add(term_norm)
                break

    return matches
def build_final_outputs():
    merged_txts = merge_txt_files_by_id()

    for pdf_id, txt_content in merged_txts.items():
        json_path = next(
            (j for j in DEFINITIONS_DIR.glob("*.json")
             if extract_first_3_digits(j.name) == pdf_id),
            None
        )

        if not json_path:
            print(f"⚠️ No JSON found for {pdf_id}, skipping")
            continue

        definitions = load_json_definitions(json_path)
        matched_defs = find_matching_definitions(KEYWORDS, definitions)

        final_text = txt_content

        if matched_defs:
            final_text += (
                "\n\n"
                "--------------------------------------------------\n"
                "DEFINED TERMS (FROM SAME PDF)\n"
                "--------------------------------------------------\n"
                + "\n\n".join(matched_defs)
            )

        output_file = OUTPUT_DIR / f"{pdf_id}_final.txt"
        output_file.write_text(final_text, encoding="utf-8")

        print(f"✅ Final file created: {output_file}")


# ================== ENTRY ==================

if __name__ == "__main__":
    build_final_outputs()
load_dotenv()  # loads variables from .env into environment
MODEL_CONFIG = {
    "provider": "gemini",              
    "model_name": "gemini-2.0-flash",
    "temperature": 0.0,
    "api_key": os.getenv("GEMINI_API_KEY")
}

if not MODEL_CONFIG["api_key"]:
    raise EnvironmentError("Missing API key in .env file")
def build_output_skeleton(run_config: Dict[str, Any], rules_json: Dict[str, Any]) -> str:
    skeleton = {}
    for key in run_config["keywords_to_extract"]:
        rule = rules_json["keywords"].get(key)
        if not rule:
            continue

        fallback = rule.get("expected_output", {}).get("fallback", "NOT SPECIFIED")
        skeleton[key] = fallback

    return json.dumps(skeleton, indent=2)

########################################
# 3. PROMPT BUILDER
########################################

def build_llm_prompt(
    rules_json: Dict[str, Any],
    run_config: Dict[str, Any],
    document_text: str
) -> str:
    prompt: List[str] = []

    prompt.append(
        "You are an expert legal document extraction system. "
        "Follow all definitions, priorities, and fallback rules strictly. "
        "Do not infer, assume, or hallucinate values."
    )

    prompt.append(f"\nDOCUMENT TYPE: {run_config['document_type'].upper()}\n")
    

    prompt.append("KEYWORD EXTRACTION RULES:\n")

    for keyword in run_config["keywords_to_extract"]:



        rule = rules_json["keywords"][keyword]

        prompt.append(f"KEYWORD: {keyword}")
        if keyword == "Title":
            prompt.append(
                "IMPORTANT: Title MUST always be populated. "
                "If uncertain, return NOT SPECIFIED."
            )

        prompt.append(f"Definition:\n{rule['definition']}")

        doc_rules = rule.get("document_type_rules", {}).get(
            run_config["document_type"]
        )

        if doc_rules:
            prompt.append("Search Instructions:")
            for k, v in doc_rules.items():
                label = k.replace("_", " ").title()
                if isinstance(v, list):
                    prompt.append(f"- {label}: {', '.join(v)}")
                else:
                    prompt.append(f"- {label}: {v}")

        if "extraction_rules" in rule:
            prompt.append("Extraction Rules:")
            for r in rule["extraction_rules"]:
                prompt.append(f"- {r}")

        expected = rule["expected_output"]
        prompt.append("Output Rules:")
        prompt.append(f"- Type: {expected['type']}")
        prompt.append(f"- Cardinality: {expected['cardinality']}")

        if "fallback" in expected:
            prompt.append(f"- If not found, return: {expected['fallback']}")

        prompt.append("\n---\n")

    output_skeleton = build_output_skeleton(run_config, rules_json)

    prompt.append(
        "OUTPUT FORMAT (MANDATORY):\n"
        "You MUST return a JSON object with the EXACT SAME keys as below.\n"
        "Do NOT add or remove any keys.\n\n"
        
        "FOR EACH KEY:\n"
        "- If the value is FOUND in the document, return an object in this format:\n"
        "  {\n"
        '    "value": "<extracted value>",\n'
        '    "reference_text": "<exact sentence from the document where the value appears>"\n'
        "  }\n\n"
        
        "- If the keyword allows MULTIPLE values, return a list of such objects.\n"
        
        "- The reference_text MUST be copied EXACTLY from the document.\n"
        "- Do NOT summarize.\n"
        "- Do NOT modify wording.\n"
        "- Do NOT paraphrase.\n"
        "- The reference_text must exist verbatim in the DOCUMENT TEXT section.\n\n"
        
        "- If a value CANNOT be determined, return the fallback value EXACTLY as provided "
        "(do NOT wrap fallback inside an object).\n\n"
        
        "Return ONLY valid JSON.\n\n"
        f"{output_skeleton}\n"
    )




    prompt.append("\nDOCUMENT TEXT:\n")
    prompt.append(document_text)

    return "\n".join(prompt)
def extract_text_from_response(response):
    if not response.candidates:
        return ""

    candidate = response.candidates[0]

    if not candidate.content or not candidate.content.parts:
        return ""

    texts = []
    for part in candidate.content.parts:
        if hasattr(part, "text") and part.text:
            texts.append(part.text)

    return "\n".join(texts)

########################################
# 4. LLM CALL (GEMINI EXAMPLE)
########################################

def call_llm(prompt: str) -> dict:
    client = genai.Client(api_key=MODEL_CONFIG["api_key"])

    response = client.models.generate_content(
        model=MODEL_CONFIG["model_name"],   # already "gemini-2.0-flash"
        contents=prompt
    )

    text = response.text or ""

    input_tokens = estimate_tokens(prompt)
    output_tokens = estimate_tokens(text)

    if not text.strip():
        print("⚠️ Empty Gemini response")

    return {
        "text": text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens
    }
        



def clean_llm_json(text: str) -> str:
    if not text:
        return ""

    text = text.strip()

    # Remove markdown code fences if present
    if text.startswith("```"):
        text = text.split("```", 1)[1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]

    text = text.strip()

    # Remove leading 'json' label if present
    if text.lower().startswith("json"):
        text = text[4:].strip()

    return text

def normalize_entity_name(name: str) -> str:
    """
    Normalize entity names for duplicate detection.
    - Lowercase
    - Remove punctuation
    - Remove extra spaces
    """
    name = name.lower()
    name = re.sub(r"[^\w\s]", "", name)  # remove punctuation
    name = re.sub(r"\s+", " ", name)     # normalize spaces
    return name.strip()


def deduplicate_entities(entity_list: list[str]) -> list[str]:
    """
    Remove duplicate entities (case and punctuation insensitive).
    Keeps first clean occurrence.
    """
    seen = set()
    result = []

    for entity in entity_list:
        normalized = normalize_entity_name(entity)

        if normalized not in seen:
            seen.add(normalized)
            result.append(entity)

    return result

def normalize_date_to_mmddyyyy(date_str: str) -> str:
    if not date_str or date_str == "NOT SPECIFIED":
        return date_str

    date_str = date_str.strip()

    # 🔥 Remove trailing punctuation
    date_str = re.sub(r"[.,]$", "", date_str)

    # 🔥 Remove ordinal suffix (1st, 2nd, 3rd, 4th)
    date_str = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str)

    date_formats = [
        "%B %d, %Y",    # November 26, 2024
        "%B %d %Y",     # November 26 2024
        "%b %d, %Y",    # Nov 26, 2024
        "%b %d %Y",     # Nov 26 2024
        "%d %B %Y",     # 26 November 2024
        "%Y-%m-%d",
        "%m/%d/%Y"
    ]

    for fmt in date_formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%m/%d/%Y")
        except ValueError:
            continue

    return date_str


########################################
# 5. MULTI-FILE PROCESSOR
########################################


def clean_text(text: Any) -> str:
    if not isinstance(text, str):
        text = str(text)

    text = re.sub(r"[^\w\s]", "", text.lower())
    return re.sub(r"\s+", " ", text).strip()
def map_llm_output_to_metadata(
    llm_output: Dict[str, Any],
    metadata_blocks: List[Dict[str, Any]],
    threshold: int = 80
) -> Dict[str, Any]:

    mapped_output = {}

    # ----------------------------
    # Text cleaner
    # ----------------------------
    def clean_text(text: str):
        text = text.lower()
        text = re.sub(r"[^\w\s]", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    # ----------------------------
    # Pre-clean metadata once
    # ----------------------------
    for block in metadata_blocks:
        block["__clean_text"] = clean_text(block.get("text", ""))

    # ----------------------------
    # Main loop
    # ----------------------------
    for key, values in llm_output.items():

        if not isinstance(values, list):
            values = [values]

        mapped_output[key] = []

        for item in values:

            if isinstance(item, dict):
                value = item.get("value")
                reference_text = item.get("reference_text")
            else:
                value = item
                reference_text = None

            if value in (None, "", "NOT SPECIFIED"):
                continue

            value_clean = clean_text(str(value))
            ref_clean = clean_text(reference_text) if reference_text else None

            best_match = None
            best_score = 0

            # =====================================================
            # 🔥 STRICT REFERENCE-DRIVEN MATCHING
            # =====================================================
            if ref_clean:

                window_size = 5
                num_blocks = len(metadata_blocks)

                for i in range(num_blocks):

                    page = metadata_blocks[i].get("page")
                    merged_text = ""

                    # Merge consecutive blocks on same page
                    for j in range(i, min(i + window_size, num_blocks)):

                        if metadata_blocks[j].get("page") != page:
                            break

                        merged_text += " " + metadata_blocks[j]["__clean_text"]

                    score = max(
                        fuzz.partial_ratio(ref_clean, merged_text),
                        fuzz.token_set_ratio(ref_clean, merged_text)
                    )

                    if score > best_score:
                        best_score = score

                        # Anchor to block that contains actual value
                        anchor_block = None
                        for j in range(i, min(i + window_size, num_blocks)):
                            if metadata_blocks[j].get("page") != page:
                                break
                            if value_clean in metadata_blocks[j]["__clean_text"]:
                                anchor_block = metadata_blocks[j]
                                break

                        best_match = anchor_block if anchor_block else metadata_blocks[i]

                # Attach result based ONLY on reference match
                if best_match and best_score >= threshold:
                    mapped_output[key].append({
                        "value": value,
                        "page": best_match.get("page"),
                        "block_id": best_match.get("block_id"),
                        "bbox": best_match.get("bbox"),
                        "page_width": best_match.get("page_width"),
                        "page_height": best_match.get("page_height")
                    })
                else:
                    mapped_output[key].append({
                        "value": value,
                        "page": None,
                        "block_id": None,
                        "bbox": None,
                        "page_width": None,
                        "page_height": None
                    })

                continue  # 🚫 DO NOT FALL BACK TO VALUE MATCHING

            # =====================================================
            # 🟢 VALUE MATCHING (ONLY IF NO REFERENCE PROVIDED)
            # =====================================================
            for block in metadata_blocks:
                if value_clean in block["__clean_text"]:
                    best_match = block
                    break

            if best_match:
                mapped_output[key].append({
                    "value": value,
                    "page": best_match.get("page"),
                    "block_id": best_match.get("block_id"),
                    "bbox": best_match.get("bbox"),
                    "page_width": best_match.get("page_width"),
                    "page_height": best_match.get("page_height")
                })
            else:
                mapped_output[key].append({
                    "value": value,
                    "page": None,
                    "block_id": None,
                    "bbox": None,
                    "page_width": None,
                    "page_height": None
                })

    return mapped_output


def load_metadata_blocks(json_path: Path) -> List[Dict[str, Any]]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    blocks = []

    def extract_paragraphs(section_key, paragraph_key):
        section = data.get(section_key, {})
        paragraphs = section.get(paragraph_key, [])

        for para in paragraphs:
            text = para.get("text")
            if not text:
                continue

            blocks.append({
                "text": text,
                "page": para.get("page"),
                "block_id": para.get("block_id"),
                "paragraph_index": para.get("paragraph_index"),
                "bbox": para.get("bbox"),
                "page_width": para.get("page_width"),     # ✅ ADDED
                "page_height": para.get("page_height")    # ✅ ADDED
            })

    # 1️⃣ BEFORE TOC
    extract_paragraphs("before_toc", "paragraphs_before_toc")

    # 2️⃣ AFTER TOC
    extract_paragraphs("after_toc", "paragraphs_after_toc")

    # 3️⃣ DEFINED TERMS
    defined_terms_section = data.get("defined_terms", {})
    terms_list = defined_terms_section.get("terms", [])

    for entry in terms_list:
        definition = entry.get("definition", "")

        for sub in entry.get("sub_paragraphs", []):
            text = sub.get("text")

            combined_text = f"{entry.get('term', '')} {definition}"

            blocks.append({
                "text": combined_text if definition else text,
                "page": sub.get("page"),
                "block_id": sub.get("block_id"),
                "paragraph_index": sub.get("paragraph_index"),
                "bbox": sub.get("bbox"),
                "page_width": sub.get("page_width"),     # ✅ ADDED
                "page_height": sub.get("page_height")    # ✅ ADDED
            })

    return blocks





def process_documents_in_folder(
    folder_path: Path,
    rules_json: Dict[str, Any],
    run_config: Dict[str, Any],
    output_dir: Path
):
    if not folder_path.exists():
        raise FileNotFoundError(
            f"Input folder does not exist: {folder_path.resolve()}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    for file in folder_path.iterdir():
        if file.suffix.lower() != ".txt":
            continue

        file_start_time = time.perf_counter()

        print(f"\nProcessing: {file.name}")

        document_text = file.read_text(encoding="utf-8")

        # ------------------------------------------------
        # STEP 1 — BUILD PROMPT
        # ------------------------------------------------
        prompt = build_llm_prompt(
            rules_json=rules_json,
            run_config=run_config,
            document_text=document_text
        )

        # ------------------------------------------------
        # STEP 1B — LLM CALL (TIMED)
        # ------------------------------------------------
        llm_start = time.perf_counter()

        llm_result = call_llm(prompt)

        raw_response_text = clean_llm_json(llm_result["text"])

        input_tokens = llm_result["input_tokens"]
        output_tokens = llm_result["output_tokens"]
        total_tokens = llm_result["total_tokens"]

        llm_end = time.perf_counter()
        print(f"🤖 LLM execution time: {llm_end - llm_start:.3f} sec")

        print("\n===== RAW LLM OUTPUT =====")
        print(raw_response_text)
        print("==========================\n")

        try:
            raw_llm_output = json.loads(raw_response_text)
        except json.JSONDecodeError:
            print("❌ Invalid JSON returned from LLM")
            continue

        # ------------------------------------------------
        # STEP 2 — METADATA MAPPING (TIMED)
        # ------------------------------------------------
        metadata_start = time.perf_counter()

        pdf_id = extract_first_3_digits(file.name)

        metadata_json_path = next(
            (
                j for j in METADATA_DIR.glob("*.json")
                if extract_first_3_digits(j.name) == pdf_id
            ),
            None
        )

        print("Metadata file found:", metadata_json_path)

        if metadata_json_path:
            metadata_blocks = load_metadata_blocks(metadata_json_path)
            print("Blocks loaded:", len(metadata_blocks))

            mapped_output = map_llm_output_to_metadata(
                llm_output=raw_llm_output,
                metadata_blocks=metadata_blocks
            )
        else:
            print("⚠️ No metadata JSON found")
            mapped_output = {}

        metadata_end = time.perf_counter()
        print(f"📌 Metadata mapping time: {metadata_end - metadata_start:.3f} sec")

        # ------------------------------------------------
        # STEP 3 — POST PROCESSING (TIMED)
        # ------------------------------------------------
        post_start = time.perf_counter()

        final_data = {}

        normalized_data_keys = {
            normalize_key(k): k for k in raw_llm_output.keys()
        }

        for key in run_config["keywords_to_extract"]:
            normalized_key = normalize_key(key)

            if normalized_key in normalized_data_keys:
                original_key = normalized_data_keys[normalized_key]
                value = raw_llm_output[original_key]

                if isinstance(value, dict) and "value" in value:
                    extracted_value = value.get("value")

                    if key == "MostRecentDocDate":
                        final_data[key] = extracted_value if extracted_value else "NOT SPECIFIED"
                    else:
                        final_data[key] = extracted_value

                    continue

                if isinstance(value, list):

                    if value and isinstance(value[0], dict):
                        value_strings = [v.get("value") for v in value]
                    else:
                        value_strings = value

                    if key == "MostRecentDocDate":
                        final_data[key] = value_strings[0] if value_strings else "NOT SPECIFIED"
                    else:
                        final_data[key] = deduplicate_entities(value_strings)

                    continue

            keyword_rule = rules_json["keywords"].get(key, {})
            expected_output = keyword_rule.get("expected_output", {})

            if isinstance(expected_output, dict):
                fallback = expected_output.get("fallback", "NOT SPECIFIED")
            else:
                fallback = "NOT SPECIFIED"

            final_data[key] = fallback

        print("DEBUG BEFORE DATE STEP:", final_data.get("MostRecentDocDate"), type(final_data.get("MostRecentDocDate")))

        for key in final_data:
            if key == "MostRecentDocDate":

                value = final_data[key]

                if isinstance(value, list):
                    value = value[0] if value else "NOT SPECIFIED"

                if isinstance(value, str) and value != "NOT SPECIFIED":
                    final_data[key] = normalize_date_to_mmddyyyy(value)
                else:
                    final_data[key] = "NOT SPECIFIED"

        print("Before saving:", final_data.get("MostRecentDocDate"))

        post_end = time.perf_counter()
        print(f"⚙️ Post-processing time: {post_end - post_start:.3f} sec")

        # ------------------------------------------------
        # FINAL OUTPUT STRUCTURE
        # ------------------------------------------------
        output_payload = {
            "extracted_values": final_data,
            "metadata_mapping": mapped_output,
                "token_usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens}
        }

        output_json = json.dumps(output_payload, indent=2, ensure_ascii=False)

        output_file = output_dir / f"{file.stem}_extracted.json"

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(output_json)

        file_end_time = time.perf_counter()
        print(f"⏱ TOTAL time for {file.name}: {file_end_time - file_start_time:.3f} sec")
        print(f"✅ Output saved to: {output_file}")


########################################
# 6. MAIN
########################################

def load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    rules_path = Path("defination and rules.json")
    config_path = Path("run_config.json")

    input_folder = Path("output_files")  # Output from merge step becomes input for LLM step
    output_folder = Path("outputs")

    rules_json = load_json(rules_path)
    run_config = load_json(config_path)

    # 🔹 STEP 1: build merged TXT files
    build_final_outputs()

    # 🔹 STEP 2: run LLM extraction on merged files
    process_documents_in_folder(
        folder_path=input_folder,
        rules_json=rules_json,
        run_config=run_config,
        output_dir=output_folder
    )



if __name__ == "__main__":
    main()
