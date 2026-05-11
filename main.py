import sys
import os
from dotenv import load_dotenv

# Force UTF-8 execution for Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# Adjust path to import from modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

from modules.utils.cost_tracker import CostTracker
from modules.utils.project_context import ProjectContext
from modules.step1_extraction import Step1Extraction
from modules.step1_5_batch_text_fixer import Step1_5BatchTextFixer
from modules.step1_6_intelligent_text_fixer import Step1_6IntelligentTextFixer
from modules.step2_qcm_extract_batch import Step2QCMExtractBatch
from modules.step3_metadata import Step3Metadata
from modules.step4_format import Step4Format
from modules.step5_builder import Step5Builder
from modules.step6_corrections import Step6Corrections
from modules.step7_categorization import Step7Categorization
from modules.step8_matcher import Step8Matcher
from modules.utils.config_loader import ConfigLoader
from modules.folder_batch_processor import FolderBatchProcessor

def main():
    """Main orchestrator for QCM Extractor v5.0."""
    tracker = CostTracker()
    cost_file = "output/total_costs.json"
    
    print("\n" + "="*60)
    print("🚀 QCM EXTRACTOR v5.0 (MODULAR SYSTEM)")
    print("="*60)
    
    # Project Selection
    context = None
    print("  N. NEW PROJECT (Start with new PDF)")
    print("  R. RESUME PROJECT (Continue existing)")
    print("  X. Exit")
    
    choice = input("\nChoice [N/R/X]: ").strip().upper()
    
    if choice == "N":
        pdf_path = input("Enter PDF path (e.g., 'exam.pdf'): ").strip()
        if not os.path.exists(pdf_path):
            print(f"❌ File not found: {pdf_path}")
            return
            
        project_name = os.path.splitext(os.path.basename(pdf_path))[0]
        context = ProjectContext(project_name)
        print(f"📁 Project '{context.name}' created.")
        
    elif choice == "R":
        projects = ProjectContext.list_projects()
        if not projects:
            print("❌ No existing projects found.")
            return
            
        print("\nExisting Projects:")
        for i, p in enumerate(projects, 1):
            print(f"  {i}. {p}")
            
        try:
            idx = int(input("\nSelect Project Number: ")) - 1
            if 0 <= idx < len(projects):
                context = ProjectContext(projects[idx])
                print(f"📂 Resumed project '{context.name}'")
                pdf_path = "Unknown (Resumed)" # We interpret this from context if needed in step 1 logic, or user re-enters if rerunning step 1
            else:
                print("❌ Invalid selection.")
                return
        except:
            print("❌ Invalid input.")
            return
            
    elif choice == "X":
        print("Goodbye!")
        return
    else:
        print("Invalid choice.")
        return

    while True:
        print("\n" + "="*60)
        print(f"📂 PROJECT: {context.name}")
        print("="*60)
        print("  1. STEP 1: Text Extraction (PDF -> TXT)")
        print("     1.6. STEP 1.6: Intelligent Text Fixing (OCR Cleaning)")
        print("  2. STEP 2: QCM Content Extraction (TXT -> JSON Page-by-Page)")
        print("  3. STEP 3: Metadata Detection (Source/Year/Module)")
        print("  4. STEP 4: Format Template Selection")
        print("  5. STEP 5: JSON Building & Merging")
        print("  6. STEP 6: Correction Processing")
        print("  7. STEP 7: Per-QCM Categorization (Llama-3.3)")
        print("  8. STEP 8: QCM Similarity Matching (vs. Reference DB)")
        print("-" * 60)
        print("  A. AUTOMATIC MODE (Run Sequence)")
        print("  E. EXPORT XLSX from last Step 8 results (no re-run)")
        print("  S. Show Cost Summary & Save")
        print("  X. Exit")
        print("="*60)
        
        choice = input("\nSelect Step [1-8, 1.6, A, E, S, X]: ").strip().upper()
        
        # Determine PDF path logic for Step 1
        current_pdf_path = pdf_path if 'pdf_path' in locals() else "ilovepdf_merged.pdf"
        
        try:
            if choice == "A":
                # === AUTOMATIC MODE SETUP ===
                print("\n⚙️  AUTOMATIC MODE CONFIGURATION")
                
                # Check for batch_config.yaml
                config_loader = ConfigLoader("batch_config.yaml")
                use_yaml = False
                batch_cfg = {}
                
                if os.path.exists("batch_config.yaml"):
                    print("📄 Found batch_config.yaml")
                    use_val = input("Use this configuration for a zero-prompt run? [Y/n]: ").strip().lower()
                    if use_val != 'n':
                        try:
                            batch_cfg = config_loader.load()
                            use_yaml = True
                        except Exception as e:
                            print(f"❌ Error loading config: {e}")
                
                if use_yaml:
                    # Check if Folder Batch Processing is enabled
                    if batch_cfg.get('folder_batch', {}).get('enabled'):
                        print("\n📂 [BATCH] Starting Folder Batch Processing...")
                        processor = FolderBatchProcessor(batch_cfg, tracker)
                        processor.run()
                        continue  # End of batch run, return to menu
                    
                    # YAML-based Configuration (Single PDF)
                    start_step = batch_cfg.get('batch_mode', {}).get('start_step', 1)
                    end_step = batch_cfg.get('batch_mode', {}).get('end_step', 7)
                    pause_for_verification = batch_cfg.get('batch_mode', {}).get('pause_for_verification', False)
                    if end_step > 8:
                        end_step = 8
                    
                    # Prepare run_config from YAML
                    run_config = {
                        'step1': batch_cfg.get('extraction', {}),
                        'step2': batch_cfg.get('qcm_extraction', {}),
                        'step3': batch_cfg.get('metadata', {}),
                        'step4': batch_cfg.get('template', {}),
                        'step6': batch_cfg.get('corrections', {})
                    }
                    print(f"🚀 [AUTO] Loaded config for Steps {start_step}-{end_step}")
                else:
                    # FALLBACK: Interactive Mode (Original Logic)
                    try:
                        start_step = int(input("Start Step [1-8]: ").strip())
                        end_step = int(input(f"End Step [{start_step}-8]: ").strip())
                        if not (1 <= start_step <= end_step <= 8):
                            raise ValueError("Invalid range.")
                    except ValueError:
                        print("❌ Invalid step range. Please enter numbers 1-8 (Start <= End).")
                        continue
                        
                    # Phase 1.5: Verification Preference
                    verify_input = input("Pause for verification after each step? [y/N]: ").strip().lower()
                    pause_for_verification = verify_input == 'y'
                    
                    # Phase 2: Pre-flight Configuration 
                    run_config = {}
                    
                    # --- Step 3 Configuration ---
                    if start_step <= 3 <= end_step:
                        print("\n📝 PRE-FLIGHT: Step 3 Metadata Configuration")
                        meta_fields = ["Year", "Source", "Category", "Subcategory", "ClinicalCase"]
                        meta_config = {"Year": "P", "Source": "S", "Category": "G", "Subcategory": "S", "ClinicalCase": "S"}
                        toggle_cycle = {
                            "Year":         ["S", "G", "P"],
                            "Source":       ["S", "G", "P"],
                            "Category":     ["S", "G", "P"],
                            "Subcategory":  ["S", "G", "P"],
                            "ClinicalCase": ["S", "CC", "G"],
                        }
                        mode_labels = {"G": "Global", "P": "Per-QCM", "S": "Skip", "CC": "Per-Group (Cas Clinique)"}
                        
                        while True:
                            print("\n  Strategy Selection per Field:")
                            for i, f in enumerate(meta_fields, 1):
                                mode = meta_config[f]
                                desc = mode_labels.get(mode, mode)
                                print(f"    [{i}] {f:<14}: {desc} [{mode}]")
                            print("\n  Commands: [Number] to toggle | [Enter] to confirm")
                            c = input("  Choice: ").strip()
                            if not c: break
                            if c.isdigit() and 1 <= int(c) <= len(meta_fields):
                                f = meta_fields[int(c)-1]
                                cycle = toggle_cycle[f]
                                current = meta_config[f]
                                next_idx = (cycle.index(current) + 1) % len(cycle) if current in cycle else 0
                                meta_config[f] = cycle[next_idx]
                                
                        # Collect Global Values and Pages Upfront
                        global_vals = {}
                        global_pages = None
                        
                        has_global = any(mode == "G" for mode in meta_config.values())
                        if has_global:
                            # Ask for pages to extract from
                            page_input = input("  Extract global metadata from which page(s)? (e.g., '1' or '1,11'): ").strip()
                            if page_input:
                                try:
                                    global_pages = [int(p.strip()) for p in page_input.split(",")]
                                except ValueError:
                                    print("  ⚠️  Invalid input, using page 1")
                                    global_pages = [1]
                            
                            # Collect values for non-ClinicalCase global fields
                            for f, mode in meta_config.items():
                                if mode == "G" and f != "ClinicalCase":
                                    val = input(f"  Enter Global Value for '{f}': ").strip()
                                    if val: global_vals[f] = val
                        
                        run_config['step3'] = {
                            "config": meta_config,
                            "global_values": global_vals,
                            "global_pages": global_pages
                        }

                    # --- Step 6 Configuration ---
                    if start_step <= 6 <= end_step:
                        print("\n📝 PRE-FLIGHT: Step 6 Correction Source")
                        print("  1. AI Knowledge (DeepSeek R1)")
                        print("  2. Specific Page Text (e.g. page 11)")
                        print("  3. Extracted Data (Auto-detect 'Correction' pages)")
                        print("  4. Vision AI (Highlights in PDF)")
                        print("  5. Manual Entry (Skip in Auto Mode)")
                        
                        c_choice = input("  Select Source [1-4]: ").strip()
                        c_config = {"source": c_choice}
                        
                        if c_choice == "1":
                            mode = input("  Mode? [S]equential (Better) or [B]atch (Cheaper): ").strip().upper()
                            c_config["ai_mode"] = mode
                        elif c_choice == "2":
                            page = input("  Enter Page Number or File Path: ").strip()
                            c_config["page_ref"] = page
                        elif c_choice == "4":
                            prompt = input("  Vision Prompt (or Enter for default): ").strip()
                            c_config["vision_prompt"] = prompt
                            
                        run_config['step6'] = c_config

                # Phase 3: Execution Loop
                print("\n" + "="*60)
                print(f"🚀 STARTING AUTO-RUN: Steps {start_step} to {end_step}")
                print("="*60)
                
                try:
                    for step_num in range(start_step, end_step + 1):
                        result = {}
                        
                        # --- Step 1: Extraction ---
                        if step_num == 1:
                            if not current_pdf_path or not os.path.exists(current_pdf_path):
                                print(f"❌ PDF not found at {current_pdf_path}")
                                if not use_yaml: # In interactive mode, ask for it
                                    current_pdf_path = input("Enter the full path to the PDF: ").strip()
                                    if not os.path.exists(current_pdf_path): break
                                else:
                                    break
                            
                            if use_yaml:
                                s1_cfg = run_config.get('step1', {})
                                result = Step1Extraction(tracker, context).run(
                                    current_pdf_path, 
                                    auto_ocr=(s1_cfg.get('method') == 'vision_ocr'),
                                    ocr_guidance=s1_cfg.get('ocr_guidance', '')
                                )
                            else:
                                result = Step1Extraction(tracker, context).run(current_pdf_path)
                            
                            # === AUTOMATIC STEP 1.5: Batch QCM Fixer ===
                            # ... (rest of Step 1.5 logic)
                            
                            # === AUTOMATIC STEP 1.6: Intelligent Text Fixer ===
                            if use_yaml:
                                s16_cfg = batch_cfg.get('text_fixing', {})
                                if s16_cfg.get('enabled', False):
                                    run_fixer = True
                                    if s16_cfg.get('skip_if_pypdfium2', True) and s1_cfg.get('method') == 'pypdfium2':
                                        print("\n[AUTO] Skipping Step 1.6 (pypdfium2 extraction used and skip_if_pypdfium2 is true)")
                                        run_fixer = False
                                        
                                    if run_fixer:
                                        print("\n[AUTO] Running Step 1.6: Intelligent Text Fixer...")
                                        try:
                                            fixer = Step1_6IntelligentTextFixer(tracker, context)
                                            fixer.run(config=s16_cfg)
                                        except Exception as e:
                                            print(f"[WARN] Step 1.6 failed: {e}")
                        # --- Step 2: Extraction ---
                        elif step_num == 2:
                            if use_yaml:
                                s2_cfg = run_config.get('step2', {})
                                result = Step2QCMExtractBatch(tracker, context).run(
                                    page_range=s2_cfg.get('page_range', 'all')
                                )
                            else:
                                result = Step2QCMExtractBatch(tracker, context).run() 
                            
                        # --- Step 3: Metadata ---
                        elif step_num == 3:
                            cfg = run_config.get('step3', {})
                            if use_yaml:
                                # Enhanced auto-detection will be Phase 2, but for now we support config mapping
                                result = Step3Metadata(tracker, context).run(
                                    auto_mode=True,
                                    config=cfg.get('fields', {}),
                                    global_values={k.capitalize(): v['value'] for k, v in cfg.get('fields', {}).items() if v.get('value')},
                                    global_pages=cfg.get('global_pages', None)
                                )
                            elif cfg:
                                result = Step3Metadata(tracker, context).run(
                                    auto_mode=True,
                                    config=cfg.get('config', {}),
                                    global_values=cfg.get('global_values', {}),
                                    global_pages=cfg.get('global_pages', None)
                                )
                            else:
                                result = Step3Metadata(tracker, context).run()
                            
                        # --- Step 4: Format ---
                        elif step_num == 4:
                            if use_yaml:
                                template_name = run_config.get('step4', {}).get('name')
                                result = Step4Format(tracker, context).run(auto_template=template_name)
                            else:
                                result = Step4Format(tracker, context).run()
                            
                        # --- Step 5: Builder ---
                        elif step_num == 5:
                            result = Step5Builder(tracker, context).run()
                            
                        # --- Step 6: Corrections ---
                        elif step_num == 6:
                            cfg = run_config.get('step6', {})
                            if use_yaml:
                                # Handle multi-page correction support from config
                                # Supports: pages: [4, 5, 6] OR pages: "4-7" OR pages: "4,5,6"
                                pages = cfg.get('pages', [])
                                if isinstance(pages, list):
                                    pages = ",".join(map(str, pages))
                                elif not isinstance(pages, str):
                                    pages = str(pages)

                                result = Step6Corrections(tracker, context).run(
                                    pdf_path=current_pdf_path,
                                    auto_mode=True,
                                    config={
                                        "source": str(cfg.get('source', 'page_text')),
                                        "pages": pages,
                                        # Phase 1: all-pages scanning mode
                                        "correction_search_mode": cfg.get("correction_search_mode", "specific_pages"),
                                        "all_pages_scan": cfg.get("all_pages_scan", {}),
                                        "page_text": cfg.get("page_text", {}),
                                        "model": cfg.get("model", "google/gemini-2.5-flash-lite-preview-09-2025"),
                                        "ai_mode": cfg.get('ai_mode', 'S'),
                                    }
                                )
                            elif cfg:
                                result = Step6Corrections(tracker, context).run(
                                    pdf_path=current_pdf_path,
                                    auto_mode=True,
                                    config=cfg
                                )
                            else:
                                result = Step6Corrections(tracker, context).run(pdf_path=current_pdf_path)
                            
                        # --- Step 7: Categorization ---
                        elif step_num == 7:
                            result = Step7Categorization(tracker, context).run()

                        # --- Step 8: QCM Matcher ---
                        elif step_num == 8:
                            result = Step8Matcher(tracker, context).run()

                        # --- Verification Logic ---
                        if not result and step_num not in [4, 5]: # Some steps returns might be empty but valid
                             print(f"⚠️  Step {step_num} returned no status. Checking consistency...")

                        if pause_for_verification:
                            print(f"\n⏸️  Step {step_num} Complete. Paused for verification.")
                            input("Press Enter to continue (or Ctrl+C to abort)...")
                        else:
                            print(f"\n✅ Step {step_num} Complete. Proceeding...")
                            
                except KeyboardInterrupt:
                    print("\n🛑 Auto-Run interrupted by user.")
                except Exception as e:
                    print(f"\n❌ CRITICAL ERROR in Step {step_num}: {e}")
                    import traceback; traceback.print_exc()
                
                print("\n✨ Auto-Run Sequence Finished.")
                input("Press Enter to return to menu...")
                continue
                
            elif choice == "1":
                if not os.path.exists(current_pdf_path):
                    current_pdf_path = input(f"Enter PDF path: ").strip()
                Step1Extraction(tracker, context).run(current_pdf_path)
                
                # === AUTOMATIC STEP 1.5: Batch QCM Fixer ===
                print("\n[AUTO] Running Step 1.5: Batch QCM Fixer...")
                try:
                    fixer = Step1_5BatchTextFixer(tracker, context)
                    fix_result = fixer.run()
                    if fix_result['fixes_applied'] > 0:
                        print(f"[OK] Fixed {fix_result['fixes_applied']} pages with splits")
                    else:
                        print("[OK] No splits detected")
                except Exception as e:
                    print(f"[WARN] Step 1.5 failed: {e}")
                    print("      Continuing with original text files...")
                # ==============================================
                
            elif choice == "1.6":
                print("\n[INTERACTIVE] Running Step 1.6: Intelligent Text Fixer...")
                fixer = Step1_6IntelligentTextFixer(tracker, context)
                fixer.run()
                
            elif choice == "2":
                Step2QCMExtractBatch(tracker, context).run()
                
            elif choice == "3":
                Step3Metadata(tracker, context).run()
                
            elif choice == "4":
                Step4Format(tracker, context).run()
                
            elif choice == "5":
                Step5Builder(tracker, context).run()
                
            elif choice == "6":
                Step6Corrections(tracker, context).run(pdf_path=current_pdf_path)
                
            elif choice == "7":
                Step7Categorization(tracker, context).run()
                
            elif choice == "8":
                Step8Matcher(tracker, context).run()

            elif choice == "E":
                print("\n📤 Re-Export: Loading last Step 8 results...")
                Step8Matcher(tracker, context).export_from_existing()
            elif choice == "S":
                tracker.display_summary()
                tracker.save(cost_file)
                print(f"✓ Costs saved to {cost_file}")
                
            elif choice == "X":
                print("Exiting. Final Costs:")
                tracker.display_summary()
                tracker.save(cost_file)
                print("Goodbye!")
                break
            else:
                print("⚠️  Invalid choice. Please select 1-7, S, or X.")
                
        except Exception as e:
            print(f"\n❌ Error in Step {choice}: {e}")
            import traceback; print(traceback.format_exc())
            print("Try running the step again or check your configuration.")

if __name__ == "__main__":
    main()
