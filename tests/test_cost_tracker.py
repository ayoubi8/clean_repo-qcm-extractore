import sys
import os

# Adjust path to import from modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from modules.utils.cost_tracker import CostTracker

# Force UTF-8 execution for Windows
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

def test_cost_tracker():
    print("Testing CostTracker...")
    tracker = CostTracker()
    
    # Log sample calls
    tracker.log_api_call("step1", "vision_ocr", {"prompt": 100, "completion": 400}, 0.0005)
    tracker.log_api_call("step2", "deepseek_r1", {"prompt": 800, "completion": 700}, 0.0012)
    
    # Display summary
    tracker.display_summary()
    
    # Test saving
    test_json = "output/test_costs.json"
    tracker.save(test_json)
    
    if os.path.exists(test_json):
        print(f"\n✅ Cost data saved to {test_json}")
        # Clean up
        os.remove(test_json)
    else:
        print(f"\n❌ Failed to save cost data")

if __name__ == "__main__":
    test_cost_tracker()
