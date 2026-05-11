import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from modules.openrouter_client import OpenRouterClient
from modules.utils.cost_tracker import CostTracker
from modules.utils.prompt_helper import PromptHelper
from modules.utils.file_manager import FileManager
from modules.utils.ai_metadata_detector import AIMetadataDetector

class Step3Metadata:
    """Detect or assign metadata (Global, Per-QCM, or Per-Group Cas Clinique) with interactive configuration."""
    
    def __init__(self, cost_tracker: CostTracker, project_context=None):
        self.client = OpenRouterClient()
        self.client.model = None 
        
        self.cost_tracker = cost_tracker
        self.file_manager = FileManager()
        self.prompt_helper = PromptHelper()
        self.context = project_context
        self.ai_detector = AIMetadataDetector(cost_tracker)
        
    def run(self, step2_dir: str = None, step1_dir: str = None,
            auto_mode: bool = False, config: Dict = None,
            global_values: Dict = None, global_pages: List[int] = None) -> Dict:
        """Main execution for Step 3 with User Config or Auto-Mode."""
        print("\n" + "="*60)
        print("STEP 3: METADATA DETECTION (Smart Config)")
        print("="*60)
        
        # 1. Setup Paths
        if self.context:
            target_step2_dir = self.context.get_path("step2_qcm", "accepted")
            target_step1_dir = self.context.get_path("step1_extraction", "accepted")
        else:
            target_step2_dir = step2_dir if step2_dir else "output/step2_qcm/accepted"
            target_step1_dir = step1_dir if step1_dir else "output/step1_extraction/accepted"
            
        if not list(Path(target_step2_dir).glob("*.json")):
            print(f"❌ No extracted QCMs found in {target_step2_dir}. Run Step 2 first.")
            return {}

        # 2. Configure Metadata Strategy
        if auto_mode and config:
            # Normalize config if it's the new nested dict format
            # New format: {"year": {"strategy": "global", "value": "2024"}, ...}
            # Old format: {"Year": "G", ...}
            normalized_config = {}
            fallback_map = {}
            for field, val in config.items():
                # Handle clinical_case specially (maps to internal key "ClinicalCase")
                if field in ("clinical_case", "ClinicalCase"):
                    if isinstance(val, dict):
                        strat = val.get("strategy", "skip")
                        if strat == "per_group":  normalized_config["ClinicalCase"] = "CC"
                        elif strat == "global":   normalized_config["ClinicalCase"] = "G"
                        else:                     normalized_config["ClinicalCase"] = "S"
                    else:
                        normalized_config["ClinicalCase"] = val
                    continue

                field_key = field.capitalize()
                if isinstance(val, dict):
                    strat = val.get("strategy", "S")
                    if strat == "global":     normalized_config[field_key] = "G"
                    elif strat == "per_qcm": normalized_config[field_key] = "P"
                    elif strat == "ai_detect": normalized_config[field_key] = "A"
                    else:                    normalized_config[field_key] = "S"
                    
                    # Store fallback value
                    if "fallback_value" in val and val["fallback_value"] is not None:
                        fallback_map[field_key] = val["fallback_value"]
                        
                    # If global and has hardcoded value, add to global_values
                    if strat == "global" and val.get("value"):
                        if not global_values: global_values = {}
                        global_values[field_key] = val.get("value")
                else:
                    normalized_config[field_key] = val
            
            # Ensure ClinicalCase has a default if not set
            if "ClinicalCase" not in normalized_config:
                normalized_config["ClinicalCase"] = "S"

            config = normalized_config
            print(f"\n⚙️  Using Auto-Mode Config: {config}")
        else:
            # Interactive configuration
            config = self._get_metadata_config()
            fallback_map = {}
            
        print(f"\n⚙️  Strategy: {config}")

        # 3. Handle Global / AI Detect Metadata
        global_vals = {}
        # Merge pre-configured globals first
        if global_values:
            global_vals.update(global_values)
            
        has_auto = "G" in config.values() or "A" in config.values()
        
        if has_auto:
            extracted = self._extract_global_metadata(
                target_step1_dir, config, global_pages
            )
            global_vals.update(extracted)
            
        # Apply fallbacks for Global/AI detects if null or missing
        for field, fallback in fallback_map.items():
            strat = config.get(field, "S")
            if strat in ["G", "A"]:
                if field not in global_vals or global_vals.get(field) is None:
                    print(f"   ⚠️ Falling back to '{fallback}' for Global field {field}")
                    global_vals[field] = fallback

        print("   Global Values set:", global_vals)

        # 4. Process All QCM Files (pass step1_dir for Cas Clinique detection)
        self._process_qcms(target_step2_dir, target_step1_dir, config, global_vals, fallback_map)
        
        return {"config": config, "global_values": global_vals}

    def _get_metadata_config(self) -> Dict[str, str]:
        """Interactive menu: Global (G), Per-QCM (P), Skip (S), Cas Clinique (CC)."""
        fields = ["Year", "Source", "Category", "Subcategory", "ClinicalCase"]
        config = {
            "Year": "P", 
            "Source": "S", 
            "Category": "G", 
            "Subcategory": "S",
            "ClinicalCase": "S",
        }
        
        # Each field has its own toggle cycle
        toggle_cycle = {
            "Year":         ["S", "G", "P"],
            "Source":       ["S", "G", "P"],
            "Category":     ["S", "G", "P"],
            "Subcategory":  ["S", "G", "P"],
            "ClinicalCase": ["S", "CC", "G"],  # CC = Per-Group (detect per page)
        }
        mode_labels = {
            "G":  "Global (one value for all QCMs)",
            "P":  "Per-QCM (detect per question context)",
            "S":  "Skip (not present)",
            "CC": "Per-Group (detect Cas Clinique per page) ← NEW",
        }
        
        while True:
            print("\n📝 METADATA CONFIGURATION:")
            print("Determine how to find each field:")
            for i, f in enumerate(fields, 1):
                raw_mode = config[f]
                mode_str = mode_labels.get(raw_mode, raw_mode)
                print(f"  [{i}] {f:<14}: {mode_str} [{raw_mode}]")
                
            print("\nCommands: [Number] to toggle mode | [Enter] to start processing")
            choice = input("Choice: ").strip()
            
            if not choice:
                return config
            
            if choice.isdigit() and 1 <= int(choice) <= len(fields):
                field = fields[int(choice)-1]
                cycle = toggle_cycle[field]
                current = config[field]
                next_idx = (cycle.index(current) + 1) % len(cycle) if current in cycle else 0
                config[field] = cycle[next_idx]
            else:
                print("Invalid choice.")

    def _extract_global_metadata(self, step1_dir: Path, config: Dict,
                                 pages: List[int] = None) -> Dict:
        """Extract global fields from specified pages or first page."""
        print("\n🔍 Scanning for Global/AI Metadata...")
        txt_files = sorted(Path(step1_dir).glob("*.txt"))
        if not txt_files:
            return {}
        
        if pages:
            print(f"   Extracting from pages: {pages}")
            texts = []
            max_input_chars = int(os.getenv("STEP3_MAX_INPUT_CHARS") or "50000")
            for page_num in pages:
                file_path = Path(step1_dir) / f"page_{page_num}.txt"
                if file_path.exists():
                    with open(file_path, 'r', encoding='utf-8') as f:
                        texts.append(f.read(max_input_chars))
            text = "\n\n".join(texts)
        else:
            print("   Extracting from page 1 (default)")
            max_input_chars = int(os.getenv("STEP3_MAX_INPUT_CHARS") or "50000")
            with open(txt_files[0], 'r', encoding='utf-8') as f:
                text = f.read(max_input_chars)
            
        # Exclude ClinicalCase from standard extraction
        global_fields    = [k for k, v in config.items() if v == "G" and k != "ClinicalCase"]
        ai_detect_fields = [k for k, v in config.items() if v == "A" and k != "ClinicalCase"]
        
        detected = {}
        
        if global_fields:
            detected.update(self._extract_metadata_with_ai(text, global_fields, "Global Document Header"))
            
        if ai_detect_fields:
            print(f"   🤖 Using AI Detector for: {ai_detect_fields}")
            results = self.ai_detector.detect_all_fields(text, ai_detect_fields)
            filtered = self.ai_detector.filter_by_confidence(results)
            detected.update(filtered)
        
        print("\n--- Detected Metadata ---")
        for k, v in config.items():
            if v in ["G", "A"] and k != "ClinicalCase":
                print(f"  {k}: {detected.get(k, 'Not found')}")
        
        return detected

    # ─────────────────────────────────────────────────────────────
    # NEW: Cas Clinique detection
    # ─────────────────────────────────────────────────────────────

    def _detect_clinical_cases(self, page_text: str, qcm_numbers: List[int]) -> List[Dict]:
        """
        Send the raw page text + QCM number list to LLM to detect Cas Clinique blocks.

        HOW IT WORKS:
          The LLM reads the full raw page text (from Step 1) together with the list of
          QCM numbers that are known to exist on that page (from Step 2). It then:
            1. Identifies any "CAS CLINIQUE" (or similar) label + the patient narrative
               paragraph that follows it.
            2. Determines which numbered questions come AFTER that narrative (until the
               next case or end of page) — those are the questions that belong to the case.
          This mirrors how Step 3 already works for Year/Source (reads Step 1 text + calls
          LLM) — the only difference is the output shape (a list instead of a dict) and the
          grouping semantics.

        Returns:
          [{ "label": "CAS CLINIQUE 1", "text": "Patient story...", "qcm_numbers": [1,2,3,4] }]
          Or [] if no clinical case is found on this page.
        """
        if not page_text.strip():
            return []

        nums_str = ", ".join(str(n) for n in qcm_numbers) if qcm_numbers else "(unknown)"

        max_input_chars = int(os.getenv("STEP3_MAX_INPUT_CHARS", "24000"))

        prompt = f"""You are analyzing a French medical exam page to detect clinical case (Cas Clinique) blocks.

TASK: Find any "Cas Clinique" (clinical case) block in the following text.

For EACH clinical case found:
  - Extract its LABEL exactly as written (e.g. "CAS CLINIQUE 1", "Cas clinique N°2")
  - Extract its full NARRATIVE TEXT (the patient story — everything between the label and the first numbered question)
  - Identify which QUESTION NUMBERS from the list below belong to this case
    (questions that appear AFTER the narrative, up to the next case header or end of page)

QCM numbers present on this page: [{nums_str}]

Return ONLY a JSON array in this exact format:
[
  {{
    "label": "CAS CLINIQUE 1",
    "text": "Salma, âgée de 56 ans, traitée depuis 3 ans par Amiodarone...",
    "qcm_numbers": [1, 2, 3, 4]
  }}
]

If NO clinical case is found on this page, return exactly: []

Do NOT include any markdown fences, explanation, or extra text — ONLY the JSON array.

RAW PAGE TEXT:
{page_text[:max_input_chars]}"""

        primary_model = os.getenv("STEP3_MODEL", "qwen/qwen3.6-plus-preview:free")
        fallback_model = os.getenv("STEP3_FALLBACK_MODEL", "google/gemini-2.0-flash-lite-001")
        max_tokens = int(os.getenv("STEP3_MAX_TOKENS") or "10000")
        
        try:
            try:
                resp = self.client.generate_completion(prompt, model=primary_model, max_tokens=max_tokens)
                model_used = primary_model
            except Exception as e:
                print(f"⚠️ Primary model failed for CC detection: {e}")
                print(f"🔄 Retrying with fallback: {fallback_model}...")
                resp = self.client.generate_completion(prompt, model=fallback_model, max_tokens=max_tokens)
                model_used = fallback_model

            content = resp["content"].strip()
            
            # Strip markdown fences
            content = re.sub(r'```(?:json)?\s*', '', content)
            content = re.sub(r'```\s*', '', content).strip()
            
            # Find the JSON array
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                json_str = match.group(0)
                json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)  # Fix trailing commas
                data = json.loads(json_str)
                
                cost = resp.get('cost', 0.0) or self.client.estimate_cost(model_used, resp["usage"])
                self.cost_tracker.log_api_call("step3_cas_clinique", model_used, resp["usage"], cost)
                
                if isinstance(data, list):
                    return data
            else:
                # Empty array as plain text
                if content.strip() in ["[]", "[ ]"]:
                    return []
                print(f"⚠️ No JSON array found in CC detection response.")

        except json.JSONDecodeError as e:
            print(f"⚠️ CC detection JSON decode error: {e}")
        except Exception as e:
            print(f"⚠️ CC detection failed: {e}")
        
        return []

    def _detect_clinical_cases_document(self, full_doc_text: str, qcm_pairs: list) -> list:
        """
        Document-level clinical case detection. Sends ALL page texts in one call.
        
        Unlike _detect_clinical_cases() which returns {label, text, qcm_numbers},
        this method returns {label, text, qcm_pairs} where each pair is {page, number}.
        This allows correct matching even when QCM numbers repeat across exam sections.
        
        Args:
            full_doc_text: Concatenated text of all pages, each preceded by "=== PAGE N ===" header
            qcm_pairs: List of {"page": N, "number": M} for every QCM in the document
        
        Returns:
            [
                {
                    "label": "CAS CLINIQUE 1",
                    "text": "Patient narrative...",
                    "qcm_pairs": [{"page": 6, "number": 1}, {"page": 7, "number": 5}]
                },
                ...
            ]
            Or [] if no clinical case found.
        """
        if not full_doc_text.strip() or not qcm_pairs:
            return []

        # Format the QCM pairs as a readable list for the LLM
        pairs_str = ", ".join(f"(page {p['page']}, Q{p['number']})" for p in qcm_pairs)

        prompt = f"""You are analyzing a French medical exam document to detect clinical case (Cas Clinique) blocks.

The document contains multiple pages marked with "=== PAGE N ===" headers.
Each page may contain patient narratives ("CAS CLINIQUE") followed by numbered questions.

TASK: Find ALL "Cas Clinique" (clinical case) blocks in the document below.

For EACH clinical case found:
  - Extract its LABEL exactly as written (e.g. "CAS CLINIQUE 1", "→ CAS CLINIQUE 2 :")
  - Extract its full NARRATIVE TEXT (the patient story — everything between the label line and the first numbered question)
  - Identify which questions belong to this case. A question belongs to a case if it appears AFTER the case narrative, up to the next "CAS CLINIQUE" header or end of document.
  - For each belonging question, return its PAGE NUMBER (from the === PAGE N === header above it) and its QUESTION NUMBER (the number before the dot, e.g. "22." → 22).

KNOWN QCM (PAGE, NUMBER) PAIRS IN THIS DOCUMENT:
{pairs_str}

IMPORTANT RULES:
- Question numbers can REPEAT across exam sections (e.g., page 1 has Q1 and page 6 also has Q1 from a different year). Always include the page number.
- A question continues to belong to a case even if a page break occurs between the case narrative and the question.
- Do NOT include questions from BEFORE the case narrative in the case's question list.
- If a question appears between two "CAS CLINIQUE" headers, it belongs to the first one.

Return ONLY a JSON array in this exact format:
[
  {{
    "label": "CAS CLINIQUE 1",
    "text": "Patient narrative text here...",
    "qcm_pairs": [
      {{"page": 6, "number": 1}},
      {{"page": 6, "number": 2}},
      {{"page": 7, "number": 5}}
    ]
  }}
]

If NO clinical case is found anywhere in the document, return exactly: []

Do NOT include markdown fences, explanation, or extra text — ONLY the JSON array.

DOCUMENT:
{full_doc_text}"""

        primary_model  = os.getenv("STEP3_MODEL", "qwen/qwen3.6-plus-preview:free")
        fallback_model = os.getenv("STEP3_FALLBACK_MODEL", "google/gemini-2.0-flash-lite-001")
        max_tokens     = int(os.getenv("STEP3_MAX_TOKENS") or "10000")

        try:
            try:
                resp = self.client.generate_completion(prompt, model=primary_model, max_tokens=max_tokens)
                model_used = primary_model
            except Exception as e:
                print(f"⚠️ Primary model failed for document CC detection: {e}")
                print(f"🔄 Retrying with fallback: {fallback_model}...")
                resp = self.client.generate_completion(prompt, model=fallback_model, max_tokens=max_tokens)
                model_used = fallback_model

            content = resp["content"].strip()

            # Strip markdown fences if model adds them
            content = re.sub(r'```(?:json)?\s*', '', content)
            content = re.sub(r'```\s*', '', content).strip()

            # Extract JSON array
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                json_str = match.group(0)
                json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)  # Fix trailing commas
                data = json.loads(json_str)

                cost = resp.get('cost', 0.0) or self.client.estimate_cost(model_used, resp["usage"])
                self.cost_tracker.log_api_call("step3_cas_clinique_doc", model_used, resp["usage"], cost)

                if isinstance(data, list):
                    return data
            else:
                if content.strip() in ["[]", "[ ]"]:
                    return []
                print("⚠️ No JSON array found in document CC detection response.")

        except json.JSONDecodeError as e:
            print(f"⚠️ Document CC detection JSON decode error: {e}")
        except Exception as e:
            print(f"⚠️ Document CC detection failed: {e}")

        return []

    # ─────────────────────────────────────────────────────────────
    # Core processing
    # ─────────────────────────────────────────────────────────────

    def _process_qcms(self, step2_dir: Path, step1_dir: Path,
                      config: Dict, global_values: Dict, fallback_map: Dict = None):
        """Apply global values and detect per-QCM / per-Group values for each batch."""
        qcm_files = sorted(Path(step2_dir).glob("*.json"))
        total = len(qcm_files)
        
        per_qcm_fields = [k for k, v in config.items() if v == "P"]
        cc_strategy    = config.get("ClinicalCase", "S")
        
        if per_qcm_fields:
            print(f"\n🚀 Processing {total} file batches with per-QCM detection...")
        elif cc_strategy in ["CC", "G"]:
            print(f"\n🚀 Processing {total} file batches with Cas Clinique detection [strategy={cc_strategy}]...")
        else:
            print(f"\n🚀 Applying global metadata to {total} file batches (no per-QCM scanning)...")
        
        # ── Global Cas Clinique — detect once from page 1 ─────────────
        global_cas = None
        if cc_strategy == "G":
            txt_files = sorted(Path(step1_dir).glob("*.txt"))
            if txt_files:
                with open(txt_files[0], 'r', encoding='utf-8') as f:
                    global_text = f.read(5000)
                cases = self._detect_clinical_cases(global_text, [])
                if cases:
                    c = cases[0]
                    global_cas = f"{c.get('label', 'CAS CLINIQUE')}\r\n{c.get('text', '')}"
                    print(f"   📋 Global Cas Clinique detected: {c.get('label')}")
        
        cc_carry_over = None  # Carries active CC text from page to page (sequential mode)
        cc_all_qcms   = []    # [(page_num, qcm_num, cas_text)] for end-of-run stats
        
        for i, q_file in enumerate(qcm_files, 1):
            with open(q_file, 'r', encoding='utf-8') as f:
                qcms = json.load(f)
            
            if not qcms:
                continue
            
            # ── Per-QCM metadata detection ─────────────────────────────
            batch_metadata = {}
            if per_qcm_fields:
                combined_text = "\\n".join([q.get('text', '') or q.get('Text', '') for q in qcms])[:2000]
                context = f"Multiple QCMs context:\\n{combined_text}"
                print(f"   Batch {i}/{total}: Detecting {per_qcm_fields}...")
                batch_metadata = self._extract_metadata_with_ai(context, per_qcm_fields, f"QCM Context (File {i})")
            else:
                print(f"   Batch {i}/{total}: Applying metadata...")
            
            # ── Cas Clinique (Per-Group) detection ─────────────────────
            cas_by_number: Dict[int, str] = {}
            if cc_strategy == "CC":
                # Try to derive page number from filename (page_1.json → 1)
                page_num = None
                m = re.search(r'(\d+)', q_file.name)
                if m:
                    page_num = int(m.group(1))

                if page_num is not None:
                    # ── Named page file (page_N.json) — sequential propagation logic ──
                    hints = [q.get("clinical_case_hint") for q in qcms if q.get("clinical_case_hint")]
                    if hints:
                        print(f"   📎 Batch {i}/{total}: Step 2 CC hint present → verifying with LLM...")

                    page_text = ""
                    txt_path = Path(step1_dir) / f"page_{page_num}.txt"
                    if txt_path.exists():
                        with open(txt_path, 'r', encoding='utf-8') as f:
                            page_text = f.read()
                    else:
                        print(f"   ⚠️  No page_{page_num}.txt found. Skipping CC detection for batch {i}.")

                    if page_text:
                        qcm_numbers = [q.get("number") or q.get("Num") for q in qcms]
                        qcm_numbers = [n for n in qcm_numbers if n is not None]
                        print(f"   🔍 Page {page_num}: Detecting CC ({len(qcm_numbers)} QCMs) → LLM call...")
                        llm_results = self._detect_cc_sequential_page(page_text, qcm_numbers)

                        triggers = {num: cas for num, cas in llm_results.items() if cas is not None}
                        if triggers:
                            for num, cas in triggers.items():
                                label     = cas.split("\r\n")[0] if "\r\n" in cas else "CAS CLINIQUE"
                                narrative = cas.split("\r\n", 1)[1] if "\r\n" in cas else cas
                                preview   = narrative[:80] + ("..." if len(narrative) > 80 else "")
                                print(f"      📋 CC triggered at Q{num} ({label}): \"{preview}\"")
                        else:
                            if cc_carry_over:
                                print(f"      ↩️  No new CC on page {page_num} — carry-over active.")
                            else:
                                print(f"      ℹ️  No Cas Clinique on page {page_num}.")

                        qcms, cc_carry_over = self._propagate_cas_clinique(qcms, llm_results, cc_carry_over)

                        if cc_carry_over:
                            carry_label = cc_carry_over.split("\r\n")[0] if "\r\n" in cc_carry_over else "CAS CLINIQUE"
                            print(f"      ↪️  Carry-over to next page: \"{carry_label}\" (active)")

                    else:
                        # No page text found — apply carry-over without LLM call
                        if cc_carry_over:
                            for qcm in qcms:
                                qcm["cas"] = cc_carry_over

                    # Collect stats entries for this page
                    for qcm in qcms:
                        num = qcm.get("number") or qcm.get("Num")
                        cc_all_qcms.append((page_num, num, qcm.get("cas")))

                else:
                    # ── Merged file (all_qcms.json) — sequential page-by-page logic ──
                    # Group QCMs by their page field and sort pages to process in order.
                    # This mirrors the page_N.json path so the same sequential propagation
                    # and carry-over logic applies regardless of how Step 2 named its output.
                    from collections import defaultdict as _dd
                    page_groups: dict = _dd(list)
                    for q in qcms:
                        pg = q.get("page") or q.get("Page")
                        if pg is not None:
                            page_groups[int(pg)].append(q)

                    if not page_groups:
                        print(f"   ⚠️  QCMs in {q_file.name} have no 'page' field. Skipping CC detection.")
                    else:
                        sorted_pages = sorted(page_groups.keys())
                        print(f"   📑 Merged file: {len(sorted_pages)} distinct pages found → \nprocessing sequentially ({sorted_pages[0]}–{sorted_pages[-1]})")

                        for pg_num in sorted_pages:
                            pg_qcms = page_groups[pg_num]
                            pg_txt  = Path(step1_dir) / f"page_{pg_num}.txt"

                            if not pg_txt.exists():
                                print(f"      ⚠️  No page_{pg_num}.txt — applying carry-over only.")
                                if cc_carry_over:
                                    for q in pg_qcms:
                                        q["cas"] = cc_carry_over
                                # Collect for stats
                                for q in pg_qcms:
                                    num = q.get("number") or q.get("Num")
                                    cc_all_qcms.append((pg_num, num, q.get("cas")))
                                continue

                            with open(pg_txt, 'r', encoding='utf-8') as f:
                                pg_text = f.read()

                            qcm_numbers = [q.get("number") or q.get("Num") for q in pg_qcms]
                            qcm_numbers = [n for n in qcm_numbers if n is not None]
                            print(f"      🔍 Page {pg_num}: Detecting CC ({len(qcm_numbers)} QCMs) → LLM call...")

                            llm_results = self._detect_cc_sequential_page(pg_text, qcm_numbers)

                            triggers = {num: cas for num, cas in llm_results.items() if cas is not None}
                            if triggers:
                                for num, cas in triggers.items():
                                    label     = cas.split("\r\n")[0] if "\r\n" in cas else "CAS CLINIQUE"
                                    narrative = cas.split("\r\n", 1)[1] if "\r\n" in cas else cas
                                    preview   = narrative[:80] + ("..." if len(narrative) > 80 else "")
                                    print(f"         📋 CC triggered at Q{num} ({label}): \"{preview}\"")
                            else:
                                if cc_carry_over:
                                    print(f"         ↩️  No new CC on page {pg_num} — carry-over active.")
                                else:
                                    print(f"         ℹ️  No Cas Clinique on page {pg_num}.")

                            pg_qcms, cc_carry_over = self._propagate_cas_clinique(
                                pg_qcms, llm_results, cc_carry_over
                            )

                            if cc_carry_over:
                                carry_label = cc_carry_over.split("\r\n")[0] if "\r\n" in cc_carry_over else "CAS CLINIQUE"
                                print(f"         ↪️  Carry-over to next page: \"{carry_label}\" (active)")

                            # Collect for stats
                            for q in pg_qcms:
                                num = q.get("number") or q.get("Num")
                                cc_all_qcms.append((pg_num, num, q.get("cas")))

            
            # ── Apply all metadata to each QCM ─────────────────────────
            for qcm in qcms:
                # 1. Global values
                if not qcm.get("year")           and "Year" in global_values:     qcm["year"]           = global_values["Year"]
                if not qcm.get("source")          and "Source" in global_values:   qcm["source"]         = global_values["Source"]
                if not qcm.get("module_detected") and "Category" in global_values: qcm["module_detected"]= global_values["Category"]
                if not qcm.get("subcategory")     and "Subcategory" in global_values: qcm["subcategory"] = global_values["Subcategory"]
                
                # 2. Per-QCM (batch level)
                if not qcm.get("year")           and "Year" in batch_metadata:     qcm["year"]           = batch_metadata["Year"]
                if not qcm.get("source")          and "Source" in batch_metadata:   qcm["source"]         = batch_metadata["Source"]
                if not qcm.get("module_detected") and "Category" in batch_metadata: qcm["module_detected"]= batch_metadata["Category"]
                if not qcm.get("subcategory")     and "Subcategory" in batch_metadata: qcm["subcategory"] = batch_metadata["Subcategory"]
                
                # 2.5 Fallbacks for Per-QCM fields still missing
                if fallback_map:
                    if config.get("Year") == "P" and not qcm.get("year") and "Year" in fallback_map:
                        qcm["year"] = fallback_map["Year"]
                    if config.get("Source") == "P" and not qcm.get("source") and "Source" in fallback_map:
                        qcm["source"] = fallback_map["Source"]
                    if config.get("Category") == "P" and not qcm.get("module_detected") and "Category" in fallback_map:
                        qcm["module_detected"] = fallback_map["Category"]
                    if config.get("Subcategory") == "P" and not qcm.get("subcategory") and "Subcategory" in fallback_map:
                        qcm["subcategory"] = fallback_map["Subcategory"]
                
                # 3. Cas Clinique (only for G strategy — CC is handled by propagation above)
                if cc_strategy == "G" and global_cas:
                    if not qcm.get("cas"):
                        qcm["cas"] = global_cas
                
                # 4. Generate Tag
                src = qcm.get("source")
                yr  = qcm.get("year")
                parts = []
                if src: parts.append(str(src))
                if yr:  parts.append(str(yr))
                qcm["tag"] = parts
                
            self._save_results(q_file.name, qcms)

        # ── Print Cas Clinique stats after all pages (sequential mode) ─────────
        if cc_strategy == "CC" and cc_all_qcms:
            self._print_cc_stats(cc_all_qcms)

    # ─────────────────────────────────────────────────────────────
    # NEW: Sequential CC detection + propagation methods
    # ─────────────────────────────────────────────────────────────

    def _detect_cc_sequential_page(self, page_text: str, qcm_numbers: List[int]) -> Dict:
        """
        Per-page LLM call for sequential CC detection.

        Asks the LLM which QCM (if any) is the FIRST question of a new Cas Clinique.
        Only the trigger QCM gets the narrative text — all others return null.
        Python propagation (_propagate_cas_clinique) spreads the text downstream.

        Returns:
            { qcm_number: "LABEL\\r\\nNarrative" }  for trigger QCMs
            { qcm_number: None }                    for all others
        """
        if not page_text.strip() or not qcm_numbers:
            return {}

        nums_str = ", ".join(str(n) for n in qcm_numbers)
        max_input_chars = int(os.getenv("STEP3_MAX_INPUT_CHARS", "24000"))

        prompt = f"""You are analyzing a French medical exam page for Cas Clinique (clinical case) detection.

TASK: For each QCM number listed below, decide if it is the VERY FIRST question of a NEW clinical case narrative introduced on this page.

CRITICAL RULES:
1. Return a JSON array with EXACTLY ONE entry per QCM number listed below — no more, no less.
2. "cas_text" must be non-null ONLY for the very first question of each new clinical case.
3. All other questions of the SAME case → "cas_text": null  (do NOT repeat the narrative)
4. Questions with no clinical case → "cas_text": null
5. "cas_text" must contain ONLY the patient story (everything between the "CAS CLINIQUE" header and the first numbered question). Do NOT include the case title.
6. "cas_label" must be the exact label as written in the text (e.g. "CAS CLINIQUE 1"). Use "CAS CLINIQUE" if no label exists.

EXAMPLE — page has "CAS CLINIQUE 1: Patient X, 45 ans..." then Q5, Q6, Q7, then "CAS CLINIQUE 2: Patient Y, 30 ans..." then Q8, Q9:
[
  {{"number": 5, "cas_label": "CAS CLINIQUE 1", "cas_text": "Patient X, 45 ans..."}},
  {{"number": 6, "cas_label": null, "cas_text": null}},
  {{"number": 7, "cas_label": null, "cas_text": null}},
  {{"number": 8, "cas_label": "CAS CLINIQUE 2", "cas_text": "Patient Y, 30 ans..."}},
  {{"number": 9, "cas_label": null, "cas_text": null}}
]

QCM NUMBERS ON THIS PAGE: [{nums_str}]

Return ONLY a valid JSON array — no markdown fences, no explanation.

PAGE TEXT:
{page_text[:max_input_chars]}"""

        primary_model  = os.getenv("STEP3_MODEL", "qwen/qwen3.6-plus-preview:free")
        fallback_model = os.getenv("STEP3_FALLBACK_MODEL", "google/gemini-2.0-flash-lite-001")
        max_tokens     = int(os.getenv("STEP3_MAX_TOKENS") or "10000")

        try:
            try:
                resp = self.client.generate_completion(prompt, model=primary_model, max_tokens=max_tokens)
                model_used = primary_model
            except Exception as e:
                print(f"⚠️ Primary model failed for CC sequential detection: {e}")
                print(f"🔄 Retrying with fallback: {fallback_model}...")
                resp = self.client.generate_completion(prompt, model=fallback_model, max_tokens=max_tokens)
                model_used = fallback_model

            content = resp["content"].strip()
            content = re.sub(r'```(?:json)?\s*', '', content)
            content = re.sub(r'```\s*', '', content).strip()

            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                json_str = match.group(0)
                json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
                data = json.loads(json_str)

                cost = resp.get('cost', 0.0) or self.client.estimate_cost(model_used, resp["usage"])
                self.cost_tracker.log_api_call("step3_cc_sequential", model_used, resp["usage"], cost)

                if isinstance(data, list):
                    result = {}
                    for entry in data:
                        num       = entry.get("number")
                        cas_text  = entry.get("cas_text")
                        cas_label = entry.get("cas_label") or "CAS CLINIQUE"
                        if num is not None:
                            result[num] = f"{cas_label}\r\n{cas_text}" if cas_text else None
                    return result
            else:
                if content.strip() in ["[]", "[ ]"]:
                    return {n: None for n in qcm_numbers}
                print("⚠️ No JSON array found in CC sequential detection response.")

        except json.JSONDecodeError as e:
            print(f"⚠️ CC sequential detection JSON decode error: {e}")
        except Exception as e:
            print(f"⚠️ CC sequential detection failed: {e}")

        return {}

    def _propagate_cas_clinique(self, qcms: List[Dict],
                                llm_results: Dict,
                                carry_over: Optional[str] = None) -> tuple:
        """
        Deterministic Python propagation of Cas Clinique text.

        Walks QCMs in document order. When a QCM has a non-null LLM result,
        it becomes the new 'current_cas' and is applied to that QCM and all
        subsequent ones until a new trigger is found. The carry_over from the
        previous page is the initial state — enabling seamless cross-page cases.

        Args:
            qcms        : QCM dicts for this page (in Step 2 document order)
            llm_results : { qcm_number: cas_str | None } from _detect_cc_sequential_page()
            carry_over  : Active CC text inherited from the previous page (or None)

        Returns:
            (updated_qcms, new_carry_over)
        """
        current_cas = carry_over

        for qcm in qcms:
            num     = qcm.get("number") or qcm.get("Num")
            llm_cas = llm_results.get(num) if num is not None else None

            if llm_cas is not None:
                current_cas = llm_cas  # New case triggered — update running state

            if current_cas is not None:
                qcm["cas"] = current_cas
            # If current_cas is None → no "cas" key set (clean, no null stored)

        return qcms, current_cas

    def _print_cc_stats(self, cc_all_qcms: List[tuple]) -> None:
        """
        Print a structured Cas Clinique assignment summary after all pages are processed.

        Args:
            cc_all_qcms: [(page_num, qcm_num, cas_text), ...]
                         collected during the page loop (sequential mode only)
        """
        from collections import defaultdict, OrderedDict

        cas_groups    = OrderedDict()      # cas_text -> { page_num: [qcm_nums] }
        no_case_pages = defaultdict(list)  # page_num -> [qcm_nums]

        for page_num, qcm_num, cas in cc_all_qcms:
            if cas:
                if cas not in cas_groups:
                    cas_groups[cas] = defaultdict(list)
                cas_groups[cas][page_num].append(qcm_num)
            else:
                no_case_pages[page_num].append(qcm_num)

        total_linked     = sum(len(nums) for pages in cas_groups.values() for nums in pages.values())
        total_standalone = sum(len(nums) for nums in no_case_pages.values())

        print("\n" + "═" * 60)
        print("📊 CAS CLINIQUE SUMMARY")
        print("═" * 60)

        for idx, (cas_text, pages) in enumerate(cas_groups.items(), 1):
            if "\r\n" in cas_text:
                label, narrative = cas_text.split("\r\n", 1)
            else:
                label, narrative = "CAS CLINIQUE", cas_text

            total_for_case = sum(len(nums) for nums in pages.values())
            preview  = narrative[:80].replace('\n', ' ')
            ellipsis = "..." if len(narrative) > 80 else ""

            print(f"\n  [CAS {idx}] {label}")
            print(f"  ├─ Narrative: \"{preview}{ellipsis}\"")
            print(f"  ├─ Total QCMs linked: {total_for_case}")
            print(f"  └─ Breakdown by page:")
            for pg, nums in sorted(pages.items()):
                nums_str = ", ".join(f"Q{n}" for n in sorted(nums))
                print(f"       Page {pg} → {nums_str}")

        if no_case_pages:
            print(f"\n  [NO CASE] QCMs with no clinical case:")
            for pg, nums in sorted(no_case_pages.items()):
                nums_str = ", ".join(f"Q{n}" for n in sorted(nums))
                print(f"  └─ Page {pg} → {nums_str}")

        print(f"\n  {'─' * 54}")
        print(f"  Total: {len(cas_groups)} clinical case(s) | "
              f"{total_linked} QCMs linked | "
              f"{total_standalone} QCMs standalone")
        print("═" * 60)

    def _extract_metadata_with_ai(self, text: str, fields: List[str], context_desc: str) -> Dict:
        """Generic AI extraction for standard metadata fields."""
        field_list = ", ".join(fields)
        prompt = f"""TASK: Extract specific metadata: {field_list}
CONTEXT: {context_desc}
INPUT TEXT:
{text}

INSTRUCTIONS:
- Return ONLY JSON.
- Keys: {field_list}
- If not found, use null.
"""
        primary_model = os.getenv("STEP3_MODEL", "qwen/qwen3.6-plus-preview:free")
        fallback_model = os.getenv("STEP3_FALLBACK_MODEL", "google/gemini-2.0-flash-lite-001")
        max_tokens = int(os.getenv("STEP3_MAX_TOKENS") or "10000")
        
        try:
            try:
                resp = self.client.generate_completion(prompt, model=primary_model, max_tokens=max_tokens)
                model_used = primary_model
            except Exception as e:
                print(f"⚠️ Primary metadata extraction failed: {e}")
                print(f"🔄 Retrying with fallback: {fallback_model}...")
                resp = self.client.generate_completion(prompt, model=fallback_model, max_tokens=max_tokens)
                model_used = fallback_model

            content = resp["content"]
            
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                json_str = match.group(0)
                json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)  # Trailing commas
                
                try:
                    data = json.loads(json_str)
                    cost = resp.get('cost', 0.0) or self.client.estimate_cost(model_used, resp["usage"])
                    self.cost_tracker.log_api_call("step3_meta", model_used, resp["usage"], cost)
                    return data
                except json.JSONDecodeError:
                    print(f"⚠️ Metadata JSON decode failed. Raw: {json_str[:50]}...")
            else:
                 print("⚠️ No JSON object found in response.")

        except Exception as e:
            print(f"⚠️ Metadata extraction failed: {e}")
            
        return {}

    def _save_results(self, filename: str, data: List[Dict]):
        if self.context:
            path = self.context.get_path("step3_metadata", "accepted") / filename
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        else:
            self.file_manager.save_accepted("step3_metadata", filename, data)
