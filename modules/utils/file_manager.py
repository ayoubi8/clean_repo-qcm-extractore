import json
import os
from pathlib import Path
from typing import Any, Dict

class FileManager:
    """Manage file operations for all steps"""
    
    def __init__(self, base_dir: str = "output"):
        self.base_dir = base_dir
    
    def save_accepted(self, step: str, filename: str, data: Any):
        """Save to accepted folder"""
        path = Path(self.base_dir) / step / "accepted" / filename
        self._save_json(path, data)
        print(f"✓ Saved to {path}")
    
    def save_rejected(self, step: str, filename: str, data: Any):
        """Save to rejected folder"""
        path = Path(self.base_dir) / step / "rejected" / filename
        self._save_json(path, data)
        print(f"⊗ Saved to {path}")
    
    def load_step_output(self, step: str, folder: str = "accepted") -> Dict:
        """Load all files from a step folder"""
        path = Path(self.base_dir) / step / folder
        if not path.exists():
            raise ValueError(f"Step folder not found: {path}")
        
        files = {}
        for file in path.glob("*.json"):
            with open(file, 'r', encoding='utf-8') as f:
                files[file.stem] = json.load(f)
        
        return files
    
    def _save_json(self, path: Path, data: Any):
        """Internal: save JSON file"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
