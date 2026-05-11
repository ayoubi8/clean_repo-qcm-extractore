import sys
import os
import shutil
from pathlib import Path

# Adjust path to import from modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from modules.utils.template_library import TemplateLibrary

# Force UTF-8 execution for Windows
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

def test_template_library():
    print("Testing TemplateLibrary...")
    test_dir = "output/test_templates"
    lib = TemplateLibrary(test_dir)
    
    template = {
        "year": None,
        "categoryName": None,
        "question": "",
        "propositions": [],
        "correction": None
    }
    
    # Test saving
    lib.save_template("Test Template", template)
    
    # Test listing
    templates = lib.list_templates()
    print(f"Templates: {templates}")
    assert "Test Template" in templates
    
    # Test loading
    loaded = lib.load_template("Test Template")
    assert loaded == template
    print("✅ Template load matches save")
    
    print("\n✅ TemplateLibrary tests passed!")
    
    # Cleanup
    shutil.rmtree(test_dir, ignore_errors=True)
    print("Test files cleaned up.")

if __name__ == "__main__":
    test_template_library()
