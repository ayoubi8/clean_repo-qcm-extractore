import json
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple
from datetime import datetime
from shutil import copy2

from modules.openrouter_client import OpenRouterClient
from modules.utils.cost_tracker import CostTracker


class Step1_5TextMerger:
    """
    Phase 1.5: Text-Level QCM Merger using Gemma
    
    Detects split QCMs at raw text level and PHYSICALLY MERGES the text files
    BEFORE Step 2 parsing. Uses google/gemma-3-27b-it:free for detection.
    
    This runs automatically after Step 1 (OCR) to ensure Step 2 receives
    complete QCMs without any splits.
    
    Key difference from Step 2.5:
    - Step 1.5: Merges TEXT files (before parsing)
    - Step 2.5: Merges JSON (after parsing) - DEPRECATED
    """
    
    VALIDATOR_MODEL = "google/gemma-3-27b-it:free"
    
    def __init__(self, cost_tracker: CostTracker = None, project_context=None):
        self.client = OpenRouterClient()
        self.cost_tracker = cost_tracker
        self.context = project_context
        self.merge_log = []
        
    def run(self, input_dir: str = None) -> Dict[str, Any]:
        """
        Main execution for Step 1.5 - Text-Level Merger.
        
        Args:
            input_dir: Directory containing Step 1 output (text files)
            
        Returns:
            Dict with merge statistics
        """
        print("\n" + "="*60)
        print("STEP 1.5: TEXT-LEVEL QCM MERGER (Gemma Detection)")
        print("="*60)
        print("[*] Detecting and merging split QCMs in text files...")
        
        # Determine input directory
        if self.context:
            target_input_dir = self.context.get_path("step1_extraction", "accepted")
        else:
            target_input_dir = Path(input_dir) if input_dir else Path("output/step1_extraction/accepted")
        
        # Backup original files
        backup_dir = target_input_dir.parent / "backup_before_merge"
        backup_dir.mkdir(exist_ok=True)
        
        # Load all text files
        txt_files = sorted(
            target_input_dir.glob("page_*.txt"),
            key=lambda x: int(re.search(r'page_(\d+)', x.name).group(1))
        )
        
        if len(txt_files) < 2:
            print("[SKIP] Only 1 page found, no merging needed.")
            return {"merged_count": 0, "total_pages": len(txt_files)}
        
        print(f"[INFO] Analyzing {len(txt_files)} pages")
        
        # Detect splits using Gemma
        splits_detected = self._detect_all_splits(txt_files)
        
        if not splits_detected:
            print("[OK] No split QCMs detected")
            return {"merged_count": 0, "total_pages": len(txt_files)}
        
        print(f"[INFO] Detected {len(splits_detected)} potential splits")
        
        # Backup files before merging
        print("[BACKUP] Creating backup of original files...")
        for txt_file in txt_files:
            copy2(txt_file, backup_dir / txt_file.name)
        
        # Perform text-level merging
        merged_count = self._merge_text_files(txt_files, splits_detected, target_input_dir)
        
        # Save merge report
        if merged_count > 0:
            self._save_merge_report(target_input_dir)
        
        print(f"\n[OK] Step 1.5 Complete: {merged_count} text files merged")
        print(f"[INFO] Original files backed up to: {backup_dir}")
        
        return {
            "merged_count": merged_count,
            "total_pages": len(txt_files),
            "merge_log": self.merge_log
        }
    
    def _detect_all_splits(self, txt_files: List[Path]) -> List[Dict[str, Any]]:
        """
        Use Gemma to detect all split QCMs across consecutive pages.
        
        Returns:
            List of split detections with page numbers and confidence
        """
        splits = []
        
        for i in range(len(txt_files) - 1):
            current_file = txt_files[i]
            next_file = txt_files[i + 1]
            
            current_num = int(re.search(r'page_(\d+)', current_file.name).group(1))
            next_num = int(re.search(r'page_(\d+)', next_file.name).group(1))
            
            # Read texts
            current_text = current_file.read_text(encoding='utf-8')
            next_text = next_file.read_text(encoding='utf-8')
            
            # Validate pair with Gemma
            result = self._validate_page_pair(current_text, next_text, current_num, next_num)
            
            if result['has_split'] and result['confidence'] >= 80:  # Only high confidence
                splits.append({
                    'page_from': current_num,
                    'page_to': next_num,
                    'qcm_number': result.get('split_qcm_number'),
                    'confidence': result['confidence']
                })
                print(f"[DETECT] Split QCM #{result.get('split_qcm_number')} "
                      f"between pages {current_num} and {next_num} "
                      f"(confidence: {result['confidence']}%)")
        
        return splits
    
    def _validate_page_pair(
        self, 
        current_text: str, 
        next_text: str,
        current_num: int,
        next_num: int
    ) -> Dict[str, Any]:
        """
        Validate a pair of consecutive pages using Gemma.
        """
        # Limit text length
        current_preview = current_text[-600:] if len(current_text) > 600 else current_text
        next_preview = next_text[:600] if len(next_text) > 600 else next_text
        
        prompt = f"""Detect if a QCM question is split between two pages.

PAGE {current_num} ENDING:
---
{current_preview}
---

PAGE {next_num} BEGINNING:
---
{next_preview}
---

DETECTION RULES:
1. Split QCM = Page {current_num} has question WITHOUT propositions + Page {next_num} starts with propositions
2. Propositions look like: "a-text", "(a) text", "A) text", "a: text"
3. Normal QCM has 4-5 propositions (A, B, C, D, E)
4. Ignore headers/footers like "page 2/10", "Parasitologie"

CRITICAL: Return ONLY this JSON (no markdown, no explanation):
{{
  "has_split": true,
  "split_qcm_number": 17,
  "confidence": 85,
  "issue_type": "split_question"
}}

If NO split:
{{
  "has_split": false,
  "split_qcm_number": null,
  "confidence": 100,
  "issue_type": "none"
}}"""
        
        try:
            response = self.client.generate_completion(
                prompt,
                model=self.VALIDATOR_MODEL,
                max_tokens=500
            )
            
            content = response['content']
            
            # Track cost
            if self.cost_tracker:
                cost = response.get('cost', 0.0) or self.client.estimate_cost(self.VALIDATOR_MODEL, response['usage'])
                self.cost_tracker.log_api_call(
                    f"step1_5_p{current_num}-{next_num}",
                    "gemma-validator",
                    response['usage'],
                    cost
                )
            
            # Parse JSON
            return self._parse_json_response(content)
            
        except Exception as e:
            print(f"[WARN] Validation failed for pages {current_num}-{next_num}: {e}")
            return {
                'has_split': False,
                'split_qcm_number': None,
                'confidence': 0,
                'issue_type': 'none'
            }
    
    def _parse_json_response(self, content: str) -> Dict[str, Any]:
        """Parse Gemma's JSON response."""
        content = content.strip()
        content = re.sub(r'```json\s*', '', content)
        content = re.sub(r'```\s*', '', content)
        
        start_idx = content.find('{')
        end_idx = content.rfind('}')
        
        if start_idx == -1 or end_idx == -1:
            raise ValueError("No JSON object found")
        
        json_str = content[start_idx:end_idx+1]
        
        try:
            result = json.loads(json_str)
            required_fields = ['has_split', 'confidence']
            for field in required_fields:
                if field not in result:
                    result[field] = False if field == 'has_split' else 0
            return result
        except json.JSONDecodeError:
            return {
                'has_split': False,
                'split_qcm_number': None,
                'confidence': 0,
                'issue_type': 'none'
            }
    
    def _merge_text_files(
        self, 
        txt_files: List[Path], 
        splits: List[Dict[str, Any]],
        output_dir: Path
    ) -> int:
        """
        Physically merge text files based on detected splits.
        
        Strategy:
        - Merge page N and N+1 into page N
        - Delete page N+1
        - Renumber subsequent pages
        """
        merged_count = 0
        pages_to_delete = set()
        
        for split in splits:
            page_from = split['page_from']
            page_to = split['page_to']
            
            # Find the files
            from_file = output_dir / f"page_{page_from}.txt"
            to_file = output_dir / f"page_{page_to}.txt"
            
            if not from_file.exists() or not to_file.exists():
                print(f"[WARN] Files not found for merge: {page_from} -> {page_to}")
                continue
            
            # Read both files
            from_text = from_file.read_text(encoding='utf-8')
            to_text = to_file.read_text(encoding='utf-8')
            
            # Merge: append page_to content to page_from
            merged_text = from_text + "\n" + to_text
            
            # Write merged content to page_from
            from_file.write_text(merged_text, encoding='utf-8')
            
            # Mark page_to for deletion
            pages_to_delete.add(page_to)
            
            merged_count += 1
            
            # Log merge
            self.merge_log.append({
                'timestamp': datetime.now().isoformat(),
                'page_from': page_from,
                'page_to': page_to,
                'qcm_number': split.get('qcm_number'),
                'confidence': split['confidence'],
                'action': 'text_merged'
            })
            
            print(f"[MERGE] Pages {page_from} + {page_to} -> page_{page_from}.txt")
        
        # Delete merged pages
        for page_num in sorted(pages_to_delete):
            file_to_delete = output_dir / f"page_{page_num}.txt"
            if file_to_delete.exists():
                file_to_delete.unlink()
                print(f"[DELETE] Removed page_{page_num}.txt")
        
        return merged_count
    
    def _save_merge_report(self, output_dir: Path):
        """Save detailed merge report."""
        if self.context:
            report_dir = self.context.get_path("step1_5_text_merge")
        else:
            report_dir = output_dir.parent.parent / "step1_5_text_merge"
        
        report_dir.mkdir(parents=True, exist_ok=True)
        report_file = report_dir / "text_merge_report.json"
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'total_merges': len(self.merge_log),
            'merges': self.merge_log
        }
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"[INFO] Merge report saved: {report_file}")


# Standalone execution for testing
if __name__ == "__main__":
    from modules.utils.cost_tracker import CostTracker
    
    tracker = CostTracker()
    merger = Step1_5TextMerger(cost_tracker=tracker)
    result = merger.run("output/3A Parasito (CT)/step1_extraction/accepted")
    print(f"\nMerge Results: {result}")
