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

load_dotenv()

from modules.step6_corrections import Step6Corrections
from modules.utils.cost_tracker import CostTracker

def test_step6_corrections():
    print("Testing Step 6 Corrections...")
    tracker = CostTracker()
    step6 = Step6Corrections(tracker)
    
    input_file = "output/step5_json/merged_qcms.json"
    if not Path(input_file).exists():
        os.makedirs("output/step5_json", exist_ok=True)
        with open(input_file, "w", encoding="utf-8") as f:
            json.dump([{"Num": 10, "Text": "Sample question", "propositions": {"A": "Yes", "B": "No"}}], f)

    # Choice 1: AI Knowledge
    print("\n--- Running AI Corrections ---")
    with patch('builtins.input', side_effect=["1"]):
        result = step6.run(input_file)
        
        if result and "file" in result:
            print(f"✅ Created corrected JSON: {result['file']}")
            with open(result["file"], 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data[0].get("Correct"):
                    print(f"✅ AI Correction applied: {data[0]['Correct']}")
        else:
            print("❌ Step 6 corrections test failed.")

if __name__ == "__main__":
    test_step6_corrections()
