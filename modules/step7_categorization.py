import json
import os
from pathlib import Path
from typing import Dict, List, Any

from modules.openrouter_client import OpenRouterClient
from modules.utils.cost_tracker import CostTracker
from modules.utils.prompt_helper import PromptHelper
from modules.utils.xlsx_exporter import export_qcms_to_xlsx

class Step7Categorization:
    """Categorize QCMs using Llama-3.3 with rich domain knowledge (Phase 3)."""
    
    def __init__(self, cost_tracker: CostTracker, project_context=None):
        # Connect OpenRouter client
        self.llama = OpenRouterClient()
        self.llama.model = None 
        
        self.cost_tracker = cost_tracker
        self.prompt_helper = PromptHelper()
        # Updated to the new rich database path
        self.db_path = Path("suport/modules-bio-chir-med.json")
        self.context = project_context
        
        # Cache for loaded modules
        self.modules_db = None
        self.system_context = None
        
    def _load_db(self):
        """Load the rich modules database."""
        if not self.db_path.exists():
            print(f"❌ Modules database not found: {self.db_path}")
            return False
            
        with open(self.db_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.modules_db = {
                "medecine": data.get("medecine", {}),
                "chirurgie": data.get("chirurgie", {}),
                "biologie": data.get("biologie", {})
            }
            self.system_context = data.get("system_context", "")
        return True
        
    def run(self, input_file: str = None) -> Dict:
        """Main execution for Step 7."""
        print("\n" + "="*60)
        print("STEP 7: PER-QCM CATEGORIZATION (Enhanced)")
        print("="*60)
        
        if not self._load_db():
            return {}
            
        if self.context:
            target_input_file = self.context.get_path("step6_corrections") / "corrected_qcms.json"
        else:
            target_input_file = input_file if input_file else "output/step6_corrections/corrected_qcms.json"
            
        if not Path(target_input_file).exists():
            print(f"❌ Input file not found: {target_input_file}")
            return {}
            
        with open(target_input_file, 'r', encoding='utf-8') as f:
            qcms = json.load(f)
            
        print(f"\n🧠 Categorizing {len(qcms)} QCMs using Smart Keyword Match + Llama-3.3...")
        
        categorized_qcms = []
        stats = {"keyword_match": 0, "ai_match": 0}
        
        for i, qcm in enumerate(qcms, 1):
            q_num = qcm.get("Num") or qcm.get("number") or i
            q_text = qcm.get("Text") or qcm.get("text", "")
            
            # 1. Determine Domain
            domain = self._normalize_domain(qcm.get("domain", qcm.get("tagSuggere", "")))
            
            print(f"  [{i}/{len(qcms)}] Q{q_num} ({domain})...", end=" ")
            
            # 2. Try Quick Keyword Match (Fast & Free)
            category = self._quick_match_by_keywords(q_text, domain)
            
            if category:
                print(f"⚡ Keyword Match: {category}")
                stats["keyword_match"] += 1
            else:
                # 3. Use AI Reasoner (High Accuracy)
                print(f"🤖 AI Analyzing...", end=" ")
                category = self._categorize_with_ai(qcm, domain)
                print(f"Detected: {category}")
                stats["ai_match"] += 1
            
            # 4. Update QCM
            qcm["categoryName"] = category
            qcm["subcategoryName"] = category
            qcm["tagSuggere"] = domain.capitalize()
            
            categorized_qcms.append(qcm)
            
        # Save result
        if self.context:
            output_dir = self.context.get_path("step7_categories")
        else:
            output_dir = Path("output/step7_categories")
            output_dir.mkdir(parents=True, exist_ok=True)
            
        output_path = output_dir / "final_qcms.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(categorized_qcms, f, indent=2, ensure_ascii=False)
            
        print(f"\n✅ Done! {stats['keyword_match']} by keywords, {stats['ai_match']} by AI.")
        print(f"📁 Saved to {output_path}")
        
        # Also export as XLSX (same folder, same data)
        export_qcms_to_xlsx(categorized_qcms, output_dir / "final_qcms.xlsx")
        
        return {"total": len(categorized_qcms), "file": str(output_path)}

    def _normalize_domain(self, domain: str) -> str:
        d = domain.lower().strip()
        if "chir" in d: return "chirurgie"
        if "bio" in d: return "biologie"
        return "medecine" # Default

    def _quick_match_by_keywords(self, text: str, domain: str) -> str:
        """Check against rich keywords in DB to avoid API calls."""
        text_lower = text.lower()
        modules = self.modules_db.get(domain, {})
        
        # Iterate all modules in this domain
        candidates = []
        for name, info in modules.items():
            for kw in info.get("keywords", []):
                # Check for exact keyword match in text
                if kw.lower() in text_lower:
                    # Give higher score to longer matches (e.g. "Insuffisance Cardiaque" > "Coeur")
                    candidates.append((name, len(kw)))
                    
        if candidates:
            # Return match with longest keyword
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0][0]
            
        return None

    def _categorize_with_ai(self, qcm: Dict, domain: str) -> str:
        """Construct a smart prompt with rules and call Llama."""
        q_text = qcm.get("Text") or qcm.get("text", "")
        props = qcm.get("propositions", {})
        if not props:
            props = {k: qcm[k] for k in ["A", "B", "C", "D", "E"] if k in qcm}
        props_text = ", ".join([f"{k}: {v}" for k, v in props.items()])
        
        prompt = self._build_prompt_with_context(q_text, props_text, domain)
        
        primary_model = os.getenv("STEP7_MODEL", "meta-llama/llama-3.3-70b-instruct")
        fallback_model = os.getenv("STEP7_FALLBACK_MODEL", "google/gemini-2.0-flash-lite-001")
        max_tokens = int(os.getenv("STEP7_MAX_TOKENS", "4000"))
        
        try:
            try:
                resp = self.llama.generate_completion(prompt, model=primary_model, max_tokens=max_tokens)
                model_used = primary_model
            except Exception as e:
                print(f"⚠️ Primary model failed: {e}")
                print(f"🔄 Retrying with fallback: {fallback_model}...")
                resp = self.llama.generate_completion(prompt, model=fallback_model, max_tokens=max_tokens)
                model_used = fallback_model

            content = resp["content"].strip()
            # Log cost
            cost = resp.get('cost', 0.0) or self.llama.estimate_cost(model_used, resp["usage"])
            self.cost_tracker.log_api_call("step7_cat", model_used, resp["usage"], cost)
            
            # Clean response to get just the Category Name
            # Prone to extra chars, so we try to fuzzy match back to DB keys
            return self._fuzzy_match_module(content, domain)
            
        except Exception as e:
            print(f"Error AI: {e}")
            return "Inconnu"

    def _build_prompt_with_context(self, question: str, props: str, domain: str) -> str:
        """Create the Expert Prompt using the new DB fields."""
        modules = self.modules_db.get(domain, {})
        
        modules_context = ""
        for name, info in modules.items():
            modules_context += f"""
- {name}:
  * Focus: {info['focus']}
  * Keywords: {', '.join(info['keywords'][:5])}...
  * Rule: {info['differentiation']}
"""

        return f"""{self.system_context}

DOMAIN: {domain.upper()}

AVAILABLE MODULES & RULES:
{modules_context}

---
QCM TO CATEGORIZE:
Question: {question}
Propositions: {props}
---

TASK: Analyze the question and propositions. Apply the differentiation rules.
Identify the SINGLE BEST matching module from the list above.

RESPONSE FORMAT: Just the module name. Nothing else.
"""

    def _fuzzy_match_module(self, text: str, domain: str) -> str:
        """Ensure the AI output matches a valid module name."""
        valid_modules = list(self.modules_db.get(domain, {}).keys())
        text_clean = text.lower().strip().replace('"', '').replace("'", "")
        
        # 1. Exact match
        for m in valid_modules:
            if m.lower() == text_clean:
                return m
                
        # 2. Contains match
        for m in valid_modules:
            if m.lower() in text_clean:
                return m
                
        return "Autre"
