import json
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple
from datetime import datetime
from shutil import copy2

from modules.openrouter_client import OpenRouterClient
from modules.utils.cost_tracker import CostTracker


class Step1_5BatchTextFixer:
    """
    Optimized Hybrid Approach: Regex Detection + Batch LLM Fixing
    
    Phase 1: Fast regex scan of all pages (< 1 sec, $0)
    Phase 2: Single batch LLM call for all detected splits (~10 sec, $0)
    
    Benefits:
    - 10x faster than sequential LLM calls
    - Same accuracy (LLM still does the fixing)
    - Scalable to large documents (100+ pages)
    """
    
    def __init__(self, cost_tracker: CostTracker = None, project_context=None):
        self.client = OpenRouterClient()
        self.cost_tracker = cost_tracker
        self.context = project_context
        self.fix_log = []
        
    def run(self, input_dir: str = None) -> Dict[str, Any]:
        """Main execution for Step 1.5 - Batch Text Fixer."""
        print("\n" + "="*60)
        print("STEP 1.5: BATCH QCM FIXER (Hybrid: Regex + LLM)")
        print("="*60)
        
        # Determine input directory
        if self.context:
            target_input_dir = self.context.get_path("step1_extraction", "accepted")
        else:
            target_input_dir = Path(input_dir) if input_dir else Path("output/step1_extraction/accepted")
        
        # Load all text files
        txt_files = sorted(
            target_input_dir.glob("page_*.txt"),
            key=lambda x: int(re.search(r'page_(\d+)', x.name).group(1))
        )
        
        if len(txt_files) < 2:
            print("[SKIP] Only 1 page found, no fixing needed.")
            return {"fixes_applied": 0, "total_pages": len(txt_files)}
        
        print(f"[INFO] Analyzing {len(txt_files)} pages")
        
        # Backup original files
        backup_dir = target_input_dir.parent / "backup_before_fix"
        backup_dir.mkdir(exist_ok=True)
        for txt_file in txt_files:
            copy2(txt_file, backup_dir / txt_file.name)
        print(f"[BACKUP] Saved to: {backup_dir}")
        
        # PHASE 1: Fast regex scan
        print("\n[PHASE 1] Fast regex scan...")
        flagged_pairs = self._regex_scan_all_pages(txt_files)
        
        if not flagged_pairs:
            print("[OK] No splits detected by regex scan")
            return {"fixes_applied": 0, "total_pages": len(txt_files), "fix_log": []}
        
        print(f"[DETECTED] {len(flagged_pairs)} potential splits")
        
        # PHASE 2: Batch LLM fix
        print("\n[PHASE 2] Batch LLM fixing...")
        fixed_pages = self._batch_llm_fix(flagged_pairs, txt_files)
        
        if not fixed_pages:
            print("[WARN] LLM batch fix failed")
            return {"fixes_applied": 0, "total_pages": len(txt_files), "fix_log": []}
        
        # Apply fixes
        fixes_applied = self._apply_fixes(fixed_pages, txt_files)
        
        # Save report
        if fixes_applied > 0:
            self._save_fix_report(target_input_dir)
        
        print(f"\n[OK] Step 1.5 Complete: {fixes_applied} splits fixed")
        
        return {
            "fixes_applied": fixes_applied,
            "total_pages": len(txt_files),
            "fix_log": self.fix_log
        }
    
    def _regex_scan_all_pages(self, txt_files: List[Path]) -> List[Tuple[int, int]]:
        """
        Phase 1: Fast regex scan to detect potential splits.
        
        Returns:
            List of (page_from, page_to) tuples
        """
        flagged_pairs = []
        
        for i in range(len(txt_files) - 1):
            current_file = txt_files[i]
            current_num = int(re.search(r'page_(\d+)', current_file.name).group(1))
            next_num = current_num + 1
            
            # Read current page
            current_text = current_file.read_text(encoding='utf-8')
            
            # Quick regex check
            if self._has_incomplete_qcm(current_text):
                flagged_pairs.append((current_num, next_num))
                print(f"  [FLAG] Pages {current_num}-{next_num}")
        
        return flagged_pairs
    
    def _has_incomplete_qcm(self, text: str) -> bool:
        """
        Fast regex check: Does page end with incomplete QCM?
        
        Criteria:
        - Ends with question number + text + colon/question mark
        - Has fewer than 3 propositions in last section
        """
        lines = text.strip().split('\n')
        
        # Get last 12 non-empty lines
        last_lines = [l.strip() for l in lines[-15:] if l.strip()]
        
        # Remove footers
        last_lines = [l for l in last_lines 
                      if not re.search(r'Dr\.|SCE|parasitologie|page\s*\d+|scanned|camscanner', l, re.I)]
        
        if len(last_lines) < 2:
            return False
        
        # Check if last line is a question
        last_line = last_lines[-1]
        is_question = bool(re.match(r'\d+[-.)]\s*.{15,}[:?]\s*$', last_line))
        
        if not is_question:
            return False
        
        # Count propositions in last 8 lines
        prop_count = sum(
            1 for line in last_lines[-8:]
            if re.match(r'^[a-e][-.)]\s*.{5,}', line, re.I)
        )
        
        # Incomplete if < 3 propositions
        return prop_count < 3
    
    def _batch_llm_fix(
        self, 
        flagged_pairs: List[Tuple[int, int]], 
        txt_files: List[Path]
    ) -> Dict[int, str]:
        """
        Phase 2: Single batch LLM call to fix all splits.
        
        Returns:
            Dict mapping page_num -> fixed_content
        """
        # Build batch prompt
        prompt = self._build_batch_prompt(flagged_pairs, txt_files)
        
        try:
            print(f"[LLM] Calling Text Fixer with {len(flagged_pairs)} pairs...")
            
            primary_model = os.getenv("STEP1_5_MODEL", "google/gemma-3-27b-it:free")
            fallback_model = os.getenv("STEP1_5_FALLBACK_MODEL", "google/gemini-2.0-flash-lite-001")
            max_tokens = int(os.getenv("STEP1_5_MAX_TOKENS", "8000"))
            
            try:
                response = self.client.generate_completion(
                    prompt,
                    model=primary_model,
                    max_tokens=max_tokens
                )
                model_used = primary_model
            except Exception as e:
                print(f"[WARN] Batch fixer primary model failed: {e}")
                print(f"[INFO] Retrying with fallback: {fallback_model}")
                response = self.client.generate_completion(
                    prompt,
                    model=fallback_model,
                    max_tokens=max_tokens
                )
                model_used = fallback_model
            
            content = response['content']
            
            # Track cost
            if self.cost_tracker:
                cost = response.get('cost', 0.0) or self.client.estimate_cost(model_used, response['usage'])
                self.cost_tracker.log_api_call(
                    "step1_5_batch_fix",
                    model_used,
                    response['usage'],
                    cost
                )
            
            print(f"[LLM] Response received ({len(content)} chars)")
            
            # Parse batch response
            return self._parse_batch_response(content, flagged_pairs)
            
        except Exception as e:
            print(f"[ERROR] Batch LLM call failed: {e}")
            return {}
    
    def _build_batch_prompt(
        self, 
        flagged_pairs: List[Tuple[int, int]], 
        txt_files: List[Path]
    ) -> str:
        """Build prompt for batch fixing."""
        
        # Collect page contents
        page_contents = {}
        for page_file in txt_files:
            page_num = int(re.search(r'page_(\d+)', page_file.name).group(1))
            page_contents[page_num] = page_file.read_text(encoding='utf-8')
        
        # Build prompt
        prompt_parts = [
            "Fix multiple split QCMs across these page pairs.",
            "",
            "TASK: For each pair, check if QCM is split. If yes, fix both pages.",
            "",
            "SPLIT CRITERIA:",
            "- Page N ends with question (e.g., '34-Question text:') but < 3 propositions",
            "- Page N+1 starts with orphan propositions (a-, b-, c-, etc.)",
            "",
            "FIXING:",
            "- Move orphan propositions from page N+1 to page N",
            "- Remove orphans from page N+1",
            "",
            "="*60,
            ""
        ]
        
        # Add each pair
        for idx, (page_from, page_to) in enumerate(flagged_pairs, 1):
            prompt_parts.extend([
                f"PAIR_{idx}: Pages {page_from}-{page_to}",
                f"---",
                f"PAGE_{page_from}:",
                page_contents[page_from][:1500],  # Limit length
                f"",
                f"PAGE_{page_to}:",
                page_contents[page_to][:1500],
                f"---",
                ""
            ])
        
        prompt_parts.extend([
            "",
            "OUTPUT FORMAT (for EACH pair):",
            "FIX_1",
            "PAGE_X: [complete fixed content]",
            "PAGE_Y: [complete fixed content]",
            "END_FIX_1",
            "",
            "If no split for a pair, output: NO_FIX_N",
            "",
            "BEGIN FIXES:"
        ])
        
        return "\n".join(prompt_parts)
    
    def _parse_batch_response(
        self, 
        content: str, 
        flagged_pairs: List[Tuple[int, int]]
    ) -> Dict[int, str]:
        """
        Parse batch LLM response to extract fixed pages.
        
        Returns:
            Dict mapping page_num -> fixed_content
        """
        fixed_pages = {}
        
        # Try to extract fixes
        for idx, (page_from, page_to) in enumerate(flagged_pairs, 1):
            # Look for FIX_N block
            fix_pattern = rf'FIX_{idx}\s*\n(.*?)\nEND_FIX_{idx}'
            match = re.search(fix_pattern, content, re.DOTALL)
            
            if not match:
                # Check for NO_FIX
                if f"NO_FIX_{idx}" in content:
                    continue
                print(f"[WARN] Could not parse FIX_{idx}")
                continue
            
            fix_block = match.group(1)
            
            # Extract individual pages
            page_from_match = re.search(rf'PAGE_{page_from}:\s*(.*?)(?=PAGE_|$)', fix_block, re.DOTALL)
            page_to_match = re.search(rf'PAGE_{page_to}:\s*(.*?)(?=PAGE_|$)', fix_block, re.DOTALL)
            
            if page_from_match:
                fixed_pages[page_from] = page_from_match.group(1).strip()
            if page_to_match:
                fixed_pages[page_to] = page_to_match.group(1).strip()
        
        print(f"[PARSE] Extracted {len(fixed_pages)} fixed pages")
        return fixed_pages
    
    def _apply_fixes(
        self, 
        fixed_pages: Dict[int, str], 
        txt_files: List[Path]
    ) -> int:
        """Apply fixes to files."""
        fixes_applied = 0
        
        for page_file in txt_files:
            page_num = int(re.search(r'page_(\d+)', page_file.name).group(1))
            
            if page_num in fixed_pages:
                # Write fixed content
                page_file.write_text(fixed_pages[page_num], encoding='utf-8')
                fixes_applied += 1
                
                # Log
                self.fix_log.append({
                    'timestamp': datetime.now().isoformat(),
                    'page': page_num,
                    'action': 'fixed'
                })
                
                print(f"  [APPLY] Fixed page {page_num}")
        
        return fixes_applied
    
    def _save_fix_report(self, output_dir: Path):
        """Save fix report."""
        if self.context:
            report_dir = self.context.get_path("step1_5_batch_fix")
        else:
            report_dir = output_dir.parent.parent / "step1_5_batch_fix"
        
        report_dir.mkdir(parents=True, exist_ok=True)
        report_file = report_dir / "batch_fix_report.json"
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'total_fixes': len(self.fix_log),
            'fixes': self.fix_log
        }
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"[INFO] Report saved: {report_file}")


# Standalone execution
if __name__ == "__main__":
    from modules.utils.cost_tracker import CostTracker
    
    tracker = CostTracker()
    fixer = Step1_5BatchTextFixer(cost_tracker=tracker)
    result = fixer.run("output/3A Parasito (CT)/step1_extraction/accepted")
    print(f"\nBatch Fix Result: {result}")
