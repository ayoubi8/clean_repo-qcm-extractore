import os
import sys
from dotenv import load_dotenv

# Force UTF-8 execution for Windows
sys.stdout.reconfigure(encoding='utf-8')

# Adjust path to import from modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

from modules.llama_client import LlamaClient

def test_llama_categorization():
    print("Testing Llama categorization...")
    try:
        client = LlamaClient()
        
        qcm_text = "Une thrombopénie périphérique peut être secondaire à:"
        propositions = {
            "A": "Une splénomégalie",
            "B": "Une CIVD",
            "C": "Une aplasie médullaire",
            "D": "Un purpura thrombopénique immunologique",
            "E": "Toutes les réponses sont justes"
        }
        modules = ["Hemobiologie", "Cardiologie", "Infectiologie", "Biochimie"]
        
        print("\nCategorizing QCM...")
        result = client.categorize_qcm(qcm_text, propositions, modules)
        
        print("\nResult:")
        import json
        print(json.dumps(result, indent=2))
        
        if result["category"] != "Unknown":
            print("\n✅ Llama client working correctly!")
        else:
            print("\n⚠️ Llama returned Unknown, check response content.")
            
    except Exception as e:
        print(f"\n❌ Test failed: {e}")

if __name__ == "__main__":
    test_llama_categorization()
