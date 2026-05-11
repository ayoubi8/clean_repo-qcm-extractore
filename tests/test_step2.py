import os
import sys
from dotenv import load_dotenv
from unittest.mock import patch
import json

# Force UTF-8 execution for Windows
sys.stdout.reconfigure(encoding='utf-8')

# Adjust path to import from modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

from modules.step2_qcm_extract import Step2QCMExtract
from modules.utils.cost_tracker import CostTracker

def test_step2_extraction():
    print("Testing Step 2 Extraction...")
    tracker = CostTracker()
    step2 = Step2QCMExtract(tracker)
    
    input_dir = "output/step1_extraction/accepted"
    if not os.path.exists(input_dir) or not any(Path(input_dir).glob("*.txt")):
        print(f"❌ Input text files not found in: {input_dir}")
        return

    # Mocking input to simulate "Accept" for first page only to save costs
    print("\n--- Testing Page-by-Page Extraction ---")
    
    # We will only process the first file to verify logic
    first_file = sorted(list(os.listdir(input_dir)))[0]
    print(f"Testing with file: {first_file}")
    
    with patch('builtins.input', side_effect=["", "a"]):
        # The first "" is for global guidance
        # The "a" is for accepting the first page
        
        # We need to monkeypatch _process_page to stop after one file for the test
        original_run = step2.run
        def run_test(pdf_dir):
            txt_files = sorted(list(os.path.Path(pdf_dir).glob("*.txt")), key=lambda x: int(os.path.basename(x).stem.split('_')[1]))[:1]
            guidance = "" 
            results = step2._process_page(txt_files[0], guidance)
            return {"total_extracted": len(results)}
            
        # Instead of monkeypatching run, let's just call _process_page directly
        with PatchFileManager() as fm:
            step2.file_manager = fm
            result = step2._process_page(os.path.Path(input_dir) / first_file, "")
            
            if result and os.path.exists(f"output/step2_qcm/accepted/{os.path.Path(first_file).stem}.json"):
                print(f"✅ Extracted {len(result)} QCMs from first page.")
                tracker.display_summary()
            else:
                print("❌ Step 2 extraction test failed.")

class PatchFileManager:
    # Minimal file manager to track output for test
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def save_accepted(self, step, filename, data):
        path = os.path.join("output", step, "accepted")
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, filename), "w", encoding="utf-8") as f:
            json.dump(data, f)
    def save_rejected(self, *args): pass

if __name__ == "__main__":
    from pathlib import Path
    import pathlib
    os.path.Path = Path
    test_step2_extraction()
