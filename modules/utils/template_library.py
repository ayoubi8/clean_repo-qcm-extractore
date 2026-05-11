import json
import os
from pathlib import Path
from typing import Dict, List

class TemplateLibrary:
    """Manage multiple QCM format templates"""
    
    def __init__(self, library_dir: str = "output/step4_format/templates"):
        self.library_dir = Path(library_dir)
        self.library_dir.mkdir(parents=True, exist_ok=True)
    
    def save_template(self, name: str, template: Dict):
        """
        Save a template with a name
        Args:
            name: e.g., "Residanat 2014", "Default Format"
            template: JSON template structure
        """
        filepath = self.library_dir / f"{name}.json"
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(template, f, indent=2, ensure_ascii=False)
        print(f"✓ Template saved: {name}")
    
    def list_templates(self) -> List[str]:
        """Get list of available templates"""
        return [f.stem for f in self.library_dir.glob("*.json")]
    
    def load_template(self, name: str) -> Dict:
        """Load a template by name"""
        filepath = self.library_dir / f"{name}.json"
        if not filepath.exists():
            raise ValueError(f"Template not found: {name}")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def select_template_interactive(self) -> Dict:
        """Show menu and let user select template"""
        templates = self.list_templates()
        
        if not templates:
            print("No saved templates found")
            return None
        
        print("\nAvailable templates:")
        for i, name in enumerate(templates, 1):
            print(f"  {i}. {name}")
        print(f"  {len(templates)+1}. Create new template")
        
        choice_str = input("\nSelect template: ").strip()
        if not choice_str.isdigit():
            return None
            
        choice = int(choice_str) - 1
        
        if 0 <= choice < len(templates):
            return self.load_template(templates[choice])
        else:
            return None  # Create new
