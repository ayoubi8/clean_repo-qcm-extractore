import os
import json
import time
from typing import List, Dict, Any, Optional
from pathlib import Path
from modules.deepseek_client import DeepSeekClient

class TextQCMParser:
    """
    Parses QCMs directly from saved OCR text files using DeepSeek reasoning.
    Phase 3 of the Enhanced Pipeline.
    """
    
    def __init__(self, deepseek_client: DeepSeekClient):
        self.client = deepseek_client

    def parse_from_ocr(
        self, 
        ocr_output_dir: str,
        metadata: Dict[str, Any],
        guidance: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Main logic to parse QCMs from text files.
        """
        print(f"\n🚀 Starting Text-Based QCM Parsing")
        print(f"   Source: {ocr_output_dir}")
        print(f"   Context: {metadata.get('module')} ({metadata.get('year')})")
        
        all_qcms = []
        
        # Find all page files
        txt_files = sorted(list(Path(ocr_output_dir).glob("page_*.txt")), key=lambda p: int(p.stem.split('_')[1]))
        
        if not txt_files:
            raise ValueError("No OCR text files found to parse!")
            
        print(f"   Found {len(txt_files)} pages to process.")
        
        # Process in batches to keep context manageable
        batch_size = 5
        total_batches = (len(txt_files) + batch_size - 1) // batch_size
        
        for i in range(0, len(txt_files), batch_size):
            batch = txt_files[i:i+batch_size]
            batch_num = (i // batch_size) + 1
            print(f"\n📦 Parsing Batch {batch_num}/{total_batches}...", end="", flush=True)
            
            qcms = self._process_batch(batch, metadata, guidance)
            all_qcms.extend(qcms)
            print(f" Extracted {len(qcms)} QCMs")
            
        return all_qcms

    def _process_batch(self, batch_files: List[Path], metadata: Dict[str, Any], guidance: str) -> List[Dict[str, Any]]:
        """
        Process a batch of text files.
        """
        # 1. Combine text
        combined_text = ""
        
        for f in batch_files:
            try:
                p_num = int(f.stem.split('_')[1])
                content = f.read_text(encoding='utf-8')
                combined_text += f"\n--- PAGE {p_num} START ---\n{content}\n--- PAGE {p_num} END ---\n"
            except Exception as e:
                print(f"Error reading {f}: {e}")

        # 2. Build Prompt
        prompt = self._build_parsing_prompt(combined_text, metadata, guidance)
        
        # 3. Call DeepSeek
        try:
            response = self.client._call_api(prompt, system_prompt="You are a strict QCM extraction engine. Return ONLY valid JSON, no explanations.")
            content = response['choices'][0]['message']['content']
            
            # Save raw response for debugging
            batch_num = int(batch_files[0].stem.split('_')[1])
            debug_file = f"debug_batch_{batch_num}_response.txt"
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # 4. Parse JSON
            extracted = self._extract_json_block(content)
            qcms = extracted.get('qcms', [])
            
            # 5. Clean/Validate
            validated_qcms = []
            for q in qcms:
                if 'text' in q and 'propositions' in q:
                    if 'page' not in q:
                        q['page'] = int(batch_files[0].stem.split('_')[1])
                    validated_qcms.append(q)
            
            return validated_qcms
            
        except Exception as e:
            print(f" ❌ Batch parsing failed: {e}")
            # Save error details
            batch_num = int(batch_files[0].stem.split('_')[1])
            error_file = f"debug_batch_{batch_num}_error.txt"
            with open(error_file, 'w', encoding='utf-8') as f:
                f.write(f"Error: {str(e)}\n\nRaw Response:\n{content if 'content' in locals() else 'No response captured'}")
            return []

    def _build_parsing_prompt(self, text: str, metadata: Dict[str, Any], guidance: str) -> str:
        return f"""
CONTEXT:
- Source: {metadata.get('source') or "Not specified"}
- Year: {metadata.get('year') or "Not specified"}  
- Module: {metadata.get('module') or "Not specified"}
- Domain: {metadata.get('domain_tag') or "Not specified"}

USER GUIDANCE (CRITICAL RULES):
{guidance}

TASK:
Extract ALL Multiple Choice Questions (QCM) from the text below.
- Preserve exact numbering (e.g., "10", "11", "12").
- Preserve all propositions (A, B, C, D, E).
- Do NOT include corrections unless explicitly visible next to the question.
- Ignore headers/footers like "Biologie 3/12 pages".

INPUT TEXT:
{text}

CRITICAL OUTPUT RULES:
1. Return ONLY raw JSON, no markdown blocks, no explanations
2. No trailing commas in JSON
3. Use double quotes for all strings
4. Format:
{{
  "qcms": [
    {{
      "number": 10,
      "text": "Question text here...",
      "propositions": {{"A": "prop A", "B": "prop B", "C": "prop C", "D": "prop D", "E": "prop E"}},
      "correction": null,
      "page": 2
    }}
  ]
}}
"""

    def _extract_json_block(self, text: str) -> Dict[str, Any]:
        """Robust JSON extraction with cleaning"""
        import re
        
        # Step 1: Remove markdown code blocks
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)
        
        # Step 2: Find JSON object
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in response")
            
        json_str = match.group(0)
        
        # Step 3: Clean common JSON errors
        # Remove trailing commas before closing braces/brackets
        json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
        
        # Remove comments (// style)
        json_str = re.sub(r'//.*?$', '', json_str, flags=re.MULTILINE)
        
        # Step 4: Parse
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            # Save malformed JSON for inspection
            with open('debug_malformed.json', 'w', encoding='utf-8') as f:
                f.write(json_str)
            raise ValueError(f"JSON parsing failed: {e}. Saved to debug_malformed.json")

