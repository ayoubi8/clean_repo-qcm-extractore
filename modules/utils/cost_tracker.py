import json
import threading
from typing import Dict, List, Optional
from datetime import datetime


def cost_step_bucket(key: str) -> Optional[str]:
    """Tracker call key -> the pipeline step it belongs to.

    Modules log calls under detailed keys ("step2_batch_p3-5",
    "step6_all_pages_scan", "cc_checker"...). Cost rows and summaries are
    per step: "1", "1.5", "1.6", "2", "3" (metadata cascade inside Step 2),
    "4", "5", "6", "7", "8". None = unknown key (caller decides).
    """
    k = str(key or "").lower()
    if k.startswith("step1_5"):
        return "1.5"
    if k.startswith("step1_6"):
        return "1.6"
    for n in ("1", "2", "3", "4", "5", "6", "7", "8"):
        if k == f"step{n}" or k.startswith(f"step{n}_"):
            return n
    if k in ("cc_checker", "ai_metadata_detect") or k.startswith(("cc_", "hint", "cas_")):
        return "3"
    return None


# Which cost buckets a run of each step may produce (Step 2 runs the
# metadata cascade = Step 3/4/5 inside its own run).
RUN_BUCKETS = {
    "1": {"1"}, "1.5": {"1.5"}, "1.6": {"1.6"}, "2": {"2", "3", "4", "5"},
    "3": {"3"}, "4": {"4"}, "5": {"5"}, "6": {"6"}, "7": {"7"}, "8": {"8"},
}


def bucket_calls(calls: List[Dict], run_step: str) -> Dict[str, Dict]:
    """Sum calls per step bucket -> {step: {cost, tokens, calls}}.
    Unknown keys count for `run_step`; buckets another step owns are dropped
    (protects against a parallel run of another step of the same project)."""
    allowed = RUN_BUCKETS.get(str(run_step), {str(run_step)})
    out: Dict[str, Dict] = {}
    for c in calls or []:
        b = cost_step_bucket(c.get("step", "")) or str(run_step)
        if b not in allowed:
            continue
        slot = out.setdefault(b, {"cost": 0.0, "tokens": 0, "calls": 0})
        t = c.get("tokens") or {}
        slot["cost"] += float(c.get("cost") or 0)
        slot["tokens"] += int(t.get("prompt", t.get("prompt_tokens", 0)) or 0) + \
            int(t.get("completion", t.get("completion_tokens", 0)) or 0)
        slot["calls"] += 1
    return out

# Shared by every tracker: log_api_call does read-modify-write on dicts and is
# called from parallel workers (Step 1 page pool, parallel Step 2, CC checker).
_LOG_LOCK = threading.RLock()

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
        with _LOG_LOCK:
            return self._log_api_call_unlocked(step, model, tokens, cost)

    def _log_api_call_unlocked(self, step: str, model: str, tokens: Dict, cost: float):
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
    
    # ── per-run deltas (cost recording + child-process runs) ──────────────
    def snapshot(self) -> Dict[str, int]:
        """Call count per key — pass to calls_since() after the run."""
        with _LOG_LOCK:
            return {k: len(v) for k, v in self.steps.items()}

    def calls_since(self, snap: Optional[Dict[str, int]]) -> List[Dict]:
        """Every call logged after `snap`, each tagged with its key."""
        snap = snap or {}
        with _LOG_LOCK:
            out = []
            for k, calls in self.steps.items():
                for c in calls[snap.get(k, 0):]:
                    out.append({"step": k, **c})
            return out

    def merge_calls(self, calls: List[Dict]) -> None:
        """Add calls recorded elsewhere (a child process) to this tracker."""
        for c in calls or []:
            c = dict(c)
            step = c.pop("step", "unknown")
            with _LOG_LOCK:
                self._log_api_call_unlocked(step, c.get("model", "unknown"),
                                            c.get("tokens") or {}, float(c.get("cost") or 0))
                if c.get("timestamp"):
                    self.steps[step][-1]["timestamp"] = c["timestamp"]

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
