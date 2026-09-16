import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

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
            global_values: Dict = None, global_pages: List[int] = None,
            cancel_check=None) -> Dict:
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
                # Phase 2 — Subcategory was removed completely. Drop it from
                # any (legacy) payload so it can never re-enter the strategy set.
                if field.lower() == "subcategory":
                    continue

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
        self._process_qcms(target_step2_dir, target_step1_dir, config, global_vals, fallback_map, cancel_check)
        
        return {"config": config, "global_values": global_vals}

    def _get_metadata_config(self) -> Dict[str, str]:
        """Interactive menu: Global (G), Per-QCM (P), Skip (S), Cas Clinique (CC)."""
        fields = ["Year", "Source", "Category", "ClinicalCase"]
        config = {
            "Year": "P",
            "Source": "S",
            "Category": "G",
            "ClinicalCase": "S",
        }

        # Each field has its own toggle cycle
        toggle_cycle = {
            "Year":         ["S", "G", "P"],
            "Source":       ["S", "G", "P"],
            "Category":     ["S", "G", "P"],
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
                      config: Dict, global_values: Dict, fallback_map: Dict = None,
                      cancel_check=None):
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
        cc_boundary_queue = []  # ends_here transitions collected per file (Phase 5 consumer)
        
        for i, q_file in enumerate(qcm_files, 1):
            if cancel_check and cancel_check():
                print(f"\n⏸ Stop requested before metadata batch {i}/{total} — "
                      f"already-processed batches are saved.")
                break
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
                from modules.utils.call_logger import item_scope
                with item_scope(f"batch_{i}/{total} ({q_file.name})"):
                    batch_metadata = self._extract_metadata_with_ai(context, per_qcm_fields, f"QCM Context (File {i})")
            else:
                print(f"   Batch {i}/{total}: Applying metadata...")
            
            # ── Cas Clinique detection (per_group CC) or hygiene-only skip ──
            # Phase 6: strategy "S" reuses the SAME per-page detection call,
            # but propagation/linkage is disabled (text hygiene without
            # linkage). Strategy "G" (global) is untouched by the redesign.
            cas_by_number: Dict[int, str] = {}
            if cc_strategy in ("CC", "S"):
                linkage_on = (cc_strategy == "CC")
                # Try to derive page number from filename (page_1.json → 1)
                page_num = None
                m = re.search(r'(\d+)', q_file.name)
                if m:
                    page_num = int(m.group(1))

                page_carry = cc_carry_over if linkage_on else None
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
                        from modules.utils.call_logger import item_scope as _is2
                        with _is2(f"page_{page_num}"):
                            cc_map = self._detect_cc_sequential_page(page_text, qcm_numbers, carry_over=page_carry)

                        triggers = {num: info for num, info in cc_map.items()
                                    if info.get("status") == "new_case"}
                        if triggers:
                            for num, info in triggers.items():
                                label     = info.get("label") or "CAS CLINIQUE"
                                narrative = info.get("text") or ""
                                preview   = narrative[:80] + ("..." if len(narrative) > 80 else "")
                                print(f"      📋 CC triggered at Q{num} ({label}): \"{preview}\"")
                        else:
                            if cc_carry_over:
                                print(f"      ↩️  No new CC on page {page_num} — carry-over active.")
                            else:
                                print(f"      ℹ️  No Cas Clinique on page {page_num}.")

                        qcms, cc_carry_over, _notes, _bq = self._propagate_cas_clinique(
                            qcms, cc_map, page_carry, linkage=linkage_on
                        )
                        if linkage_on:
                            cc_boundary_queue.extend(_bq)

                        if cc_carry_over:
                            carry_label = cc_carry_over.split("\r\n")[0] if "\r\n" in cc_carry_over else "CAS CLINIQUE"
                            print(f"      ↪️  Carry-over to next page: \"{carry_label}\" (active)")

                    else:
                        # No page text found — apply carry-over without LLM call
                        # (linkage only; under skip nothing carries anyway)
                        if cc_carry_over and linkage_on:
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
                            if cancel_check and cancel_check():
                                print(f"\n⏸ Stop requested before CC page {pg_num} "
                                      f"— already-processed pages are saved.")
                                break
                            pg_qcms = page_groups[pg_num]
                            pg_txt  = Path(step1_dir) / f"page_{pg_num}.txt"

                            if not pg_txt.exists():
                                print(f"      ⚠️  No page_{pg_num}.txt — applying carry-over only.")
                                if cc_carry_over and linkage_on:
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

                            from modules.utils.call_logger import item_scope as _is3
                            with _is3(f"page_{pg_num}"):
                                cc_map = self._detect_cc_sequential_page(pg_text, qcm_numbers, carry_over=page_carry)

                            triggers = {num: info for num, info in cc_map.items()
                                        if info.get("status") == "new_case"}
                            if triggers:
                                for num, info in triggers.items():
                                    label     = info.get("label") or "CAS CLINIQUE"
                                    narrative = info.get("text") or ""
                                    preview   = narrative[:80] + ("..." if len(narrative) > 80 else "")
                                    print(f"         📋 CC triggered at Q{num} ({label}): \"{preview}\"")
                            else:
                                if cc_carry_over and linkage_on:
                                    print(f"         ↩️  No new CC on page {pg_num} — carry-over active.")
                                else:
                                    print(f"         ℹ️  No Cas Clinique on page {pg_num}.")

                            pg_qcms, cc_carry_over, _notes, _bq = self._propagate_cas_clinique(
                                pg_qcms, cc_map, page_carry, linkage=linkage_on
                            )
                            if linkage_on:
                                cc_boundary_queue.extend(_bq)

                            if cc_carry_over and linkage_on:
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

                # 2. Per-QCM (batch level)
                if not qcm.get("year")           and "Year" in batch_metadata:     qcm["year"]           = batch_metadata["Year"]
                if not qcm.get("source")          and "Source" in batch_metadata:   qcm["source"]         = batch_metadata["Source"]
                if not qcm.get("module_detected") and "Category" in batch_metadata: qcm["module_detected"]= batch_metadata["Category"]

                # 2.5 Fallbacks for Per-QCM fields still missing
                if fallback_map:
                    if config.get("Year") == "P" and not qcm.get("year") and "Year" in fallback_map:
                        qcm["year"] = fallback_map["Year"]
                    if config.get("Source") == "P" and not qcm.get("source") and "Source" in fallback_map:
                        qcm["source"] = fallback_map["Source"]
                    if config.get("Category") == "P" and not qcm.get("module_detected") and "Category" in fallback_map:
                        qcm["module_detected"] = fallback_map["Category"]
                
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

        # Phase 2 boundary-transition stash: Phase 5's bounded boundary check
        # (run_boundary_checks) is the designated consumer. Phase 5: the
        # queue is persisted for that consumer (no longer inert in-memory only).
        # Phase 6: under skip, linkage is off — no transitions ever queue.
        self._cc_boundary_pending_queue = list(cc_boundary_queue)
        if cc_boundary_queue and cc_strategy == "CC":
            self._save_boundary_transitions(list(cc_boundary_queue))
        if cc_boundary_queue:
            print(f"[CC-STATE] {len(cc_boundary_queue)} ends_here transition(s) "
                  f"queued for the boundary check")

    def _save_boundary_transitions(self, transitions: List[Dict]) -> None:
        """Phase 5: persist the ends_here transition queue for
        run_boundary_checks. Written to the step3_metadata folder ROOT (NOT
        accepted/, which downstream glob-reads as QCM lists). Replaces the
        file each run — every fired Step 3 enqueue is fresh."""
        payload = {"transitions": transitions or []}
        try:
            if self.context:
                d = self.context.get_path("step3_metadata")
            else:
                d = Path("output/step3_metadata")
            d.mkdir(parents=True, exist_ok=True)
            with open(d / "cc_boundary_transitions.json", "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[CC-STATE] ⚠️ could not save boundary transitions: {e}")

    # ─────────────────────────────────────────────────────────────
    # NEW: Sequential CC detection + propagation methods
    # ─────────────────────────────────────────────────────────────

    # Valid 5-status enum for the Phase 1 state-aware classifier
    _CC_STATUSES = ("new_case", "continues", "ends_here", "unrelated", "uncertain")

    def _parse_cc_statuses(self, content: str, qcm_numbers: List[int]) -> Dict[int, Dict]:
        """Parse the 5-status classifier response into
        {qcm_number: {"status": ..., "label": ..., "text": ...}}.

        Robustness contract:
        - Status strings outside the enum are coerced to "uncertain".
        - A listed number with NO entry in the response defaults to "uncertain"
          (never silently dropped).
        - An entry with no explicit "status" infers one: cas_text non-null
          → "new_case", else "uncertain" (keeps simple responses parseable).
        - A response that parses to an EMPTY array → {} (no entries at all).
        """
        cleaned = re.sub(r'```(?:json)?\s*', '', content or '')
        cleaned = re.sub(r'```\s*', '', cleaned).strip()
        match = re.search(r'\[.*\]', cleaned, re.DOTALL)
        if not match:
            return None
        json_str = re.sub(r',(\s*[}\]])', r'\1', match.group(0))
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, list):
            return None
        if not data:
            return {}
        result: Dict[int, Dict] = {}
        for entry in data:
            if not isinstance(entry, dict):
                continue
            num = entry.get("number")
            if num is None:
                continue
            status = entry.get("status")
            if isinstance(status, str):
                status = status.strip().lower()
            if status not in self._CC_STATUSES:
                cas_text = entry.get("cas_text")
                status = "new_case" if cas_text else "uncertain"
            label = entry.get("cas_label") or "CAS CLINIQUE"
            text = entry.get("cas_text")
            result[num] = {"status": status, "label": label, "text": text}
        for n in qcm_numbers:
            if n not in result:
                result[n] = {"status": "uncertain", "label": None, "text": None}
        return result

    def _detect_cc_sequential_page(self, page_text: str, qcm_numbers: List[int],
                                   carry_over: Optional[str] = None) -> Dict:
        """
        Per-page LLM call for state-aware CC detection (Phase 2 contract).

        State-aware classifier: for each QCM number it picks exactly ONE of:
          new_case  — first question of a fresh narrative on THIS page (+ label/text)
          continues — explicitly depends on the currently active (carried-over) case
          ends_here — the active case does NOT cover this QCM (explicit termination)
          unrelated — no case applies, and none was running
          uncertain — ambiguous, defer to the checker (same as today's fallback)

        Narratives in this corpus usually have NO "CAS CLINIQUE" header, so the
        classifier anchors on patient-specific content vs question-stem language,
        including narratives FUSED into the QCM's own text block.

        Returns (Phase 2 contrat — the raw status map):
            { qcm_number: {"status", "label", "text"} }
            An EMPTY map ({}) means the call produced no usable page decision
            (failure/garbage/empty response) — the Python state machine then
            treats every listed number as "uncertain" (legacy-propagate).
        """
        if not page_text.strip() or not qcm_numbers:
            return {}

        nums_str = ", ".join(str(n) for n in qcm_numbers)
        max_input_chars = int(os.getenv("STEP3_MAX_INPUT_CHARS", "24000"))

        if carry_over:
            co = carry_over
            if "\r\n" in co:
                co_label, co_narrative = co.split("\r\n", 1)
            elif "\n" in co:
                co_label, co_narrative = co.split("\n", 1)
            else:
                co_label, co_narrative = "CAS CLINIQUE", co
            co_preview = co_narrative[:1500]
            carry_block = f"""
CURRENTLY ACTIVE CASE (carried over from an earlier page — running now):
- Label: {co_label}
- Narrative (may be truncated): {co_preview}
Questions on THIS page may belong to THAT case ("continues") or the case may
end before them ("ends_here") — judge each number individually.
"""
        else:
            carry_block = """
CURRENTLY ACTIVE CASE (carried over from an earlier page): NONE.
A new narrative may START on this page ("new_case") — none is running already.
"""

        prompt = f"""You are analyzing a French medical exam page for Cas Clinique (clinical case) detection.
{carry_block}
TASK: For EACH QCM number listed below, output exactly ONE status:
- "new_case"   : this question is the FIRST question of a NEW clinical case narrative appearing on this page. Fill "cas_label" (exact label as written, or "CAS CLINIQUE" if none exists) and "cas_text" (the patient story ONLY — everything between the case header/start and the first numbered question; do NOT include the title or the questions).
- "continues"  : a case is already running (see CURRENTLY ACTIVE CASE), this question belongs to it, and NO new case starts here.
- "ends_here"  : a case WAS running, but the active case does NOT inform this question. No new case starts.
- "unrelated"  : no clinical case applies, and none is running.
- "uncertain"  : genuinely ambiguous — you cannot decide confidently.

FUSED-NARRATIVE RULE (critical): in this corpus a patient narrative often has NO
"CAS CLINIQUE" header, and it may even be FUSED directly into what looks like a
single question block with no separator. Even when patient-specific content
(age, presenting complaint, history, exam or lab findings, started treatment)
precedes the actual interrogative/imperative sentence inside one question block,
classify that block "new_case" (derive the label as "CAS CLINIQUE"). A patient
narrative is NEVER background for the question — extract it, never fold it in.
Anchor on third-person descriptive patient content, NOT on imperative or
interrogative stems like "Quelle est votre conduite...", "Parmi les
propositions suivantes..." or "Conduite face a...".

CRITICAL RULES:
1. Return a JSON array with EXACTLY ONE entry per QCM number listed below — no more, no less.
2. Questions of the SAME case after its first one → "continues" (or "ends_here"); do NOT repeat the narrative in them.
3. "cas_text" is required ONLY for "new_case"; all other statuses use null.
4. Do NOT include the case title inside "cas_text".

ANSWER FORMAT (JSON array):
[
  {{"number": 5, "status": "new_case", "cas_label": "CAS CLINIQUE 1", "cas_text": "Patient X, 45 ans..."}},
  {{"number": 6, "status": "continues", "cas_label": null, "cas_text": null}},
  {{"number": 7, "status": "ends_here", "cas_label": null, "cas_text": null}},
  {{"number": 8, "status": "unrelated", "cas_label": null, "cas_text": null}}
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

            status_map = self._parse_cc_statuses(content, qcm_numbers)
            if status_map is not None:
                cost = resp.get('cost', 0.0) or self.client.estimate_cost(model_used, resp["usage"])
                self.cost_tracker.log_api_call("step3_cc_sequential", model_used, resp["usage"], cost)
                # Phase 2: return the raw 5-status map. An empty array
                # response also yields {} — downstream propagation then
                # treats every listed number as "uncertain"
                # (legacy-propagate), never as a hard negative.
                return status_map

            print("⚠️ No JSON array found in CC sequential detection response.")

        except json.JSONDecodeError as e:
            print(f"⚠️ CC sequential detection JSON decode error: {e}")
        except Exception as e:
            print(f"⚠️ CC sequential detection failed: {e}")

        return {}

    def _normalize_cc_info(self, info) -> Dict:
        """Normalize one per-QCM detection payload into a status dict.
        Accepts the current 5-status dict shape and, for robustness, the
        legacy string shape ("LABEL\\r\\nNarrative" implied a new_case)."""
        if not info:
            return {"status": "uncertain", "label": None, "text": None}
        if isinstance(info, str):
            if "\r\n" in info:
                label, text = info.split("\r\n", 1)
            elif "\n" in info:
                label, text = info.split("\n", 1)
            else:
                label, text = "CAS CLINIQUE", info
            return {"status": "new_case",
                    "label": label or "CAS CLINIQUE", "text": text}
        return info

    def _propagate_cas_clinique(self, qcms: List[Dict],
                                cc_map: Dict,
                                carry_over: Optional[str] = None,
                                linkage: bool = True) -> tuple:
        """Phase 2 — status-driven propagation state machine (pure Python).

        Consumes the 5-status detector map {qcm_number: {"status", "label",
        "text"}} per page and replaces the legacy blind forward-propagation:

          new_case  -> current case replaced by the fresh narrative; attached
                       here and downstream until the next change.
          continues -> the active (carried-over) case EXPLICITLY confirmed;
                       attached. If nothing is running this degrades to a
                       no-op (cannot confirm a case that does not exist).
          ends_here -> the case CLOSES: no attach here or downstream until
                       the next new_case. The immediate boundary is queued
                       for the Phase 5 bounded boundary check (one call per
                       transition, fired only when a case actually ended).
                       Outcomes land in "case_belonging_check" later via
                       _process_qcms; the queue itself stays inert in this
                       module (auditable, no side effects beyond the note).
          unrelated -> no linkage at all; NO case_belonging_check entry.
          uncertain -> legacy safety valve: persist the running case if any
                       (today's blind-propagate behavior), and record an
                       audit note; a technical failure or an individual
                       uncertain can NEVER clear a case.

        Also attaches per-QCM "case_belonging_check" notes directly (only for
        real linkage decisions — new_case/continues/ends_here/uncertain;
        unrelated is deliberately unnoted, per the population rule).

        Returns:
            (updated_qcms, new_carry_over, check_notes, boundary_queue)
            boundary_queue: [{case_cas, trigger_page/number/uid}] — inert
            until Phase 5 (run_boundary_checks).
        """
        current_cas = carry_over if linkage else None
        check_notes: Dict[Any, str] = {}
        boundary_queue: List[Dict] = []

        for qcm in qcms:
            num   = qcm.get("number") or qcm.get("Num")
            info  = self._normalize_cc_info(cc_map.get(num) if num is not None else None)
            st    = info.get("status") or "uncertain"

            if not linkage:
                # Phase 6 — skip strategy: hygiene WITHOUT linkage.
                # Text hygiene only: a detected narrative is applied to the
                # QCM(s) it is directly attached to (fused/triggered QCM),
                # NEVER carried forward — no chains, no "continues" linkage,
                # NO case_belonging_check entries (they are reserved for
                # actual linkage decisions, and none are made under skip).
                # The CC Checker / boundary check must not run under skip.
                if st == "new_case" and info.get("text"):
                    qcm["cas"] = (f"{info.get('label') or 'CAS CLINIQUE'}"
                                  f"\r\n{info['text']}")
                continue

            if st == "new_case" and info.get("text"):
                current_cas = f"{info.get('label') or 'CAS CLINIQUE'}\r\n{info['text']}"
                qcm["cas"] = current_cas
                note = f"new_case: {info.get('label') or 'CAS CLINIQUE'} starts this case"
            elif st == "continues" and current_cas is not None:
                qcm["cas"] = current_cas
                note = "continues: detector confirmed the carried-over case"
            elif st == "ends_here" and current_cas is not None:
                boundary_queue.append({
                    "case_cas": current_cas,
                    "trigger_page": qcm.get("page"),
                    "trigger_number": num,
                    "trigger_uid": qcm.get("uid"),
                })
                current_cas = None
                note = "ends_here: case does not inform this question"
            elif st == "uncertain":
                if current_cas is not None:
                    qcm["cas"] = current_cas
                note = ("uncertain: ambiguous — legacy propagation kept"
                        + (" (attached)" if qcm.get("cas") else " (nothing running)"))
            else:
                note = None  # unrelated (or continues/ends_here with no case running)

            if note and note != "unrelated":
                qcm["case_belonging_check"] = note
                check_notes[num] = note

        return qcms, current_cas, check_notes, boundary_queue

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
        """Generic AI extraction for standard metadata fields.

        Taxonomy-enriched: the Algerian medical exam taxonomy (faculties +
        modules-by-level + rules) is injected into the prompt, and the LLM's
        free-text answer is validated/canonicalized by the Python helpers in
        modules.utils.metadata_context. The LLM is the recommender; Python is
        the validator — hallucinations outside the closed list are rejected to None.
        """
        from modules.utils.metadata_context import (
            build_context_block, normalize_module, normalize_year,
            normalize_faculty, find_faculty_in_text, derive_source,
        )

        field_list = ", ".join(fields)
        taxonomy_block = build_context_block()
        prompt = f"""TASK: Extract specific metadata: {field_list}
CONTEXT: {context_desc}

{taxonomy_block}

INPUT TEXT:
{text}

INSTRUCTIONS:
- Return ONLY JSON. Keys: {field_list}, "faculty"
- "Category": the canonical module name from VALID MODULES BY LEVEL (exactly as written). null if unknown.
- "Year": the START year of any "YYYY/YYYY" pair (e.g. "2025/2026" -> "2025"). Plain 4-digit year stays as-is.
- "Source": derive per RULES — "Externat {{faculty}}" if Category matched, else "Residanat {{faculty}}". null if faculty unknown.
- "faculty": the matched faculty from VALID FACULTIES (intermediate field, used to derive Source).
If a field is not found or ambiguous, use null.
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

                    # Post-process: validate / canonicalize against the taxonomy.
                    # Accept both capitalized (LLM-returned-per-prompt) and lowercase keys.
                    raw_cat = data.get("Category") or data.get("category")
                    data["Category"] = normalize_module(raw_cat) if raw_cat else None

                    raw_yr = data.get("Year") or data.get("year")
                    data["Year"] = normalize_year(raw_yr) if raw_yr else None

                    # Faculty: prefer the LLM's answer; fall back to a text scan.
                    raw_fac = data.get("faculty") or find_faculty_in_text(text)
                    faculty = normalize_faculty(raw_fac) if raw_fac else None
                    data["Source"] = derive_source(data.get("Category"), faculty)

                    # Drop the intermediate "faculty" key so it doesn't leak as a QCM field.
                    data.pop("faculty", None)

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
