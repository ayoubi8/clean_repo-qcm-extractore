import re
import time
import pypdfium2 as pdfium
from typing import Dict, Any, List, Optional
from PIL import Image

class TextExtractionManager:
    """
    Manages text extraction from documents using either:
    1. Direct PDF extraction (pypdfium2) - Fast/Free
    2. Vision AI OCR (OpenRouter) - Slower/Paid
    """
    
    def __init__(self, vision_client=None):
        """
        Args:
            vision_client: OpenRouterClient instance (required for OCR method)
        """
        self.vision_client = vision_client
        
    def choose_extraction_method(self, file_path: str) -> str:
        """
        Interactive prompt for user to choose method.
        Returns 'pdf' or 'ocr'.
        """
        print("\n" + "=" * 70)
        print("TEXT EXTRACTION METHOD")
        print("=" * 70)
        print("\nChoose how to extract text from the document:")
        print("\n  [1] PDF Text Extraction (pypdfium2)")
        print("      ✅ Fast and free")
        print("      ✅ Works for text-based PDFs")
        print("      ❌ Fails on scanned/image-based PDFs")
        
        print("\n  [2] OCR Vision AI (Qwen/Gemini)")
        print("      ✅ Works on any document (scanned or text)")
        print("      ✅ High accuracy")
        print("      ❌ Slower and costs money (~$0.50-1.00 per 100 pages)")
        
        # Try to detect if PDF has text
        try:
            has_text = self._detect_pdf_text(file_path)
            if has_text:
                print(f"\n💡 Recommendation: PDF appears to have extractable text → Use Option 1")
            else:
                print(f"\n💡 Recommendation: PDF appears to be scanned/images → Use Option 2")
        except:
             print("\n💡 Recommendation: Unknown format")
        
        choice = input("\nSelect method (1 or 2): ").strip()
        return 'pdf' if choice == '1' else 'ocr'
    
    def extract_all_pages(self, file_path: str, method: str, pages: List[Image.Image] = None) -> Dict[str, Any]:
        """
        Extract text from ALL pages using chosen method.
        
        Args:
            file_path: Path to document
            method: 'pdf' or 'ocr'
            pages: List of PIL Images (required specifically for method='ocr')
            
        Returns dict with:
            - 'method_used': str
            - 'total_pages': int
            - 'pages': {page_num: text}
            - 'combined_text': str
            - 'extraction_cost': float
        """
        if method == 'pdf':
            return self._extract_with_pypdfium(file_path)
        else:
            return self._extract_with_ocr(pages)
    
    def _detect_pdf_text(self, file_path: str) -> bool:
        """
        Quick check if PDF has extractable text.
        Tests first 3 pages.
        """
        try:
            pdf = pdfium.PdfDocument(file_path)
            total_chars = 0
            check_pages = min(3, len(pdf))
            
            for i in range(check_pages):
                textpage = pdf[i].get_textpage()
                text = textpage.get_text_range()
                total_chars += len(text.strip())
                
            pdf.close()
            # If we average > 50 chars per page, it's likely text-based
            return (total_chars / check_pages) > 50
        except Exception:
            return False
        
    def _extract_with_pypdfium(self, file_path: str) -> Dict[str, Any]:
        """
        Extract text using pypdfium2 from ALL pages.
        """
        pdf = pdfium.PdfDocument(file_path)
        pages_text = {}
        
        print(f"\n📄 Extracting text from {len(pdf)} pages (Option 1: PDF Layer)...")
        
        for page_num in range(len(pdf)):
            try:
                page = pdf[page_num]
                textpage = page.get_textpage()
                text = textpage.get_text_range()
                clean_text = self._clean_text(text)
                
                # If page is empty, mark it
                if not clean_text:
                    clean_text = "[EMPTY_PAGE]"
                    
                pages_text[page_num + 1] = clean_text
            except Exception as e:
                pages_text[page_num + 1] = f"[ERROR extracting page: {e}]"
            
            # Progress indicator (every 10 pages)
            if (page_num + 1) % 10 == 0:
                print(f"  Processed {page_num + 1}/{len(pdf)} pages...", end='\r')
        
        print(f"  Processed {len(pdf)}/{len(pdf)} pages - Done.")
        combined = "\n\n--- PAGE BREAK ---\n\n".join([pages_text[k] for k in sorted(pages_text.keys())])
        
        return {
            'method_used': 'pypdfium2',
            'total_pages': len(pdf),
            'pages': pages_text,
            'combined_text': combined,
            'extraction_cost': 0.0
        }
    
    def _extract_with_ocr(self, pages: List[Image.Image]) -> Dict[str, Any]:
        """
        Extract text using Vision AI OCR from ALL pages.
        """
        if not self.vision_client:
            raise ValueError("Vision client required for OCR method")
            
        if not pages:
             raise ValueError("No images provided for OCR extraction")
        
        pages_text = {}
        total_cost = 0.0
        
        print(f"\n🤖 Running OCR on {len(pages)} pages (Option 2: Vision AI)...")
        print("   This is slower but handles scanned documents perfectly.")
        
        # Simple OCR prompt
        ocr_prompt = """
        Extract ALL text from this image exactly as it appears.
        Preserve structure, question numbers, and headers.
        Return raw text only.
        """
        
        for idx, page_img in enumerate(pages):
            page_num = idx + 1
            
            try:
                # Use generate_completion from OpenRouterClient
                # We reuse the client assuming it handles images
                response = self.vision_client.generate_completion(ocr_prompt, [page_img])
                
                text = response.get('content', '')
                usage = response.get('usage', {})
                cost = response.get('cost', 0.0) or self.vision_client.estimate_cost(self.vision_client.model, usage)
                total_cost += cost
                
                pages_text[page_num] = text
                
                print(f"  Page {page_num}/{len(pages)}: {len(text)} chars extracted (${cost:.4f})")
                
            except Exception as e:
                print(f"  ❌ Error on page {page_num}: {e}")
                pages_text[page_num] = "[OCR_ERROR]"
        
        combined = "\n\n--- PAGE BREAK ---\n\n".join([pages_text[k] for k in sorted(pages_text.keys())])
        
        return {
            'method_used': 'vision_ocr',
            'total_pages': len(pages),
            'pages': pages_text,
            'combined_text': combined,
            'extraction_cost': total_cost
        }
    
    def _clean_text(self, text: str) -> str:
        """
        Clean extracted text to remove common garbage.
        """
        if not text:
            return ""
            
        # Remove null bytes
        text = text.replace('\x00', '')
        
        # Normalize whitespace (preserve newlines but collapse repeated spaces)
        # We don't want to kill newlines as they are important for layout detection
        lines = text.splitlines()
        clean_lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in lines]
        return '\n'.join(clean_lines).strip()
