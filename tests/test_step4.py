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

from modules.step4_format import Step4Format
from modules.utils.cost_tracker import CostTracker

def test_step4_format():
    print("Testing Step 4 Format Template...")
    tracker = CostTracker()
    step4 = Step4Format(tracker)
    
    # Ensure a template exists
    os.makedirs("output/step4_format/templates", exist_ok=True)
    with open("output/step4_format/templates/Test-Template.json", "w", encoding="utf-8") as f:
        json.dump({"key": "value"}, f)

    # Choice 1 for Template list, Choice a for potential confirmation
    # We provide extra inputs just in case it goes to new template creation
    mock_inputs = ["1", "a", "NewTemplate", "guidance", "y"]
    
    print("\n--- Testing Template Selection ---")
    with patch('builtins.input', side_effect=mock_inputs):
        result = step4.run("output/step3_metadata/accepted")
        print(f"Result Status: {result.get('status')}")
        
        # Verify current_template.json was created
        active_template = Path("output/step4_format/current_template.json")
        if active_template.exists():
            print("✅ current_template.json created.")
        else:
            print("❌ Step 4 active template creation failed.")

if __name__ == "__main__":
    test_step4_format()
