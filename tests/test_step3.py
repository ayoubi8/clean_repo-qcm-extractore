import os
import sys
from dotenv import load_dotenv
from unittest.mock import patch
import json
from pathlib import Path

# Force UTF-8 execution for Windows
sys.stdout.reconfigure(encoding='utf-8')

# Adjust path to import from modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from modules.step3_metadata import Step3Metadata
from modules.utils.cost_tracker import CostTracker

def test_step3_metadata():
    print("Testing Step 3 Metadata Detection...")
    tracker = CostTracker()
    step3 = Step3Metadata(tracker)
    
    step2_dir = "output/step2_qcm/accepted"
    step1_dir = "output/step1_extraction/accepted"
    
    # Mocking input for Global mode (Choice 1) and Accept (Choice a)
    print("\n--- Testing Global Metadata Mode ---")
    with patch('builtins.input', side_effect=["1", "a"]):
        result = step3.run(step2_dir, step1_dir)
        print(f"Result: {result}")
        
        # Verify output
        output_files = list(Path("output/step3_metadata/accepted").glob("*.json"))
        if output_files:
            print(f"✅ Created {len(output_files)} metadata-enriched files.")
            # Inspect one
            with open(output_files[0], 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "source" in data[0]:
                    print(f"✅ Metadata injected correctly: Source={data[0]['source']}")
        else:
            print("❌ Step 3 metadata test failed.")

if __name__ == "__main__":
    test_step3_metadata()
