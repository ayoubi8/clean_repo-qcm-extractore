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

from modules.step5_builder import Step5Builder
from modules.utils.cost_tracker import CostTracker

def test_step5_builder():
    print("Testing Step 5 JSON Builder...")
    tracker = CostTracker()
    builder = Step5Builder(tracker)
    
    step3_dir = "output/step3_metadata/accepted"
    template_path = "output/step4_format/current_template.json"
    
    if not Path(template_path).exists():
         # Create a dummy template if Step 4 didn't run in this environment
         os.makedirs("output/step4_format", exist_ok=True)
         with open(template_path, "w", encoding="utf-8") as f:
             json.dump({"Num": 0, "Text": "", "A": "", "categoryName": ""}, f)
             
    print("\n--- Running Builder ---")
    result = builder.run(step3_dir, template_path)
    
    if result and "output_file" in result:
        print(f"✅ Created merged JSON with {result['total_qcms']} QCMs.")
        # Verify content
        with open(result["output_file"], 'r', encoding='utf-8') as f:
            data = json.load(f)
            if data and "Num" in data[0]:
                print(f"✅ Mapping verified for first item: Num={data[0]['Num']}")
    else:
        print("❌ Step 5 builder test failed.")

if __name__ == "__main__":
    test_step5_builder()
