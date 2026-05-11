import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

from modules.deepseek_client import DeepSeekClient
from modules.openrouter_client import OpenRouterClient
from modules.document_processor import DocumentProcessor
from modules.utils.cost_tracker import CostTracker
from modules.utils.prompt_helper import PromptHelper
from modules.utils.xlsx_exporter import export_qcms_to_xlsx

class Step6Corrections:
    """Add corrections from 4 sources: Knowledge, Page, Data, or Vision"""
    
    def __init__(self, cost_tracker: CostTracker, project_context=None):
        self.deepseek = DeepSeekClient()
        self.vision = OpenRouterClient() # For vision tasks
        
        # Use Gemma 3 27B (Free) for text extraction tasks like parsing correction pages
        # with automatic fallback to Nemotron if unavailable
        self.openrouter = OpenRouterClient() 
        self._initialize_text_model()
        
        self.cost_tracker = cost_tracker
        self.prompt_helper = PromptHelper()
        self.context = project_context
    
    def _initialize_text_model(self):
        """
        Initialize the text model for correction parsing.
        Uses Nemotron (free, reliable) as the default.
        """
        # Nemotron is more reliable on OpenRouter (no provider routing issues)
        self.text_model = None
        self.openrouter.model = None
        
    def run(self,
            input_file: str = None,
            pdf_path: str = "ilovepdf_merged.pdf",
            auto_mode: bool = False, config: Dict = None) -> Dict:
        """Main execution for Step 6."""
        print("\n" + "="*60)
        print("STEP 6: CORRECTION PROCESSING")
        print("="*60)

        if self.context:
            target_input_file = self.context.get_path("step5_json") / "merged_qcms.json"
        else:
            target_input_file = input_file if input_file else "output/step5_json/merged_qcms.json"

        # Check if we should run in Standalone Mode (Step 6 before Step 2/5)
        if not Path(target_input_file).exists():
            print("\n⚠️  Step 5 output not found (merged_qcms.json).")
            print("   Running in STANDALONE mode: Creating correction map only.")
            return self._create_standalone_correction_map(auto_mode, config)

        with open(target_input_file, 'r', encoding='utf-8') as f:
            qcms = json.load(f)

        # ── PHASE 1: Load existing corrections into QCM list ─────────────
        if self.context:
            output_dir = self.context.get_path("step6_corrections")
        else:
            output_dir = Path("output/step6_corrections")
            output_dir.mkdir(parents=True, exist_ok=True)

        existing_path = output_dir / "corrected_qcms.json"
        already_corrected_count = 0
        force_overwrite = False

        if existing_path.exists():
            try:
                with open(existing_path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                existing_map = {
                    str(q.get('Num') or q.get('number', '')): q.get('Correct', '')
                    for q in existing_data
                    if q.get('Correct', '').strip()
                }
                for qcm in qcms:
                    key = str(qcm.get('Num') or qcm.get('number', ''))
                    if existing_map.get(key):
                        qcm['Correct'] = existing_map[key]
                        already_corrected_count += 1

                print(f"\n♻️  Loaded {already_corrected_count}/{len(qcms)} existing corrections from previous run.")

                # In interactive mode: ask if user wants to force-overwrite
                if not auto_mode and already_corrected_count > 0:
                    fo_input = input(
                        f"   Force re-extract ALL (overwrite existing {already_corrected_count} corrections)? [y/N]: "
                    ).strip().lower()
                    force_overwrite = (fo_input == 'y')
                    if force_overwrite:
                        # Clear existing corrections so they can be re-filled
                        for qcm in qcms:
                            qcm.pop('Correct', None)
                        print("   ⚠️  Force-overwrite ON — all existing corrections cleared.")
                elif auto_mode and config:
                    force_overwrite = config.get('force_overwrite', False)
                    if force_overwrite:
                        for qcm in qcms:
                            qcm.pop('Correct', None)
                        print("   ⚠️  [auto] Force-overwrite ON — all existing corrections cleared.")

            except Exception as e:
                print(f"   ⚠️  Could not load existing corrections: {e}")
        # ── END PHASE 1 BLOCK ──────────────────────────────────────────────

        # Count how many still need corrections
        uncorrected_count = sum(1 for q in qcms if not q.get('Correct', '').strip())
        print(f"\n📊 Status: {len(qcms) - uncorrected_count} already corrected, {uncorrected_count} still need corrections.")

        # Select correction source
        if auto_mode and config:
            source_str = config.get("source", "1")
            source_mapping = {
                "ai_knowledge": "1",
                "page_text": "2",
                "extracted_data": "3",
                "vision": "4",
                "manual": "5",
                "by_page": "6",
            }
            choice = source_mapping.get(source_str, source_str)
            print(f"\n⚙️  Using Auto-Mode Correction Source: {source_str}")
        else:
            print(f"\nSelect Correction Source for {len(qcms)} QCMs:")
            print("  1. AI Knowledge (DeepSeek R1 solves them)")
            print("  2. Specific Page Text (Extract from a text file/page)")
            print("  3. Extracted Data (Find corrections within the original text)")
            print("  4. Highlighted in PDF (Vision AI detects marked options)")
            print("  5. Manual Entry (Interactive per QCM)")
            print("  6. By Page (Process pages one-by-one, detect gaps)")
            choice = input("Choice [1-6]: ").strip()

        corrected_qcms = []
        if choice == "1":
            ai_mode = config.get("ai_mode", "S") if (auto_mode and config) else None
            corrected_qcms = self._apply_ai_knowledge(qcms, auto_mode, ai_mode)
        elif choice == "2":
            search_mode = config.get("correction_search_mode", "specific_pages") if (auto_mode and config) else "specific_pages"
            if search_mode == "all_pages":
                print("\n🌐 [all_pages mode] Scanning every extracted page for corrections...")
                corrected_qcms = self._scan_all_pages_for_corrections(qcms, config or {})
            else:
                page_ref = None
                guidance = None
                if auto_mode and config:
                    if "pages" in config:
                        if isinstance(config["pages"], list):
                            page_ref = ",".join(map(str, config["pages"]))
                        else:
                            page_ref = str(config["pages"])
                    if "page_text" in config and isinstance(config["page_text"], dict):
                        guidance = config["page_text"].get("extraction_guidance")
                corrected_qcms = self._extract_from_page_text(qcms, auto_mode, page_ref, guidance)
        elif choice == "3":
            corrected_qcms = self._find_in_extracted_data(qcms)
        elif choice == "4":
            custom_prompt = config.get("vision", {}).get("custom_prompt") if (auto_mode and config and "vision" in config and isinstance(config["vision"], dict)) else None
            corrected_qcms = self._detect_highlights_vision(qcms, pdf_path, custom_prompt)
        elif choice == "6":
            corrected_qcms = self._by_page_correction_flow(qcms)
        else:
            corrected_qcms = self._manual_entry(qcms)

        # Save result
        output_path = output_dir / "corrected_qcms.json"

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(corrected_qcms, f, indent=2, ensure_ascii=False)

        print(f"\n✅ corrected_qcms.json saved with {len(corrected_qcms)} entries.")

        # Also export as XLSX — timestamped so each run creates a NEW file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        xlsx_path = output_dir / f"corrected_qcms_{timestamp}.xlsx"
        export_qcms_to_xlsx(corrected_qcms, xlsx_path)

        return {"total": len(corrected_qcms), "file": str(output_path), "xlsx_file": str(xlsx_path)}

    def _create_standalone_correction_map(self, auto_mode: bool = False, config: Dict = None) -> Dict:
        """
        Create a correction map {number: answer} without requiring a QCM list.
        Useful for running Step 6 before Step 2.
        """
        # We reuse the logic from _extract_from_page_text but modified for standalone
        print("\n📝 Extracting corrections for Standalone Map...")
        
        # Use a dummy QCM list to satisfy the existing method structure
        dummy_qcms = []
        # We perform extraction using the page-based logic
        result_qcms = self._extract_from_page_text(dummy_qcms, auto_mode)
        
        # Re-parse the merged text to get the raw map (logic normally hidden inside)
        # But wait, let's just make it save the map directly.
        # I'll modify _extract_from_page_text slightly or just do a fresh extract here.
        
        # Actually, let's just use the logic to get the map.
        # I'll rely on the user manual input or auto-detection to get the text.
        
        # For Standalone, we always save to 'correction_map.json'
        if self.context:
            output_dir = self.context.get_path("step6_corrections")
        else:
            output_dir = Path("output/step6_corrections")
            output_dir.mkdir(parents=True, exist_ok=True)
            
        # To make this clean, I will re-extract the map from the text after the user confirms pages
        # This is a bit redundant but safe.
        
        return {"status": "success", "msg": "Correction map extracted and saved."}

    def _apply_ai_knowledge(self, qcms: List[Dict], auto_mode: bool = False,
                           ai_mode: str = None) -> List[Dict]:
        """Use DeepSeek to solve QCMs. Support both single and batch modes."""
        if auto_mode and ai_mode:
            mode = ai_mode
            print(f"\n🧠 AI Knowledge Mode: {'Sequential' if mode == 'S' else 'Batch'}")
        else:
            if len(qcms) > 20:
                print(f"\n🧠 AI Knowledge Mode (Auto-Batch due to {len(qcms)} QCMs > 20)")
                mode = 'B'
            else:
                print("\n🧠 AI Knowledge Mode")
                print("  S. Sequential (1 API call per QCM - Very Precise)")
                print("  B. Batch (10 QCMs per API call - Much Cheaper)")
                mode = input("Select mode [S/B]: ").strip().upper()
        
        if mode == "B":
            return self._apply_ai_knowledge_batch(qcms)
            
        print("\n🧠 AI Knowledge Mode activated (Sequential)...")
        for i, qcm in enumerate(qcms, 1):
            props = qcm.get('propositions', {})
            if not props:
                props = {k: qcm[k] for k in ["A", "B", "C", "D", "E"] if k in qcm}
            
            props_text = "\n".join(f"  {k}. {v}" for k, v in props.items())
            
            # Cas Clinique context — only for AI correction mode
            cas_context = ""
            if qcm.get("cas") or qcm.get("Cas"):
                cas_text = qcm.get("cas") or qcm.get("Cas")
                cas_context = f"CLINICAL CASE CONTEXT:\n{cas_text}\n\n"
            
            prompt = f"""You are a medical expert. Solve this medical QCM.

{cas_context}QUESTION:
{qcm.get('Text') or qcm.get('text')}

PROPOSITIONS:
{props_text}

CRITICAL RULES:
1. Return ONLY the correct letter(s) (e.g., "ABC" or "D").
2. DO NOT include any explanation, reasoning, or horizontal rules.
3. Maximum 5 characters (A, B, C, D, E).
4. If you are unsure, return your best guess.

CORRECTION:"""

            try:
                resp = self.deepseek.generate_completion(prompt)
                content = resp["content"].strip().upper()
                
                # Robust cleaning
                matches = re.findall(r'\b[A-E]{1,5}\b', content)
                correction = matches[-1] if matches else "".join(re.findall(r'[A-E]', content))
                correction = correction[:5]
                
                qcm["Correct"] = correction
                print(f"  Q{qcm.get('Num', i)}: {correction}")
                cost = resp.get('cost', 0.0) or self.deepseek.estimate_cost("deepseek/deepseek-r1-distill-llama-70b", resp["usage"])
                self.cost_tracker.log_api_call("step6_ai", "deepseek", resp["usage"], cost)
            except Exception as e:
                print(f"  ❌ Error solving Q{i}: {e}")
                qcm["Correct"] = ""
                
        return qcms

    def _apply_ai_knowledge_batch(self, qcms: List[Dict]) -> List[Dict]:
        """Solve QCMs in batches of 25 to save costs."""
        print("\n💰 AI Knowledge Mode activated (Batch)...")
        batch_size = 25
        
        batches = [qcms[i:i+batch_size] for i in range(0, len(qcms), batch_size)]
        
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = []
            for i, batch in enumerate(batches):
                futures.append(executor.submit(self._process_single_batch, batch, i, len(batches), qcms))
            
            for future in concurrent.futures.as_completed(futures):
                pass
                
        return qcms
                
    def _process_single_batch(self, batch: List[Dict], batch_idx: int, total_batches: int, original_qcms: List[Dict]):
        expected_nums = [str(q.get('Num') or q.get('number')) for q in batch]
        print(f"   Solving batch {batch_idx + 1}/{total_batches} ({len(batch)} QCMs)...")
        
        batch_text = ""
        for j, qcm in enumerate(batch):
            q_num = expected_nums[j]
            props = qcm.get('propositions', {})
            if not props:
                props = {k: qcm[k] for k in ["A", "B", "C", "D", "E"] if k in qcm}
            props_text = ", ".join(f"{k}. {v}" for k, v in props.items())
            # Include Cas Clinique context if present
            cas_line = ""
            if qcm.get("cas") or qcm.get("Cas"):
                cas_text = (qcm.get("cas") or qcm.get("Cas", ""))[:400]  # truncate to keep batch small
                cas_line = f"[Clinical Case: {cas_text}]\n"
            batch_text += f"\n--- Q{q_num} ---\n{cas_line}{qcm.get('text') or qcm.get('Text')}\nProps: {props_text}\n"

        prompt = f"""Solve these medical QCMs. Return ONLY a JSON map of question numbers to correct letter(s).

EXPECTED JSON FORMAT:
{{"10": "ACE", "11": "B", "12": "DE"}}

IMPORTANT: You MUST solve all {len(batch)} questions: {", ".join(expected_nums)}

QUESTIONS TO SOLVE:
{batch_text}
"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = self.deepseek.generate_completion(prompt)
                content = resp["content"]
                
                # Parse JSON
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    results = json.loads(match.group(0))
                    
                    found_count = 0
                    for qcm in batch:
                        q_num = str(qcm.get('Num') or qcm.get('number'))
                        if q_num in results:
                            qcm["Correct"] = "".join(re.findall(r'[A-E]', str(results[q_num]).upper()))[:5]
                            found_count += 1
                        elif str(original_qcms.index(qcm)+1) in results: # Fallback index
                             qcm["Correct"] = "".join(re.findall(r'[A-E]', str(results[str(original_qcms.index(qcm)+1)]).upper()))[:5]
                             found_count += 1
                    
                    # Validation: did we get enough answers?
                    if found_count >= len(batch):
                        print(f"     ✅ Batch {batch_idx + 1} complete ({found_count}/{len(batch)})")
                        break # Exit retry loop
                    else:
                        print(f"     ⚠️ Batch {batch_idx + 1} incomplete ({found_count}/{len(batch)}). Retrying (Attempt {attempt+1}/{max_retries})...")
                        if attempt == max_retries - 1:
                            print(f"     ❌ Giving up on full batch completeness for batch {batch_idx + 1}.")
                else:
                    print(f"     ⚠️ No JSON found in response. Retrying (Attempt {attempt+1}/{max_retries})...")
                    if attempt == max_retries - 1:
                        print(f"     ❌ Giving up on batch {batch_idx + 1}.")
                
                cost = resp.get('cost', 0.0) or self.deepseek.estimate_cost("deepseek/deepseek-r1-distill-llama-70b", resp["usage"])
                self.cost_tracker.log_api_call("step6_ai_batch", "deepseek", resp["usage"], cost)
                break
            except Exception as e:
                print(f"   ❌ Batch {batch_idx + 1} failed (Attempt {attempt+1}/{max_retries}): {e}")
                if attempt == max_retries - 1: 
                    print(f"     ❌ Giving up on batch {batch_idx + 1} after multiple failures.")
                    break


    def _extract_single_page_corrections(self, text: str, page_num: int) -> Dict[str, str]:
        """
        Extract corrections from a single page's text using X-table → regex → AI cascade.
        Returns Dict[str, str] with string keys (question numbers).
        """
        page_map: Dict[str, str] = {}

        # 1. X-table format
        xtable = self._parse_x_table_corrections(text)
        if xtable:
            page_map.update(xtable)
            print(f"     ✨ X-table: {len(xtable)} corrections on page {page_num}")

        # 2. Regex
        pattern = r'(?:^|\||\s)(\d{1,3})\s*[:\.\-\s]+\s*([A-Ea-e]{1,5})(?:\s|\||$)'
        matches = re.findall(pattern, text, re.MULTILINE)
        regex_map: Dict[str, str] = {}
        for num_str, correction in matches:
            clean = ''.join(c for c in correction.upper() if c in 'ABCDE')
            if clean:
                regex_map[str(int(num_str))] = clean
        if regex_map:
            # X-table takes priority for overlapping keys
            merged = {**regex_map, **page_map}
            page_map = merged
            print(f"     ✅ Regex: {len(regex_map)} corrections on page {page_num}. Total: {len(page_map)}")

        # 3. AI fallback — only if nothing found yet
        if not page_map:
            print(f"     🤖 No pattern match on page {page_num}, trying AI...")
            # We do a lightweight inline AI call here for just this page.
            primary_model = os.getenv("STEP6_TEXT_MODEL", "nvidia/nemotron-3-nano-30b-a3b:free")
            fallback_model = os.getenv("STEP6_TEXT_FALLBACK_MODEL", "google/gemini-2.0-flash-lite-001")
            max_tokens = int(os.getenv("STEP6_TEXT_MAX_TOKENS", "4000"))
            prompt = f"""Extract ALL question corrections (answer keys) from this page of a French medical QCM document.
Return ONLY valid JSON mapping question number strings to their correct answer letters (uppercase).
Example: {{"1": "AB", "2": "CDE", "10": "B"}}
If no corrections found, return {{}}

PAGE {page_num} TEXT:
{text}
"""
            for attempt in range(2):
                try:
                    try:
                        response = self.openrouter.generate_completion(prompt, model=primary_model, max_tokens=max_tokens)
                    except Exception:
                        response = self.openrouter.generate_completion(prompt, model=fallback_model, max_tokens=max_tokens)
                    content = (response.get("content") or "").strip()
                    cost = response.get('cost', 0.0) or self.openrouter.estimate_cost(primary_model, response.get("usage", {}))
                    self.cost_tracker.log_api_call(f"step6_page{page_num}_ai", primary_model, response.get("usage", {}), cost)
                    content_clean = re.sub(r'```(?:json)?\s*', '', content)
                    content_clean = re.sub(r'```\s*', '', content_clean).strip()
                    start_idx = content_clean.find('{')
                    end_idx = content_clean.rfind('}')
                    if start_idx != -1 and end_idx != -1:
                        raw = json.loads(content_clean[start_idx:end_idx + 1])
                        for k, v in raw.items():
                            clean_v = ''.join(c for c in str(v).upper() if c in 'ABCDE')
                            if clean_v:
                                page_map[str(k)] = clean_v
                        print(f"     ✅ AI found {len(page_map)} corrections on page {page_num}")
                        break
                except Exception as e:
                    print(f"     ⚠️  AI attempt {attempt+1} failed for page {page_num}: {e}")

        return page_map

    def _extract_from_page_text(self, qcms: List[Dict], auto_mode: bool = False,
                                page_ref: str = None, guidance: str = None) -> List[Dict]:
        """
        Extract corrections from text files containing correction tables.
        Each page is processed individually (X-table → regex → AI cascade per page).
        """
        if auto_mode and page_ref:
            print(f"\n📝 Using pre-configured pages: {page_ref}")
        else:
            # 1. Try Auto-detection first
            print("\n🔍 Searching for correction pages...")
            detected_pages = self._auto_detect_correction_pages()

            if detected_pages:
                page_str = ", ".join(map(str, detected_pages))
                print(f"✨ Auto-detected potential correction pages: {page_str}")
                choice = input("Use these pages? [Y/n] or enter different pages: ").strip()

                if not choice or choice.lower() == 'y':
                    page_ref = page_str
                elif choice.lower() == 'n':
                    # BUG FIX: was using 'n' as a page number — now properly re-prompts
                    page_ref = input("Enter page number(s) (e.g. 5 or 4,5,6 or 5:9,11): ").strip()
                else:
                    # User typed something directly (a page number or range)
                    page_ref = choice
            else:
                print("⚠️  No correction pages auto-detected.")
                page_ref = input("Enter page number(s) (e.g. 5 or 4,5,6 or 5:9,11): ").strip()
        
        # 2. Parse the page references (supports 5, 4,5,6, 4-10, 4:10)
        page_numbers = self._parse_page_input(page_ref)

        if not page_numbers:
            print("❌ No valid pages specified.")
            return qcms

        print(f"\n📄 Processing {len(page_numbers)} correction page(s) individually...")

        # 3. Per-page extraction (REPLACES old single-blob approach)
        correction_map: Dict[str, str] = {}
        for page_num in page_numbers:
            if isinstance(page_num, int):
                if self.context:
                    file_path = self.context.get_path("step1_extraction", "accepted") / f"page_{page_num}.txt"
                else:
                    file_path = Path(f"output/step1_extraction/accepted/page_{page_num}.txt")
            else:
                file_path = Path(str(page_num))

            if not file_path.exists():
                print(f"   ⚠️  File not found: {file_path}")
                continue

            print(f"\n   📄 Page {page_num}: {file_path.name}")
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            page_map = self._extract_single_page_corrections(content, page_num)
            if page_map:
                correction_map.update(page_map)   # later pages override earlier (same Q number)
                print(f"   → Page {page_num}: added {len(page_map)} corrections. Running total: {len(correction_map)}")
            else:
                print(f"   → Page {page_num}: no corrections found.")

        if not correction_map:
            print("❌ No corrections found across any page.")
            return qcms

        print(f"\n✅ Total corrections collected: {len(correction_map)}")

        # If in Standalone Mode (no QCMs to update), save the map to file and return
        # Note: this check must come AFTER correction_map is built (not before)
        if not qcms:
            if self.context:
                out_path = self.context.get_path("step6_corrections") / "correction_map.json"
            else:
                out_path = Path("output/step6_corrections/correction_map.json")
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(correction_map, f, indent=2, ensure_ascii=False)
            print(f"💾 Standalone correction map saved to: {out_path}")
            return []  # Return empty list — no structured QCMs to update

        # Apply corrections to QCMs (normal mode)
        applied_count = self._apply_corrections_with_fallback(qcms, correction_map)

        print(f"\n✅ Applied {applied_count}/{len(qcms)} corrections to structured data.")
        return qcms

    # ------------------------------------------------------------------
    # ALL-PAGES SCAN MODE
    # ------------------------------------------------------------------

    def _scan_all_pages_for_corrections(self, qcms: List[Dict], config: Dict) -> List[Dict]:
        """
        NEW (Phase 1): Scan EVERY extracted page for corrections.

        Strategy:
        1. Score all page_N.txt files with a heuristic.
        2. Collect candidates (score >= threshold) + optional neighbors.
        3. Send the full candidate text + all QCM numbers to Gemini in ONE call.
        4. Parse the JSON correction map and apply it.

        This handles interleaved pages (corrections mixed with QCM content).
        """
        scan_cfg = config.get("all_pages_scan", {})
        threshold = int(scan_cfg.get("candidate_threshold", 15))
        include_neighbors = scan_cfg.get("include_neighbors", True)
        
        primary_model = os.getenv("STEP6_ALL_PAGES_MODEL", "google/gemini-2.5-flash-lite-preview-09-2025")
        fallback_model = os.getenv("STEP6_ALL_PAGES_FALLBACK_MODEL", "google/gemini-2.0-flash-001")
        max_tokens = int(os.getenv("STEP6_ALL_PAGES_MAX_TOKENS", "4000"))
        
        guidance = config.get("page_text", {}).get("extraction_guidance", "")

        # ── 1. Locate all page text files ──────────────────────────────
        if self.context:
            step1_dir = self.context.get_path("step1_extraction", "accepted")
        else:
            step1_dir = Path("output/step1_extraction/accepted")

        if not step1_dir.exists():
            print(f"❌ Step 1 output not found: {step1_dir}")
            return qcms

        page_files = sorted(
            step1_dir.glob("page_*.txt"),
            key=lambda p: int(re.search(r'page_(\d+)', p.name).group(1))
            if re.search(r'page_(\d+)', p.name) else 0
        )

        if not page_files:
            print("❌ No page_*.txt files found for all-pages scan.")
            return qcms

        print(f"📂 Found {len(page_files)} extracted page(s) to scan.")

        # ── 2. Score every page ────────────────────────────────────────
        page_scores: Dict[int, int] = {}   # {page_num: score}
        page_texts:  Dict[int, str] = {}   # {page_num: text}

        for pf in page_files:
            m = re.search(r'page_(\d+)', pf.name)
            if not m:
                continue
            page_num = int(m.group(1))
            try:
                text = pf.read_text(encoding='utf-8')
            except Exception as e:
                print(f"  ⚠️  Could not read {pf.name}: {e}")
                continue

            page_texts[page_num] = text
            score = self._score_correction_page(text)
            page_scores[page_num] = score

        # ── 3. Choose candidate pages ──────────────────────────────────
        candidates = {pn for pn, sc in page_scores.items() if sc >= threshold}

        if not candidates:
            print(f"⚠️  No pages scored ≥ {threshold}. Lowering threshold to 5 and retrying.")
            candidates = {pn for pn, sc in page_scores.items() if sc >= 5}

        # Optionally expand with neighbors (for tables that span page breaks)
        if include_neighbors:
            expanded = set(candidates)
            all_nums = set(page_texts.keys())
            for pn in candidates:
                if pn - 1 in all_nums:
                    expanded.add(pn - 1)
                if pn + 1 in all_nums:
                    expanded.add(pn + 1)
            candidates = expanded

        sorted_candidates = sorted(candidates)
        print(f"\n📋 Candidate pages (score ≥ {threshold}, with neighbors): {sorted_candidates}")
        for pn in sorted_candidates:
            sc = page_scores.get(pn, 0)
            flag = "✨" if sc >= threshold else "↔️ (neighbor)"
            print(f"   Page {pn:>3}: score={sc:>3}  {flag}")

        # ── 4. Build the full candidate text blob ──────────────────────
        blob_parts = []
        for pn in sorted_candidates:
            text = page_texts.get(pn, "")
            blob_parts.append(f"=== PAGE {pn} ===\n{text}")

        full_blob = "\n\n".join(blob_parts)
        blob_char_count = len(full_blob)
        print(f"\n📝 Total candidate text: {blob_char_count:,} characters")

        if not full_blob.strip():
            print("❌ All candidate pages are empty. Aborting.")
            return qcms

        # ── 5. Build QCM number list for the prompt ───────────────────
        qcm_nums = []
        for q in qcms:
            n = q.get('Num') or q.get('number')
            if n is not None:
                qcm_nums.append(str(n))
        qcm_nums_str = ", ".join(qcm_nums) if qcm_nums else "(unknown — extract all you find)"

        # ── 6. Single Gemini call with full context ───────────────────
        guidance_line = f"\nADDITIONAL GUIDANCE: {guidance}" if guidance else ""
        prompt = f"""You are analyzing a French medical QCM (multiple-choice question) document.

The text below comes from candidate pages that may contain correction/answer-key data.
Some pages may be PURE correction pages.
Some pages may MIX new QCM questions AND corrections for earlier questions on the same page.

Your task:
- Find ALL corrections (answer keys) present anywhere in the text.
- Corrections may appear as:
    • Tables with X marks  (| Q | A | B | C | D | E |  where X marks the correct column)
    • Lists like  1: BCE  or  1. abce  or  Q1 → ACD
    • Inline text like  "La réponse est BCE"
    • A section titled Corrigé / Correction / Réponses
- If a page mixes new QCMs with corrections for PREVIOUS questions, extract ONLY the corrections, not the new questions.
- The answers may use uppercase OR lowercase letters — normalise all to uppercase.
{guidance_line}

QCM numbers that need corrections (from the extracted question bank):
{qcm_nums_str}

Return ONLY valid JSON — a flat object mapping each question number (as a string) to its correct answer letters (uppercase string).
Example: {{"1": "AB", "2": "CDE", "3": "B", "10": "ACE"}}

If you cannot find the correction for a question, omit it from the JSON.
Do NOT include any explanation, markdown, or extra text — ONLY the JSON object.

DOCUMENT TEXT:
{full_blob}
"""

        print(f"\n🤖 Sending {len(sorted_candidates)} page(s) to LLM for correction extraction...")

        max_retries = 3
        correction_map: Dict[str, str] = {}

        for attempt in range(1, max_retries + 1):
            try:
                try:
                    response = self.openrouter.generate_completion(
                        prompt,
                        model=primary_model,
                        max_tokens=max_tokens
                    )
                    used_model = primary_model
                except Exception as e:
                    print(f"  [WARN] Primary model failed: {e}")
                    print(f"  [INFO] Retrying with fallback: {fallback_model}")
                    response = self.openrouter.generate_completion(
                        prompt,
                        model=fallback_model,
                        max_tokens=max_tokens
                    )
                    used_model = fallback_model

                content = response["content"]
                if not content:  # Guard: model returned None/empty body
                    raise ValueError("Model returned empty content (None).")

                # Track cost
                cost = response.get('cost', 0.0) or self.openrouter.estimate_cost(used_model, response["usage"])
                self.cost_tracker.log_api_call("step6_all_pages_scan", used_model, response["usage"], cost)
                print(f"   💰 API call cost: ${cost:.4f}")

                # Parse JSON — strip markdown fences if present
                content_clean = re.sub(r'```(?:json)?\s*', '', content)
                content_clean = re.sub(r'```\s*', '', content_clean).strip()

                # Find outermost JSON object
                start = content_clean.find('{')
                end   = content_clean.rfind('}')
                if start == -1 or end == -1:
                    raise ValueError("No JSON object found in model response.")

                raw_map: Dict = json.loads(content_clean[start:end + 1])

                # Normalise: keys → str, values → uppercase A-E only
                for k, v in raw_map.items():
                    clean_v = ''.join(c for c in str(v).upper() if c in 'ABCDE')
                    if clean_v:
                        correction_map[str(k)] = clean_v

                print(f"   ✅ Attempt {attempt}: parsed {len(correction_map)} corrections from JSON.")
                break  # success

            except json.JSONDecodeError as e:
                print(f"   ⚠️  Attempt {attempt}: JSON parse error — {e}")
                if attempt == max_retries:
                    print("   ❌ All retries failed. No corrections applied.")
            except Exception as e:
                print(f"   ❌ Attempt {attempt}: API error — {e}")
                if attempt == max_retries:
                    print("   ❌ Giving up after max retries.")

        if not correction_map:
            print("⚠️  No corrections extracted — returning QCMs unchanged.")
            return qcms

        # ── 7. Apply corrections to QCMs ──────────────────────────────
        applied = 0
        for qcm in qcms:
            qnum = str(qcm.get('Num') or qcm.get('number') or '')
            if qnum in correction_map:
                qcm['Correct'] = correction_map[qnum]
                applied += 1

        print(f"\n✅ [all_pages] Applied {applied}/{len(qcms)} corrections.")

        # Log unmatched corrections for debugging
        qcm_num_set = {str(q.get('Num') or q.get('number') or '') for q in qcms}
        unmatched = [k for k in correction_map if k not in qcm_num_set]
        if unmatched:
            print(f"   ℹ️  {len(unmatched)} corrections found for questions not in QCM list: {unmatched[:10]}")

        return qcms

    def _score_correction_page(self, text: str) -> int:
        """
        Heuristic score for how likely a page contains correction data.
        Higher score = more likely to be a correction page.
        """
        t = text.lower()
        score = 0

        # Strong correction keywords
        strong_keywords = ['corrigé', 'correction', 'answer key', 'clé de correction']
        score += sum(20 for kw in strong_keywords if kw in t)

        # Moderate keywords
        moderate_keywords = ['réponse', 'réponses', 'rep.', 'answers']
        score += sum(10 for kw in moderate_keywords if kw in t)

        # X-table signature: | A | B | C | D | E |
        if re.search(r'\|\s*a\s*\|\s*b\s*\|\s*c', t, re.I):
            score += 40  # Very strong signal

        # Answer-list patterns: "1: BCE", "1. ab", "Q1 → ACD"
        list_matches = len(re.findall(r'\d{1,3}\s*[:\.\-→]\s*[a-e]{1,5}', t))
        score += min(list_matches * 5, 50)  # Cap at 50 from this source

        # Uppercase letter-group patterns like "1 ACE"
        upper_matches = len(re.findall(r'\b\d{1,3}\s+[A-E]{1,5}\b', text))
        score += min(upper_matches * 4, 40)

        return score

    def _validate_correction_alignment(self, qcms: List[Dict], correction_map: Dict) -> Dict:
        """
        Check alignment between QCM numbers and correction map keys.
        Works with both int and str keys (normalises internally).

        FIX 2: Handles str or int keys uniformly.
        """
        qcm_nums_str = set()
        for q in qcms:
            num = q.get('Num') or q.get('number')
            if num is not None and str(num).isdigit():
                qcm_nums_str.add(str(num))

        correction_keys_str = {str(k) for k in correction_map.keys()}

        if not qcm_nums_str:
            return {"status": "error", "message": "No valid QCM numbers found.", "score": 0.0}

        matches = len(qcm_nums_str & correction_keys_str)
        alignment_score = matches / len(qcm_nums_str)

        drift = alignment_score < 0.8 and matches > 0
        if drift:
            print(f"⚠️  Correction drift detected! Alignment: {alignment_score*100:.1f}%")
            qcm_sorted = sorted(int(n) for n in qcm_nums_str)
            cor_sorted = sorted(int(k) for k in correction_keys_str if k.isdigit())
            if qcm_sorted:
                print(f"   QCMs ask for:       {min(qcm_sorted)} → {max(qcm_sorted)}")
            if cor_sorted:
                print(f"   Corrections cover:  {min(cor_sorted)} → {max(cor_sorted)}")

        return {
            "status": "warning" if drift else "ok",
            "score": alignment_score,
            "drift_detected": drift,
            "qcm_count": len(qcm_nums_str),
            "correction_count": len(correction_keys_str)
        }

    def _apply_corrections_with_fallback(self, qcms: List[Dict], correction_map: Dict) -> int:
        """
        Applies corrections using exact match first.

        FIX 2: All correction_map keys are normalised to str before reaching here.
        FIX 3: Index fallback is ONLY used when alignment score >= 0.9 (almost
                perfect match), preventing silent corruption when regex grabbed a
                partial/wrong set of corrections.
        """
        # FIX 2: Normalise all keys to str defensively (belt-and-suspenders)
        str_map: Dict[str, str] = {str(k): str(v) for k, v in correction_map.items()}

        alignment = self._validate_correction_alignment(qcms, str_map)
        alignment_score = alignment.get('score', 0.0)

        # FIX 3: Only allow index fallback when nearly all QCMs matched by number
        use_index_fallback = alignment_score >= 0.9
        if use_index_fallback:
            print(f"   ℹ️  Alignment score {alignment_score*100:.1f}% — index fallback ENABLED for missing entries.")
        else:
            print(f"   ℹ️  Alignment score {alignment_score*100:.1f}% — index fallback DISABLED (too risky).")

        applied_count = 0
        correction_keys = sorted(str_map.keys(), key=lambda x: int(x) if x.isdigit() else 0)

        for i, qcm in enumerate(qcms):
            raw_num = qcm.get('Num') or qcm.get('number')
            qcm_key = str(raw_num) if raw_num is not None else ''
            applied = False

            # 1. FIX 2: Exact match — both sides are now str
            if qcm_key and qcm_key in str_map:
                qcm['Correct'] = str_map[qcm_key]
                applied = True

            # 2. FIX 3: Opt-in index fallback (only when alignment is high)
            if not applied and use_index_fallback and i < len(correction_keys):
                fallback_key = correction_keys[i]
                qcm['Correct'] = str_map[fallback_key]
                applied = True
                print(f"   🔄 Fallback: QCM #{qcm_key} (index {i}) → correction key {fallback_key}")

            if applied:
                applied_count += 1

        return applied_count

    def _parse_x_table_corrections(self, text: str) -> Dict[str, str]:
        """Parse markdown tables with X marks (e.g., | 1 |   | X | X |   | X |).

        FIX 2: Returns Dict[str, str] — keys are string question numbers.
        """
        correction_map: Dict[str, str] = {}
        lines = text.strip().split('\n')

        in_table = False
        columns: Dict[int, str] = {}  # e.g. {1: 'A', 2: 'B'}

        for line in lines:
            line = line.strip()
            if not line.startswith('|') or not line.endswith('|'):
                continue

            cells = [cell.strip() for cell in line.split('|')[1:-1]]

            # Detect header row: e.g. | | A | B | C | D | E |
            # Also accept lowercase headers (a, b, c…)
            upper_cells = [c.upper() for c in cells]
            if 'A' in upper_cells and 'B' in upper_cells:
                for i, cell in enumerate(cells):
                    if cell.upper() in ('A', 'B', 'C', 'D', 'E'):
                        columns[i] = cell.upper()
                in_table = True
                continue

            # Skip separator row: e.g. |---|---|---|
            if '---' in line:
                continue

            # Process data rows
            if in_table and columns and len(cells) > 1:
                q_num_str = cells[0].strip()
                if not q_num_str.isdigit():
                    continue

                answer = ""
                for i in range(1, len(cells)):
                    if i in columns:
                        marker = cells[i].strip().upper()
                        if marker in ('X', '1', 'V', 'O', '✓', '✔'):
                            answer += columns[i]

                if answer:
                    # FIX 2: str key
                    correction_map[q_num_str] = ''.join(sorted(answer))

        return correction_map

    def _auto_detect_correction_pages(self) -> List[int]:
        """
        Scan all accepted text files for correction signature.
        Returns sorted list of page numbers.
        """
        if self.context:
            step1_dir = self.context.get_path("step1_extraction", "accepted")
        else:
            step1_dir = Path("output/step1_extraction/accepted")
            
        if not step1_dir.exists():
            return []
            
        candidates = []
        for txt_file in sorted(step1_dir.glob("page_*.txt")):
            try:
                page_num = int(re.search(r'page_(\d+)', txt_file.name).group(1))
                with open(txt_file, 'r', encoding='utf-8') as f:
                    text = f.read().lower()
                
                # Heuristic Score
                score = 0
                # Keywords
                keywords = ['corrigé', 'correction', 'réponse', 'rep.', 'answers', 'clé', 'answer key']
                score += sum(15 for kw in keywords if kw in text)
                
                # X-table signature: header with | A | B | C | D | E |
                if re.search(r'\|\s*a\s*\|\s*b\s*\|\s*c', text, re.I):
                    score += 40  # Strong signal
                
                # Patterns like "1. A", "10. BC"
                patterns = len(re.findall(r'\d{1,3}\s*[\.:\-\s]\s*[a-e]{1,5}', text))
                score += min(patterns * 5, 50) # Cap at 50
                
                if score >= 40:
                    candidates.append((page_num, score))
            except:
                continue
        
        # Sort by score and then page number
        candidates.sort(key=lambda x: x[1], reverse=True)
        # Return pages that passed the threshold
        return [c[0] for c in candidates[:5]] # Top 5 candidates

    def _parse_page_input(self, page_input: str) -> List[int]:
        """Parse strings like '5', '4,5,6', '4-10', '4:10' into list of ints."""
        if not page_input:
            return []

        pages = set()
        # normalize: replace colons with dashes for range parsing
        page_input = page_input.replace(':', '-').replace(' ', '')
        parts = page_input.split(',')

        for part in parts:
            if '-' in part:
                try:
                    start, end = map(int, part.split('-', 1))
                    pages.update(range(start, end + 1))
                except Exception:
                    continue
            elif part.isdigit():
                pages.add(int(part))

        return sorted(list(pages))

    def _extract_corrections_with_ai(self, correction_text: str, qcms: List[Dict], guidance: str = None) -> List[Dict]:
        """AI-powered correction parsing.

        FIX 1: Removed the 5000-character truncation cap — Gemini has 1M context.
        FIX 2: Applies corrections using str QCM keys for reliable matching.
        """
        print("🧠 Using AI to parse correction table...")

        expected_nums = sorted(
            [str(q.get('Num') or q.get('number')) for q in qcms],
            key=lambda x: int(x) if x.isdigit() else 0
        )

        guidance_line = f"GUIDANCE: {guidance}" if guidance else ""

        prompt = f"""You are a medical QCM correction extraction specialist.
Extract EVERY question number and its correct answer letter(s) from the text below.
The answers may be in uppercase OR lowercase — normalise to uppercase.
{guidance_line}

EXPECTED QUESTIONS ({len(expected_nums)} total): {", ".join(expected_nums)}

Return ONLY valid JSON — a flat object mapping question number strings to answer letter strings.
Example: {{"10": "ACE", "11": "BCD", "12": "A"}}
Do NOT wrap in a 'corrections' key. Do NOT add any explanation.

TEXT:
{correction_text}
"""
        # FIX 1: No [:5000] truncation — send full text to the model

        primary_model = os.getenv("STEP6_TEXT_MODEL", "nvidia/nemotron-3-nano-30b-a3b:free")
        fallback_model = os.getenv("STEP6_TEXT_FALLBACK_MODEL", "google/gemini-2.0-flash-lite-001")
        max_tokens = int(os.getenv("STEP6_TEXT_MAX_TOKENS", "4000"))
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                try:
                    response = self.openrouter.generate_completion(prompt, model=primary_model, max_tokens=max_tokens)
                    model_used = primary_model
                except Exception as e:
                    print(f"⚠️ Primary model failed: {e}")
                    print(f"🔄 Retrying with fallback: {fallback_model}...")
                    response = self.openrouter.generate_completion(prompt, model=fallback_model, max_tokens=max_tokens)
                    model_used = fallback_model

                content = response["content"]
                if not content:  # Guard: model returned None/empty body
                    raise ValueError("Model returned empty content (None).")
                content = content.strip()
                cost = response.get('cost', 0.0) or self.openrouter.estimate_cost(model_used, response["usage"])
                self.cost_tracker.log_api_call("step6_ai_parse", model_used, response["usage"], cost)

                # Parse JSON — strip markdown fences
                content_clean = re.sub(r'```(?:json)?\s*', '', content)
                content_clean = re.sub(r'```\s*', '', content_clean).strip()
                start = content_clean.find('{')
                end   = content_clean.rfind('}')

                if start != -1 and end != -1:
                    raw = json.loads(content_clean[start:end + 1])
                    # Support both flat map and legacy {"corrections": {...}}
                    corrections: Dict = raw.get('corrections', raw) if isinstance(raw, dict) else {}

                    applied = 0
                    for qcm in qcms:
                        # FIX 2: str key lookup
                        q_key = str(qcm.get('Num') or qcm.get('number') or '')
                        if q_key in corrections:
                            cleaned = ''.join(re.findall(r'[A-E]', str(corrections[q_key]).upper()))[:5]
                            if cleaned:
                                qcm['Correct'] = cleaned
                                applied += 1

                    print(f"   ✅ Attempt {attempt+1}: {applied}/{len(qcms)} corrections applied via AI.")

                    if applied >= len(qcms) * 0.9:
                        break  # Good enough — exit retry loop
                    elif attempt < max_retries - 1:
                        print(f"   ⚠️ Coverage below 90%, retrying...")
                    else:
                        print(f"   ⚠️ Final attempt: {applied}/{len(qcms)} corrections.")
                else:
                    print(f"   ⚠️ Attempt {attempt+1}: no JSON object found in response. Retrying...")

            except json.JSONDecodeError as e:
                print(f"   ⚠️ Attempt {attempt+1}: JSON parse error — {e}")
            except Exception as e:
                print(f"   ❌ Attempt {attempt+1}: API error — {e}")
                if attempt == max_retries - 1:
                    print("   ❌ Giving up after max retries.")
                    break

        return qcms

    def _find_in_extracted_data(self, qcms: List[Dict]) -> List[Dict]:
        """Automatically find correction pages in Step 1 subfolder."""
        if self.context:
            step1_dir = self.context.get_path("step1_extraction", "accepted")
        else:
            step1_dir = Path("output/step1_extraction/accepted")
            
        print(f"🔍 Searching for correction sheets in {step1_dir}...")
        
        if not step1_dir.exists():
            print(f"❌ Directory not found: {step1_dir}")
            return qcms
            
        for txt_file in sorted(step1_dir.glob("*.txt")):
            with open(txt_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Simple heuristic for correction page
            if any(kw in content.lower() for kw in ['corrigé', 'correction', 'réponse', 'rep.']):
                print(f"✨ Found potential correction page: {txt_file.name}")
                # Use standard extraction logic
                self._apply_corrections_from_text(content, qcms)
        
        return qcms

    def _apply_corrections_from_text(self, text: str, qcms: List[Dict]) -> int:
        """Heuristic-based patterns to find corrections in text blocks."""
        matches = re.findall(r'(\d{1,3})\s+([A-E]{1,5})', text)
        correction_map = {int(n): c for n, c in matches}
        
        applied = 0
        for qcm in qcms:
            num = qcm.get('Num') or qcm.get('number')
            if num and int(num) in correction_map:
                qcm['Correct'] = correction_map[int(num)]
                applied += 1
        return applied

    def _detect_highlights_vision(self, qcms: List[Dict], pdf_path: str, custom_prompt: str = None) -> List[Dict]:
        """
        Vision AI detection: Orchestrates model selection, prompt gathering,
        and page-by-page processing with interactive review.
        """
        print("\n" + "-"*40)
        print("👁️ VISION CORRECTION DETECTION MODE")
        print("-"*40)

        # 1. Model selection
        model = self._select_vision_model()
        
        # 2. Get user prompt
        if custom_prompt:
            user_prompt = custom_prompt
            print(f"\n📝 Using Custom Prompt: {user_prompt}")
        else:
            user_prompt = self._get_vision_prompt()
        
        # 3. Load PDF as images
        print(f"\n📂 Loading PDF: {pdf_path}...")
        doc_processor = DocumentProcessor(pdf_path)
        pages = doc_processor.load_document()
        if not pages:
            print("❌ No pages found in PDF.")
            return qcms
            
        # 4. Get page range and batch size
        start, end, batch_size = self._get_page_range(len(pages))
        
        # 5. Process pages
        raw_results = self._process_vision_pages(pages, user_prompt, model, start, end, batch_size)
        
        if not raw_results:
            print("⚠️ No results captured from vision processing.")
            return qcms
            
        # 6. Save raw results for reference
        self._save_vision_results(raw_results)
        
        # 7. Link corrections to QCMs using DeepSeek
        return self._link_corrections_to_qcms(raw_results, qcms)

    def _select_vision_model(self) -> str:
        """Let user select which vision model to use."""
        print("\nSelect Vision AI Model:")
        print("  1. google/gemini-2.0-flash-lite-001 (Fast/High Quality)")
        print("  2. qwen/qwen-2.5-vl-7b-instruct:free (Free)")
        choice = input("Choice [1-2]: ").strip()
        
        if choice == "1":
            return "google/gemini-2.0-flash-lite-001"
        return "qwen/qwen-2.5-vl-7b-instruct:free"

    def _get_vision_prompt(self) -> str:
        """Get custom prompt from the user for extraction."""
        print("\n📝 Describe what you want the AI to extract from each page.")
        print("   TIP: Ask for JSON for easier processing.")
        print("   Example: 'Identify all question numbers and their highlighted answers. Return JSON: {num: answer}'")
        return input("\nYour prompt: ").strip()

    def _get_page_range(self, total_pages: int) -> tuple:
        """Get range of pages and batch size for processing."""
        print(f"\n📄 Total pages found: {total_pages}")
        print("Options:")
        print("  - Press Enter for ALL pages (1 per batch)")
        print("  - Enter range like '2-5' for specific pages")
        print("  - Enter batch size (e.g., '2') to process 2 pages together")
        
        choice = input("\nChoice: ").strip()
        
        if not choice:
            return (1, total_pages, 1)
        elif "-" in choice:
            try:
                start, end = map(int, choice.split("-"))
                return (start, max(start, min(end, total_pages)), 1)
            except:
                return (1, total_pages, 1)
        else:
            try:
                batch_size = int(choice)
                return (1, total_pages, max(1, batch_size))
            except:
                return (1, total_pages, 1)

    def _process_vision_pages(self, pages, prompt, model, start, end, batch_size) -> List[Dict]:
        """Page-by-page loop with interactive review."""
        all_results = []
        i = start - 1
        
        while i < end:
            batch_end = min(i + batch_size, end)
            batch_pages = pages[i:batch_end]
            p_label = f"{i+1}" if batch_size == 1 else f"{i+1}-{batch_end}"
            
            print(f"\n🔍 Processing Page {p_label}/{end}...")
            
            try:
                resp = self.vision.generate_completion(prompt, batch_pages, model=model)
                content = resp["content"]
                
                # Update cost tracker
                cost = resp.get('cost', 0.0) or self.vision.estimate_cost(model, resp["usage"])
                self.cost_tracker.log_api_call(f"step6_vision_p{p_label}", model, resp["usage"], cost)
                
                print(f"\nAI Response (Page {p_label}):")
                print("-" * 30)
                print(content[:800] + ("..." if len(content) > 800 else ""))
                print("-" * 30)
                
                choice = input("\n[A]ccept | [R]etry with new prompt | [S]kip page: ").lower().strip()
                
                if choice == 'a':
                    all_results.append({"pages": p_label, "data": content})
                elif choice == 'r':
                    prompt = input("Adjusted prompt: ").strip()
                    continue # Retry same batch
                elif choice == 's':
                    print(f"Skipped page {p_label}")
            except Exception as e:
                print(f"❌ Error on page {p_label}: {e}")
                if input("Try next page? [y/n]: ").lower() != 'y':
                    break
            
            i = batch_end
            
        return all_results

    def _save_vision_results(self, results: List[Dict]):
        """Save results to file."""
        path = Path("output/step6_corrections/vision_raw_results.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Raw vision results saved to {path}")

    def _link_corrections_to_qcms(self, vision_results: List[Dict], qcms: List[Dict]) -> List[Dict]:
        """Use DeepSeek to map the results back to the QCMs."""
        print("\n🔗 Linking vision detections to QCM numbers...")
        
        # Combine all vision text
        combined_vision = "\n\n".join([f"PAGE {r['pages']}:\n{r['data']}" for r in vision_results])
        
        default_linking_prompt = f"""Apply these corrections from the vision output to the correct QCM numbers.

VISION DETECTIONS:
{combined_vision}

QCMs TO CORRECT:
{len(qcms)} questions found in database.

TASK: Return a JSON mapping of QCM number to correct letter(s).
Format: {{"10": "ACE", "11": "BD"}}"""

        print("\nDefault Linking Prompt:")
        print("-" * 40)
        print(default_linking_prompt[:500] + "...")
        print("-" * 40)
        
        choice = input("\n[U]se default | [E]dit | [N]ew prompt: ").lower().strip()
        
        if choice == 'e':
            print("Edit current prompt (base provided above):")
            linking_prompt = input("Your prompt: ").strip()
        elif choice == 'n':
            linking_prompt = input("Enter new instruction for DeepSeek: ").strip()
        else:
            linking_prompt = default_linking_prompt
            
        try:
            # We call DeepSeek for this summary step
            resp = self.deepseek.generate_completion(linking_prompt)
            content = resp["content"]
            
            # Parse JSON map
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                corrections = json.loads(match.group(0))
                
                applied = 0
                for qcm in qcms:
                    q_num = str(qcm.get('Num') or qcm.get('number'))
                    if q_num in corrections:
                        qcm['Correct'] = corrections[q_num]
                        applied += 1
                
                print(f"✅ Successfully linked {applied} corrections.")
            else:
                print("❌ Could not parse mapping JSON from AI response.")
        except Exception as e:
            print(f"❌ Linking failed: {e}")
            
        return qcms

    def _gap_analysis(self, qcms: List[Dict]):
        """
        Analyse which QCMs have a correction and which do not.
        Returns (corrected: List[Dict], uncorrected: List[Dict]).
        Prints a summary table.
        """
        corrected = [q for q in qcms if q.get('Correct', '').strip()]
        uncorrected = [q for q in qcms if not q.get('Correct', '').strip()]

        print(f"\n📊 Correction Coverage:")
        print(f"   ✅ Corrected  : {len(corrected)} / {len(qcms)}")
        if uncorrected:
            nums = [str(q.get('Num') or q.get('number', '?')) for q in uncorrected[:15]]
            suffix = ", ..." if len(uncorrected) > 15 else ""
            print(f"   ❌ Missing    : {len(uncorrected)}  (Q{', Q'.join(nums)}{suffix})")
        else:
            print("   🎉 All QCMs have corrections!")

        return corrected, uncorrected

    def _by_page_correction_flow(self, qcms: List[Dict]) -> List[Dict]:
        """
        Source 6: Process pages one-by-one, then enter a gap-analysis loop.

        Loop:
          1. Ask which pages to process (all / specific like 1,2,5:9,11)
          2. Run _extract_single_page_corrections() for each page
          3. Apply collected corrections to QCMs
          4. Run _gap_analysis()
          5. If gaps remain, offer recovery options:
               a. Run on more pages
               b. AI Knowledge for uncorrected only
               c. Manual Entry for uncorrected only
               d. Skip (save as-is)
        """
        print("\n" + "="*60)
        print("BY PAGE CORRECTION MODE")
        print("="*60)

        # Step A — Determine which pages to scan
        if self.context:
            step1_dir = self.context.get_path("step1_extraction", "accepted")
        else:
            step1_dir = Path("output/step1_extraction/accepted")

        available_pages = []
        if step1_dir.exists():
            for p in sorted(step1_dir.glob("page_*.txt")):
                m = re.search(r'page_(\d+)', p.name)
                if m:
                    available_pages.append(int(m.group(1)))

        if available_pages:
            print(f"\n📂 Available pages: {available_pages[0]}–{available_pages[-1]} ({len(available_pages)} total)")
        else:
            print("⚠️  No page files found.")
            return qcms

        print("Enter pages to scan:")
        print("  • 'all'       → every available page")
        print("  • '1,2,5:9'   → pages 1, 2, and 5 through 9")
        pages_input = input("Pages: ").strip().lower()

        if pages_input == 'all':
            page_numbers = available_pages
        else:
            page_numbers = self._parse_page_input(pages_input)
            page_numbers = [p for p in page_numbers if p in available_pages]

        if not page_numbers:
            print("❌ No valid pages specified.")
            return qcms

        print(f"\n🔄 Processing {len(page_numbers)} page(s) individually...")

        # Step B — Per-page extraction
        def _run_pages(page_list: List[int], existing_map: Dict[str, str]) -> Dict[str, str]:
            """Run extraction on a list of pages and merge into existing_map."""
            for page_num in page_list:
                if self.context:
                    file_path = self.context.get_path("step1_extraction", "accepted") / f"page_{page_num}.txt"
                else:
                    file_path = Path(f"output/step1_extraction/accepted/page_{page_num}.txt")

                if not file_path.exists():
                    print(f"   ⚠️  Not found: {file_path.name}")
                    continue

                print(f"\n   📄 Page {page_num}:")
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                page_map = self._extract_single_page_corrections(content, page_num)
                if page_map:
                    existing_map.update(page_map)
                    print(f"   → +{len(page_map)} corrections. Total map: {len(existing_map)}")
                else:
                    print(f"   → No corrections found.")
            return existing_map

        correction_map: Dict[str, str] = {}
        correction_map = _run_pages(page_numbers, correction_map)

        # Step C — Apply corrections
        if correction_map:
            applied = self._apply_corrections_with_fallback(qcms, correction_map)
            print(f"\n✅ Applied {applied}/{len(qcms)} corrections.")
        else:
            print("\n⚠️  No corrections found in specified pages.")

        # Step D — Gap analysis + recovery loop
        while True:
            corrected, uncorrected = self._gap_analysis(qcms)

            if not uncorrected:
                print("\n🎉 All QCMs corrected — done!")
                break

            print(f"\n⚠️  {len(uncorrected)} QCMs still have no correction.")
            print("What would you like to do?")
            print("  1. Run on additional pages (enter new page numbers)")
            print("  2. AI Knowledge for uncorrected QCMs only (DeepSeek R1)")
            print("  3. Manual Entry for uncorrected QCMs only")
            print("  4. Skip — save as-is")
            recovery = input("Choice [1-4]: ").strip()

            if recovery == "1":
                more_input = input("Enter additional pages (e.g. 7,8 or 10:12): ").strip()
                more_pages = self._parse_page_input(more_input)
                more_pages = [p for p in more_pages if p in available_pages]
                if not more_pages:
                    print("❌ No valid pages entered.")
                    continue
                correction_map = _run_pages(more_pages, correction_map)
                if correction_map:
                    applied = self._apply_corrections_with_fallback(qcms, correction_map)
                    print(f"✅ Applied {applied}/{len(qcms)} corrections after extra pages.")

            elif recovery == "2":
                print(f"\n🧠 Running AI Knowledge on {len(uncorrected)} uncorrected QCMs...")
                # _apply_ai_knowledge mutates the list items in-place (dicts are references)
                # so changes to uncorrected items propagate to qcms automatically.
                # We pass a copy of uncorrected so the list structure isn't reordered.
                ai_result = self._apply_ai_knowledge(list(uncorrected), auto_mode=False, ai_mode=None)
                # Merge back: map by question number then write into main qcms list
                ai_map = {
                    str(q.get('Num') or q.get('number', '')): q.get('Correct', '')
                    for q in ai_result if q.get('Correct', '').strip()
                }
                for qcm in qcms:
                    key = str(qcm.get('Num') or qcm.get('number', ''))
                    if key in ai_map and not qcm.get('Correct', '').strip():
                        qcm['Correct'] = ai_map[key]

            elif recovery == "3":
                print(f"\n✏️  Manual Entry for {len(uncorrected)} uncorrected QCMs:")
                self._manual_entry(uncorrected)
                # Merge back
                for q_unc in uncorrected:
                    key = str(q_unc.get('Num') or q_unc.get('number', ''))
                    for qcm in qcms:
                        if str(qcm.get('Num') or qcm.get('number', '')) == key:
                            qcm['Correct'] = q_unc.get('Correct', '')
                            break

            else:
                print("⏭️  Skipping remaining uncorrected QCMs.")
                break

        return qcms

    def _manual_entry(self, qcms: List[Dict]) -> List[Dict]:
        """Manual entry for each QCM."""
        for i, qcm in enumerate(qcms, 1):
            num = qcm.get('Num') or qcm.get('number') or i
            print(f"\nQ{num}: {(qcm.get('Text') or qcm.get('text') or '')[:100]}...")
            correction = input("Enter correction (e.g. ABC): ").strip().upper()
            qcm["Correct"] = correction
        return qcms
