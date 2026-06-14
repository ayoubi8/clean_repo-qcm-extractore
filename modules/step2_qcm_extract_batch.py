import json
import os
import re
from pathlib import Path
from typing import Dict, List, Any

from modules.openrouter_client import OpenRouterClient
from modules.utils.cost_tracker import CostTracker
from modules.utils.prompt_helper import PromptHelper
from modules.utils.file_manager import FileManager


class Step2QCMExtractBatch:
    """
    v7.0 - Batch Extraction (All Pages at Once)
    
    Processes ALL pages in a single LLM call to:
    - Eliminate split QCM problems (LLM sees full context)
    - Faster processing (1 call instead of N calls)
    - More accurate (better context understanding)
    
    Smart fallback: Gemma (free) → Gemini Flash Lite (if too large)
    """
    
    def __init__(self, cost_tracker: CostTracker, project_context=None):
        self.client = OpenRouterClient()
        self.cost_tracker = cost_tracker
        self.file_manager = FileManager()
        self.prompt_helper = PromptHelper()
        self.context = project_context

    @staticmethod
    def _safe_int(value, default: int = 0) -> int:
        """Safely convert a value to int, returning default on None/invalid."""
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
        
    def run(self, input_dir: str = None, page_range: str = None, config: Dict = None) -> Dict:
        """Main execution for Step 2 - Batch mode."""
        print("\n" + "="*60)
        print("STEP 2: BATCH QCM EXTRACTION (v7.0 - All Pages)")
        print("="*60)
        
        # Determine input directory
        if self.context:
            target_input_dir = self.context.get_path("step1_extraction", "accepted")
        else:
            target_input_dir = input_dir if input_dir else "output/step1_extraction/accepted"
            
        txt_files = sorted(
            Path(target_input_dir).glob("*.txt"),
            key=lambda x: self._safe_int(self._extract_page_number(x.name))
        )
        
        if not txt_files:
            print(f"❌ No text files found in {target_input_dir}")
            return {"total_extracted": 0}
            
        print(f"📄 Found {len(txt_files)} pages")
        
        # NEW: Check for pre-extracted corrections (Standalone Step 6)
        correction_map = self._load_correction_map()
        if correction_map:
            print(f"✨ Found {len(correction_map)} pre-extracted corrections. Will apply them.")
        
        # Handle page range
        if not page_range:
            print(f"\n📋 Page range: 1-{len(txt_files)}")
            print(f"   Options:")
            print(f"   • '1-{len(txt_files)}'  → single batch (all pages at once)")
            print(f"   • '1-5'         → single batch (pages 1–5 only)")
            print(f"   • '3-3-3'       → auto-loop: 3 pages per chunk")
            print(f"   • '5-5-5'       → auto-loop: 5 pages per chunk")
            print(f"   • '1-1-1'       → auto-loop: 1 page per chunk (safest)")
            page_range = input(f"\nYour choice: ").strip()
        else:
            print(f"\n📋 [AUTO] Using page range: {page_range}")
        
        # Parse range
        loop_match = re.match(r'^(\d+)-\1-\1$', page_range.strip())
        
        if loop_match:
            chunk_size = int(loop_match.group(1))
            total_extracted = self._run_loop_mode(txt_files, chunk_size, correction_map, config)
            print(f"\n✅ Step 2 Complete. Total new/updated QCMs in this loop run: {total_extracted}")
            return {"total_extracted": total_extracted}
        else:
            start_page, end_page = self._parse_page_range(page_range, len(txt_files))
            
            # Select files
            selected_files = [f for f in txt_files 
                             if start_page <= self._extract_page_number(f.name) <= end_page]
            
            print(f"[INFO] Processing pages {start_page}-{end_page} ({len(selected_files)} pages)")
            
            # Concatenate all pages
            full_text = self._concatenate_pages(selected_files)
            
            print(f"[INFO] Total text: {len(full_text)} characters")
            
            # Extract all QCMs in one call
            all_qcms = self._extract_all_qcms_batch(full_text, start_page, end_page, config)
            
            if not all_qcms:
                print("❌ No QCMs extracted")
                return {"total_extracted": 0}
                
            # Post-processing: Guarantee every QCM has a valid 'page' field
            all_qcms = self._stamp_pages(all_qcms, selected_files)
            # NEW: Apply corrections if we have them
            if correction_map:
                applied = 0
                for qcm in all_qcms:
                    qnum = str(qcm.get('number'))
                    if qnum in correction_map:
                        qcm['Correct'] = correction_map[qnum]
                        applied += 1
                print(f"✅ Applied {applied} corrections to extracted QCMs.")
            
            # INTEGRITY CHECK: detect and fix incomplete QCMs
            all_qcms = self._apply_incomplete_fix(all_qcms, txt_files, config)
            
            # Save results (Accumulate safe)
            self._save_batch_results_accumulate(all_qcms)
            
            print(f"\n✅ Step 2 Complete. Total new/updated QCMs in this run: {len(all_qcms)}")
            return {"total_extracted": len(all_qcms)}


    def _load_correction_map(self) -> Dict:
        """Load pre-extracted corrections if available."""
        if self.context:
            map_file = self.context.get_path("step6_corrections") / "correction_map.json"
        else:
            map_file = Path("output/step6_corrections/correction_map.json")
            
        if map_file.exists():
            try:
                with open(map_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _parse_page_range(self, range_str: str, max_pages: int) -> tuple:
        """Parse page range string like '1-6' or '1-5'."""
        if not range_str:
            return 1, max_pages
        
        try:
            if '-' in range_str:
                start, end = range_str.split('-')
                return int(start.strip()), int(end.strip())
            else:
                page = int(range_str.strip())
                return page, page
        except:
            print(f"[WARN] Invalid range '{range_str}', using all pages")
            return 1, max_pages
    
    def _concatenate_pages(self, files: List[Path]) -> str:
        """Concatenate all page texts with clear separators."""
        parts = []
        
        for file in files:
            page_num = self._extract_page_number(file.name)
            try:
                text = file.read_text(encoding='utf-8')
                parts.append(f"=== PAGE {page_num} ===\n{text}")
            except Exception as e:
                print(f"[WARN] Error reading {file.name}: {e}")
        
        return "\n\n".join(parts)
    
    def _extract_all_qcms_batch(self, full_text: str, start_page: int, end_page: int, config: Dict = None) -> List[Dict]:
        """Extract all QCMs using batch LLM call with smart fallback."""
        
        # Pull extraction guidance if provided in config
        guidance = "- If metadata markers (e.g. year ->YYYY, subcategory **bold**) appear before a question, extract them into 'year' and 'subcategory' fields."
        if config and "qcm_extraction" in config and "extraction_guidance" in config["qcm_extraction"]:
            guidance = config["qcm_extraction"]["extraction_guidance"]

        # Phase 2: clinical_case_hint — lightweight signal for Step 3 Cas Clinique detection
        cc_hint_enabled = False
        if config and "qcm_extraction" in config:
            cc_hint_enabled = config["qcm_extraction"].get("clinical_case_hints", False)

        cc_hint_rule = ""
        cc_hint_format = ""
        if cc_hint_enabled:
            cc_hint_rule = (
                "- If a 'Cas Clinique' (clinical case) header and patient narrative appears immediately "
                "BEFORE this question (not another QCM, but a patient story block), add a field "
                "\"clinical_case_hint\" with the label exactly as written (e.g. \"CAS CLINIQUE 1\"). "
                "Otherwise omit this field entirely."
            )
            cc_hint_format = '\n    "clinical_case_hint": "CAS CLINIQUE 1"  (only if a Cas Clinique precedes this QCM)'

        prompt = f"""Extract ALL QCMs (multiple choice questions) from these pages.

{full_text}

TASK: Extract every QCM with its number, question text, and all propositions.

IMPORTANT RULES:
- The text is divided by markers in the format `=== PAGE X ===`. Each QCM MUST include a "page" field set to X, where X is the number from the `=== PAGE X ===` marker that appears IMMEDIATELY BEFORE the question text.
- If a QCM spans two pages (question on one page, propositions on the next), assign it to the page where the QUESTION TEXT begins.
- QCMs may span across page breaks — merge split QCMs but assign to the page of the question text.
- Number each QCM (1, 2, 3, etc.). Preserve the original question numbers EXACTLY.
- Extract all propositions (a, b, c, d, e).
- Do NOT include Answer Key tables in the output.
{guidance}
{cc_hint_rule}

OUTPUT FORMAT (JSON array):
[
  {{
    "page": 3,
    "number": 1,
    "text": "Question text here?",
    "propositions": {{
      "a": "First proposition",
      "b": "Second proposition",
      "c": "Third proposition",
      "d": "Fourth proposition",
      "e": "Fifth proposition"
    }},
    "year": "2024",
    "subcategory": "Example Subcategory"{cc_hint_format}
  }}
]
("page" is REQUIRED for every QCM — read it from the `=== PAGE X ===` marker before the question.)
(year, subcategory{', clinical_case_hint' if cc_hint_enabled else ''} are optional, include only if detected.)

Return ONLY the JSON array, no markdown, no explanation.
"""
        
        primary_model = os.getenv("STEP2_MODEL", "google/gemini-2.5-flash-lite-preview-09-2025")
        fallback_model = os.getenv("STEP2_FALLBACK_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
        max_tokens = int(os.getenv("STEP2_MAX_TOKENS", "20000"))
        
        print(f"[API] Trying primary model: {primary_model}...")
        try:
            try:
                response = self.client.generate_completion(
                    prompt, 
                    model=primary_model,
                    max_tokens=max_tokens
                )
                model_used = primary_model
            except Exception as e:
                print(f"[WARN] Primary model failed: {e}")
                print(f"[INFO] Retrying with fallback: {fallback_model}")
                response = self.client.generate_completion(
                    prompt,
                    model=fallback_model,
                    max_tokens=max_tokens
                )
                model_used = fallback_model
                
        except Exception as e2:
            print(f"❌ Both primary and fallback models failed. Final error: {e2}")
            return []
        
        # Parse response
        content = response["content"]
        cost = response.get('cost', 0.0) or self.client.estimate_cost(model_used, response["usage"])
        
        self.cost_tracker.log_api_call(
            f"step2_batch_p{start_page}-{end_page}",
            model_used,
            response["usage"],
            cost
        )
        
        print(f"[OK] Used {model_used} (${cost:.4f})")
        
        # Parse JSON
        qcms = self._parse_json(content)
        
        if qcms:
            print(f"[SUCCESS] Extracted {len(qcms)} QCMs")
            
            # Show preview
            for q in qcms[:3]:
                num = q.get('number', '?')
                text = (q.get('text', '') or '')[:50]
                prop_count = len(q.get('propositions', {}))
                print(f"  Q{num}: {text}... ({prop_count} props)")
            
            if len(qcms) > 3:
                print(f"  ... and {len(qcms)-3} more")
        
        return qcms
    
    def _parse_json(self, content: str) -> List[Dict]:
        """Parse JSON from LLM response."""
        # Remove markdown code blocks
        content = re.sub(r'```json\s*', '', content)
        content = re.sub(r'```\s*', '', content)
        content = content.strip()
        
        # Find JSON array
        start = content.find('[')
        end = content.rfind(']')
        
        if start == -1 or end == -1:
            print(f"[ERROR] No JSON array found in response")
            return []
        
        json_str = content[start:end+1]
        
        try:
            qcms = json.loads(json_str)
            return qcms if isinstance(qcms, list) else []
        except json.JSONDecodeError as e:
            print(f"[ERROR] JSON parse error: {e}")
            return []
    
    def _sanitize_qcms(self, qcms: List[Dict]) -> List[Dict]:
        """
        Ensure every QCM has integer 'page' and 'number' fields.
        Converts None / missing / non-numeric values to 0 to prevent
        TypeError during sorted() comparisons.
        Also warns when number is missing so unusual LLM output is visible.
        """
        for qcm in qcms:
            raw_num = qcm.get('number')
            raw_page = qcm.get('page')
            if raw_num is None or not isinstance(raw_num, int):
                safe_num = self._safe_int(raw_num, default=0)
                if raw_num is None:
                    print(f"  [SANITIZE] QCM with null number on page {raw_page} → assigned number=0 (manual review needed)")
                qcm['number'] = safe_num
            if raw_page is None or not isinstance(raw_page, int):
                qcm['page'] = self._safe_int(raw_page, default=0)
        return qcms

    def _save_batch_results_accumulate(self, new_qcms: List[Dict]):
        """
        Merge new QCMs into existing all_qcms.json using (page, number) as the key.
        - Same (page, number) → update existing entry
        - New (page, number) → add as new entry
        Never deletes QCMs from other page runs.
        """
        if self.context:
            output_dir = self.context.get_path("step2_qcm", "accepted")
        else:
            output_dir = Path("output/step2_qcm/accepted")
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Save as single file
        output_file = output_dir / "all_qcms.json"
        
        # Load existing QCMs
        existing = []
        if output_file.exists():
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
                print(f"[MERGE] Found {len(existing)} existing QCMs in all_qcms.json")
            except Exception as e:
                print(f"[WARN] Could not load existing QCMs: {e}. Starting fresh.")
                existing = []

        # Sanitize both incoming and existing QCMs to guarantee int page/number
        new_qcms  = self._sanitize_qcms(new_qcms)
        existing  = self._sanitize_qcms(existing)

        # Build map keyed by (page, number) — both are guaranteed ints now
        existing_map = {}
        for q in existing:
            key = (q['page'], q['number'])
            existing_map[key] = q

        # Merge new QCMs
        added = 0
        updated = 0
        for qcm in new_qcms:
            key = (qcm['page'], qcm['number'])
            if key in existing_map:
                updated += 1
            else:
                added += 1
            existing_map[key] = qcm

        # Sort by (page, number) — both ints, no more TypeError
        merged = sorted(existing_map.values(), key=lambda q: (q['page'], q['number']))

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        
        print(f"[SAVE] Saved to: {output_file}")
        print(f"💾 Total QCMs in file: {len(merged)}  (+{added} new  |  {updated} updated)")

    
    def _extract_page_number(self, filename: str) -> int:
        """Extract page number from filename."""
        match = re.search(r'page_?(\d+)', filename, re.IGNORECASE)
        return int(match.group(1)) if match else 0
        
    def _stamp_pages(self, qcms: List[Dict], selected_files: List[Path]) -> List[Dict]:
        """
        Ensure every QCM has a valid 'page' field within the chunk's valid range.

        Strategy:
          1. If LLM returned a page within [min_page, max_page] → keep it (correct).
          2. If page is missing, null, 0, or outside the valid range → stamp start_page.
             This guards against LLM hallucinations (e.g. returning page=1 for everything
             even when the chunk spans pages 4-6).
        """
        page_numbers = sorted([self._extract_page_number(f.name) for f in selected_files])
        min_page = page_numbers[0] if page_numbers else 1
        max_page = page_numbers[-1] if page_numbers else min_page

        corrected = 0
        for qcm in qcms:
            p = qcm.get('page')
            if not p or not isinstance(p, int) or p == 0:
                qcm['page'] = min_page   # Missing: stamp start
                corrected += 1
            elif p < min_page or p > max_page:
                # LLM returned a page outside the valid chunk range — correct it
                qcm['page'] = min_page
                corrected += 1
            # else: valid page from LLM, keep it as-is

        if corrected:
            print(f"   [PAGE-STAMP] Corrected {corrected} QCM(s) with missing/invalid page "
                  f"(valid range: {min_page}–{max_page})")

        return qcms

    def _run_loop_mode(self, txt_files: List[Path], chunk_size: int, correction_map: Dict, config: Dict = None) -> int:
        """
        Auto-loop: split all pages into chunks of chunk_size,
        run one LLM call per chunk, accumulate results.
        """
        total_pages = len(txt_files)
        chunks = [txt_files[i:i + chunk_size] for i in range(0, total_pages, chunk_size)]
        total_chunks = len(chunks)

        print(f"\n🔁 AUTO-LOOP MODE: {total_pages} pages → {total_chunks} chunks of {chunk_size}")
        print(f"   Each chunk = 1 LLM call. Results accumulate in all_qcms.json\n")

        total_extracted = 0

        for i, chunk in enumerate(chunks, start=1):
            start_p = self._extract_page_number(chunk[0].name)
            end_p   = self._extract_page_number(chunk[-1].name)
            print(f"\n{'='*60}")
            print(f"📦 Chunk {i}/{total_chunks}: pages {start_p}–{end_p}  ({len(chunk)} pages)")
            print(f"{'='*60}")

            full_text = self._concatenate_pages(chunk)
            qcms = self._extract_all_qcms_batch(full_text, start_p, end_p, config)

            if qcms:
                qcms = self._stamp_pages(qcms, chunk)
                
                # NEW: Apply corrections if we have them
                if correction_map:
                    applied = 0
                    for qcm in qcms:
                        qnum = str(qcm.get('number'))
                        if qnum in correction_map:
                            qcm['Correct'] = correction_map[qnum]
                            applied += 1
                    print(f"✅ Applied {applied} corrections to extracted QCMs.")

                # INTEGRITY CHECK: detect and fix incomplete QCMs
                qcms = self._apply_incomplete_fix(qcms, txt_files, config)

                self._save_batch_results_accumulate(qcms)
                total_extracted += len(qcms)
            else:
                print(f"⚠️  No QCMs extracted for chunk {i} (pages {start_p}–{end_p}). Skipping.")

        print(f"\n✅ AUTO-LOOP COMPLETE — All {total_chunks} chunks processed.")
        return total_extracted

    def _compute_min_prop_threshold(self, qcms: List[Dict]) -> int:
        """
        Dynamically determine the minimum 'normal' proposition count for this batch.
        QCMs with fewer propositions than this threshold are considered incomplete.
        """
        from collections import Counter
        counts = [len(q.get('propositions', {})) for q in qcms if q.get('propositions')]
        if not counts:
            return 4  # safe default
        
        freq = Counter(counts)
        # "Normal" counts = those that appear in >= 2 QCMs (legitimately part of the exam)
        normal_counts = sorted([c for c, n in freq.items() if n >= 2])
        
        if not normal_counts:
            # All QCMs have unique counts — nothing to flag as "abnormally low"
            return min(counts)  
        
        proj_min = normal_counts[0]  # smallest legitimate prop count
        return proj_min

    def _detect_incomplete_qcms(self, qcms: List[Dict], threshold: int) -> List[Dict]:
        """
        Return QCMs whose proposition count is below the project minimum threshold.
        These are candidates for being split across page breaks.
        """
        incomplete = []
        for q in qcms:
            prop_count = len(q.get('propositions', {}))
            if prop_count < threshold:
                incomplete.append(q)
                print(f"  ⚠️  Q{q.get('number')} (page {q.get('page')}) has only {prop_count} props "
                      f"(threshold={threshold}) → flagged for re-extraction")
        return incomplete

    def _reextract_for_incomplete(self, flagged: List[Dict], all_txt_files: List[Path], config: Dict) -> List[Dict]:
        """
        For each incomplete QCM, re-run the LLM on a ±1 page window to capture
        any propositions that spilled onto the adjacent page.
        Returns the list of re-extracted QCMs (may still be incomplete).
        """
        page_map = {self._extract_page_number(f.name): f for f in all_txt_files}
        results = []
        
        for qcm in flagged:
            p = qcm.get('page', 0)
            qnum = qcm.get('number')
            
            # Build expanded window [P-1, P, P+1]
            window_pages = [pg for pg in [p-1, p, p+1] if pg in page_map]
            window_files = [page_map[pg] for pg in window_pages]
            
            print(f"\n  🔄 Re-extracting Q{qnum} (page {p}) using window: pages {window_pages}")
            
            expanded_text = self._concatenate_pages(window_files)
            extracted = self._extract_all_qcms_batch(
                expanded_text,
                min(window_pages), max(window_pages),
                config
            )
            
            # Find the matching QCM by number
            match = next((q for q in extracted if q.get('number') == qnum), None)
            if match and len(match.get('propositions', {})) > len(qcm.get('propositions', {})):
                match['page'] = p  # preserve original page stamp
                results.append(match)
                print(f"  ✅ Q{qnum} now has {len(match['propositions'])} propositions")
            else:
                results.append(qcm)  # keep original if no improvement
                print(f"  ❌ Q{qnum} still incomplete after re-extraction")
        
        return results

    def _save_to_check_bucket(self, qcms: List[Dict], threshold: int):
        """
        Save still-incomplete QCMs to the 'check' bucket for manual review.
        Warn only — does not block the pipeline.
        """
        if self.context:
            check_dir = self.context.get_path("step2_qcm") / "check"
        else:
            check_dir = Path("output/step2_qcm/check")
        check_dir.mkdir(parents=True, exist_ok=True)
        
        still_incomplete = [q for q in qcms if len(q.get('propositions', {})) < threshold]
        
        if not still_incomplete:
            return
        
        check_file = check_dir / "incomplete_qcms.json"
        # Load existing entries to avoid duplicates
        existing = []
        if check_file.exists():
            try:
                with open(check_file, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except:
                existing = []
        
        existing_keys = {(self._safe_int(q.get('page')), self._safe_int(q.get('number'))) for q in existing}
        new_entries = [q for q in still_incomplete
                       if (self._safe_int(q.get('page')), self._safe_int(q.get('number'))) not in existing_keys]
        
        all_entries = existing + new_entries
        with open(check_file, 'w', encoding='utf-8') as f:
            json.dump(all_entries, f, indent=2, ensure_ascii=False)
        
        print(f"\n⚠️  WARNING: {len(still_incomplete)} QCM(s) still incomplete after re-extraction.")
        print(f"   Saved to: {check_file}")
        for q in still_incomplete:
            print(f"   → Q{q.get('number')} (page {q.get('page')}) — {len(q.get('propositions', {}))} props")
        print("   These QCMs are kept in all_qcms.json but need manual review.")

    def _apply_incomplete_fix(self, qcms: List[Dict], all_txt_files: List[Path], config: Dict) -> List[Dict]:
        """
        Full pipeline for detecting and fixing incomplete QCMs.
        Phase 1: Compute dynamic threshold
        Phase 2: Detect incomplete QCMs
        Phase 3: Re-extract on expanded page window
        Phase 4: Save still-incomplete to check bucket (warn only)
        Returns: updated qcms list with improved propositions where possible
        """
        threshold = self._compute_min_prop_threshold(qcms)
        print(f"\n[INTEGRITY] Dynamic proposition threshold for this batch: {threshold}")
        
        flagged = self._detect_incomplete_qcms(qcms, threshold)
        
        if not flagged:
            print("[INTEGRITY] ✅ All QCMs have complete propositions.")
            return qcms
        
        print(f"[INTEGRITY] Found {len(flagged)} incomplete QCM(s). Running re-extraction...")
        
        # Re-extract on ±1 page window
        fixed = self._reextract_for_incomplete(flagged, all_txt_files, config)
        
        # Merge fixed back into main list
        fixed_map = {(self._safe_int(q.get('page')), self._safe_int(q.get('number'))): q for q in fixed}
        updated = []
        for q in qcms:
            key = (self._safe_int(q.get('page')), self._safe_int(q.get('number')))
            updated.append(fixed_map.get(key, q))
        
        # Save any still-incomplete to check bucket
        self._save_to_check_bucket(updated, threshold)
        
        return updated




# Standalone test
if __name__ == "__main__":
    from modules.utils.cost_tracker import CostTracker
    
    tracker = CostTracker()
    extractor = Step2QCMExtractBatch(tracker, None)
    result = extractor.run("output/3A Parasito (CT)/step1_extraction/accepted")
    print(f"\nResult: {result}")
