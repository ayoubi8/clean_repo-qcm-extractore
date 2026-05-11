import os
import re
from pathlib import Path
from typing import Dict, Any, List
import concurrent.futures

from modules.openrouter_client import OpenRouterClient
from modules.utils.cost_tracker import CostTracker

class Step1_6IntelligentTextFixer:
    """
    Step 1.6 - Intelligent Text Fixing
    Uses an LLM to correct OCR errors in medical French text before QCM extraction.
    """
    
    def __init__(self, cost_tracker: CostTracker = None, project_context=None):
        self.client = OpenRouterClient()
        self.cost_tracker = cost_tracker
        self.context = project_context
        
    def run(self, input_dir: str = None, config: Dict = None) -> Dict[str, Any]:
        print("\n" + "="*60)
        print("STEP 1.6: INTELLIGENT TEXT FIXER (OCR Correction)")
        print("="*60)
        
        if self.context:
            target_input_dir = self.context.get_path("step1_extraction", "accepted")
        else:
            target_input_dir = Path(input_dir) if input_dir else Path("output/step1_extraction/accepted")
            
        txt_files = sorted(
            Path(target_input_dir).glob("page_*.txt"),
            key=lambda x: int(re.search(r'page_(\d+)', x.name).group(1))
        )
        
        if not txt_files:
            print(f"❌ No text files found in {target_input_dir}")
            return {"status": "error"}
            
        # Parse config
        primary_model = os.getenv("STEP1_6_MODEL", "meta-llama/llama-3.3-70b-instruct")
        fallback_model = os.getenv("STEP1_6_FALLBACK_MODEL", "google/gemini-2.0-flash-lite-001")
        max_tokens = int(os.getenv("STEP1_6_MAX_TOKENS", "4000"))
        guidance = config.get("guidance", "Focus on medical French terminology. l/I confusion, missing accents.") if config else ""
        
        print(f"🧠 Using AI: {primary_model}")
        print(f"📄 Processing {len(txt_files)} pages...")
        
        fixed_count = 0
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_to_file = {
                executor.submit(self._fix_text_file, txt_file, primary_model, fallback_model, max_tokens, guidance): txt_file
                for txt_file in txt_files
            }
            
            for future in concurrent.futures.as_completed(future_to_file):
                txt_file = future_to_file[future]
                try:
                    result = future.result()
                    if result:
                        fixed_count += 1
                except Exception as e:
                    print(f"❌ Failed to process {txt_file.name}: {e}")
                    
        print(f"\n✅ Step 1.6 Complete: Processed {fixed_count} pages.")
        return {"status": "success", "processed": fixed_count}
        
    def _fix_text_file(self, txt_file: Path, primary_model: str, fallback_model: str, max_tokens: int, guidance: str) -> bool:
        content = txt_file.read_text(encoding='utf-8')
        
        prompt = f"""Fix OCR errors in this French medical exam text.
RULES:
1. Fix wrong letters, missing accents, and split medical terms
2. Preserve ALL question numbers, proposition letters (A/B/C/D/E), and structure EXACTLY
3. Do NOT change any medical facts, numbers, or answer content
4. Return ONLY the corrected text, no explanations, no wrappers.
GUIDANCE: {guidance}

TEXT:
{content}
"""

        try:
            try:
                response = self.client.generate_completion(prompt, model=primary_model, max_tokens=max_tokens)
                used_model = primary_model
            except Exception as e:
                print(f"  [WARN] Primary model failed for {txt_file.name}: {e}")
                print(f"  [INFO] Retrying with fallback: {fallback_model}")
                response = self.client.generate_completion(prompt, model=fallback_model, max_tokens=max_tokens)
                used_model = fallback_model
                
            fixed_content = response['content']
            
            # Remove markdown code blocks if the LLM added them
            fixed_content = re.sub(r'^```[\w]*\n?', '', fixed_content)
            fixed_content = re.sub(r'\n?```$', '', fixed_content)
            
            # Log cost
            if self.cost_tracker:
                cost = response.get('cost', 0.0) or self.client.estimate_cost(used_model, response['usage'])
                self.cost_tracker.log_api_call("step1_6_text_fix", used_model, response['usage'], cost)
                
            # Write back
            txt_file.write_text(fixed_content, encoding='utf-8')
            print(f"  ✅ Fixed {txt_file.name}")
            return True
        except Exception as e:
            print(f"  ❌ Error fixing {txt_file.name}: {e}")
            return False
