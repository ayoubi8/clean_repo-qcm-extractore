import sys
import os
from unittest.mock import patch

# Adjust path to import from modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from modules.utils.prompt_helper import PromptHelper

# Force UTF-8 execution for Windows
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

def test_prompt_helper():
    print("Testing PromptHelper...")
    helper = PromptHelper()
    
    # Test guidance collection with mock input
    with patch('builtins.input', return_value="Extract columns"):
        guidance = helper.get_user_guidance(
            "Test Step",
            context="Testing the helper",
            examples=["Example 1", "Example 2"]
        )
        print(f"Received guidance: {guidance}")
        assert guidance == "Extract columns"
    
    # Test confirmation with mock input
    with patch('builtins.input', return_value="y"):
        confirmed = helper.confirm_action("Proceed?")
        print(f"Confirmed: {confirmed}")
        assert confirmed is True

    with patch('builtins.input', return_value="n"):
        confirmed = helper.confirm_action("Proceed?")
        print(f"Confirmed: {confirmed}")
        assert confirmed is False

    print("\n✅ PromptHelper tests passed!")

if __name__ == "__main__":
    test_prompt_helper()
