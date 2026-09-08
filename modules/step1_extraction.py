import os
import json
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
from modules.model_policy import get_model_pair

class Step1Extraction:
    """Text extraction with dual mode: pypdfium2 or Vision OCR"""
    
    def __init__(self, cost_tracker: CostTracker, project_context=None):
        self.cost_tracker = cost_tracker
        self.file_manager = FileManager()
        self.prompt_helper = PromptHelper()
        self.context = project_context
        self.cache = OCRCache()
    
    def run(self, pdf_path: str, auto_ocr: bool = False, ocr_guidance: str = "", force_overwrite: bool = False, cancel_check=None) -> Dict:
        """
        Main execution
        Returns: {"output_dir": "output/project/step1_extraction", "method": "vision_ocr", "cost": 0.0073}
        """
        print("\n" + "="*60)
        print("STEP 1: TEXT EXTRACTION")
        print("="*60)
        
        # Clear OCR cache when the user confirmed overwrite — otherwise the
        # cache returns stale (possibly bad) OCR results for the same PDF.
        if force_overwrite:
            print("[OVERWRITE] Clearing OCR cache for this PDF...")
            self.cache.clear(pdf_path)
        
        # Load document
        doc_processor = DocumentProcessor(pdf_path)
        pages = doc_processor.load_document()
        
        if not pages:
            print("❌ No pages loaded from PDF.")
            return {}
            
        # Choose method
        if auto_ocr:
            print(f"\n[AUTO] Using Vision OCR (as configured)")
            return self._extract_with_vision(pdf_path, pages, ocr_guidance, cancel_check)
        
        print("\nSelect extraction method:")
        print("  1. pypdfium2 (Fast, free, text-based PDFs)")
        print("  2. Vision OCR (Scanned PDFs, costs ~$0.0005/page)")
        choice = input("Choice [1-2]: ").strip()
        
        if choice == "1":
            return self._extract_with_pypdfium2(pdf_path, len(pages))
        else:
            return self._extract_with_vision(pdf_path, pages, cancel_check=cancel_check)
    
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
    
    def _extract_with_vision(self, pdf_path: str, pages: List[Image.Image], guidance: str = "", cancel_check=None) -> Dict:
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
        pdf_hash = self.cache.get_pdf_hash(pdf_path)
        expected_pages = len(pages)
        
        # 1. Check for cached pages
        results = [None] * len(pages)
        pending_pages = [] # (index_0, image)
        
        print("\n🔍 Checking cache...")
        for i in range(len(pages)):
            if cancel_check and cancel_check():
                break
            cached_text = self.cache.get(pdf_path, i+1, pdf_hash)
            if cached_text:
                results[i] = {"text": cached_text, "cost": 0.0, "source": "cache"}
            else:
                pending_pages.append((i, pages[i]))
        
        print(f"✅ Found {len(pages) - len(pending_pages)} pages in cache.")
        if pending_pages:
            print(f"🚀 Processing {len(pending_pages)} pages with Vision OCR (Parallel)...")
            
        # 2. Process pending pages in parallel
        def process_page(idx, img):
            if cancel_check and cancel_check():
                return idx, None, 0.0, {}, "stopped"
            prompt = self._build_vision_prompt(guidance)
            primary_model, fallback_model = get_model_pair("step1_ocr")
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
                self.cache.save(pdf_path, idx + 1, content, pdf_hash)
                
                return idx, content, cost, usage, used_model
            except Exception as e:
                print(f"❌ Error on page {idx+1}: {e}")
                return idx, None, 0.0, {}, "error"

        # Use max 5 threads to avoid overwhelming rate limits (Gemini is fine, others vary)
        max_workers = max(1, int(os.getenv("STEP1_MAX_WORKERS", "5")))
        print(f"[STEP1] Processing {len(pending_pages)} uncached page(s) with {max_workers} concurrent request(s).")
        executor = ThreadPoolExecutor(max_workers=max_workers)
        future_to_idx = {executor.submit(process_page, idx, img): idx for idx, img in pending_pages}
        failed_indices = []
        try:
            for future in as_completed(future_to_idx):
                idx, content, cost, usage, used_model = future.result()
                if content is not None:
                    results[idx] = {"text": content, "cost": cost, "source": "api"}
                    total_cost += cost
                elif used_model == "error":
                    failed_indices.append(idx)
                if usage and used_model not in ("error", "stopped"):
                    self.cost_tracker.log_api_call(
                        "step1", used_model,
                        {"prompt": usage.get("prompt_tokens", 0), "completion": usage.get("completion_tokens", 0)},
                        cost
                    )
                if content is not None:
                    print(f"  Page {idx+1} completed ✓ (${cost:.4f})")
                if cancel_check and cancel_check():
                    for pending in future_to_idx:
                        pending.cancel()
                    break
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        # A failed page gets one bounded second pass. This catches transient
        # provider/rate-limit failures without multiplying every page's cost.
        retry_limit = max(0, int(os.getenv("STEP1_FAILED_PAGE_RETRIES", "1")))
        for retry_number in range(retry_limit):
            if not failed_indices or (cancel_check and cancel_check()):
                break
            retrying = failed_indices
            failed_indices = []
            print(f"[STEP1] Retrying {len(retrying)} failed page(s), pass {retry_number + 1}/{retry_limit}.")
            for idx in retrying:
                if cancel_check and cancel_check():
                    break
                idx, content, cost, usage, used_model = process_page(idx, pages[idx])
                if content is not None:
                    results[idx] = {"text": content, "cost": cost, "source": "retry"}
                    total_cost += cost
                    if usage:
                        self.cost_tracker.log_api_call(
                            "step1", used_model,
                            {"prompt": usage.get("prompt_tokens", 0), "completion": usage.get("completion_tokens", 0)},
                            cost,
                        )
                else:
                    failed_indices.append(idx)

        # 3. Save all results
        for i, res in enumerate(results, 1):
            if not res:
                continue
            
            # Save using project context
            if self.context:
                save_path = self.context.get_path("step1_extraction", "accepted") / f"page_{i}.txt"
            else:
                save_path = Path("output/step1_extraction/accepted") / f"page_{i}.txt"
                save_path.parent.mkdir(parents=True, exist_ok=True)
                
            output_dir = str(save_path.parent)
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(res["text"])

        missing_pages = [i for i, res in enumerate(results, 1) if not res]
        if missing_pages:
            error_dir = (self.context.get_path("step1_extraction", "errors")
                         if self.context else Path("output/step1_extraction/errors"))
            error_dir.mkdir(parents=True, exist_ok=True)
            for page_num in missing_pages:
                (error_dir / f"page_{page_num}.txt").write_text(
                    "OCR_FAILED: page was not completed after the configured retries.\n",
                    encoding="utf-8",
                )

        if self.context:
            manifest_path = self.context.get_path("step1_extraction") / "_page_manifest.json"
        else:
            manifest_path = Path("output/step1_extraction/_page_manifest.json")
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({
            "expected_pages": expected_pages,
            "completed_pages": expected_pages - len(missing_pages),
            "missing_pages": missing_pages,
        }, indent=2), encoding="utf-8")
                
        return {
            "output_dir": output_dir,
            "method": "vision_ocr",
            "cost": total_cost,
            "page_count": expected_pages,
            "completed_pages": expected_pages - len(missing_pages),
            "missing_pages": missing_pages,
        }

    @staticmethod
    def _build_vision_prompt(guidance: str = "") -> str:
        """Build the OCR prompt while preserving correction-page layout."""
        return f"""Transcribe ALL content from this page exactly as it appears. Follow these rules:
1. Preserve natural reading order (top to bottom, left to right).
2. TABLES ARE CRITICAL: Convert ordinary tables and conventional answer-key tables into markdown table format. Preserve every row, cell, and mark.
3. A correction page may contain multiple independent QCM blocks (correction blocks) on one physical horizontal line. One OCR line does NOT equal one question.
4. For every correction block, keep the question number associated with its A-E marks, R:, T:, and SCORE fields. A new question number starts a new block.
5. Preserve R: and T: literally and separately. T: is page content and must never be dropped. Preserve scores as page content.
6. Do not flatten side-by-side correction blocks into one logical table when that would destroy their associations. A structure such as QCM number, A-E marks, R:, T:, SCORE: is preferred.
7. On normal QCM pages, preserve the existing reading order and table behavior.
8. Do NOT solve or interpret corrections. Transcribe the page only; do not decide the final answer letters.
9. Do NOT summarise, skip, or paraphrase any content. Do NOT add commentary — output ONLY the page content.
{guidance}"""
