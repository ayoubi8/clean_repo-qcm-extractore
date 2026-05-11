import json
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple
from datetime import datetime


class Step2_5QCMMerger:
    """
    Phase 1: Automatic QCM Merger
    
    Detects and merges QCMs that are split across multiple pages using regex-based
    detection at the structural JSON level (no LLM calls, zero cost).
    
    This runs automatically after Step 2 QCM extraction to fix split QCMs before
    proceeding to Step 3.
    """
    
    def __init__(self, project_context=None):
        self.context = project_context
        self.merge_log = []
        
    def run(self, input_dir: str = None) -> Dict[str, Any]:
        """
        Main execution for Step 2.5 - Automatic QCM Merger.
        
        Args:
            input_dir: Directory containing Step 2 output (JSON files)
            
        Returns:
            Dict with merge statistics
        """
        print("\n" + "="*60)
        print("STEP 2.5: AUTOMATIC QCM MERGER (Phase 1)")
        print("="*60)
        print("[*] Detecting and merging split QCMs...")
        
        # Determine input/output directory
        if self.context:
            target_input_dir = self.context.get_path("step2_qcm", "accepted")
        else:
            target_input_dir = Path(input_dir) if input_dir else Path("output/step2_qcm/accepted")
        
        # Load all page data
        pages_data = self._load_all_pages(target_input_dir)
        
        if len(pages_data) < 2:
            print("[SKIP] Only 1 page found, no merging needed.")
            return {"merged_count": 0, "total_pages": len(pages_data)}
        
        print(f"[INFO] Loaded {len(pages_data)} pages")
        
        # Detect and merge split QCMs
        merged_count = self._merge_split_qcms(pages_data)
        
        # Save updated data
        if merged_count > 0:
            self._save_merged_data(pages_data, target_input_dir)
            self._save_merge_report(target_input_dir)
        
        print(f"\n[OK] Step 2.5 Complete: {merged_count} QCMs merged")
        
        return {
            "merged_count": merged_count,
            "total_pages": len(pages_data),
            "merge_log": self.merge_log
        }
    
    def _load_all_pages(self, directory: Path) -> List[Dict[str, Any]]:
        """
        Load all page JSON files and their raw text.
        
        Returns:
            List of dict with: {page_num, qcms, raw_text, file_path}
        """
        json_files = sorted(
            directory.glob("page_*.json"),
            key=lambda x: int(re.search(r'page_(\d+)', x.name).group(1))
        )
        
        pages_data = []
        for json_file in json_files:
            try:
                page_num = int(re.search(r'page_(\d+)', json_file.name).group(1))
                
                # Load QCM data
                with open(json_file, 'r', encoding='utf-8') as f:
                    qcms = json.load(f)
                
                # Load raw text for proposition detection
                # Try to find corresponding text file from step1
                if self.context:
                    text_file = self.context.get_path("step1_extraction", "accepted") / f"page_{page_num}.txt"
                else:
                    text_file = json_file.parent.parent.parent / "step1_extraction" / "accepted" / f"page_{page_num}.txt"
                
                raw_text = ""
                if text_file.exists():
                    with open(text_file, 'r', encoding='utf-8') as f:
                        raw_text = f.read()
                
                pages_data.append({
                    'page_num': page_num,
                    'qcms': qcms if isinstance(qcms, list) else [qcms],
                    'raw_text': raw_text,
                    'file_path': json_file
                })
                
            except Exception as e:
                print(f"[WARN] Error loading {json_file.name}: {e}")
        
        return pages_data
    
    def _merge_split_qcms(self, pages_data: List[Dict[str, Any]]) -> int:
        """
        Main merging logic: detect and merge split QCMs across consecutive pages.
        
        Returns:
            Number of merges performed
        """
        merged_count = 0
        
        for i in range(len(pages_data) - 1):
            current_page = pages_data[i]
            next_page = pages_data[i + 1]
            
            # Check if current page has incomplete QCM at end
            is_incomplete, incomplete_qcm_idx = self._detect_incomplete_qcm_at_end(
                current_page['qcms']
            )
            
            # Check if next page has orphan propositions at start
            orphan_props = self._detect_orphan_propositions_at_start(
                next_page['raw_text'],
                next_page['qcms']
            )
            
            # If both conditions met, perform merge
            if is_incomplete and orphan_props:
                success = self._perform_merge(
                    current_page,
                    next_page,
                    incomplete_qcm_idx,
                    orphan_props
                )
                
                if success:
                    merged_count += 1
                    # Log merge for report
                    self.merge_log.append({
                        'timestamp': datetime.now().isoformat(),
                        'page_from': current_page['page_num'],
                        'page_to': next_page['page_num'],
                        'qcm_number': current_page['qcms'][incomplete_qcm_idx].get('number'),
                        'propositions_added': list(orphan_props.keys())
                    })
                    
                    print(f"[MERGE] QCM #{current_page['qcms'][incomplete_qcm_idx].get('number')} "
                          f"(pages {current_page['page_num']} -> {next_page['page_num']})")
        
        return merged_count
    
    def _detect_incomplete_qcm_at_end(self, qcms: List[Dict]) -> Tuple[bool, int]:
        """
        Detect if last QCM has incomplete propositions.
        
        Returns:
            (is_incomplete, qcm_index)
        """
        if not qcms:
            return False, -1
        
        last_qcm = qcms[-1]
        propositions = last_qcm.get('propositions', {})
        
        # Heuristic: Normal QCM has 4-5 propositions
        # If <3 propositions, likely incomplete
        if len(propositions) < 3:
            return True, len(qcms) - 1
        
        # Additional check: propositions dict is empty
        if not propositions:
            return True, len(qcms) - 1
        
        return False, -1
    
    def _detect_orphan_propositions_at_start(
        self, 
        raw_text: str, 
        qcms: List[Dict]
    ) -> Dict[str, str]:
        """
        Detect orphan propositions at page start using regex on raw text.
        
        Args:
            raw_text: Raw OCR text from step1
            qcms: Parsed QCMs (to check if they were incorrectly parsed)
            
        Returns:
            Dict of orphan propositions {option: text}
        """
        if not raw_text:
            return {}
        
        lines = raw_text.strip().split('\n')[:15]  # Check first 15 lines
        
        orphan_props = {}
        
        for line in lines:
            line_clean = line.strip()
            
            # Regex patterns for proposition formats:
            # a- text, a) text, (a) text, [a] text, A- text, etc.
            patterns = [
                r'^[\(\[]?([a-eA-E])[\)\]]?\s*[-:]\s*(.+)',  # a- ... or (a) ... or [a] ...
                r'^[\(\[]?([a-eA-E])[\)\]]\s+(.+)',           # a) ... or (a) ...
                r'^\(?([a-eA-E])\)?\s*[-:]\s*(.+)',           # Flexible
            ]
            
            for pattern in patterns:
                match = re.match(pattern, line_clean)
                if match:
                    option = match.group(1).upper()  # Normalize to uppercase
                    text = match.group(2).strip()
                    
                    # Ignore very short text (likely not a real proposition)
                    if len(text) > 5:
                        orphan_props[option] = text
                    break
            
            # Stop if we hit a QCM number (new question starting)
            if re.match(r'^\d+[-\.\):]', line_clean):
                break
            
            # Stop if we hit non-proposition text (unless it's very short)
            if line_clean and len(line_clean) > 20 and not any(re.match(p, line_clean) for p in patterns):
                # Could be continuation of previous proposition
                continue
        
        # Only return if we found at least 2 propositions (reduces false positives)
        if len(orphan_props) >= 2:
            return orphan_props
        
        return {}
    
    def _perform_merge(
        self,
        current_page: Dict[str, Any],
        next_page: Dict[str, Any],
        qcm_idx: int,
        orphan_props: Dict[str, str]
    ) -> bool:
        """
        Perform the actual merge operation.
        
        Args:
            current_page: Current page data
            next_page: Next page data
            qcm_idx: Index of incomplete QCM in current page
            orphan_props: Orphan propositions from next page
            
        Returns:
            True if merge successful
        """
        try:
            # Add orphan propositions to incomplete QCM
            current_qcm = current_page['qcms'][qcm_idx]
            
            if 'propositions' not in current_qcm:
                current_qcm['propositions'] = {}
            
            # Merge propositions
            current_qcm['propositions'].update(orphan_props)
            
            # Mark as merged (for tracking/debugging)
            current_qcm['_merged_from_page'] = next_page['page_num']
            current_qcm['_merge_timestamp'] = datetime.now().isoformat()
            
            # Remove orphan propositions from next page if they were parsed as a separate QCM
            # Check if first QCM in next page has no number or no text (likely the orphan)
            if next_page['qcms']:
                first_qcm = next_page['qcms'][0]
                
                # If first QCM has no question text or no number, it's likely orphan
                if not first_qcm.get('text') or not first_qcm.get('number'):
                    next_page['qcms'].pop(0)
                    print(f"   [CLEAN] Removed orphan QCM from page {next_page['page_num']}")
            
            return True
            
        except Exception as e:
            print(f"[ERROR] Merge failed: {e}")
            return False
    
    def _save_merged_data(self, pages_data: List[Dict[str, Any]], output_dir: Path):
        """
        Save updated QCM data back to JSON files.
        """
        print("\n[SAVE] Saving merged data...")
        
        for page_data in pages_data:
            try:
                file_path = page_data['file_path']
                
                # Save updated QCMs
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(page_data['qcms'], f, indent=2, ensure_ascii=False)
                
            except Exception as e:
                print(f"[WARN] Error saving {file_path.name}: {e}")
    
    def _save_merge_report(self, output_dir: Path):
        """
        Save detailed merge report for review.
        """
        if self.context:
            report_dir = self.context.get_path("step2_5_merge")
        else:
            report_dir = output_dir.parent.parent / "step2_5_merge"
        
        report_dir.mkdir(parents=True, exist_ok=True)
        report_file = report_dir / "merge_report.json"
        
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
    merger = Step2_5QCMMerger()
    result = merger.run()
    print(f"\nMerge Results: {result}")
