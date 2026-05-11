import json
import os
import re
from typing import Dict, List, Optional
from modules.openrouter_client import OpenRouterClient

class AIMetadataDetector:
    """AI-powered metadata detection with confidence scoring."""
    
    def __init__(self, cost_tracker):
        self.client = OpenRouterClient()
        self.cost_tracker = cost_tracker
        
    def detect_all_fields(self, text: str, fields: List[str]) -> Dict[str, any]:
        """
        Detect multiple metadata fields with confidence scores.
        
        Args:
            text: Text to analyze (from page 1 or specified pages)
            fields: List of fields to detect ['Year', 'Source', 'Category', 'Subcategory']
            
        Returns:
            {
                'year': {'value': '2024', 'confidence': 0.95},
                'source': {'value': 'Training Book', 'confidence': 0.88},
                ...
            }
        """
        # Normalize fields to lowercase for internal processing but keep display names
        prompt_fields = [f.lower() for f in fields]
        
        prompt = f"""Analyze this medical exam text and extract metadata.

TEXT:
{text[:4000]}

TASK: Extract the following fields with confidence scores (0.0-1.0):
{', '.join(fields)}

INSTRUCTIONS:
- Year: Publication year or exam year (e.g., 2024, 2023)
- Source: Book name, exam series, university, or publisher (e.g., "Training Book Series", "Résidanat Oran")
- Category: Medical specialty (e.g., "Pédiatrie", "Cardiologie", "Médecine Interne")
- Subcategory: Sub-specialty or specific topic if present (e.g., "Néonatologie", "HTA")

Return ONLY JSON:
{{
  "year": {{"value": "2024", "confidence": 0.95}},
  "source": {{"value": "Training Book Series", "confidence": 0.88}},
  "category": {{"value": "Pédiatrie", "confidence": 0.92}},
  "subcategory": {{"value": null, "confidence": 0.0}}
}}

If a field is not found or ambiguous, use null with confidence 0.0.
"""
        
        try:
            primary_model = os.getenv("STEP3_MODEL", "qwen/qwen3.6-plus-preview:free")
            fallback_model = os.getenv("STEP3_FALLBACK_MODEL", "google/gemini-2.0-flash-lite-001")
            max_tokens = int(os.getenv("STEP3_MAX_TOKENS", "4000"))

            try:
                response = self.client.generate_completion(
                    prompt,
                    model=primary_model,
                    max_tokens=max_tokens
                )
                model_used = primary_model
            except Exception as e:
                print(f"⚠️ Primary AI detector model failed: {e}. Retrying with {fallback_model}...")
                response = self.client.generate_completion(
                    prompt,
                    model=fallback_model,
                    max_tokens=max_tokens
                )
                model_used = fallback_model
            
            content = response["content"]
            
            # Parse JSON
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                
                # Log cost
                cost = response.get('cost', 0.0) or self.client.estimate_cost(model_used, response["usage"])
                self.cost_tracker.log_api_call("ai_metadata_detect", model_used, response["usage"], cost)
                
                return data
            else:
                print("⚠️ No JSON found in AI response")
                return self._empty_result(prompt_fields)
                
        except Exception as e:
            print(f"❌ AI metadata detection failed: {e}")
            return self._empty_result(prompt_fields)
    
    def _empty_result(self, fields: List[str]) -> Dict:
        """Return empty result structure."""
        return {field: {"value": None, "confidence": 0.0} for field in fields}
    
    def filter_by_confidence(self, results: Dict, min_confidence: float = 0.6) -> Dict:
        """Filter results by minimum confidence threshold and return simple map."""
        filtered = {}
        # Map detected internal names back to Step 3 expected display names
        mapping = {
            "year": "Year",
            "source": "Source",
            "category": "Category",
            "subcategory": "Subcategory"
        }
        
        for field, data in results.items():
            display_name = mapping.get(field.lower(), field.capitalize())
            if data and data.get('confidence', 0) >= min_confidence:
                filtered[display_name] = data['value']
            else:
                conf = data.get('confidence', 0) if data else 0
                print(f"⚠️ Low confidence for {display_name}: {conf:.2f} (threshold: {min_confidence})")
        
        return filtered
