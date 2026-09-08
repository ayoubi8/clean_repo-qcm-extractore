import hashlib
import json
import os
from pathlib import Path
from typing import Optional

class OCRCache:
    """Cache OCR results to save time and cost."""
    
    def __init__(self, cache_dir: str = ".cache/ocr"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
    def get_pdf_hash(self, pdf_path: str) -> str:
        """Compute the PDF hash once and reuse it across all page lookups."""
        return hashlib.md5(open(pdf_path, 'rb').read()).hexdigest()

    def _get_cache_key(self, pdf_path: str, page_num: int, file_hash: str = None) -> str:
        """Generate a unique hash for a PDF file content + page number."""
        file_hash = file_hash or self.get_pdf_hash(pdf_path)
        return f"{file_hash}_p{page_num}"

    def get(self, pdf_path: str, page_num: int, file_hash: str = None) -> Optional[str]:
        """Retrieve cached text if it exists."""
        key = self._get_cache_key(pdf_path, page_num, file_hash)
        cache_file = self.cache_dir / f"{key}.json"
        
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("text")
            except:
                pass
        return None
        
    def save(self, pdf_path: str, page_num: int, text: str, file_hash: str = None):
        """Save OCR result to cache."""
        key = self._get_cache_key(pdf_path, page_num, file_hash)
        cache_file = self.cache_dir / f"{key}.json"
        
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump({"text": text, "pdf": pdf_path, "page": page_num}, f)

    def clear(self, pdf_path: str):
        """Remove all cached pages for a given PDF file."""
        try:
            file_hash = hashlib.md5(open(pdf_path, 'rb').read()).hexdigest()
        except Exception:
            return
        prefix = f"{file_hash}_p"
        removed = 0
        for cache_file in self.cache_dir.glob(f"{prefix}*.json"):
            try:
                cache_file.unlink()
                removed += 1
            except Exception:
                pass
        if removed:
            print(f"[OCR-CACHE] Cleared {removed} cached page(s) for {Path(pdf_path).name}")
