import os
import json
import time
from typing import List, Dict, Any, Optional
from pathlib import Path
from PIL import Image

class OCRProcessor:
    """
    Handles page-by-page OCR extraction with user guidance and persistent text storage.
    Phase 1 of the Enhanced OCR Pipeline.
    """
    
    def __init__(self, vision_client, output_dir_base='ocr_output', model_name=None):
        """
        Args:
            vision_client: OpenRouterClient instance
            output_dir_base: Base directory for storing OCR results
            model_name: Specific model to use (default: env or qwen-2.5-vl-7b)
        """
        self.client = vision_client
        self.output_dir_base = output_dir_base
        # Default to env setting or fall back to efficient model
        self.model = model_name or os.getenv("OCR_MODEL", "qwen/qwen-2.5-vl-7b-instruct")
        
    def collect_ocr_guidance(self) -> str:
        """Interactive prompt for OCR hints"""
        print("\n" + "-" * 50)
        print("🔍 STAGE 1: OCR GUIDANCE")
        
        print("-" * 50)
        print("Help the AI understand this document's visual structure.")
        print("Examples:")
        print("  - 'Questions are numbered 1-60'")
        print("  - 'Answers are highlighted in yellow'")
        print("  - 'Two-column layout, read left column first'")
        print("  - 'Ignore handwritten notes in margins'")
        
        guidance = input("\nEnter OCR guidance (or Press Enter to skip): ").strip()
        return guidance

    def process_document(self, pages: List[Image.Image], guidance: str = "") -> Dict[str, Any]:
        """
        Process each page individually with guidance.
        Saves results to a timestamped subdirectory to allow debugging/re-use.
        """
        if not pages:
            raise ValueError("No pages provided for OCR processing.")

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join(self.output_dir_base, timestamp)
        os.makedirs(output_dir, exist_ok=True)
        
        print(f"\n🚀 Starting Page-by-Page OCR")
        print(f"   Model: {self.model}")
        print(f"   Output Store: {output_dir}")
        print(f"   Guidance: {guidance if guidance else 'None'}")
        
        results = {
            'output_dir': output_dir,
            'pages': {},
            'total_cost': 0.0,
            'model': self.model,
            'guidance': guidance,
            'timestamp': timestamp,
            'page_count': len(pages)
        }
        
        manifest_data = [] # For saving detailed metadata about each page run
        
        for i, page_img in enumerate(pages):
            page_num = i + 1
            print(f"\n📄 Processing Page {page_num}/{len(pages)}...", end="", flush=True)
            
            # Construct Guided Prompt
            prompt = "Extract ALL text from this image exactly as it appears. Preserve layout structure."
            if guidance:
                prompt += f"\n\nUSER GUIDANCE (Pay attention to this):\n{guidance}"
            
            # Small optimization: Append standard instruction about robustness
            prompt += "\n\nReturn the raw text content only. Do not add markdown code blocks unless they are part of the original text."

            try:
                start_t = time.time()
                
                # Call Vision API using OpenRouterClient
                # Assuming client.generate_completion(prompt, [image], model=...)
                # Note: OpenRouterClient.generate_completion signature might need model override or we rely on client default if passed during init
                # But here we want explicit control. The client handles 'model' param in payload construction if passed? 
                # Let's check OpenRouterClient.generate_completion... 
                # It currently takes prompt, images, max_tokens. It relies on self.model.
                # So we might need to temporarily override or update OpenRouterClient. 
                # **Correction**: In `openrouter_client.py` (checked memory), generate_completion takes prompt, images, max_tokens. Use self.model. 
                # However, this class can set client.model before calling.
                
                original_model = self.client.model
                self.client.model = self.model
                
                response = self.client.generate_completion(
                    prompt=prompt,
                    images=[page_img],
                    max_tokens=4000
                )
                
                self.client.model = original_model # Restore just in case
                
                duration = time.time() - start_t
                
                # Handle response format (dict or string based on recent changes?)
                # We updated it to return dict {'content':..., 'usage':...}
                content = ""
                usage = {}
                
                if isinstance(response, dict):
                    content = response.get('content', '')
                    usage = response.get('usage', {})
                else: 
                    # Fallback if old version
                    content = str(response)
                
                # Cost Calculation
                cost = response.get('cost', 0.0) or self.client.estimate_cost(self.model, usage)
                results['total_cost'] += cost
                
                # Save Text Content
                filename = f"page_{page_num}.txt"
                file_path = os.path.join(output_dir, filename)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
                    
                results['pages'][page_num] = file_path
                
                # Update manifest
                manifest_data.append({
                    "page": page_num,
                    "file": filename,
                    "cost": cost,
                    "duration": duration,
                    "tokens": usage.get('total_tokens', 0)
                })
                
                print(f" Done! (${cost:.4f})")
                
            except Exception as e:
                print(f" ❌ Error: {e}")
                # Log error
                err_file = os.path.join(output_dir, f"page_{page_num}_error.txt")
                with open(err_file, "w", encoding="utf-8") as f:
                    f.write(str(e))
                results['pages'][page_num] = None
        
        # Save manifest.json
        manifest_path = os.path.join(output_dir, "manifest.json")
        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump({
                    "meta": {
                        "timestamp": timestamp,
                        "model": self.model,
                        "guidance": guidance,
                        "total_pages": len(pages),
                        "total_cost": results['total_cost']
                    },
                    "pages": manifest_data
                }, f, indent=2)
        except Exception as e:
            print(f"⚠️ Warning: Could not save manifest: {e}")
            
        print(f"\n✅ OCR Processing Complete!")
        print(f"   Output saved to: {output_dir}")
        print(f"   Total Cost: ${results['total_cost']:.4f}")
        
        return results
