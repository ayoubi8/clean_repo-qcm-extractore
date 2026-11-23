import os
from modules.utils import run_env  # per-run config overlay (see run_env.py)
from modules.openrouter_client import OpenRouterFatalError
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
from modules.utils.page_text import (
    BLANK_INK_RATIO, BLANK_PAGE_MARKER, LIKELY_BLANK_INK_RATIO, has_text, page_ink_ratio,
)


class EmptyOCRReply(RuntimeError):
    """The model answered, but with no page text."""


class Step1Extraction:
    """Text extraction with dual mode: pypdfium2 or Vision OCR"""
    
    def __init__(self, cost_tracker: CostTracker, project_context=None):
        self.cost_tracker = cost_tracker
        self.file_manager = FileManager()
        self.prompt_helper = PromptHelper()
        self.context = project_context
        self.cache = OCRCache()
    
    def run(self, pdf_path: str, auto_ocr: bool = False, ocr_guidance: str = "", force_overwrite: bool = False, cancel_check=None,
            repair_missing: bool = False) -> Dict:
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
            return self._extract_with_vision(pdf_path, pages, ocr_guidance, cancel_check, repair_missing)
        
        print("\nSelect extraction method:")
        print("  1. pypdfium2 (Fast, free, text-based PDFs)")
        print("  2. Vision OCR (Scanned PDFs, costs ~$0.0005/page)")
        choice = input("Choice [1-2]: ").strip()
        
        if choice == "1":
            return self._extract_with_pypdfium2(pdf_path, pages, repair_missing)
        else:
            return self._extract_with_vision(pdf_path, pages, cancel_check=cancel_check,
                                             repair_missing=repair_missing)
    
    def _page_path(self, page_num: int) -> Path:
        if self.context:
            return self.context.get_path("step1_extraction", "accepted") / f"page_{page_num}.txt"
        path = Path("output/step1_extraction/accepted") / f"page_{page_num}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _existing_page_text(self, page_num: int) -> str:
        path = self._page_path(page_num)
        try:
            text = path.read_text(encoding="utf-8") if path.exists() else ""
        except (OSError, UnicodeDecodeError):
            return ""
        return text if has_text(text) else ""

    def _write_page_manifest(self, expected: int, missing: List[int], blank: List[int],
                             recovered: List[int], repair: bool) -> None:
        """Page outcome of this run. `repair` + `recovered_pages` tell the next
        steps which pages are new, so good pages are not paid for twice."""
        if self.context:
            path = self.context.get_path("step1_extraction") / "_page_manifest.json"
        else:
            path = Path("output/step1_extraction/_page_manifest.json")
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "expected_pages": expected,
            "completed_pages": expected - len(missing),
            "missing_pages": missing,
            "blank_pages": blank,
            "recovered_pages": recovered,
            "repair": repair,
        }, indent=2), encoding="utf-8")

    def _record_page_errors(self, expected: int, missing: List[int], reason: str) -> None:
        """Failed pages get an error note and never stay as a 0 KB page."""
        error_dir = (self.context.get_path("step1_extraction", "errors")
                     if self.context else Path("output/step1_extraction/errors"))
        error_dir.mkdir(parents=True, exist_ok=True)
        for page_num in range(1, expected + 1):
            note = error_dir / f"page_{page_num}.txt"
            if page_num in missing:
                note.write_text(f"{reason}\n", encoding="utf-8")
                page = self._page_path(page_num)
                if page.exists() and not self._existing_page_text(page_num):
                    page.unlink()
            elif note.exists():
                note.unlink()

    def _extract_with_pypdfium2(self, pdf_path: str, pages: List[Image.Image],
                                repair_missing: bool = False) -> Dict:
        """Free extraction using pypdfium2"""
        page_count = len(pages)
        print(f"\nExtracting {page_count} pages with pypdfium2...")

        pdf = pdfium.PdfDocument(pdf_path)
        missing, blank, recovered = [], [], []

        for i, page in enumerate(pdf, 1):
            if repair_missing and self._existing_page_text(i):
                continue
            textpage = page.get_textpage()
            text = textpage.get_text_range()
            if has_text(text):
                recovered.append(i)
            elif page_ink_ratio(pages[i - 1]) < LIKELY_BLANK_INK_RATIO:
                text = BLANK_PAGE_MARKER
                blank.append(i)
            else:
                missing.append(i)      # an image page: it has no text layer
                print(f"Page {i}/{page_count}... no text layer")
                continue

            with open(self._page_path(i), "w", encoding="utf-8") as f:
                f.write(text)

            print(f"Page {i}/{page_count}... ✓ (Free)")

        self._record_page_errors(page_count, missing, "NO_TEXT_LAYER: this page is an image.")
        self._write_page_manifest(page_count, missing, blank, recovered, repair_missing)
        if missing:
            raise RuntimeError(
                f"{len(missing)} of {page_count} page(s) have no text layer: "
                f"{self._page_list(missing)}. Use Vision OCR for this PDF.")

        return {
            "output_dir": str(self._page_path(1).parent),
            "method": "pypdfium2",
            "cost": 0.0,
            "page_count": page_count,
            "blank_pages": blank,
        }

    @staticmethod
    def _page_list(pages: List[int], limit: int = 12) -> str:
        shown = ", ".join(str(p) for p in pages[:limit])
        return f"{shown} and {len(pages) - limit} more" if len(pages) > limit else shown

    def _extract_with_vision(self, pdf_path: str, pages: List[Image.Image], guidance: str = "", cancel_check=None,
                             repair_missing: bool = False) -> Dict:
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
            # Repair run: a page that already has text is kept as it is.
            existing = self._existing_page_text(i + 1) if repair_missing else ""
            if existing:
                results[i] = {"text": existing, "cost": 0.0, "source": "existing"}
                continue
            cached_text = self.cache.get(pdf_path, i+1, pdf_hash)
            if has_text(cached_text):
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
            ink = page_ink_ratio(img)
            if ink < BLANK_INK_RATIO:
                print(f"  Page {idx+1} is blank: no OCR call needed.")
                return idx, BLANK_PAGE_MARKER, 0.0, {}, "blank"
            prompt = self._build_vision_prompt(guidance)
            primary_model, fallback_model = get_model_pair("step1_ocr")
            max_tokens = int(run_env.getenv("STEP1_MAX_TOKENS", "15000"))

            def ocr_call(model):
                response = client.generate_completion(prompt, [img], model=model, max_tokens=max_tokens)
                if has_text(response.get("content")):
                    return response
                # An empty reply is still billed: keep it in the project cost.
                empty_usage = response.get("usage") or {}
                if empty_usage:
                    self.cost_tracker.log_api_call(
                        "step1", model,
                        {"prompt": empty_usage.get("prompt_tokens", 0),
                         "completion": empty_usage.get("completion_tokens", 0)},
                        response.get("cost", 0.0) or client.estimate_cost(model, empty_usage),
                    )
                raise EmptyOCRReply(f"{model} returned no text (finish_reason={response.get('finish_reason')})")

            try:
                try:
                    response = ocr_call(primary_model)
                    used_model = primary_model
                except OpenRouterFatalError:
                    raise
                except Exception as e:
                    print(f"  [WARN] Page {idx+1} primary OCR failed: {e}")
                    print(f"  [INFO] Retrying Page {idx+1} with fallback: {fallback_model}")
                    response = ocr_call(fallback_model)
                    used_model = fallback_model

                content = response["content"]
                usage = response["usage"]
                cost = response.get('cost', 0.0) or client.estimate_cost(used_model, usage)
                
                # Save to cache immediately
                self.cache.save(pdf_path, idx + 1, content, pdf_hash)
                
                return idx, content, cost, usage, used_model
            except OpenRouterFatalError:
                raise   # bad key / no credits → abort Step 1 with a clear error
            except EmptyOCRReply as e:
                if ink < LIKELY_BLANK_INK_RATIO:
                    print(f"  Page {idx+1} treated as blank: almost no ink and no OCR text.")
                    return idx, BLANK_PAGE_MARKER, 0.0, {}, "blank"
                print(f"❌ Empty OCR on page {idx+1}: {e}")
                return idx, None, 0.0, {}, "error"
            except Exception as e:
                print(f"❌ Error on page {idx+1}: {e}")
                return idx, None, 0.0, {}, "error"

        # Use max 5 threads to avoid overwhelming rate limits (Gemini is fine, others vary)
        max_workers = max(1, int(run_env.getenv("STEP1_MAX_WORKERS", "5")))
        print(f"[STEP1] Processing {len(pending_pages)} uncached page(s) with {max_workers} concurrent request(s).")
        executor = ThreadPoolExecutor(max_workers=max_workers)
        future_to_idx = {executor.submit(run_env.bind(process_page), idx, img): idx for idx, img in pending_pages}
        failed_indices = []
        try:
            for future in as_completed(future_to_idx):
                idx, content, cost, usage, used_model = future.result()
                if content is not None:
                    results[idx] = {"text": content, "cost": cost,
                                    "source": "blank" if used_model == "blank" else "api"}
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
        retry_limit = max(0, int(run_env.getenv("STEP1_FAILED_PAGE_RETRIES", "1")))
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
                    results[idx] = {"text": content, "cost": cost,
                                    "source": "blank" if used_model == "blank" else "retry"}
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
            save_path = self._page_path(i)
            output_dir = str(save_path.parent)
            if res["source"] == "existing":
                continue
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(res["text"])

        missing_pages = [i for i, res in enumerate(results, 1) if not res]
        blank_pages = [i for i, res in enumerate(results, 1) if res and res["source"] == "blank"]
        recovered_pages = [i for i, res in enumerate(results, 1)
                           if res and res["source"] not in ("blank", "existing")]
        self._record_page_errors(expected_pages, missing_pages,
                                 "OCR_FAILED: page was not completed after the configured retries.")
        self._write_page_manifest(expected_pages, missing_pages, blank_pages,
                                  recovered_pages, repair_missing)

        # Hold the PDF here: Step 2 must not be paid for on incomplete text.
        if missing_pages and not (cancel_check and cancel_check()):
            raise RuntimeError(
                f"{len(missing_pages)} of {expected_pages} page(s) failed OCR: "
                f"{self._page_list(missing_pages)}. Retry failed redoes only these pages.")

        return {
            "output_dir": output_dir,
            "method": "vision_ocr",
            "cost": total_cost,
            "page_count": expected_pages,
            "completed_pages": expected_pages - len(missing_pages),
            "missing_pages": missing_pages,
            "blank_pages": blank_pages,
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
10. Exam origin lines such as "• Question N° 32, Sec 01 de l'année 2021-2022" or "Question N° 07, Partie pratique, Rattrapage de l'année 2020-2021" are page content: transcribe each one verbatim on its OWN line, BEFORE the question it introduces. Keep question numbering prefixes ("29-", "30-") and section or chapter titles ("Partie pratique", "Rattrapage") exactly as printed.
{guidance}"""
