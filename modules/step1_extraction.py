import os
from pathlib import Path
from typing import List, Dict
from PIL import Image
import pypdfium2 as pdfium
from concurrent.futures import ThreadPoolExecutor, as_completed

from modules.document_processor import DocumentProcessor
from modules.openrouter_client import OpenRouterClient
from modules.utils.cost_tracker import CostTracker
from modules.utils.prompt_helper import PromptHelper
from modules.utils.file_manager import FileManager
from modules.utils.ocr_cache import OCRCache

class Step1Extraction:
    """Text extraction with dual mode: pypdfium2 or Vision OCR"""
    
    def __init__(self, cost_tracker: CostTracker, project_context=None):
        self.cost_tracker = cost_tracker
        self.file_manager = FileManager()
        self.prompt_helper = PromptHelper()
        self.context = project_context
        self.cache = OCRCache()
    
    def run(self, pdf_path: str, auto_ocr: bool = False, ocr_guidance: str = "") -> Dict:
        """
        Main execution
        Returns: {"output_dir": "output/project/step1_extraction", "method": "vision_ocr", "cost": 0.0073}
        """
        print("\n" + "="*60)
        print("STEP 1: TEXT EXTRACTION")
        print("="*60)
        
        # Load document
        doc_processor = DocumentProcessor(pdf_path)
        pages = doc_processor.load_document()
        
        if not pages:
            print("❌ No pages loaded from PDF.")
            return {}
            
        # Choose method
        if auto_ocr:
            print(f"\n[AUTO] Using Vision OCR (as configured)")
            return self._extract_with_vision(pdf_path, pages, ocr_guidance)
        
        print("\nSelect extraction method:")
        print("  1. pypdfium2 (Fast, free, text-based PDFs)")
        print("  2. Vision OCR (Scanned PDFs, costs ~$0.0005/page)")
        choice = input("Choice [1-2]: ").strip()
        
        if choice == "1":
            return self._extract_with_pypdfium2(pdf_path, len(pages))
        else:
            return self._extract_with_vision(pdf_path, pages)
    
    def _extract_with_pypdfium2(self, pdf_path: str, page_count: int) -> Dict:
        """Free extraction using pypdfium2"""
        print(f"\nExtracting {page_count} pages with pypdfium2...")
        
        pdf = pdfium.PdfDocument(pdf_path)
        
        for i, page in enumerate(pdf, 1):
            textpage = page.get_textpage()
            text = textpage.get_text_range()
            
            # Save using project context
            if self.context:
                path = self.context.get_path("step1_extraction", "accepted") / f"page_{i}.txt"
            else:
                # Fallback for legacy
                path = Path("output/step1_extraction/accepted") / f"page_{i}.txt"
                path.parent.mkdir(parents=True, exist_ok=True)
                
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
                
            print(f"Page {i}/{page_count}... ✓ (Free)")
        
        output_dir = str(path.parent) if self.context else "output/step1_extraction/accepted"
        
        return {
            "output_dir": output_dir,
            "method": "pypdfium2",
            "cost": 0.0,
            "page_count": page_count
        }
    
    def _extract_with_vision(self, pdf_path: str, pages: List[Image.Image], guidance: str = "") -> Dict:
        """OCR extraction using Vision AI (with caching and parallel processing)"""
        if not guidance:
            guidance = self.prompt_helper.get_user_guidance(
                "OCR Guidance",
                f"Processing {len(pages)} pages",
                ["Two-column layout", "Ignore headers/footers"]
            )
        
        client = OpenRouterClient()
        total_cost = 0.0
        output_dir = ""
        
        # 1. Check for cached pages
        results = [None] * len(pages)
        pending_pages = [] # (index_0, image)
        
        print("\n🔍 Checking cache...")
        for i in range(len(pages)):
            cached_text = self.cache.get(pdf_path, i+1)
            if cached_text:
                results[i] = {"text": cached_text, "cost": 0.0, "source": "cache"}
            else:
                pending_pages.append((i, pages[i]))
        
        print(f"✅ Found {len(pages) - len(pending_pages)} pages in cache.")
        if pending_pages:
            print(f"🚀 Processing {len(pending_pages)} pages with Vision OCR (Parallel)...")
            
        # 2. Process pending pages in parallel
        def process_page(idx, img):
            prompt = f"""Transcribe ALL content from this page exactly as it appears. Follow these rules:
1. Preserve natural reading order (top to bottom, left to right).
2. TABLES ARE CRITICAL: Convert every table — including answer-key grids, correction tables with X marks, and any grid with columns — into markdown table format using | pipe separators. Never skip a table.
3. For answer-key / correction tables (e.g., | Q | A | B | C | D | E | with X marks): reproduce each row exactly with its X marks preserved.
4. Do NOT summarise, skip, or paraphrase any content. Every line, every cell, every mark must appear in the output.
5. Do NOT add any commentary or explanation — output ONLY the page content.
{guidance}"""
            primary_model = os.getenv("STEP1_MODEL") or os.getenv("OCR_MODEL", "qwen/qwen3-vl-30b-a3b-instruct")
            fallback_model = os.getenv("STEP1_FALLBACK_MODEL", "qwen/qwen-2.5-vl-7b-instruct:free")
            max_tokens = int(os.getenv("STEP1_MAX_TOKENS", "15000"))

            try:
                try:
                    response = client.generate_completion(prompt, [img], model=primary_model, max_tokens=max_tokens)
                    used_model = primary_model
                except Exception as e:
                    print(f"  [WARN] Page {idx+1} primary OCR failed: {e}")
                    print(f"  [INFO] Retrying Page {idx+1} with fallback: {fallback_model}")
                    response = client.generate_completion(prompt, [img], model=fallback_model, max_tokens=max_tokens)
                    used_model = fallback_model

                content = response["content"]
                usage = response["usage"]
                cost = response.get('cost', 0.0) or client.estimate_cost(used_model, usage)
                
                # Save to cache immediately
                self.cache.save(pdf_path, idx + 1, content)
                
                return idx, content, cost, usage, used_model
            except Exception as e:
                print(f"❌ Error on page {idx+1}: {e}")
                return idx, f"ERROR: {str(e)}", 0.0, {}, "error"

        # Use max 5 threads to avoid overwhelming rate limits (Gemini is fine, others vary)
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_idx = {executor.submit(process_page, idx, img): idx for idx, img in pending_pages}
            
            for future in as_completed(future_to_idx):
                idx, content, cost, usage, used_model = future.result()
                results[idx] = {"text": content, "cost": cost, "source": "api"}
                total_cost += cost
                
                if usage and used_model != "error":
                    self.cost_tracker.log_api_call(
                        "step1", used_model,
                        {"prompt": usage.get("prompt_tokens", 0), "completion": usage.get("completion_tokens", 0)},
                        cost
                    )
                print(f"  Page {idx+1} completed ✓ (${cost:.4f})")

        # 3. Save all results
        for i, res in enumerate(results, 1):
            if not res: continue
            
            # Save using project context
            if self.context:
                save_path = self.context.get_path("step1_extraction", "accepted") / f"page_{i}.txt"
            else:
                save_path = Path("output/step1_extraction/accepted") / f"page_{i}.txt"
                save_path.parent.mkdir(parents=True, exist_ok=True)
                
            output_dir = str(save_path.parent)
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(res["text"])
                
        return {
            "output_dir": output_dir,
            "method": "vision_ocr",
            "cost": total_cost,
            "page_count": len(pages)
        }
