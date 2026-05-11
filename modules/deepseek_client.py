import os
import json
import time
import httpx
from typing import Dict, Any, Optional

class DeepSeekClient:
    """
    Client for interacting with DeepSeek reasoning models via OpenRouter.
    Specialized for logic-based analysis (Metadata extraction, Classification).
    """
    
    # Approx pricing per 1M tokens (Input / Output)
    PRICING = {
        "deepseek/deepseek-r1-distill-llama-70b": {"prompt": 0.23, "completion": 0.69},
        "deepseek/deepseek-r1": {"prompt": 0.55, "completion": 2.19},  # Estimates
    }

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the DeepSeek client.
        Args:
            api_key: OpenRouter API key. If None, tries DEEPSEEK_API_KEY then OPENROUTER_API_KEY from env.
        """
        if api_key:
            self.api_key = api_key
        else:
            self.api_key = os.getenv("OPENROUTER_API_KEY")
            
        if not self.api_key:
            raise ValueError("API Key missing. Set OPENROUTER_API_KEY env or pass explicit key.")
            
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://qcm-extractor.local",
            "X-Title": "QCM Extractor Hybrid",
            "Content-Type": "application/json"
        }
        
        primary_model = os.getenv("STEP6_AI_MODEL", "deepseek/deepseek-r1-distill-llama-70b")
        fallback_model = os.getenv("STEP6_AI_FALLBACK_MODEL", "deepseek/deepseek-r1")
        self.MODELS = [primary_model, fallback_model]
        self.primary_model = primary_model

    def generate_completion(self, prompt: str, system_prompt: str = "") -> Dict[str, Any]:
        """
        Public method to get a completion with cost and usage information.
        """
        try:
            result = self._call_api(prompt, system_prompt)
            content = result['choices'][0]['message']['content']
            usage = result.get('usage', {})
            # Prefer real cost from API, fall back to local estimate
            api_cost = usage.get('cost', 0.0)
            cost = float(api_cost) if api_cost and float(api_cost) > 0 else self.estimate_cost(result)
            
            return {
                "content": content,
                "usage": usage,
                "cost": cost,  # Real cost from OpenRouter API
                "model": result.get('used_model')
            }
        except Exception as e:
            return {
                "content": str(e),
                "usage": {},
                "cost": 0.0,
                "model": None
            }

    def _call_api(self, prompt: str, system_prompt: str = "") -> Dict[str, Any]:
        """
        Internal method to call OpenRouter API with retry logic and fallback.
        Returns full response dict from API.
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        max_tokens = int(os.getenv("STEP6_AI_MAX_TOKENS", "4000"))
        full_payload = {
            "messages": messages,
            "temperature": 0.1,  # Low temp for reasoning
            "max_tokens": max_tokens
        }

        retries = 3
        
        # Try primary logic model first, then fallback
        for model in self.MODELS:
            payload = {**full_payload, "model": model}
            
            for attempt in range(retries):
                try:
                    with httpx.Client(timeout=45.0) as client:
                        response = client.post(
                            "https://openrouter.ai/api/v1/chat/completions",
                            headers=self.headers,
                            json=payload
                        )
                        
                        if response.status_code == 200:
                            data = response.json()
                            if 'error' in data:
                                raise ValueError(f"API Error: {data['error']}")
                            
                            # Attach used model to result for cost calc
                            data['used_model'] = model 
                            return data
                            
                        # If Rate Limit or Server Error, wait and retry
                        if response.status_code in [429, 500, 502, 503]:
                            time.sleep(2 * (attempt + 1))
                            continue
                            
                        response.raise_for_status()
                        
                except Exception as e:
                    print(f"⚠️  Attempt {attempt+1} failed with {model}: {e}")
                    if attempt < retries - 1:
                        time.sleep(2)
            
            # If we're here, all retries for this model failed. Try next model if available.
            print(f"⚠️  Model {model} failed. Switching to fallback if available...")
            
        raise RuntimeError("All DeepSeek models failed.")

    def estimate_cost(self, response_data: Dict[str, Any]) -> float:
        """
        Calculate estimated cost for a request.
        FALLBACK: Prefer the 'cost' field from the API usage object.
        """
        usage = response_data.get('usage', {})
        
        # Try real cost from API first
        api_cost = usage.get('cost', 0.0)
        if api_cost and float(api_cost) > 0:
            return float(api_cost)
        
        # Fallback to local estimate
        model = response_data.get('used_model', self.primary_model)
        
        rates = self.PRICING.get(model, {"prompt": 0.5, "completion": 1.5})
        
        p_tokens = usage.get('prompt_tokens', 0)
        c_tokens = usage.get('completion_tokens', 0)
        
        return (p_tokens / 1_000_000 * rates['prompt']) + (c_tokens / 1_000_000 * rates['completion'])

    def analyze_metadata(self, text: str) -> Dict[str, Any]:
        """
        Analyze exam text to extract Source, Year, Module, and Domain Tag.
        """
        system_prompt = (
            "You are a medical exam classifier. Analyze the text provided. "
            "Return STRICT JSON format."
        )
        
        user_prompt = f"""
        Analyze the following text extracted from a medical QCM exam page.
        Identify:
        1. "source": The University, Faculty, or Exam name (e.g., "Residanat 2016", "Constantine").
        2. "year": The year of the exam (integer).
        3. "module": The specific medical module (e.g., "Cardiologie", "Traumatologie").
        4. "domain_tag": The broad category (MUST be one of: "Medecine", "Chirurgie", "Biologie").

        Text Content:
        \"\"\"{text[:4000]}\"\"\" (truncated if too long)
        
        Return ONLY valid JSON:
        {{
            "source": "...",
            "year": 2024,
            "module": "...",
            "domain_tag": "..."
        }}
        """
        
        try:
            result = self._call_api(user_prompt, system_prompt)
            content = result['choices'][0]['message']['content']
            
            # Basic JSON extraction
            import re
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                json_str = match.group(0)
                data = json.loads(json_str)
                
                # Add usage/cost metadata to the return dict for main.py to track
                data['_cost'] = self.estimate_cost(result)
                return data
            else:
                raise ValueError("No JSON found in response")
                
        except Exception as e:
            print(f"❌ Metadata Analysis Failed: {e}")
            return {
                "source": "Unknown",
                "year": None,
                "module": "Unknown",
                "domain_tag": "Unknown",
                "_cost": 0.0
            }

    def classify_domain(self, module_name: str) -> Dict[str, Any]:
        """
        Classify a single module name into Bio/Chir/Med.
        Useful if manual input needs validation.
        """
        prompt = f"""
        Classify the medical module "{module_name}" into one of three domains:
        1. Medecine
        2. Chirurgie
        3. Biologie
        
        Return ONLY JSON: {{"domain": "..."}}
        """
        
        try:
            result = self._call_api(prompt)
            content = result['choices'][0]['message']['content']
            if "{" in content:
                # simple parse
                import re
                json_str = re.search(r'\{.*\}', content, re.DOTALL).group(0)
                return json.loads(json_str)
            return {"domain": "Unknown"}
        except:
            return {"domain": "Unknown"}
