import json
from difflib import SequenceMatcher
from typing import Dict, Any, Optional
from pathlib import Path

class MetadataAnalyzer:
    """
    Analyzes document text to extract metadata using DeepSeek reasoning models.
    Works with output from TextExtractionManager.
    """
    
    def __init__(self, deepseek_client, modules_file_path: str):
        """
        Args:
            deepseek_client: Instance of DeepSeekClient
            modules_file_path: Path to modules-bio-chir-med.json
        """
        self.deepseek = deepseek_client
        self.modules = self._load_modules(modules_file_path)
        
    def analyze_from_saved_ocr(self, ocr_output_dir: str, guidance: str = "") -> Dict[str, Any]:
        """
        Read all page_N.txt files and analyze with DeepSeek.
        Phase 2 of Enhanced Pipeline.
        """
        print(f"\n🧠 Analyzing from saved OCR text...")
        print(f"   Source: {ocr_output_dir}")
        
        # Read text files
        pages = {}
        total_pages = 0
        
        try:
            # Find all .txt files
            txt_files = list(Path(ocr_output_dir).glob("page_*.txt"))
            total_pages = len(txt_files)
            
            for f in txt_files:
                # Extract page number from filename "page_1.txt"
                try:
                    num = int(f.stem.split('_')[1])
                    with open(f, 'r', encoding='utf-8') as file:
                        pages[num] = file.read()
                except:
                    continue
                    
            if not pages:
                raise ValueError("No text files found in output directory")
                
            # Create extracted_text structure compatible with existing methods
            extracted_text = {
                'pages': pages,
                'total_pages': total_pages,
                'method_used': 'persistent_ocr',
                'extraction_cost': 0.0 # Already paid for
            }
            
            # Prepare text
            text_for_analysis = self._prepare_text_for_analysis(extracted_text)
            
            # Build prompt with guidance
            prompt = self._build_analysis_prompt(text_for_analysis, total_pages)
            if guidance:
                prompt += f"\n\nUSER GUIDANCE FOR ANALYSIS:\n{guidance}\n(Pay strict attention to this guidance)"
            
            # Call DeepSeek
            # We use the existing _call_api via client logic
            # Call DeepSeek manually below
            # Wait, the existing analyze_document calls _build_analysis_prompt internally without guidance param.
            # We should refactor slightly or override. 
            # Better approach: We implement the core call here cleanly.
            
            # Re-build prompt correctly with guidance
            final_prompt = prompt 
            
            response_data = self.deepseek._call_api(final_prompt, system_prompt="You are a medical exam metadata extractor.")
            
            content = response_data['choices'][0]['message']['content']
            usage = response_data.get('usage', {})
            api_cost = usage.get('cost', 0.0)
            cost = float(api_cost) if api_cost and float(api_cost) > 0 else self.deepseek.estimate_cost(response_data)
            
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                parsed_result = json.loads(json_match.group(0))
            else:
                raise ValueError("No valid JSON returned")
                
            # Match module
            if parsed_result.get('module'):
                matched = self.match_module(parsed_result['module'])
                parsed_result['matched_module'] = matched
            else:
                parsed_result['matched_module'] = None
                
            parsed_result['analysis_cost'] = cost
            return parsed_result

        except Exception as e:
            print(f"❌ Analysis parsing error: {e}")
            return {'error': str(e)}
    
    def _prepare_text_for_analysis(self, extracted_text: Dict[str, Any]) -> str:
        """
        Prepare text for DeepSeek analysis.
        Strategy: Page 1-3 fully + Last Page fully + Random samples.
        """
        pages = extracted_text['pages']
        total_pages = extracted_text['total_pages']
        
        text_parts = []
        
        # Header: First 3 pages
        count = 0
        for i in range(1, total_pages + 1):
            if i in pages:
                text_parts.append(f"=== PAGE {i} ===\n{pages[i]}")
                count += 1
                if count >= 3:
                    break
        
        # Footer: Last page (if not already included)
        if total_pages > 3 and total_pages in pages:
            text_parts.append(f"=== PAGE {total_pages} (LAST) ===\n{pages[total_pages]}")
        
        # Body: Sample every 10th page if document is long
        if total_pages > 10:
            for i in range(5, total_pages, 10):
                if i in pages:
                    # Take first 500 chars only
                    text_parts.append(f"=== PAGE {i} (SAMPLE) ===\n{pages[i][:500]}...")
        
        combined = "\n\n".join(text_parts)
        
        # Truncate to safety limit (approx 8k tokens -> 30k chars is safe for 70b models, but we keep it tight)
        max_chars = 15000
        if len(combined) > max_chars:
            combined = combined[:max_chars] + "\n\n[... TRUNCATED ...]"
            
        return combined
    
    def _build_analysis_prompt(self, text: str, total_pages: int) -> str:
        """
        Build comprehensive prompt for DeepSeek.
        """
        return f"""Analyze this French medical examination document and extract metadata.

DOCUMENT INFO:
- Total pages: {total_pages}
- Text provided: First/last pages + samples from middle

YOUR TASK:
Extract the following information:

1. **Source**: University/Institution name or exam context (e.g., "Faculté de Médecine de Blida", "Residanat 2016").
   Look in headers, footers, or title pages.

2. **Year**: Academic year or exam date (e.g., 2024, "2024-2025").

3. **Module**: The specific medical specialty (e.g., "Cardiologie", "Traumatologie", "Biochimie").
   Crucial: Look at the *content* of the questions if the title is ambiguous.

4. **Domain Classification**: Based on the module, classify into:
   - "Biologie": (Biochimie, Microbio, Parasito, Immuno, etc.)
   - "Chirurgie": (Ortho, Uro, Neurochir, Ophtalmo, etc.)
   - "Medecine": (Cardio, Pneumo, Pedia, Neuro, etc.)

DOCUMENT TEXT:
\"\"\"
{text}
\"\"\"

Return ONLY valid JSON (no markdown):
{{
  "source": "detected source or null",
  "year": number or null,
  "module": "specific module name or null",
  "domain_tag": "Biologie" or "Chirurgie" or "Medecine" or null,
  "confidence": {{
    "source": 0.5,
    "year": 0.5,
    "module": 0.5
  }},
  "reasoning": "brief explanation"
}}
"""
    
    def match_module(self, detected_module: str) -> Optional[Dict[str, Any]]:
        """
        Match detected module to modules-bio-chir-med.json database using fuzzy matching.
        """
        if not detected_module:
            return None
            
        best_match = None
        best_score = 0.0
        
        detected_norm = detected_module.lower().strip()
        
        # Iterate over categories (medecine, chirurgie, biologie)
        for category, modules in self.modules.items():
            for module_name in modules:
                module_norm = module_name.lower()
                
                # 1. Exact substring match (Very strong)
                if detected_norm == module_norm:
                    return {'matched_name': module_name, 'categoryName': module_name, 'tag': category, 'confidence': 1.0}
                
                # 2. Sequential Similarity
                similarity = SequenceMatcher(None, detected_norm, module_norm).ratio()
                
                # 3. Boost if one contains the other
                if detected_norm in module_norm or module_norm in detected_norm:
                    similarity = max(similarity, 0.85)
                
                if similarity > best_score:
                    best_score = similarity
                    best_match = {
                        'matched_name': module_name,
                        'categoryName': module_name,
                        'tag': category,
                        'confidence': similarity
                    }
        
        # Threshold: 0.6 (allows for typos but filters total deviations)
        if best_match and best_match['confidence'] > 0.6:
            return best_match
        
        return None
    
    def _load_modules(self, file_path: str) -> Dict[str, Any]:
        """
        Load modules from JSON file.
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Warning: Could not load modules file: {e}")
            return {}
