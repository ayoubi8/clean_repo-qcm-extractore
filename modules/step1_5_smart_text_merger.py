import json
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime
from shutil import copy2

from modules.openrouter_client import OpenRouterClient
from modules.utils.cost_tracker import CostTracker


class Step1_5SmartTextMerger:
    """
    Phase 1.5: Smart Sequential Text-Level QCM Merger
    
    Optimized workflow:
    1. Process pages sequentially (page 1, then 2, then 3...)
    2. Quick check: Does current page have incomplete QCM?
    3. If YES: Call LLM to fix BOTH current + next page
    4. If NO: Move to next page
    
    This minimizes LLM calls and processing time.
    """
    
    FIXER_MODEL = "google/gemma-3-27b-it:free"
    
    def __init__(self, cost_tracker: CostTracker = None, project_context=None):
        self.client = OpenRouterClient()
        self.cost_tracker = cost_tracker
        self.context = project_context
        self.fix_log = []
        
    def run(self, input_dir: str = None) -> Dict[str, Any]:
        """Main execution for Step 1.5 - Smart Text Merger."""
        print("\n" + "="*60)
        print("STEP 1.5: SMART TEXT-LEVEL QCM FIXER (Gemma)")
        print("="*60)
        print("[*] Sequential page-by-page analysis...")
        
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
        
        print(f"[INFO] Processing {len(txt_files)} pages sequentially")
        
        # Backup original files
        backup_dir = target_input_dir.parent / "backup_before_fix"
        backup_dir.mkdir(exist_ok=True)
        for txt_file in txt_files:
            copy2(txt_file, backup_dir / txt_file.name)
        print(f"[BACKUP] Original files saved to: {backup_dir}")
        
        # Sequential processing
        fixes_applied = 0
        i = 0
        
        while i < len(txt_files) - 1:
            current_file = txt_files[i]
            next_file = txt_files[i + 1]
            
            current_num = int(re.search(r'page_(\d+)', current_file.name).group(1))
            next_num = int(re.search(r'page_(\d+)', next_file.name).group(1))
            
            print(f"\n[CHECK] Pages {current_num}-{current_num+1}...", end=" ")
            
            # Read both pages
            current_text = current_file.read_text(encoding='utf-8')
            next_text = next_file.read_text(encoding='utf-8')
            
            # Call LLM to detect AND fix in one shot
            fixed_current, fixed_next, was_split = self._detect_and_fix(
                current_text, next_text, current_num, next_num
            )
            
            if was_split and fixed_current and fixed_next:
                # Write fixed versions
                current_file.write_text(fixed_current, encoding='utf-8')
                next_file.write_text(fixed_next, encoding='utf-8')
                
                fixes_applied += 1
                
                # Log fix
                self.fix_log.append({
                    'timestamp': datetime.now().isoformat(),
                    'page_from': current_num,
                    'page_to': next_num,
                    'action': 'split_fixed'
                })
                
                print(f"SPLIT FIXED!")
            else:
                print("OK")
            
            i += 1
        
        # Save fix report
        if fixes_applied > 0:
            self._save_fix_report(target_input_dir)
        
        print(f"\n[OK] Step 1.5 Complete: {fixes_applied} splits fixed")
        
        return {
            "fixes_applied": fixes_applied,
            "total_pages": len(txt_files),
            "fix_log": self.fix_log
        }
    
    def _detect_and_fix(
        self,
        current_text: str,
        next_text: str,
        current_num: int,
        next_num: int
    ) -> Tuple[Optional[str], Optional[str], bool]:
        """
        Use LLM to detect if split exists AND return fixed versions.
        
        Returns:
            (fixed_current, fixed_next, was_split)
        """
        prompt = f"""Analyze these two consecutive pages for split QCMs (multiple choice questions).

PAGE {current_num}:
---
{current_text}
---

PAGE {next_num}:
---
{next_text}
---

TASK: Detect if a QCM is split across these pages.

SPLIT DETECTION CRITERIA:
1. Page {current_num} ends with a question number and text (e.g., "34-Question text:") but has FEWER than 4 propositions
2. Page {current_num+1} starts with propositions (a-, b-, c-, d-, e-) that belong to that question

EXAMPLES OF SPLITS:
- Page ends with "34-La dianzampébose est une protozoose : Les" + only "a-Extra-intestinale." and "b-Due à une amibe."
- Next page starts with "c. Due à un parasite binucléé" "a. Transmise par un vecteur." etc.

IF SPLIT DETECTED:
1. Take ALL orphan propositions from start of page {current_num+1}
2. Add them to the incomplete QCM on page {current_num}
3. Remove those propositions from page {current_num+1}
4. Return BOTH fixed pages

IF NO SPLIT:
Return exactly: NO_SPLIT

OUTPUT FORMAT (if split detected):
START_PAGE_{current_num}
[complete fixed text of page {current_num} with all propositions added]
END_PAGE_{current_num}
START_PAGE_{next_num}
[complete fixed text of page {current_num+1} with orphan propositions removed]
END_PAGE_{next_num}

BEGIN ANALYSIS:"""
        
        try:
            response = self.client.generate_completion(
                prompt,
                model=self.FIXER_MODEL,
                max_tokens=3000
            )
            
            content = response['content'].strip()
            
            # Track cost
            if self.cost_tracker:
                cost = response.get('cost', 0.0) or self.client.estimate_cost(self.FIXER_MODEL, response['usage'])
                self.cost_tracker.log_api_call(
                    f"step1_5_detect_fix_p{current_num}-{next_num}",
                    "gemma-detect-fix",
                    response['usage'],
                    cost
                )
            
            # Check if split detected
            if "NO_SPLIT" in content:
                return None, None, False
            
            # Parse fixed pages
            fixed_current, fixed_next = self._parse_fixed_pages(content, current_num, next_num)
            
            if fixed_current and fixed_next:
                return fixed_current, fixed_next, True
            else:
                return None, None, False
            
        except Exception as e:
            print(f"[ERROR] LLM call failed: {e}")
            return None, None, False
    
    def _parse_fixed_pages(
        self, 
        content: str, 
        current_num: int, 
        next_num: int
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract fixed page contents from LLM response.
        """
        try:
            # Find page markers
            current_start = content.find(f"START_PAGE_{current_num}")
            current_end = content.find(f"END_PAGE_{current_num}")
            next_start = content.find(f"START_PAGE_{next_num}")
            next_end = content.find(f"END_PAGE_{next_num}")
            
            if current_start == -1 or current_end == -1 or next_start == -1 or next_end == -1:
                print("[WARN] Could not find page markers in LLM response")
                return None, None
            
            # Extract content between markers
            fixed_current = content[current_start:current_end]
            fixed_current = fixed_current.replace(f"START_PAGE_{current_num}", "").strip()
            
            fixed_next = content[next_start:next_end]
            fixed_next = fixed_next.replace(f"START_PAGE_{next_num}", "").strip()
            
            # Validation: fixed pages should not be empty
            if len(fixed_current) < 50 or len(fixed_next) < 20:
                print("[WARN] Fixed pages too short, likely parsing error")
                return None, None
            
            return fixed_current, fixed_next
            
        except Exception as e:
            print(f"[ERROR] Parsing failed: {e}")
            return None, None
    
    def _save_fix_report(self, output_dir: Path):
        """Save detailed fix report."""
        if self.context:
            report_dir = self.context.get_path("step1_5_smart_fix")
        else:
            report_dir = output_dir.parent.parent / "step1_5_smart_fix"
        
        report_dir.mkdir(parents=True, exist_ok=True)
        report_file = report_dir / "fix_report.json"
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'total_fixes': len(self.fix_log),
            'fixes': self.fix_log
        }
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"[INFO] Fix report saved: {report_file}")


# Standalone execution for testing
if __name__ == "__main__":
    from modules.utils.cost_tracker import CostTracker
    
    tracker = CostTracker()
    merger = Step1_5SmartTextMerger(cost_tracker=tracker)
    result = merger.run("output/3A Parasito (CT)/step1_extraction/accepted")
    print(f"\nFix Results: {result}")
