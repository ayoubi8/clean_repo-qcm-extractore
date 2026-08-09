import json
import os
import re
from typing import Dict, List, Optional
from modules.openrouter_client import OpenRouterClient
from modules.utils.metadata_context import (
    build_context_block, normalize_module, normalize_year,
    normalize_faculty, find_faculty_in_text, derive_source,
)

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
        taxonomy_block = build_context_block()
        
        prompt = f"""Analyze this medical exam text and extract metadata.

{taxonomy_block}

TEXT:
{text[:4000]}

TASK: Extract the following fields with confidence scores (0.0-1.0):
{', '.join(fields)}, "faculty"

INSTRUCTIONS:
- "category": the canonical module name from VALID MODULES BY LEVEL (exactly as written). null if unknown.
- "year": the START year of any "YYYY/YYYY" pair (e.g. "2025/2026" -> "2025"). Plain 4-digit year stays as-is.
- "source": derive per RULES — "Externat {{faculty}}" if category matched, else "Residanat {{faculty}}". null if faculty unknown.
- "subcategory": specific topic if present, else null.
- "faculty": the matched faculty from VALID FACULTIES (intermediate field, used to derive source).

Return ONLY JSON:
{{
  "year": {{"value": "2024", "confidence": 0.95}},
  "source": {{"value": "Externat Oran", "confidence": 0.88}},
  "category": {{"value": "Cardiologie", "confidence": 0.92}},
  "subcategory": {{"value": null, "confidence": 0.0}},
  "faculty": {{"value": "Oran", "confidence": 0.9}}
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

                # Post-process: validate / canonicalize against the taxonomy.
                # The LLM is the recommender; Python is the validator.
                self._canon(data, "category", "category", normalize_module)
                self._canon(data, "year", "year", normalize_year)

                # Faculty is an intermediate field used to derive source.
                fac_entry = data.get("faculty") or {}
                raw_fac = fac_entry.get("value") if isinstance(fac_entry, dict) else fac_entry
                if not raw_fac:
                    raw_fac = find_faculty_in_text(text[:4000])
                faculty = normalize_faculty(raw_fac) if raw_fac else None

                # Source is derived deterministically from module + faculty.
                cat_entry = data.get("category") or {}
                mod_val = cat_entry.get("value") if isinstance(cat_entry, dict) else cat_entry
                if "source" not in data or not isinstance(data["source"], dict):
                    data["source"] = {"value": None, "confidence": 0.0}
                data["source"]["value"] = derive_source(mod_val, faculty)
                # Boost source confidence when we derived it from a known faculty.
                if data["source"]["value"]:
                    data["source"]["confidence"] = max(data["source"].get("confidence", 0.0), 0.8)

                data.pop("faculty", None)

                return data
            else:
                print("⚠️ No JSON found in AI response")
                return self._empty_result(prompt_fields)
                
        except Exception as e:
            print(f"❌ AI metadata detection failed: {e}")
            return self._empty_result(prompt_fields)

    @staticmethod
    def _canon(data: dict, key: str, alt_key: Optional[str], normalizer) -> None:
        """In-place: canonicalize data[key] / data[alt_key] "value" via `normalizer`.
        If the normalizer rejects the LLM value (returns None), set confidence 0.0."""
        entry = data.get(key) or (data.get(alt_key) if alt_key else None)
        if not isinstance(entry, dict):
            return
        raw = entry.get("value")
        canon = normalizer(raw) if raw else None
        entry["value"] = canon
        if canon is None:
            entry["confidence"] = 0.0
    
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
