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
        # Step-2 sidecar files share this folder but hold non-QCM payloads —
        # they are consumed elsewhere (Step 6 / boundary check) and must never
        # enter the per-batch propagation loop (moot bug: iterating their dict
        # root yields string keys and `q.get("page")` crashed the cascade).
        qcm_files = sorted(f for f in Path(step2_dir).glob("*.json")
                           if f.name not in self._STEP2_SIDECAR_FILES)
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
        # H-fix — cross-page pending candidate state (distinct from
        # carry_over: carry_over = an already-ATTACHED running case;
        # pending_case = a trailing narrative detected on a page holding
        # ZERO QCMs, waiting for its FIRST QCM-bearing page to claim it).
        cc_pending_case = None   # {"label": str, "text": str, "page": int} | None
        
        for i, q_file in enumerate(qcm_files, 1):
            if cancel_check and cancel_check():
                print(f"\n⏸ Stop requested before metadata batch {i}/{total} — "
                      f"already-processed batches are saved.")
                break
            with open(q_file, 'r', encoding='utf-8') as f:
                qcms = json.load(f)

            if not qcms:
                continue

            # Defense-in-depth: a batch file must hold a non-empty list of
            # QCM dicts. Any other payload (dict root, stray markdown, etc.)
            # is skipped with a visible warn instead of crashing the cascade.
            if not isinstance(qcms, list) or not all(isinstance(q, dict) for q in qcms):
                print(f"   ⚠️  Skipping {q_file.name}: not a QCM list "
                      f"(unexpected payload shape) — Step 6 / audits unaffected.")
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
                            cc_map = self._detect_cc_sequential_page(
                                page_text, qcm_numbers, carry_over=page_carry,
                                pending_case=cc_pending_case)
                        trailing = cc_map.pop("_trailing", None)

                        # H-fix — resolve the pending candidate at the FIRST
                        # QCM-bearing page (one attempt; never retried forward).
                        cc_map, claim_num, decline_num = self._apply_pending_case_resolution(
                            qcms, cc_map, cc_pending_case)
                        # V4-3 Num predicate guard (log-only)
                        self._log_num_gap(
                            (cc_pending_case or {}).get("prev_max"), qcm_numbers)
                        # CC Detection v4 — text cleanup + detector notes
                        # (AFTER resolution: a rewritten claim entry carries
                        # the pending narrative, not the dropped anchor's extras)
                        self._apply_anchor_extras(qcms, cc_map)

                        triggers = {num: info for num, info in cc_map.items()
                                    if isinstance(info, dict) and info.get("status") == "new_case"}
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

                        # H-fix — pending resolution outcomes (origin page
                        # captured BEFORE the state clears)
                        pending_origin = (cc_pending_case or {}).get("page")
                        if claim_num is not None:
                            cc_pending_case = None
                            for qcm in qcms:
                                num = qcm.get("number") or qcm.get("Num")
                                if num == claim_num:
                                    qcm["case_belonging_check"] = (
                                        f"new_case (cross-page): narrative from page "
                                        f"{pending_origin} (its own page held no QCM) "
                                        f"claimed by this question — pending candidate attached")
                        elif decline_num is not None and linkage_on:
                            cc_pending_case = None
                            for qcm in qcms:
                                num = qcm.get("number") or qcm.get("Num")
                                if num == decline_num:
                                    qcm["case_belonging_check"] = (
                                        f"cross-page: narrative from page "
                                        f"{pending_origin} pending was offered "
                                        f"once and declined (this question does not claim it) "
                                        f"— candidate dropped")
                        elif decline_num is not None:
                            # skip strategy: candidate spent, no linkage note
                            cc_pending_case = None
                        # trailing from a QCM-bearing page (its own narrative may
                        # itself trail for a later page — same mechanics)
                        if trailing and claim_num is None and decline_num is None:
                            cc_pending_case = {"label": trailing.get("label") or "CAS CLINIQUE",
                                               "text": trailing.get("text") or "",
                                               "page": page_num,
                                               "prev_max": (max(qcm_numbers)
                                                            if qcm_numbers else None)}

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
                        if not isinstance(q, dict):
                            continue
                        pg = q.get("page") or q.get("Page")
                        if pg is not None:
                            page_groups[int(pg)].append(q)

                    if not page_groups and not Path(step1_dir).glob("page_*.txt"):
                        print(f"   ⚠️  QCMs in {q_file.name} have no 'page' field. Skipping CC detection.")
                    else:
                        # H-fix — visit QCM-free pages too: a case narrative can
                        # trail at the END of a page holding ZERO QCMs (its
                        # claiming QCM lives on a LATER page). Pages that exist
                        # as step-1 text but have no QCM group join the walk
                        # (same 1-call-per-page budget; OQ-4 decision (i)).
                        txt_page_nums: set = set()
                        for p in Path(step1_dir).glob("page_*.txt"):
                            m = re.search(r"(\d+)", p.name)
                            if m:
                                txt_page_nums.add(int(m.group(1)))
                        sorted_pages = sorted(set(page_groups.keys()) | txt_page_nums)
                        print(f"   📑 Merged file: {len(sorted_pages)} distinct pages found → \nprocessing sequentially ({sorted_pages[0]}–{sorted_pages[-1]})")

                        for pg_num in sorted_pages:
                            if cancel_check and cancel_check():
                                print(f"\n⏸ Stop requested before CC page {pg_num} "
                                      f"— already-processed pages are saved.")
                                break
                            pg_qcms = page_groups.get(pg_num, [])
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
                                cc_map = self._detect_cc_sequential_page(
                                    pg_text, qcm_numbers, carry_over=page_carry,
                                    pending_case=cc_pending_case)
                            trailing = cc_map.pop("_trailing", None)

                            # H-fix — the ONE pending resolution attempt (never
                            # retried forward; see _apply_pending_case_resolution)
                            cc_map, claim_num, decline_num = self._apply_pending_case_resolution(
                                pg_qcms, cc_map, cc_pending_case)
                            # V4-3 Num predicate guard (log-only)
                            self._log_num_gap(
                                (cc_pending_case or {}).get("prev_max"),
                                qcm_numbers)
                            # CC Detection v4 — text cleanup + detector notes
                            # (AFTER resolution: a rewritten claim entry
                            # carries the pending narrative, not the dropped
                            # anchor's extras)
                            self._apply_anchor_extras(pg_qcms, cc_map)

                            triggers = {num: info for num, info in cc_map.items()
                                        if isinstance(info, dict) and info.get("status") == "new_case"}
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

                            if pg_qcms:
                                pg_qcms, cc_carry_over, _notes, _bq = self._propagate_cas_clinique(
                                    pg_qcms, cc_map, page_carry, linkage=linkage_on
                                )
                                if linkage_on:
                                    cc_boundary_queue.extend(_bq)

                                # H-fix — pending resolution outcomes
                                pending_origin = (cc_pending_case or {}).get("page")
                                if claim_num is not None:
                                    cc_pending_case = None
                                    for qcm in pg_qcms:
                                        num = qcm.get("number") or qcm.get("Num")
                                        if num == claim_num:
                                            qcm["case_belonging_check"] = (
                                                f"new_case (cross-page): narrative from page "
                                                f"{pending_origin} (its own page held no QCM) "
                                                f"claimed by this question — pending candidate attached")
                                elif decline_num is not None and linkage_on:
                                    cc_pending_case = None
                                    for qcm in pg_qcms:
                                        num = qcm.get("number") or qcm.get("Num")
                                        if num == decline_num:
                                            qcm["case_belonging_check"] = (
                                                f"cross-page: narrative from page "
                                                f"{pending_origin} pending was offered "
                                                f"once and declined (this question does not claim it) "
                                                f"— candidate dropped")
                                elif decline_num is not None:
                                    cc_pending_case = None   # skip: no linkage note
                                if trailing and claim_num is None and decline_num is None:
                                    cc_pending_case = {"label": trailing.get("label") or "CAS CLINIQUE",
                                                       "text": trailing.get("text") or "",
                                                       "page": pg_num,
                                                       "prev_max": (max(qcm_numbers)
                                                                    if qcm_numbers else None)}
                            else:
                                # QCM-free narrative page: the pending candidate
                                # persists WITHOUT re-affirmation (OQ-3 decision
                                # A); a NEW trailing narrative replaces it.
                                if trailing:
                                    cc_pending_case = {"label": trailing.get("label") or "CAS CLINIQUE",
                                                       "text": trailing.get("text") or "",
                                                       "page": pg_num,
                                                       "prev_max": None}

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

    def _parse_cc_response(self, content: str, qcm_numbers: List[int]):
        """Schema-sniffing wrapper (CC Detection v4): new anchor schema vs
        legacy 5-status schema.

        - v4 schema: entries carry `anchor_num` (int) + `cas_text` +
          optional `cas_label` / `anchor_text_clean` / `note`.
          Validation (parser-enforced, never model-hoped): an anchor is
          accepted ONLY if anchor_num is (a) one of this page's own QCM
          numbers, or (b) exactly max(qcm_numbers)+1 — the trailing case,
          routed into the reserved `"_trailing"` key so the SHIPPED
          pending_case machinery resolves it on the next page's first
          `number`/`Num` (merged-JSON "Num" requirement, V4-3). Anything
          else → the entry is dropped + logged (never cascaded).
        - legacy schema (any entry with "status") → `_parse_cc_statuses`
          untouched (all phase-0..7 / H-fix tests keep their contracts).
        """
        cleaned = re.sub(r'```(?:json)?\s*', '', content or '')
        cleaned = re.sub(r'```\s*', '', cleaned).strip()
        match = re.search(r'\[.*\]', cleaned, re.DOTALL)
        if not match:
            return None, None
        json_str = re.sub(r',(\s*[}\]])', r'\1', match.group(0))
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None, None
        if not isinstance(data, list):
            return None, None
        if not (data and any(
                isinstance(e, dict) and "anchor_num" in e for e in data)):
            # legacy (5-status) schema or plain empty array
            status_map, trailing = self._parse_cc_statuses(
                content, qcm_numbers, include_trailing=True)
            return status_map, trailing

        valid = set(qcm_numbers)
        max_plus1 = (max(qcm_numbers) + 1) if qcm_numbers else None
        result: Dict[int, Dict] = {}
        trailing = None
        for entry in data:
            if "_trailing" in entry:
                # a reasoning model may STILL emit the old page-level field;
                # accept it in the same shape (tolerant union).
                tv = entry.get("_trailing")
                if isinstance(tv, dict) and tv.get("text"):
                    trailing = {"label": tv.get("label") or "CAS CLINIQUE",
                                "text": tv.get("text")}
                continue
            num = entry.get("anchor_num")
            try:
                num = int(num)
            except (TypeError, ValueError):
                print(f"   ⚠️ [CC-V4] anchor proposal rejected: anchor_num "
                      f"not an integer ({num!r}) — entry dropped, never cascaded")
                continue
            text = (entry.get("cas_text") or "").strip()
            if not text:
                print(f"   ⚠️ [CC-V4] anchor proposal rejected: Q{num} has no "
                      f"cas_text — entry dropped, never cascaded")
                continue
            note = (entry.get("note") or "").strip()
            # Zero-QCM page: the WHOLE page is a trailing holder — any
            # anchor reports the narrative the page ends with; first wins.
            if not valid:
                if trailing is None:
                    trailing = {"label": entry.get("cas_label") or "CAS CLINIQUE",
                                "text": text}
                    if note:
                        trailing["note"] = note
                continue
            if num in valid:
                result[num] = {
                    "status": "new_case",
                    "label": entry.get("cas_label") or "CAS CLINIQUE",
                    "text": text,
                }
                if note:
                    # L1-only field (V4-OQ-2): distinct from the checker's
                    # own `case_belonging_check` verdicts by the `detector:`
                    # prefix; stored on the QCM dict by _apply_anchor_extras.
                    result[num]["detector_note"] = note
                if entry.get("anchor_text_clean") is not None:
                    result[num]["anchor_text_clean"] = entry["anchor_text_clean"]
            elif max_plus1 is not None and num == max_plus1:
                # trailing narrative: this page ENDS with the case; the NEXT
                # page's first QCM (by merged "Num") claims it. Emitted as
                # the reserved "_trailing" so the shipped pending_case
                # resolution (claims/decline, ONE attempt, Num-keyed)
                # consumes it unchanged.
                trailing = {
                    "label": entry.get("cas_label") or "CAS CLINIQUE",
                    "text": text,
                }
                if note:
                    trailing["note"] = note
            else:
                print(f"   ⚠️ [CC-V4] anchor proposal rejected: Q{num} is "
                      f"neither this page's number nor max+1 ({max_plus1}) "
                      f"— entry dropped, never cascaded")
        for n in qcm_numbers:
            if n not in result:
                result[n] = {"status": "uncertain", "label": None, "text": None}
        return result, trailing

    def _apply_anchor_extras(self, qcms: List[Dict], cc_map: Dict) -> None:
        """CC Detection v4 — apply `anchor_text_clean` and the `detector:`
        note from the anchor map onto the page's QCM dicts.

        - anchor_text_clean non-null → the now-clean question text replaces
          the QCM's own text (key present wins: `text` else `Text`).
        - anchor_text_clean null/absent (the model judged the narrative
          already a separate block) → run `cas_text_split` on the anchored
          QCM as a safety net, in case the model missed a fusion.
        Runs BEFORE propagation (text shape is read downstream only)."""
        from modules.cas_text_split import split_cas_from_text
        for qcm in qcms:
            num = qcm.get("number") or qcm.get("Num")
            info = cc_map.get(num) if num is not None else None
            if not isinstance(info, dict):
                continue
            if info.get("detector_note"):
                qcm["cc_detector_note"] = f"detector: {info['detector_note']}"
            clean = info.get("anchor_text_clean")
            if isinstance(clean, str) and clean.strip():
                if "text" in qcm:
                    qcm["text"] = clean
                elif "Text" in qcm:
                    qcm["Text"] = clean
                else:
                    qcm["text"] = clean
            else:
                # null clean → safety net: scrub narrative from the stem
                cas_val = qcm.get("cas")
                if cas_val:
                    new_text, removed = split_cas_from_text(
                        qcm.get("text") or qcm.get("Text"), cas_val)
                    if removed:
                        if "text" in qcm:
                            qcm["text"] = new_text
                        elif "Text" in qcm:
                            qcm["Text"] = new_text
                        else:
                            qcm["text"] = new_text

    @staticmethod
    def _log_num_gap(prev_max: Optional[int], pg_nums: List[int]) -> None:
        """CC Detection v4 (V4-3) — the Num predicate guard: a trailing
        candidate rescued via `max(per-page nums)+1` arithmetic must land on
        a CONTIGUOUS `Num` in the merged JSON. Log (never block) when the
        next page does not start at prev_max+1 — the pending_claim still
        resolves, but reviewers must know the arithmetic was off."""
        if prev_max is None or not pg_nums:
            return
        if min(pg_nums) != prev_max + 1:
            print(f"   ⚠️ [CC-V4] Num gap: trailing case expects Num "
                  f"{prev_max + 1} but this page starts at Num "
                  f"{min(pg_nums)} — pending resolution proceeds on the "
                  f"claim rule, review recommended")


    def _parse_cc_statuses(self, content: str, qcm_numbers: List[int],
                           include_trailing: bool = False):
        """Parse the 5-status classifier response into
        {qcm_number: {"status": ..., "label": ..., "text": ...}}.

        Robustness contract:
        - Status strings outside the enum are coerced to "uncertain".
        - A listed number with NO entry in the response defaults to "uncertain"
          (never silently dropped).
        - An entry with no explicit "status" infers one: cas_text non-null
          → "new_case", else "uncertain" (keeps simple responses parseable).
        - A response that parses to an EMPTY array → {} (no entries at all).

        Cross-page trailing narrative (H-fix): with `include_trailing=True`,
        a reserved `"_trailing"` element in the array is extracted (NOT a
        QCM entry) and returned as
        `({"status_map"}, "trailing" | None)`; QCM numbers are ints so the
        string key can never collide with a listed QCM number.
        """
        cleaned = re.sub(r'```(?:json)?\s*', '', content or '')
        cleaned = re.sub(r'```\s*', '', cleaned).strip()
        match = re.search(r'\[.*\]', cleaned, re.DOTALL)
        if not match:
            return (None, None) if include_trailing else None
        json_str = re.sub(r',(\s*[}\]])', r'\1', match.group(0))
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return (None, None) if include_trailing else None
        if not isinstance(data, list):
            return (None, None) if include_trailing else None
        if not data:
            result = {}
            if include_trailing:
                return result, None
            return result
        result: Dict[int, Dict] = {}
        trailing = None
        for entry in data:
            if not isinstance(entry, dict):
                continue
            if "_trailing" in entry:
                if include_trailing:
                    tv = entry.get("_trailing")
                    if isinstance(tv, dict) and tv.get("text"):
                        trailing = {"label": tv.get("label") or "CAS CLINIQUE",
                                    "text": tv.get("text")}
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
            # H-fix: keep cross-page claim evidence — the resolution state
            # machine reads "claims_pending_case"; only genuinely unknown
            # keys pass through (raw model duplicates of the canonical keys
            # — number/cas_label/cas_text — are NOT duplicated on the entry,
            # keeping exact-dict test contracts unaffected).
            for k, v in entry.items():
                if k not in result[num] and k not in ("number", "status",
                                                      "cas_label", "cas_text"):
                    result[num][k] = v
        for n in qcm_numbers:
            if n not in result:
                result[n] = {"status": "uncertain", "label": None, "text": None}
        if include_trailing:
            return result, trailing
        return result

    def _detect_cc_sequential_page(self, page_text: str, qcm_numbers: List[int],
                                   carry_over: Optional[str] = None,
                                   pending_case: Optional[Dict] = None) -> Dict:
        """
        Per-page LLM call for CC detection — CC Detection v4 (anchor schema).

        v4 replaces the 5-status enumeration with an ANCHOR-ONLY reasoning
        prompt: the model reports ONE entry per NEW patient narrative it
        finds on the page ({anchor_num, cas_label, cas_text,
        anchor_text_clean, note}); unlisted numbers propagate as the shipped
        uncertainty semantics (never a hard negative). A narrative at the
        very END of the page (or on a zero-QCM page) is anchored to
        max(page numbers)+1 / 1 respectively, which `_parse_cc_response`
        routes into the reserved `"_trailing"` key so the SHIPPED
        pending_case machinery attaches it to the NEXT page's first
        `number`/`Num` (merged-JSON "Num" requirement).

        Legacy compatibility: if the response parses to the OLD 5-status
        schema, `_parse_cc_response` falls through to `_parse_cc_statuses`
        untouched — all shipped consumers keep working either way.

        Returns (Phase 2 contract — the raw status map):
            { qcm_number: {"status", "label", "text"[, "detector_note",
                           "anchor_text_clean"]} [, "_trailing": {...}] }
            An EMPTY map ({}) means the call produced no usable page decision
            (failure/garbage/empty response) — the Python state machine then
            treats every listed number as "uncertain" (legacy-propagate).
        """
        if not page_text.strip():
            return {}

        if not qcm_numbers:
            nums_str = "none — this page holds no numbered questions"
        else:
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
This case is ALREADY linked — you never need to anchor it again. Report an
anchor ONLY when a NEW patient narrative starts on this page; the active
case flows automatically over un-anchored questions.
"""
        else:
            carry_block = """
CURRENTLY ACTIVE CASE (carried over from an earlier page): NONE.
"""

        pending_block = ""
        if pending_case:
            p_label = pending_case.get("label") or "CAS CLINIQUE"
            p_text = (pending_case.get("text") or "")[:1500]
            pending_block = f"""
PENDING CASE — DETECTED AT THE END OF AN EARLIER PAGE (NOT yet attached to any question):
- Label: {p_label}
- Narrative (may be truncated): {p_text}
This pending narrative is ALREADY TRACKED by the pipeline: it attaches
automatically to the first question of a coming page. Do NOT re-report it
as an anchor of your own — only report anchors for NEW patient narratives
that genuinely appear on THIS page.
"""

        if qcm_numbers:
            trailing_hint_lines = (
                "When the page ENDS with a narrative and no QCM follows it on"
                f" this page, report anchor_num = {max(qcm_numbers) + 1}"
                " — the pipeline delivers it to that QCM's"
                " \"Num\" on the next page on your behalf.")
        else:
            trailing_hint_lines = (
                "This page holds ZERO numbered questions: if a patient"
                " narrative exists anywhere in this page text, report it as"
                " an anchor with anchor_num 1 and full cas_text — the"
                " pipeline routes it to the next page's first question"
                " by Num.")

        prompt = f"""You are analyzing one page of a French medical exam (OCR text) to find any
clinical-case ("Cas Clinique") narratives on it, and to determine exactly
which QCM number each one belongs to.
THINKING (use it if your model exposes reasoning/thinking abilities — ignore
this section otherwise): before answering, silently reason step by step:
(a) locate every block of this page that reads as a patient-situation
description by the definition below; (b) for each candidate, check the
not-a-narrative list (question stems, OCR noise fragments, proposition
lists) and discard anything failing it; (c) decide the owning QCM by
reading order, applying the trailing rule for narratives nothing follows;
(d) prepare anchor_text_clean for fused blocks; (e) only then emit the
JSON array. Never print the reasoning itself — the JSON array alone is
the answer.
{carry_block}{pending_block}
## Trailing cases
{trailing_hint_lines.strip()}
## What IS a clinical case narrative
Descriptive prose about a specific patient: a name or initial, an age, and
their clinical/paraclinical profile (history, presenting complaint, exam
findings, lab/imaging results). Third person, describing someone — never
instructing or asking the reader anything. This is the PATTERN, not literal
text to match:
- "Madame F., 37 ans, suivie pour une thyroïdite de Hashimoto..."
- "Zhor, 77 ans, est diabétique de type II, découvert en 2021. Bilan
  initial: GAJ: 1.92 g/l, HbA1c=7.9%..."
A narrative may lack any "Cas Clinique" header and may even be FUSED directly
into the FIRST question's own text block with no separator — in that fused
case you STILL report it as an anchor (see anchor_text_clean below).

## What is NOT a clinical case narrative (confirmed real mistakes to avoid)
- An ordinary question stem, even when medically coherent and well-written:
  "Parmi les causes de syncope au cours de la cardiomyopathie hypertrophique,
  on peut citer:" — this is a question, not a patient.
- Short fragments with no sentence structure — isolated numbers, page
  annotations, section headers: "HTA 38 30" — OCR noise, not a narrative,
  regardless of where it sits.
- A lettered answer-choice list — "a- ... b- ... c- ... d- ... e- ..." (with
  or without checkmarks) — always propositions, never a narrative.
If you are not confident something is a genuine patient narrative by this
definition, do not report it.

## Which QCM it belongs to
A narrative belongs to the QCM immediately after it in reading order — never
to a QCM that already appeared earlier in the text, even if no better
candidate exists on this page.
If the page ENDS with a narrative and no QCM follows it on this page at all
(this includes pages with ZERO numbered questions), it belongs to the next
page's first question — the "Trailing cases" section above tells you what
anchor_num to report in that situation.

## Output format
Return a JSON array. Include an entry ONLY for each QCM number that anchors
a genuine NEW narrative — do NOT list every QCM on the page:
[
  {{
    "anchor_num": <int>,
    "cas_label": "<as written, or \"CAS CLINIQUE\" if unlabeled>",
    "cas_text": "<the narrative only — patient story, nothing else>",
    "anchor_text_clean": "<if the narrative was fused directly into this
       QCM's own question text with no separator, that QCM's own text with
       the narrative removed — null if the narrative was already a
       separate block>",
    "note": "<one short sentence — why this is a genuine narrative>"
  }}
]
If no genuine narrative starts on this page, return [].

QCM NUMBERS ON THIS PAGE (in order): [{nums_str}]

Return ONLY a valid JSON array — no markdown fences, no explanation.

PAGE TEXT:
{page_text[:max_input_chars]}"""

        # V4-0: reasoning-capable primary, fast model kept for outage
        # resilience only (env knobs reused — no new config surface).
        primary_model  = os.getenv("STEP3_MODEL", "google/gemini-2.5-pro")
        fallback_model = os.getenv("STEP3_FALLBACK_MODEL", "google/gemini-2.5-flash-lite")
        max_tokens     = int(os.getenv("STEP3_MAX_TOKENS") or "10000")

        # FIX-2/FIX-3 (ratrapage run): a model call "succeeding" is not enough
        # — BLANK responses (null/whitespace) and UNPARSABLE responses are
        # treated as failures too, so the fallback model gets its try before
        # the page forfeits. Guardrail: at most 2 calls per page (primary +
        # fallback — the same 2-model policy as the pipeline elsewhere); if
        # both fail/blank/unparsable the result is {} = the exact legacy
        # behavior (whole page -> uncertain/legacy-propagate), so recall can
        # never regress.
        attempts = ((primary_model, "primary"), (fallback_model, "fallback"))
        for attempt_model, attempt_label in attempts:
            if attempt_label == "fallback":
                print(f"🔄 Retrying with fallback: {fallback_model}...")
            try:
                resp = self.client.generate_completion(prompt, model=attempt_model, max_tokens=max_tokens)
            except Exception as e:
                print(f"⚠️ {attempt_label} model failed for CC sequential detection: {e}")
                continue

            content = (resp.get("content") or "").strip()
            status_map, trailing = self._parse_cc_response(
                content, qcm_numbers)

            if not content:
                print(f"⚠️ {attempt_label} model returned an empty/blank response — treating as failure.")
                continue
            if status_map is None:
                print(f"⚠️ No JSON array found in CC response ({attempt_label} model).")
                continue

            cost = resp.get('cost', 0.0) or self.client.estimate_cost(attempt_model, resp["usage"])
            self.cost_tracker.log_api_call("step3_cc_sequential", attempt_model, resp["usage"], cost)
            # Phase 2: return the raw 5-status map. An empty array response
            # also yields {} — downstream propagation then treats every
            # listed number as "uncertain" (legacy-propagate), never as a
            # hard negative.
            # H-fix: attach the cross-page trailing narrative as the reserved
            # "_trailing" key ONLY when actually detected (int keys can never
            # collide, and the key is omitted entirely when None so every
            # existing consumer keeps working unchanged).
            if trailing:
                status_map["_trailing"] = trailing
            return status_map

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

    # Sidecar files Step 2 writes into step2_qcm/accepted (answer-key page
    # list) plus cc-redesign audit artifacts that share the folder tree —
    # none of these are QCM lists.
    _STEP2_SIDECAR_FILES = {
        "correction_pages.json",
        "cc_boundary_transitions.json",
        "cc_boundary_checks.json",
        "clinical_case_verification.json",
    }

    def _apply_pending_case_resolution(self, pg_qcms: List[Dict], cc_map: Dict,
                                       pending: Optional[Dict]) -> tuple:
        """H-fix — the ONE resolution attempt for a cross-page pending
        candidate (`pending_case`: a trailing narrative detected at the end
        of an earlier page that never attached to any QCM).

        Decided AT the first QCM-bearing page reached (either path), exactly
        once per candidate — never retried on any later page:
          - CLAIMED  (an entry sets "claims_pending_case": true with a
            claim-compatible status) → the entry is rewritten into the
            standard `new_case` shape using the PENDING narrative, so the
            existing propagation attaches it (full chain under per_group;
            single hygienic attach under skip). The caller writes the
            distinct cross-page note into `case_belonging_check`.
          - UNRELATED/ENDS_HERE on the FIRST page QCM → DECLINE: candidate
            dropped permanently (note written by the caller on the deciding
            QCM; per_group only).
          - UNCERTAIN on the first QCM → safety-valve CLAIM (same doctrine as
            the running-case uncertain: attach, let the checker backstop).
          - Anything else indeterminate (e.g. "continues" on a DIFFERENT
            running case without a claim flag) → attempt spent → DECLINE
            with a note.

        Returns (cc_map_after, claim_num, decline_num, origin_page).
        """
        if not pending:
            return cc_map, None, None
        origin = pending.get("page")
        p_label = pending.get("label") or "CAS CLINIQUE"
        p_text = pending.get("text") or ""

        ordered = [q for q in pg_qcms if isinstance(q, dict)]
        first_num = None
        first_info = None
        claim_num = None
        for q in ordered:
            num = q.get("number") or q.get("Num")
            info = cc_map.get(num) if num is not None else None
            if not isinstance(info, dict):
                info = None
            if first_num is None:
                first_num, first_info = num, info
            st = (info.get("status") or "uncertain") if info else "uncertain"
            if info and info.get("claims_pending_case") and st in ("continues", "new_case"):
                claim_num = num
                break

        if claim_num is not None:
            cc_map[claim_num] = {"status": "new_case", "label": p_label, "text": p_text}
            return cc_map, claim_num, None

        # no claim → decide by the FIRST page QCM's verdict (OQ-5: both
        # decline statuses count; uncertain = safety-valve claim; other
        # statuses = attempt spent → decline).
        first_status = "uncertain"
        if isinstance(first_info, dict):
            first_status = first_info.get("status") or "uncertain"
        if first_status == "uncertain":
            if first_num is not None:
                cc_map[first_num] = {"status": "new_case",
                                     "label": p_label, "text": p_text}
                cc_map[first_num]["_pending_uncertain_claim"] = True
                return cc_map, first_num, None
            return cc_map, None, None

        # decline (unrelated / ends_here / indeterminate) — permanent drop
        return cc_map, None, first_num

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
