import os
import sys
from dotenv import load_dotenv
import json
from pathlib import Path

# Force UTF-8 execution for Windows
sys.stdout.reconfigure(encoding='utf-8')

# Adjust path to import from modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

from modules.step7_categorization import Step7Categorization
from modules.utils.cost_tracker import CostTracker

def test_step7_categorization():
    print("Testing Step 7 Categorization...")
    tracker = CostTracker()
    step7 = Step7Categorization(tracker)
    
    input_file = "output/step6_corrections/corrected_qcms.json"
    if not Path(input_file).exists():
        os.makedirs("output/step6_corrections", exist_ok=True)
        with open(input_file, "w", encoding="utf-8") as f:
            json.dump([{"Num": 10, "Text": "Une thrombopénie périphérique...", "domain": "Biologie", "A": "..."}], f)

    print("\n--- Running Categorization ---")
    result = step7.run(input_file)
    
    if result and "file" in result:
        print(f"✅ Created final JSON: {result['file']}")
        with open(result["file"], 'r', encoding='utf-8') as f:
            data = json.load(f)
            if data[0].get("categoryName"):
                print(f"✅ Category assigned: {data[0]['categoryName']}")
    else:
        print("❌ Step 7 categorization test failed.")

if __name__ == "__main__":
    test_step7_categorization()
