import json
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple
from datetime import datetime

from modules.openrouter_client import OpenRouterClient
from modules.utils.cost_tracker import CostTracker


class Step1_5TextValidator:
    """
    Phase 2: Text-Level Validator using Gemma-3-27b
    
    Detects split QCMs and potential issues at the raw OCR text level
    BEFORE structured parsing. Uses google/gemma-3-27b-it:free
    for fast, cost-free validation (same model as Step 2).
    
    This runs automatically after Step 1 (OCR) to identify pages that
    may contain split QCMs or incomplete content.
    """
    
    VALIDATOR_MODEL = "google/gemma-3-27b-it:free"
    
    def __init__(self, cost_tracker: CostTracker = None, project_context=None):
        self.client = OpenRouterClient()
        self.cost_tracker = cost_tracker
        self.context = project_context
        self.validation_log = []
        
    def run(self, input_dir: str = None) -> Dict[str, Any]:
        """
        Main execution for Step 1.5 - Text-Level Validator.
        
        Args:
            input_dir: Directory containing Step 1 output (text files)
            
        Returns:
            Dict with validation statistics and flags
        """
        print("\n" + "="*60)
        print("STEP 1.5: TEXT-LEVEL VALIDATOR (Phase 2 - Gemma)")
        print("="*60)
        print("[*] Analyzing OCR text for potential split QCMs...")
        
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
            print("[SKIP] Only 1 page found, no validation needed.")
            return {"validated_pairs": 0, "splits_detected": 0}
        
        print(f"[INFO] Validating {len(txt_files)-1} page pairs")
        
        # Validate consecutive page pairs
        splits_detected = 0
        flagged_pages = set()
        
        for i in range(len(txt_files) - 1):
            current_file = txt_files[i]
            next_file = txt_files[i + 1]
            
            current_num = int(re.search(r'page_(\d+)', current_file.name).group(1))
            next_num = int(re.search(r'page_(\d+)', next_file.name).group(1))
            
            # Read texts
            current_text = current_file.read_text(encoding='utf-8')
            next_text = next_file.read_text(encoding='utf-8')
            
            # Validate pair
            result = self._validate_page_pair(
                current_text, 
                next_text, 
                current_num, 
                next_num
            )
            
            if result['has_split']:
                splits_detected += 1
                flagged_pages.add(current_num)
                flagged_pages.add(next_num)
                
                print(f"[DETECT] Split QCM between pages {current_num} and {next_num} "
                      f"(confidence: {result['confidence']}%)")
                
                # Log validation
                self.validation_log.append({
                    'timestamp': datetime.now().isoformat(),
                    'page_from': current_num,
                    'page_to': next_num,
                    'has_split': True,
                    'qcm_number': result.get('split_qcm_number'),
                    'confidence': result['confidence'],
                    'issue_type': result.get('issue_type', 'split_question')
                })
        
        # Save validation report
        if splits_detected > 0:
            self._save_validation_report(target_input_dir)
        
        print(f"\n[OK] Step 1.5 Complete: {splits_detected} potential splits detected")
        
        return {
            "validated_pairs": len(txt_files) - 1,
            "splits_detected": splits_detected,
            "flagged_pages": sorted(list(flagged_pages)),
            "validation_log": self.validation_log
        }
    
    def _validate_page_pair(
        self, 
        current_text: str, 
        next_text: str,
        current_num: int,
        next_num: int
    ) -> Dict[str, Any]:
        """
        Validate a pair of consecutive pages using Nemotron.
        
        Args:
            current_text: Text from current page
            next_text: Text from next page
            current_num: Current page number
            next_num: Next page number
            
        Returns:
            Dict with validation results
        """
        # Build validation prompt
        prompt = self._build_validation_prompt(current_text, next_text, current_num, next_num)
        
        try:
            # Call primary validator
            try:
                response = self.client.generate_completion(
                    prompt,
                    model=self.VALIDATOR_MODEL,
                    max_tokens=500
                )
                model_used = self.VALIDATOR_MODEL
            except Exception as e:
                error_msg = str(e).lower()
                print(f"[WARN] Primary validator failed: {e}")
                
                # Fallback triggers
                fallback_triggers = ["context", "length", "token", "too large", "404", "route", "not found", "provider"]
                
                if any(word in error_msg for word in fallback_triggers):
                    print(f"[INFO] Falling back to Gemini 2.0 Flash Lite for validation...")
                    response = self.client.generate_completion(
                        prompt,
                        model="google/gemini-2.0-flash-lite-001",
                        max_tokens=500
                    )
                    model_used = "google/gemini-2.0-flash-lite-001"
                else:
                    raise e
            
            content = response['content']
            
            # Track cost
            if self.cost_tracker:
                cost = response.get('cost', 0.0) or self.client.estimate_cost(model_used, response['usage'])
                self.cost_tracker.log_api_call(
                    f"step1_5_p{current_num}-{next_num}",
                    model_used,
                    response['usage'],
                    cost
                )
            
            # Parse JSON response
            result = self._parse_validation_response(content)
            
            return result
            
        except Exception as e:
            print(f"[WARN] Validation failed for pages {current_num}-{next_num}: {e}")
            # Return safe default (assume no split on error)
            return {
                'has_split': False,
                'split_qcm_number': None,
                'confidence': 0,
                'issue_type': 'none'
            }
    
    def _build_validation_prompt(
        self, 
        current_text: str, 
        next_text: str,
        current_num: int,
        next_num: int
    ) -> str:
        """
        Build the Nemotron validation prompt.
        """
        # Limit text length to avoid token limits
        current_preview = current_text[-500:] if len(current_text) > 500 else current_text
        next_preview = next_text[:500] if len(next_text) > 500 else next_text
        
        return f"""You are a medical exam analyzer. Detect if a QCM question is split between two pages.

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
3. Normal QCM has 4-5 propositions (A, B, C, D, E or a, b, c, d, e)
4. Ignore headers/footers like "page 2/10", "Parasitologie", doctor names

CRITICAL OUTPUT RULE:
- MUST start response directly with {{
- MUST end response directly with }}
- NO markdown (```json), NO explanations
- ONLY return this exact JSON structure:

{{
  "has_split": true,
  "split_qcm_number": 17,
  "confidence": 85,
  "issue_type": "split_question"
}}

If NO split detected:
{{
  "has_split": false,
  "split_qcm_number": null,
  "confidence": 100,
  "issue_type": "none"
}}

issue_type options: "split_question", "incomplete_propositions", "none"

BEGIN JSON OUTPUT NOW:"""
    
    def _parse_validation_response(self, content: str) -> Dict[str, Any]:
        """
        Parse Nemotron's JSON response.
        """
        # Clean response
        content = content.strip()
        content = re.sub(r'```json\s*', '', content)
        content = re.sub(r'```\s*', '', content)
        
        # Find JSON object
        start_idx = content.find('{')
        end_idx = content.rfind('}')
        
        if start_idx == -1 or end_idx == -1:
            raise ValueError("No JSON object found in response")
        
        json_str = content[start_idx:end_idx+1]
        
        try:
            result = json.loads(json_str)
            
            # Validate required fields
            required_fields = ['has_split', 'confidence']
            for field in required_fields:
                if field not in result:
                    result[field] = False if field == 'has_split' else 0
            
            return result
            
        except json.JSONDecodeError as e:
            print(f"[WARN] JSON parsing failed: {e}")
            # Return safe default
            return {
                'has_split': False,
                'split_qcm_number': None,
                'confidence': 0,
                'issue_type': 'none'
            }
    
    def _save_validation_report(self, output_dir: Path):
        """
        Save detailed validation report for review.
        """
        if self.context:
            report_dir = self.context.get_path("step1_5_validation")
        else:
            report_dir = output_dir.parent.parent / "step1_5_validation"
        
        report_dir.mkdir(parents=True, exist_ok=True)
        report_file = report_dir / "validation_report.json"
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'total_validations': len(self.validation_log),
            'splits_detected': sum(1 for v in self.validation_log if v['has_split']),
            'validations': self.validation_log
        }
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"[INFO] Validation report saved: {report_file}")


# Standalone execution for testing
if __name__ == "__main__":
    from modules.utils.cost_tracker import CostTracker
    
    tracker = CostTracker()
    validator = Step1_5TextValidator(cost_tracker=tracker)
    result = validator.run("output/3A Parasito (CT)/step1_extraction/accepted")
    print(f"\nValidation Results: {result}")
