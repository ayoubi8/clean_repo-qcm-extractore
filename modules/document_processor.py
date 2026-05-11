import pypdfium2 as pdfium
from PIL import Image
import io
from pathlib import Path
from typing import List, Union

class DocumentProcessor:
    def __init__(self, file_path: Union[str, Path]):
        """
        Initialize the DocumentProcessor with a file path.
        """
        self.file_path = Path(file_path)
        if not self.file_path.exists():
            raise FileNotFoundError(f"File not found: {self.file_path}")
        self.pages: List[Image.Image] = []

    def load_document(self) -> List[Image.Image]:
        """
        Converts the document (PDF or Image) to a list of PIL Images.
        Returns list of PIL Image objects.
        """
        self.pages = [] # Reset
        
        if self.file_path.suffix.lower() == '.pdf':
            try:
                # Use pypdfium2 which is detailed as more stable on this system
                pdf = pdfium.PdfDocument(str(self.file_path))
                n_pages = len(pdf)
                
                print(f"Converting {n_pages} PDF pages to images...")
                
                for i in range(n_pages):
                    page = pdf[i]
                    # Scale=2.0 roughly equals 144dpi, good for OCR
                    bitmap = page.render(scale=2.0) 
                    pil_image = bitmap.to_pil()
                    self.pages.append(pil_image.convert('RGB'))
                    
                pdf.close()
            except Exception as e:
                raise RuntimeError(f"Error processing PDF with pypdfium2: {str(e)}")
        
        elif self.file_path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.webp']:
            try:
                img = Image.open(self.file_path).convert('RGB')
                self.pages.append(img)
            except Exception as e:
                raise RuntimeError(f"Error processing image: {str(e)}")
        
        else:
            raise ValueError(f"Unsupported file format: {self.file_path.suffix}")
            
        print(f"Loaded {len(self.pages)} pages from {self.file_path.name}")
        return self.pages

    def get_sample_pages(self) -> List[Image.Image]:
        """
        Extracts first 2 and last 1 pages as samples.
        If document has <= 3 pages, returns all pages.
        """
        if not self.pages:
            self.load_document()
            
        if not self.pages:
            return []
            
        total_pages = len(self.pages)
        
        if total_pages <= 3:
            return self.pages[:] # Return copy
            
        # First 2 pages
        samples = self.pages[:2]
        # Last 1 page
        samples.append(self.pages[-1])
        
        return samples

    def get_correction_pages(self) -> List[Image.Image]:
        """
        Placeholder for fetching correction pages.
        Currently returns the last page as a potential correction page candidate.
        """
        if not self.pages:
            return []
        if len(self.pages) > 1:
            return [self.pages[-1]]
        return []
