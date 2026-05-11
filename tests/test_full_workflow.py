import os
import sys
import json
import time
from pathlib import Path
from dotenv import load_dotenv

# Import our modules
from modules.document_processor import DocumentProcessor
from modules.text_extraction_manager import TextExtractionManager
from modules.metadata_analyzer import MetadataAnalyzer
from modules.deepseek_client import DeepSeekClient
from modules.openrouter_client import OpenRouterClient

# Load env
load_dotenv()

def run_test_workflow(file_path: str, extraction_method: str):
    """
    Run the full workflow on a single file using specified method
    """
    print(f"\n🧪 TESTING WORKFLOW: {extraction_method.upper()} on {Path(file_path).name}")
    print("-" * 60)
    
    start_time = time.time()
    costs = {
        'extraction': 0.0,
        'metadata': 0.0,
        'vision': 0.0
    }
    
    # 1. Initialize
    print("1. Initializing...")
    try:
        doc_processor = DocumentProcessor(file_path)
        vision_client = OpenRouterClient(cache_enabled=True)
        deepseek_client = DeepSeekClient(api_key=os.getenv('OPENROUTER_API_KEY'))
        text_manager = TextExtractionManager(vision_client=vision_client)
        metadata_analyzer = MetadataAnalyzer(
            deepseek_client=deepseek_client, 
            modules_file_path='suport/modules-bio-chir-med.json'
        )
    except Exception as e:
        print(f"❌ Init failed: {e}")
        return False

    # 2. Load Docs
    print("2. Loading Pages...")
    pages = doc_processor.load_document()
    print(f"   Loaded {len(pages)} pages")
    
    # 3. Text Extraction
    print(f"3. Extracting Text ({extraction_method})...")
    extracted_text = text_manager.extract_all_pages(
        file_path=file_path,
        method=extraction_method,
        pages=pages if extraction_method == 'ocr' else None
    )
    costs['extraction'] = extracted_text.get('extraction_cost', 0.0)
    print(f"   Extracted {len(extracted_text['combined_text'])} chars. Cost: ${costs['extraction']:.4f}")
    
    # 4. Metadata Analysis
    print("4. Analyzing Metadata...")
    metadata = metadata_analyzer.analyze_document(extracted_text)
    costs['metadata'] = metadata.get('analysis_cost', 0.0)
    
    print(f"   Detected Module: {metadata.get('module')} ({metadata.get('domain_tag')})")
    
    if metadata.get('matched_module'):
        print(f"   ✅ Matched DB: {metadata['matched_module']['categoryName']}")
    else:
        print(f"   ⚠️ No DB Match Found")
        
    # 5. Simulate One Batch Vision Extraction (Cost Check)
    print("5. Simulating Vision Extraction (1 Batch)...")
    batch_size = 3
    sample_batch = pages[:batch_size]
    
    # We won't actually call the API to save money, but we'll use our estimator
    estimated_vision_cost = len(pages) * 0.005 # rough estimate per page
    costs['vision'] = estimated_vision_cost
    
    # 6. Report
    elapsed = time.time() - start_time
    total_cost = sum(costs.values())
    
    print("\n📊 TEST RESULTS")
    print("-" * 30)
    print(f"Time Taken: {elapsed:.2f}s")
    print(f"Extraction Cost: ${costs['extraction']:.4f}")
    print(f"Analysis Cost:   ${costs['metadata']:.4f}")
    print(f"Est. Vision Cost: ${costs['vision']:.4f}")
    print(f"TOTAL EST. COST: ${total_cost:.4f}")
    
    if metadata.get('module'):
        return True
    return False

def main():
    print("========================================")
    print("   AUTOMATED SYSTEM TEST SUITE")
    print("========================================")
    
    # Find a test file
    test_pdf = ""
    pdfs = list(Path('.').glob('*.pdf'))
    if pdfs:
        test_pdf = str(pdfs[0])
    else:
        print("❌ No PDF found in directory for testing.")
        return

    # Test Case 1: PDF Text Extraction
    print("\n[TEST CASE 1] Text-Based PDF Extraction (pypdfium2)")
    success_1 = run_test_workflow(test_pdf, 'pdf')
    
    # Test Case 2: OCR Extraction
    # We use the same PDF but force OCR mode to test the vision pipeline
    print("\n[TEST CASE 2] OCR Extraction (Vision AI)")
    success_2 = run_test_workflow(test_pdf, 'ocr')
    
    print("\n========================================")
    print(f"Test 1 (PDF): {'✅ PASS' if success_1 else '❌ FAIL'}")
    print(f"Test 2 (OCR): {'✅ PASS' if success_2 else '❌ FAIL'}")
    print("========================================")

if __name__ == "__main__":
    main()
