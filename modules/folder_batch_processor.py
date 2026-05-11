import os
import glob
import time
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

from modules.utils.project_context import ProjectContext
from modules.utils.cost_tracker import CostTracker
from modules.step1_extraction import Step1Extraction
from modules.step1_5_batch_text_fixer import Step1_5BatchTextFixer
from modules.step2_qcm_extract_batch import Step2QCMExtractBatch
from modules.step3_metadata import Step3Metadata
from modules.step4_format import Step4Format
from modules.step5_builder import Step5Builder
from modules.step6_corrections import Step6Corrections
from modules.step7_categorization import Step7Categorization

class FolderBatchProcessor:
    """Orchestrates processing of multiple PDFs in a folder."""
    
    def __init__(self, config: Dict[str, Any], tracker: CostTracker):
        self.config = config
        self.tracker = tracker
        self.batch_cfg = config.get('folder_batch', {})
        self.input_folder = Path(self.batch_cfg.get('input_folder', 'input'))
        self.file_pattern = self.batch_cfg.get('file_pattern', '*.pdf')
        self.output_base = Path(self.batch_cfg.get('output_base', 'output/batch_results'))
        
    def run(self):
        """Main batch processing loop."""
        print("\n" + "█"*60)
        print("  FOLDER BATCH PROCESSOR")
        print("█"*60)
        
        # 1. Find PDF files
        pdf_paths = sorted(list(self.input_folder.glob(self.file_pattern)))
        
        if not pdf_paths:
            print(f"❌ No files found matching '{self.file_pattern}' in {self.input_folder}")
            return
            
        print(f"📂 Found {len(pdf_paths)} files to process.")
        
        results_summary = {
            "batch_start": datetime.now().isoformat(),
            "config_used": self.config,
            "processed_files": [],
            "errors": []
        }
        
        # 2. Process each file
        for i, pdf_path in enumerate(pdf_paths, 1):
            project_name = pdf_path.stem
            print(f"\n🚀 [{i}/{len(pdf_paths)}] Processing: {project_name}")
            print("-" * 40)
            
            try:
                # Initialize Project Context for this PDF
                context = ProjectContext(project_name)
                
                # Execute Pipeline
                file_result = self._process_single_pdf(pdf_path, context)
                
                results_summary["processed_files"].append({
                    "file": str(pdf_path),
                    "project": project_name,
                    "status": "success",
                    "details": file_result
                })
                
            except Exception as e:
                print(f"❌ Failed to process {project_name}: {e}")
                results_summary["processed_files"].append({
                    "file": str(pdf_path),
                    "project": project_name,
                    "status": "failed",
                    "error": str(e)
                })
                results_summary["errors"].append({"file": str(pdf_path), "error": str(e)})

        # 3. Final Report
        results_summary["batch_end"] = datetime.now().isoformat()
        self._save_batch_report(results_summary)
        
        print("\n" + "█"*60)
        print(f"✅ BATCH COMPLETE: {len(pdf_paths)} files handled.")
        print(f"📄 Report saved to {self.output_base}")
        print("█"*60)

    def _process_single_pdf(self, pdf_path: Path, context: ProjectContext) -> Dict:
        """Run the full extraction pipeline for one PDF."""
        start_time = time.time()
        
        # Step 1: Extraction
        s1_cfg = self.config.get('extraction', {})
        s1_result = Step1Extraction(self.tracker, context).run(
            str(pdf_path),
            auto_ocr=(s1_cfg.get('method') == 'vision_ocr'),
            ocr_guidance=s1_cfg.get('ocr_guidance', '')
        )
        
        # Step 2: QCM Batch Extraction
        s2_cfg = self.config.get('qcm_extraction', {})
        s2_result = Step2QCMExtractBatch(self.tracker, context).run(
            page_range=s2_cfg.get('page_range', 'all')
        )
        
        # Step 3: Metadata
        s3_cfg = self.config.get('metadata', {})
        # Map YAML config to Step3 format (Phase 2 logic)
        s3_result = Step3Metadata(self.tracker, context).run(
            auto_mode=True,
            config=s3_cfg.get('fields', {}),
            global_values={k.capitalize(): v['value'] for k, v in s3_cfg.get('fields', {}).items() if v.get('value')},
            global_pages=s3_cfg.get('global_pages', None)
        )
        
        # Step 4: Template Mapping
        s4_cfg = self.config.get('template', {})
        s4_result = Step4Format(self.tracker, context).run(auto_template=s4_cfg.get('name'))
        
        # Step 5: Final Builder
        s5_result = Step5Builder(self.tracker, context).run()
        
        # Step 6: Corrections (if enabled)
        s6_cfg = self.config.get('corrections', {})
        s6_result = {}
        if s6_cfg:
            pages = s6_cfg.get('pages', [])
            if isinstance(pages, list): pages = ",".join(map(str, pages))
            s6_result = Step6Corrections(self.tracker, context).run(
                pdf_path=str(pdf_path),
                auto_mode=True,
                config={
                    "source": str(s6_cfg.get('source', '1')),
                    "page_ref": str(pages),
                    "ai_mode": s6_cfg.get('ai_mode', 'S')
                }
            )
            # Re-run builder if corrected
            if s6_result:
                Step5Builder(self.tracker, context).run()
        
        # Step 7: Categorization
        s7_result = {}
        if self.config.get('categorization', {}).get('enabled'):
            s7_result = Step7Categorization(self.tracker, context).run()

        return {
            "duration": round(time.time() - start_time, 2),
            "qcms_extracted": s2_result.get('total_extracted', 0),
            "final_file": s5_result.get('output_file')
        }

    def _save_batch_report(self, summary: Dict):
        """Save a JSON summary of the entire batch run."""
        self.output_base.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self.output_base / f"batch_results_{timestamp}.json"
        
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
