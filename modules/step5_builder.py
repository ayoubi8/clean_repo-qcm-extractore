import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

from modules.utils.xlsx_exporter import export_qcms_to_xlsx

from modules.deepseek_client import DeepSeekClient
from modules.utils.file_manager import FileManager
from modules.utils.cost_tracker import CostTracker

class Step5Builder:
    """Build final JSON by mapping Step 3 data to Step 4 template"""
    
    def __init__(self, cost_tracker: CostTracker, project_context=None):
        self.client = DeepSeekClient()
        self.file_manager = FileManager()
        self.cost_tracker = cost_tracker
        self.context = project_context
        
    def run(self, step3_dir: str = None, template_path: str = None) -> Dict:
        """Main execution for Step 5."""
        print("\n" + "="*60)
        print("STEP 5: JSON BUILDING & MERGING")
        print("="*60)
        
        if self.context:
            target_step3_dir = self.context.get_path("step3_metadata", "accepted")
            target_template_path = self.context.get_path("step4_format") / "current_template.json"
        else:
            target_step3_dir = step3_dir if step3_dir else "output/step3_metadata/accepted"
            target_template_path = template_path if template_path else "output/step4_format/current_template.json"
        
        # 1. Load template
        if not Path(target_template_path).exists():
            print(f"❌ Template not found at {target_template_path}. Please run Step 4 first.")
            return {}
            
        with open(target_template_path, 'r', encoding='utf-8') as f:
            template = json.load(f)
            
        # 2. Load all QCMs from Step 3
        q_files = sorted(list(Path(target_step3_dir).glob("*.json")))
        if not q_files:
            print(f"❌ No QCM data found in {target_step3_dir}. Please run Step 3 first.")
            return {}
            
        all_qcms = []
        for q_file in q_files:
            with open(q_file, 'r', encoding='utf-8') as f:
                all_qcms.extend(json.load(f))
                
        print(f"📄 Loaded {len(all_qcms)} QCMs from {len(q_files)} files. Mapping to template...")
        
        # 3. Mapping each QCM to the template format
        final_qcms = []
        for i, qcm in enumerate(all_qcms, 1):
            mapped = self._map_to_template(qcm, template)
            final_qcms.append(mapped)
            if i % 10 == 0 or i == len(all_qcms):
                print(f"  Processed {i}/{len(all_qcms)}...")
            
        # 4. Save result
        if self.context:
            output_dir = self.context.get_path("step5_json")
        else:
            output_dir = Path("output/step5_json")
            output_dir.mkdir(parents=True, exist_ok=True)
            
        output_path = output_dir / "merged_qcms.json"
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(final_qcms, f, indent=2, ensure_ascii=False)
            
        print(f"\n✅ Merged JSON saved to {output_path}")
        
        # Also export as XLSX — use a timestamped name so each run creates a NEW file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        xlsx_path = output_dir / f"merged_qcms_{timestamp}.xlsx"
        export_qcms_to_xlsx(final_qcms, xlsx_path)
        
        return {"total_qcms": len(final_qcms), "output_file": str(output_path), "xlsx_file": str(xlsx_path)}

    def _map_to_template(self, qcm: Dict, template: Dict) -> Dict:
        """Map extracted fields from Step 3 QCM to the provided template structure."""
        # Start with a copy of the template
        new_qcm = template.copy()
        
        # Mapping rules: Template Key -> possible keys in extracted QCM
        # This handles common variations in field naming
        field_map = {
            "Num": ["number", "Num", "id", "num"],
            "Text": ["text", "Text", "question", "questionText"],
            "Correct": ["correction", "Correct", "answer"],
            "categoryName": ["module", "categoryName", "module_detected"],
            "subcategoryName": ["subcategory", "subcategoryName"],
            "tagSuggere": ["tagSuggere", "domain", "domain_tag"],
            "Year": ["year", "Year"],
            "Source": ["source", "Source"],
            "Tag": ["tag", "Tag"],
            # Cas Clinique — maps internal 'cas' field to template key 'Cas'
            "Cas": ["cas", "Cas", "clinical_case"],
        }
        
        # Perform mapping for standard fields
        for template_key in new_qcm.keys():
            # Check if template key matches any of our known mapped fields
            for map_key, variations in field_map.items():
                if template_key == map_key or template_key in variations:
                    # Look through variations in the QCM data
                    for var in variations:
                        val = qcm.get(var)
                        if val is not None and val != "" and val != []:
                            new_qcm[template_key] = val
                            break
                    break
                    
        # Specially handle propositions A-E if they are at the top level of the template
        # or in a 'propositions' dict in the QCM
        qcm_props = qcm.get("propositions", {})
        for key in ["A", "B", "C", "D", "E"]:
            if key in new_qcm:
                # Try getting from QCM root first (e.g., qcm['A'])
                if key in qcm:
                    new_qcm[key] = qcm[key]
                # Then try dictionary 'propositions' (e.g., qcm['propositions']['A'] or 'a')
                elif key in qcm_props:                  # Exact match (e.g., "A")
                    new_qcm[key] = qcm_props[key]
                elif key.lower() in qcm_props:          # Case-insensitive fallback (e.g., "a")
                    new_qcm[key] = qcm_props[key.lower()]
                    
        # Apply fallback: carry over unmapped non-null step3 fields to empty template fields
        for k, v in qcm.items():
            if k in new_qcm and (new_qcm[k] is None or new_qcm[k] == "" or new_qcm[k] == []):
                if v is not None and v != "" and v != []:
                    new_qcm[k] = v

        # Auto-propagate Cas Clinique: always include if the QCM has it,
        # even when the active template doesn't define a "Cas" key.
        # This ensures CC narratives are never silently lost for any template
        # (including the User-Provided-Template).
        # If the template already has "Cas" defined, standard mapping above already handled it.
        cas_value = qcm.get("cas") or qcm.get("Cas")
        if cas_value is not None and cas_value != "":
            if "Cas" not in new_qcm or new_qcm.get("Cas") in [None, "", 0]:
                new_qcm["Cas"] = cas_value
                    
        return new_qcm
