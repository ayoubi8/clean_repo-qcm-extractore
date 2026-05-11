import sys
import os
from pathlib import Path

# Adjust path to import from modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from modules.utils.file_manager import FileManager

# Force UTF-8 execution for Windows
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

def test_file_manager():
    print("Testing FileManager...")
    fm = FileManager()
    
    # Test saving accepted
    test_data = {"text": "Test content for accepted"}
    fm.save_accepted("step_test", "page_1.json", test_data)
    
    # Test saving rejected
    test_data_rejected = {"text": "Test content for rejected"}
    fm.save_rejected("step_test", "page_1_rejected.json", test_data_rejected)
    
    # Test loading
    output = fm.load_step_output("step_test")
    print(f"Loaded output: {output}")
    assert "page_1" in output
    assert output["page_1"] == test_data
    
    print("\n✅ FileManager tests passed!")
    
    # Cleanup test files
    import shutil
    shutil.rmtree(Path("output/step_test"), ignore_errors=True)
    print("Test files cleaned up.")

if __name__ == "__main__":
    test_file_manager()
