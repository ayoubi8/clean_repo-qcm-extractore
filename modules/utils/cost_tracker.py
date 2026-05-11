import json
from typing import Dict, List
from datetime import datetime

class CostTracker:
    """Track API costs across all steps"""
    
    def __init__(self):
        self.steps = {}
        self.models = {
            "vision_ocr": {"cost": 0, "tokens": {"prompt": 0, "completion": 0}},
            "deepseek_r1": {"cost": 0, "tokens": {"prompt": 0, "completion": 0}},
            "llama_3.3": {"cost": 0, "tokens": {"prompt": 0, "completion": 0}}
        }
        
    def log_api_call(self, step: str, model: str, tokens: Dict, cost: float):
        """
        Log individual API call
        Args:
            step: e.g., "step1", "step2"
            model: e.g., "vision_ocr", "deepseek_r1"
            tokens: {"prompt": 100, "completion": 400}
            cost: 0.0005
        """
        if step not in self.steps:
            self.steps[step] = []
            
        self.steps[step].append({
            "model": model,
            "tokens": tokens,
            "cost": cost,
            "timestamp": datetime.now().isoformat()
        })
        
        # Update model totals
        if model in self.models:
            self.models[model]["cost"] += cost
            self.models[model]["tokens"]["prompt"] += tokens.get("prompt", tokens.get("prompt_tokens", 0))
            self.models[model]["tokens"]["completion"] += tokens.get("completion", tokens.get("completion_tokens", 0))
        else:
            # Add model if it doesn't exist
            self.models[model] = {
                "cost": cost,
                "tokens": {
                    "prompt": tokens.get("prompt", tokens.get("prompt_tokens", 0)),
                    "completion": tokens.get("completion", tokens.get("completion_tokens", 0))
                }
            }
    
    def get_step_summary(self, step: str) -> Dict:
        """Get cost summary for a specific step"""
        if step not in self.steps:
            return {"total_cost": 0, "call_count": 0, "total_tokens": {"prompt": 0, "completion": 0}}
            
        calls = self.steps[step]
        return {
            "total_cost": sum(c["cost"] for c in calls),
            "call_count": len(calls),
            "total_tokens": {
                "prompt": sum(c["tokens"].get("prompt", 0) for c in calls),
                "completion": sum(c["tokens"].get("completion", 0) for c in calls)
            }
        }
    
    def get_total_summary(self) -> Dict:
        """Get complete cost breakdown"""
        return {
            "per_model": self.models.copy(),
            "per_step": {step: self.get_step_summary(step) for step in self.steps},
            "total_cost": sum(m["cost"] for m in self.models.values()),
            "total_tokens": sum(
                m["tokens"]["prompt"] + m["tokens"]["completion"] 
                for m in self.models.values()
            )
        }
    
    def save(self, filepath: str):
        """Save complete cost state to JSON"""
        state = {
            "models": self.models,
            "steps": self.steps,
            "summary": self.get_total_summary()
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            
    def load(self, filepath: str):
        """Load cost state from JSON"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # If it's the new format with "models" and "steps" keys
            if "models" in data and "steps" in data:
                self.models = data["models"]
                self.steps = data["steps"]
            # Fallback for old format (which was just the summary)
            elif "per_model" in data:
                self.models = data["per_model"]
                # We can't perfectly restore steps from summary, but we can 
                # at least keep the per-model totals.
                self.steps = {} 
        except Exception as e:
            print(f"Error loading costs: {e}")
            
    def display_summary(self):
        """Pretty print cost summary"""
        summary = self.get_total_summary()
        
        print("\n" + "="*60)
        print("💰 COST SUMMARY")
        print("="*60)
        print("\nPer-Model Costs:")
        for model, data in summary["per_model"].items():
            tokens = data["tokens"]["prompt"] + data["tokens"]["completion"]
            print(f"  {model:20s}: ${data['cost']:.4f} ({tokens:,} tokens)")
        
        print("\nPer-Step Costs:")
        for step, data in summary["per_step"].items():
            print(f"  {step:20s}: ${data['total_cost']:.4f}")
        
        print(f"\n  {'TOTAL':20s}: ${summary['total_cost']:.4f}")
        print("="*60)
