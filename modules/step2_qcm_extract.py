import json
import os
import re
from pathlib import Path
from typing import Dict, List, Any

from modules.openrouter_client import OpenRouterClient
from modules.utils.cost_tracker import CostTracker
from modules.utils.prompt_helper import PromptHelper
from modules.utils.file_manager import FileManager
from modules.step2_5_qcm_merger import Step2_5QCMMerger

class Step2QCMExtract:
    """
    v6.0 - Full Page Semantic Extraction
    Uses AI to detect QCMs directly without rigid regex patterns.
    """
    
    def __init__(self, cost_tracker: CostTracker, project_context=None):
        # We get the models from env at runtime, no need to set here
        self.client.model = None 
        
        self.cost_tracker = cost_tracker
        self.file_manager = FileManager()
        self.prompt_helper = PromptHelper()
        self.context = project_context
        
    def run(self, input_dir: str = None) -> Dict:
        """Main execution for Step 2."""
        print("\n" + "="*60)
        print("STEP 2: QCM CONTENT EXTRACTION (v6.0 - Semantic AI)")
        print("="*60)
        
        # Determine input directory
        if self.context:
            target_input_dir = self.context.get_path("step1_extraction", "accepted")
        else:
            target_input_dir = input_dir if input_dir else "output/step1_extraction/accepted"
            
        txt_files = sorted(
            Path(target_input_dir).glob("*.txt"), 
            key=lambda x: self._extract_page_number(x.name)
        )
        
        if not txt_files:
            print(f"❌ No text files found in {target_input_dir}")
            return {"total_extracted": 0}
            
        print(f"📄 Found {len(txt_files)} pages to process in {target_input_dir}")
        
        # Get user guidance ONCE for all pages
        guidance = self.prompt_helper.get_user_guidance(
            "Extraction Strategy",
            "Initial extraction rules",
            [
                "The AI will semantically detect QCMs, not rely on number patterns",
                "Works even if questions have bold markers like **10)**",
                "Works even if some questions have no numbers",
                "Specify any pages to skip (e.g., 'skip page 1, 11')"
            ]
        )
        
        all_results = []
        for txt_file in txt_files:
            page_results = self._process_page_semantic(txt_file, guidance)
            if page_results:
                all_results.extend(page_results)
        
        # Post-processing: Allow re-extraction of specific pages
        while True:
            print("\n" + "="*60)
            print(f"✅ Extraction Complete. {len(all_results)} QCMs extracted.")
            print("="*60)
            print("Options:")
            print("  [R] Re-extract specific page(s)")
            print("  [C] Continue to next step")
            
            choice = input("\nChoice [R/C]: ").strip().upper()
            
            if choice == "R":
                page_input = input("Enter page number(s) to re-extract (e.g., '3' or '3,5,7'): ").strip()
                try:
                    pages_to_redo = [int(p.strip()) for p in page_input.split(",")]
                    for page_num in pages_to_redo:
                        # Find the file
                        target_file = None
                        for f in txt_files:
                            if self._extract_page_number(f.name) == page_num:
                                target_file = f
                                break
                        
                        if target_file:
                            print(f"\n🔄 Re-extracting page {page_num}...")
                            new_results = self._process_page_semantic(target_file, guidance)
                            
                            # Remove old results for this page
                            all_results = [r for r in all_results if r.get('page') != page_num]
                            
                            # Add new results
                            if new_results:
                                all_results.extend(new_results)
                                print(f"✅ Page {page_num} re-extracted successfully.")
                        else:
                            print(f"❌ Page {page_num} not found.")
                except ValueError:
                    print("❌ Invalid input. Please enter numbers separated by commas.")
            else:
                break
        
        # ============================================================
        # AUTOMATIC STEP 2.5: Merge split QCMs
        # ============================================================
        print("\n🔗 Running automatic QCM merger (Step 2.5)...")
        try:
            merger = Step2_5QCMMerger(project_context=self.context)
            merge_result = merger.run(
                input_dir=str(self.context.get_path("step2_qcm", "accepted")) if self.context else None
            )
            
            if merge_result['merged_count'] > 0:
                print(f"✅ Merged {merge_result['merged_count']} split QCMs automatically")
            else:
                print("✅ No split QCMs detected")
        except Exception as e:
            print(f"⚠️  Warning: Auto-merge failed: {e}")
            print("   Continuing with un-merged data...")
        # ============================================================
                
        print(f"\n✅ Step 2 Complete. Total QCMs extracted: {len(all_results)}")
        return {"total_extracted": len(all_results)}

    def _process_page_semantic(self, file_path: Path, global_guidance: str) -> List[Dict]:
        """
        Process a page using SEMANTIC AI detection.
        """
        page_num = self._extract_page_number(file_path.name)
        print(f"\n🔍 Processing Page {page_num}...")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                full_text = f.read()
        except Exception as e:
            print(f"❌ Error reading {file_path}: {e}")
            return []
        
        # Check if user wants to skip this page
        if self._should_skip_page(page_num, global_guidance):
            print(f"⏭️  Skipping Page {page_num} (per user guidance)")
            return []
        
        # Build semantic extraction prompt
        prompt = self._build_semantic_prompt(full_text, page_num, global_guidance)
        
        primary_model = os.getenv("STEP2_MODEL", "google/gemini-2.5-flash-lite-preview-09-2025")
        fallback_model = os.getenv("STEP2_FALLBACK_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
        max_tokens = int(os.getenv("STEP2_MAX_TOKENS", "20000"))
        
        try:
            try:
                response = self.client.generate_completion(prompt, model=primary_model, max_tokens=max_tokens)
                model_used = primary_model
            except Exception as e:
                print(f"[WARN] Primary model failed: {e}")
                print(f"[INFO] Retrying with fallback: {fallback_model}")
                response = self.client.generate_completion(prompt, model=fallback_model, max_tokens=max_tokens)
                model_used = fallback_model

            content = response["content"]
            # Calculate cost
            cost = response.get('cost', 0.0) or self.client.estimate_cost(model_used, response["usage"])
            self.cost_tracker.log_api_call(
                f"step2_p{page_num}", 
                model_used, 
                response["usage"], 
                cost
            )
            
            page_qcms = self._parse_json(content)
            
            if not page_qcms:
                print(f"⚠️  No QCMs found on Page {page_num}.")
                choice = input("[R]etry with guidance | [S]kip | [D]ebug: ").lower().strip()
                if choice == 'r':
                    new_guidance = input("New guidance: ")
                    return self._process_page_semantic(file_path, new_guidance)
                elif choice == 'd':
                    print(f"\n--- RAW RESPONSE ---\n{content[:1500]}...")
                return []
            
            # Show results
            print(f"📊 Found {len(page_qcms)} QCMs:")
            for q in page_qcms[:3]:
                num = q.get('number', '?')
                text = (q.get('text', '') or '')[:50]
                print(f"   Q{num}: {text}...")
            if len(page_qcms) > 3:
                print(f"   ... and {len(page_qcms)-3} more.")
            
            choice = input(f"[A]ccept | [V]iew all | [R]etry | [S]kip: ").lower().strip()
            
            if choice == 'a':
                self._save_results(page_qcms, page_num)
                return page_qcms
            elif choice == 'v':
                print(json.dumps(page_qcms, indent=2, ensure_ascii=False))
                return self._accept_or_skip(page_qcms, page_num)
            elif choice == 'r':
                new_guidance = input("New guidance: ")
                return self._process_page_semantic(file_path, new_guidance)
            else:
                return []
                
        except Exception as e:
            print(f"❌ Error: {e}")
            return []

    def _save_results(self, qcms: List[Dict], page_num: int):
        """Save results to appropriate folder."""
        if self.context:
            path = self.context.get_path("step2_qcm", "accepted") / f"page_{page_num}.json"
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(qcms, f, indent=2, ensure_ascii=False)
            print(f"Saved to {path}")
        else:
            self.file_manager.save_accepted("step2_qcm", f"page_{page_num}.json", qcms)

    def _accept_or_skip(self, qcms: List[Dict], page_num: int) -> List[Dict]:
        choice = input(f"[A]ccept | [S]kip: ").lower().strip()
        if choice == 'a':
            self._save_results(qcms, page_num)
            return qcms
        return []

    def _build_semantic_prompt(self, text: str, page_num: int, guidance: str) -> str:
        """
        Build a SEMANTIC extraction prompt that doesn't rely on regex.
        The AI must understand the CONTENT, not match patterns.
        """
        return f"""
TASK: Extract ALL medical QCMs (Multiple Choice Questions) from this page.

🧠 SEMANTIC UNDERSTANDING (VERY IMPORTANT):
You must READ and UNDERSTAND the text to identify QCMs. Do NOT rely on simple number patterns.

A QCM typically has:
- A question stem (may or may not start with a number)
- Multiple propositions labeled A, B, C, D, E (or similar)
- Sometimes the number has formatting like **10)** or is missing

📋 EXAMPLES OF WHAT TO DETECT:
1. Standard: "10) Une thrombopénie périphérique... A. ... B. ... C. ... D. ... E. ..."
2. Bold format: "**10)** Une thrombopénie... A. ... B. ..."
3. No number: "Une thrombopénie périphérique peut être... A. ... B. ... C. ... D. ... E. ..."
4. Different numbering: "Question N°10: ..."

🚫 IGNORE (OCR NOISE):
- "Here is the extracted text from the image..."
- "---" (horizontal rules)
- "3/12 pages" (page headers)
- "restored to its natural reading order"

✅ PRESERVE METADATA:
If you see text like "Biologie", "Cardiologie", "2014" near a question, 
include it in the metadata_detected field.

USER GUIDANCE: {guidance}

⚠️ IMPORTANT OUTPUT RULES:
1. START DIRECTLY with `[` (Do NOT use ```json or ```).
2. END DIRECTLY with `]`.
3. SEPARATE objects with COMMAS `,`.
4. ESCAPE quotes inside strings (`\"`).

OUTPUT FORMAT:
[
  {{
    "number": 10,
    "text": "Question content...",
    "propositions": {{"A": "...", "B": "..."}},
    "correction": null,
    "page": {page_num},
    "metadata_detected": {{ "module": null, "source": null, "year": null }}
  }}
]

If NO valid QCMs found, return exactly: []

PAGE TEXT:
{text}
"""

    def _should_skip_page(self, page_num: int, guidance: str) -> bool:
        """Check if user guidance says to skip this page."""
        skip_patterns = [
            f"skip page {page_num}",
            f"skip {page_num}",
            f"ignore page {page_num}",
            f"page {page_num} is correction"
        ]
        guidance_lower = guidance.lower()
        return any(p in guidance_lower for p in skip_patterns)

    def _accept_or_skip(self, qcms: List[Dict], page_num: int) -> List[Dict]:
        choice = input(f"[A]ccept | [S]kip: ").lower().strip()
        if choice == 'a':
            self.file_manager.save_accepted("step2_qcm", f"page_{page_num}.json", qcms)
            return qcms
        return []

    def _parse_json(self, content: str) -> List[Dict]:
        """
        Robust JSON extraction that handles common LLM errors.
        Strategies:
        1. Clean logic (trailing commas, missing commas).
        2. Fallback: Stream Decoder (extracts individual objects if list structure matches).
        """
        import re
        
        # Step 1: Remove markdown code blocks
        content = re.sub(r'```json\s*', '', content)
        content = re.sub(r'```\s*', '', content)
        
        # Step 2: Find JSON boundaries
        # Remove anything BEFORE the first [ or {
        array_start = content.find('[')
        object_start = content.find('{')
        
        start_idx = -1
        if array_start != -1 and object_start != -1:
            start_idx = min(array_start, object_start)
        elif array_start != -1:
            start_idx = array_start
        elif object_start != -1:
            start_idx = object_start
            
        if start_idx >= 0:
            content = content[start_idx:]
        
        # Step 3: Remove anything AFTER the last ] or }
        content = content.strip()
        last_array = content.rfind(']')
        last_object = content.rfind('}')
        end_idx = max(last_array, last_object)
        
        if end_idx != -1 and end_idx < len(content) - 1:
            content = content[:end_idx + 1]
        
        # Strategy A: Try Standard with Cleanups
        cleaned_content = content
        cleaned_content = re.sub(r',(\s*[}\]])', r'\1', cleaned_content) # Trailing commas
        cleaned_content = re.sub(r'}(\s*){', r'}, \1{', cleaned_content) # Missing comma between objects
        cleaned_content = re.sub(r'}(\s*)"number"', r'}, \1"number"', cleaned_content)

        try:
            data = json.loads(cleaned_content)
            if isinstance(data, dict): return [data]
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            pass # Continue to Strategy B

        # Strategy B: Stream Decoder (The "Nuclear Option" for bad lists)
        # This ignores the outer structure and blindly hunts for valid JSON objects
        try:
            objects = []
            decoder = json.JSONDecoder()
            pos = 0
            while pos < len(content):
                # Skip whitespace/garbage until we find a {
                if content[pos].isspace() or content[pos] in ',[]':
                    pos += 1
                    continue
                
                try:
                    obj, idx = decoder.raw_decode(content, pos)
                    if isinstance(obj, dict):
                        objects.append(obj)
                    pos = idx
                except json.JSONDecodeError:
                    pos += 1 # Skip invalid char and try next
            
            if objects:
                return objects
        except Exception:
            pass

        # If all failed, log it
        print(f"⚠️  JSON extraction failed.")
        with open('debug_json_error.txt', 'w', encoding='utf-8') as f:
            f.write(f"Parsed Content:\n{content}\n\nOriginal Error attempt failed.")
        return []

    def _extract_page_number(self, filename: str) -> int:
        match = re.search(r'page_(\d+)', filename)
        return int(match.group(1)) if match else 0