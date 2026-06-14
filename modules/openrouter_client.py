import os
import base64
import io
import time
import json
from typing import List, Dict, Any, Union
import httpx
from PIL import Image
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class OpenRouterClient:
    def __init__(self, cache_enabled: bool = False):
        """
        Initialize the OpenRouter client.
        Args:
            cache_enabled (bool): Whether to enable caching (placeholder for now).
        """
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            # Try to load from default location if not set
            try:
                load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))
                self.api_key = os.getenv("OPENROUTER_API_KEY")
            except:
                pass
                
        self.model = os.getenv("STEP1_MODEL") or os.getenv("OCR_MODEL", "qwen/qwen3-vl-30b-a3b-instruct")
        self.fallback_model = os.getenv("STEP1_FALLBACK_MODEL", "qwen/qwen-2.5-vl-7b-instruct:free") 
        self.site_url = os.getenv("SITE_URL", "https://local.dev")
        self.site_name = os.getenv("SITE_NAME", "QCM Extractor")
        
        # Masked key log for debugging
        masked_key = "None"
        if self.api_key:
            if len(self.api_key) <= 8:
                masked_key = "****"
            else:
                masked_key = self.api_key[:8] + "****" + self.api_key[-4:]
        print(f"[OpenRouterClient] Loaded API Key: {masked_key}")

        # Headers required by OpenRouter
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": self.site_url,
            "X-Title": self.site_name,
            "Content-Type": "application/json"
        }

        
    def _encode_image(self, image: Image.Image, format: str = "JPEG") -> str:
        """
        Encodes a PIL Image to a base64 string.
        Resizes image if too large (max 1024px) to optimize token usage.
        Compresses with quality=65 to reduce payload size while maintaining readability.
        """
        # Create copy to avoid modifying original
        img_copy = image.copy()
        
        # Add resizing logic
        max_size = 1024
        if max(img_copy.size) > max_size:
            img_copy.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            
        buffered = io.BytesIO()
        # Convert to RGB if necessary (e.g. for PNGs with transparency)
        if img_copy.mode in ('RGBA', 'LA'):
            background = Image.new(img_copy.mode[:-1], img_copy.size, (255, 255, 255))
            background.paste(img_copy, img_copy.split()[-1])
            img_copy = background
            
        # Optimize=True and lower quality for better compression (Cost Opt #1)
        img_copy.convert('RGB').save(buffered, format=format, quality=65, optimize=True)
        return base64.b64encode(buffered.getvalue()).decode('utf-8')

    def generate_completion(self, prompt: str, images: List[Image.Image] = None, max_tokens: int = 4000, model: str = None) -> Dict[str, Any]:
        """
        Calls the OpenRouter API with the Vision model.
        Returns the full response object to allow access to usage stats.
        """
        target_model = model if model else self.model
        
        if not self.api_key:
             raise ValueError("OPENROUTER_API_KEY is not set. Please check your .env file.")

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text", 
                        "text": prompt,
                        # OpenRouter Prompt Caching (Cost Opt #2)
                        # Ensure static parts of the prompt are at the beginning 
                        # and effectively cached if supported by the model/provider
                        "cache_control": {"type": "ephemeral"} 
                    }
                ]
            }
        ]

        if images:
            for img in images:
                base64_img = self._encode_image(img)
                messages[0]["content"].append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_img}"
                    }
                })

        payload = {
            "model": target_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.1 # Low temp for precise extraction
        }

        retries = 3
        backoff = 2
        
        for attempt in range(retries):
            try:
                # Use a new client for each request to avoid pool issues, or reuse if better
                with httpx.Client(timeout=60.0) as client:
                    response = client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers=self.headers,
                        json=payload
                    )
                    
                    if response.status_code != 200:
                        error_msg = f"HTTP {response.status_code}: {response.text}"
                        print(f"API Error (Attempt {attempt + 1}): {error_msg}")
                        raise httpx.HTTPStatusError(error_msg, request=response.request, response=response)

                    result = response.json()
                    
                    if 'error' in result:
                         raise ValueError(f"OpenRouter API Error: {result['error']}")
                         
                    if 'choices' not in result or not result['choices']:
                         raise ValueError("Empty response from API")

                    usage = result.get('usage', {})
                    return {
                        "content": result['choices'][0]['message']['content'],
                        "usage": usage,
                        "cost": usage.get('cost', 0.0)  # Real cost from OpenRouter API
                    }
            
            except Exception as e:
                print(f"Error calling OpenRouter (Attempt {attempt + 1}/{retries}): {e}")
                if attempt < retries - 1:
                    time.sleep(backoff * (attempt + 1))
                else:
                    raise RuntimeError(f"Failed to get response from OpenRouter after {retries} attempts") from e
        return {}

    @staticmethod
    def get_cost(response: Dict) -> float:
        """
        Get the REAL cost from the API response.
        Falls back to estimate_cost() if the API didn't return a cost.
        
        Usage: cost = OpenRouterClient.get_cost(response)
        """
        api_cost = response.get('cost', 0.0)
        if api_cost and float(api_cost) > 0:
            return float(api_cost)
        # Fallback to local estimate
        return OpenRouterClient.estimate_cost('unknown', response.get('usage', {}))

    @staticmethod
    def estimate_cost(model: str, usage: Dict[str, int]) -> float:
        """
        FALLBACK: Estimate cost based on usage and model.
        Prefer get_cost() which reads the real cost from the API.
        """
        # Pricing per 1M tokens (Prompt / Completion) — used ONLY as fallback
        rates = {
            "qwen/qwen-2-vl-72b-instruct": {"prompt": 0.4, "completion": 0.4},
            "qwen/qwen-2-vl-7b-instruct": {"prompt": 0.1, "completion": 0.1},
            "qwen/qwen-2.5-vl-7b-instruct:free": {"prompt": 0.0, "completion": 0.0},
            "nvidia/nemotron-3-nano-30b-a3b:free": {"prompt": 0.0, "completion": 0.0},
            "google/gemini-2.0-flash-exp:free": {"prompt": 0.0, "completion": 0.0},
            "google/gemma-3-27b-it:free": {"prompt": 0.0, "completion": 0.0},
            "google/gemini-2.0-flash-lite-001": {"prompt": 0.1, "completion": 0.3},
            "deepseek/deepseek-r1-distill-llama-70b": {"prompt": 0.23, "completion": 0.69},
        }
        
        rate = rates.get(model, {"prompt": 0.1, "completion": 0.1})
        p_tokens = usage.get('prompt_tokens', 0)
        c_tokens = usage.get('completion_tokens', 0)
        
        return (p_tokens / 1_000_000 * rate['prompt']) + (c_tokens / 1_000_000 * rate['completion'])

    def analyze_structure(self, pages: List[Image.Image]) -> Dict[str, Any]:
        """
        Analyzes the document structure using sample pages.
        Returns a dictionary containing the detected structure and metadata.
        """
        print("Sending sample pages for structure analysis...")
        
        prompt = """
        SYSTEM PROMPT (CACHEABLE):
        You are a medical QCM extraction specialist. Analyze these sample pages and identify:
        
        1. **QCM Structure**:
           - Question format pattern
           - Proposition markers (A, B, C, D, E or 1, 2, 3...)
           - Answer key format (Correct: AB, Correct: A, etc.)
        
        2. **Metadata Detection**:
           - Source information (university name, exam name)
           - Year/date if present
           - Category/Module names
           - Page headers/footers
        
        3. **Correction Format**:
           - Inline corrections (next to questions)
           - Separate correction page (corrigé-type)
           - Answer key location pattern
        
        4. **Layout Characteristics**:
           - Single/multi-column
           - Questions per page estimate
           - Special markers or separators
        
        Return JSON format:
        {
            "structure": {
                "qcm_pattern": "detected pattern description",
                "proposition_markers": ["A", "B", "C", "D", "E"],
                "answer_format": "format description"
            },
            "metadata": {
                "source_detected": "string or null",
                "year_detected": "number or null",
                "categories_found": ["category1", "category2"]
            },
            "correction_type": "inline | separate_page | mixed",
            "estimated_qcm_count": number
        }
        """
        
        try:
            response = self.generate_completion(prompt, pages)
            response_text = response['content']
            
            # Clean up response to ensure valid JSON
            cleaned_text = response_text.replace("```json", "").replace("```", "").strip()
            
            # Find the start and end of the JSON object
            start_idx = cleaned_text.find('{')
            end_idx = cleaned_text.rfind('}')
            
            if start_idx != -1 and end_idx != -1:
                json_str = cleaned_text[start_idx:end_idx+1]
                return json.loads(json_str)
            else:
                raise ValueError("No JSON object found in response")
                
        except Exception as e:
            print(f"Error parsing structure analysis response: {e}")
            # Return a safe default fallback
            return {
                "structure": {
                    "qcm_pattern": "unknown",
                    "proposition_markers": ["A", "B", "C", "D", "E"],
                    "answer_format": "unknown"
                },
                "metadata": {
                    "source_detected": None,
                    "year_detected": None,
                    "categories_found": []
                },
                "correction_type": "inline",
                "estimated_qcm_count": 0
            }

