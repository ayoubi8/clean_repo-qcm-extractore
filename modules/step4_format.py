import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from modules.utils.template_library import TemplateLibrary
from modules.utils.file_manager import FileManager
from modules.utils.prompt_helper import PromptHelper
from modules.deepseek_client import DeepSeekClient

class Step4Format:
    """Prepare final JSON format using templates"""
    
    def __init__(self, cost_tracker, project_context=None):
        self.library = TemplateLibrary()
        self.file_manager = FileManager()
        self.prompt_helper = PromptHelper()
        self.client = DeepSeekClient()
        self.cost_tracker = cost_tracker
        self.context = project_context
        
    def run(self, step3_dir: str = None, auto_template: str = None) -> Dict:
        """Main execution for Step 4."""
        print("\n" + "="*60)
        print("STEP 4: JSON FORMAT TEMPLATE")
        print("="*60)
        
        if self.context:
            target_step3_dir = self.context.get_path("step3_metadata", "accepted")
        else:
            target_step3_dir = step3_dir if step3_dir else "output/step3_metadata/accepted"
            
        # 1. Check for user-provided Template.json and register it
        user_template_path = Path("Template.json")
        if user_template_path.exists():
            try:
                with open(user_template_path, 'r', encoding='utf-8') as f:
                    user_template = json.load(f)
                # If template is a list with one item, use that item as the schema
                if isinstance(user_template, list) and len(user_template) > 0:
                    user_template = user_template[0]
                self.library.save_template("User-Provided-Template", user_template)
            except Exception as e:
                print(f"⚠️  Could not load Template.json: {e}")
            
        # 2. Select template
        if auto_template:
            print(f"\n[AUTO] Selecting template: {auto_template}")
            try:
                template = self.library.load_template(auto_template)
            except ValueError:
                print(f"⚠️  Template '{auto_template}' not found. Falling back to interactive.")
                template = self.library.select_template_interactive()
        else:
            template = self.library.select_template_interactive()
        
        if template:
            print("\n✅ Template selected.")
            self._save_current_template(template)
            return {"status": "template_ready", "template": template}
        else:
            # 3. Create new template logic (Only in interactive mode)
            if auto_template:
                print("❌ Template selection failed in auto-mode.")
                return {}
            return self._create_new_template(target_step3_dir)

    def _create_new_template(self, step3_dir: Path) -> Dict:
        """Create a custom template using interactive field selection (Phase 2)."""
        print("\n🔧 CUSTOM TEMPLATE BUILDER")
        print("Select the fields you want in your final JSON output.")
        
        # 1. Define available fields with defaults
        fields_config = {
            "Num": {"desc": "Question Number (e.g. 10)", "default": True, "key": "Num"},
            "Text": {"desc": "Question Stem", "default": True, "key": "Text"},
            "Propositions": {"desc": "Choices (A-E)", "default": True, "key": "Propositions (Map)"},
            "Correct": {"desc": "Correct Answer (e.g. ABC)", "default": True, "key": "Correct"},
            "Year": {"desc": "Exam Year", "default": True, "key": "Year"},
            "Category": {"desc": "Medical Module", "default": True, "key": "categoryName"},
            "Subcategory": {"desc": "Specific Course/Topic", "default": False, "key": "subcategoryName"},
            "Source": {"desc": "University/Origin", "default": False, "key": "Source"},
            "Tag": {"desc": "Combined [Source, Year]", "default": True, "key": "Tag"},
            "ClinicalCase": {"desc": "Cas Clinique narrative linked to QCM", "default": False, "key": "Cas"},
        }
        
        # 2. Interactive Selection
        selected = self._interactive_field_selection(fields_config)
        
        # 3. Build Template Structure
        new_template = {
            "Num": 0,
            "Text": "Question text here..."
        }
        
        # Add optional fields based on selection
        if selected["Propositions"]:
            new_template["A"] = "Option A"
            new_template["B"] = "Option B"
            new_template["C"] = "Option C"
            new_template["D"] = "Option D"
            new_template["E"] = "Option E"
            
        if selected["Correct"]: new_template["Correct"] = "ABC"
        if selected["Year"]: new_template["Year"] = "2024"
        if selected["Category"]: new_template["categoryName"] = "Cardiologie"
        if selected["Subcategory"]: new_template["subcategoryName"] = "HTA"
        if selected["Source"]: new_template["Source"] = "Alger"
        if selected["Tag"]: new_template["Tag"] = ["Alger", "2024"]
        if selected["ClinicalCase"]: new_template["Cas"] = "CAS CLINIQUE 1\r\nPatient narrative..."
        
        print("\n✨ Generated Template:")
        print(json.dumps(new_template, indent=2, ensure_ascii=False))
        
        name = input("\nEnter name for this template (e.g. 'MyFormat'): ").strip() or "Custom-v1"
        self.library.save_template(name, new_template)
        self._save_current_template(new_template)
        
        return {"status": "new_template_created", "template": new_template}

    def _interactive_field_selection(self, fields_config: Dict) -> Dict:
        """Show checkboxes and let user toggle."""
        # Initialize user selection with defaults
        selection = {k: v["default"] for k, v in fields_config.items()}
        keys = list(fields_config.keys())
        
        while True:
            print("\nIncluding these fields:")
            for i, k in enumerate(keys, 1):
                status = "[x]" if selection[k] else "[ ]"
                desc = fields_config[k]["desc"]
                print(f"  {i}. {status} {k:<12} ({desc})")
                
            print("\nOptions: [Number] to toggle | [A]ll | [N]one | [Enter] to Confirm")
            choice = input("Choice: ").strip().lower()
            
            if not choice:
                break
            elif choice == 'a':
                selection = {k: True for k in selection}
            elif choice == 'n':
                selection = {k: False for k in selection}
            elif choice.isdigit() and 1 <= int(choice) <= len(keys):
                key = keys[int(choice)-1]
                selection[key] = not selection[key]
                
        return selection

    def _save_current_template(self, template: Dict):
        """Saves the chosen template as the active one for Step 5."""
        if self.context:
            path = self.context.get_path("step4_format") / "current_template.json"
        else:
            path = Path("output/step4_format/current_template.json")
            path.parent.mkdir(parents=True, exist_ok=True)
            
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(template, f, indent=2, ensure_ascii=False)

    def _parse_json(self, content: str) -> Dict:
        """Robustly extracts and parses JSON from the response."""
        try:
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                json_str = match.group(0)
                # Clean potential trailing commas
                json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
                return json.loads(json_str)
        except Exception as e:
            print(f"Failed to parse JSON: {e}")
        return {}
