"""
Quick script to verify available Gemma models on OpenRouter
"""
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")

if not api_key:
    print("ERROR: OPENROUTER_API_KEY not found in .env")
    exit(1)

print("Querying OpenRouter for available models...\n")

try:
    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"}
        )
        
        if response.status_code != 200:
            print(f"ERROR: HTTP {response.status_code}")
            print(response.text)
            exit(1)
        
        models = response.json()
        
        # Search for Gemma models
        gemma_models = [m for m in models.get('data', []) if 'gemma' in m['id'].lower()]
        
        print(f"Found {len(gemma_models)} Gemma models:\n")
        
        for model in gemma_models:
            model_id = model['id']
            pricing = model.get('pricing', {})
            prompt_price = pricing.get('prompt', 'N/A')
            completion_price = pricing.get('completion', 'N/A')
            
            is_free = prompt_price == '0' or prompt_price == 0
            
            print(f"  {'[FREE]' if is_free else '[PAID]'} {model_id}")
            print(f"     Prompt: ${prompt_price}/1M tokens")
            print(f"     Completion: ${completion_price}/1M tokens")
            print()
        
        # Check for specific models
        print("\nChecking specific models:")
        
        targets = [
            "google/gemma-3-27b-it:free",
            "google/gemma-2-27b-it:free",
            "google/gemma-27b-it:free",
            "google/gemma-2-9b-it:free",
            "nvidia/nemotron-3-nano-30b-a3b:free"
        ]
        
        all_model_ids = [m['id'] for m in models.get('data', [])]
        
        for target in targets:
            if target in all_model_ids:
                print(f"  [OK] {target} - AVAILABLE")
            else:
                print(f"  [X] {target} - NOT FOUND")
        
        print("\n\nTesting a simple API call with google/gemma-2-9b-it:free...")
        
        # Test API call
        test_response = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "google/gemma-2-9b-it:free",
                "messages": [
                    {"role": "user", "content": "Say 'Hello' in one word."}
                ],
                "max_tokens": 10
            }
        )
        
        if test_response.status_code == 200:
            result = test_response.json()
            content = result['choices'][0]['message']['content']
            print(f"  [OK] Test successful! Response: {content}")
        else:
            print(f"  [X] Test failed: HTTP {test_response.status_code}")
            print(f"     {test_response.text}")

except Exception as e:
    print(f"ERROR: {e}")
