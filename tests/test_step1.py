import os
import sys
from dotenv import load_dotenv
from unittest.mock import patch

# Force UTF-8 execution for Windows
sys.stdout.reconfigure(encoding='utf-8')

# Adjust path to import from modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

from modules.step1_extraction import Step1Extraction
from modules.utils.cost_tracker import CostTracker

def test_step1_extraction():
    print("Testing Step 1 Extraction...")
    tracker = CostTracker()
    step1 = Step1Extraction(tracker)
    
    pdf_path = "ilovepdf_merged.pdf"
    if not os.path.exists(pdf_path):
        print(f"❌ PDF not found: {pdf_path}")
        return

    # Test pypdfium2 (Option 1)
    print("\n--- Testing pypdfium2 ---")
    with patch('builtins.input', side_effect=["1"]):
        result = step1.run(pdf_path)
        print(f"Result: {result}")
        if result and os.path.exists("output/step1_extraction/accepted/page_1.txt"):
            print("✅ pypdfium2 extraction worked!")
        else:
            print("❌ pypdfium2 extraction failed.")

    # We won't test Vision OCR here to save costs unless explicitly asked, 
    # but the logic is identical to previous working OCR code.

if __name__ == "__main__":
    test_step1_extraction()
