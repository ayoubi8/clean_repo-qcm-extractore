import os
import sys
from pathlib import Path

try:
    import pypdfium2 as pdfium
except ImportError:
    print("❌ pypdfium2 is required. Please install it using: pip install pypdfium2")
    sys.exit(1)

def split_pdf_interactive():
    print("=" * 60)
    print("📄 QCM Extractor - PDF Splitter Utility")
    print("=" * 60)
    
    # 1. Get Input File
    while True:
        input_path = input("Enter the path to the PDF file: ").strip()
        # Remove quotation marks if dragged and dropped into terminal
        input_path = input_path.strip("\"'")
        
        if os.path.exists(input_path) and input_path.lower().endswith('.pdf'):
            break
        print(f"❌ File not found or not a PDF: {input_path}")
        
    try:
        pdf = pdfium.PdfDocument(input_path)
        total_pages = len(pdf)
        print(f"✅ Loaded PDF with {total_pages} pages.")
    except Exception as e:
        print(f"❌ Failed to read PDF: {e}")
        return

    # 2. Get Range
    print("\nSpecify the page range to extract (1-based index).")
    while True:
        try:
            start_str = input(f"Start page (1-{total_pages}): ").strip()
            if not start_str: continue
            start_page = int(start_str)
            
            end_str = input(f"End page ({start_page}-{total_pages}) [Press Enter for same as start]: ").strip()
            end_page = int(end_str) if end_str else start_page
            
            if 1 <= start_page <= end_page <= total_pages:
                break
            print(f"❌ Invalid range. Must be between 1 and {total_pages}.")
        except ValueError:
            print("❌ Please enter valid numbers.")

    # 3. Get Mode
    print("\nHow would you like to save the pages?")
    print("  1) Save as a single merged PDF (e.g., one file containing pages 5 to 10)")
    print("  2) Save as individual PDFs (e.g., 6 separate files, one for each page)")
    
    while True:
        mode = input("Choice [1/2]: ").strip()
        if mode in ['1', '2']:
            split_individual = (mode == '2')
            break
        print("❌ Invalid choice.")

    # 4. Setup Output Directory
    base_name = Path(input_path).stem
    output_dir = Path("pdf_splits") / base_name
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 5. Process
    start_idx = start_page - 1
    end_idx = end_page - 1
    indices = list(range(start_idx, end_idx + 1))
    
    print(f"\n⚙️ Processing {len(indices)} pages...")
    
    try:
        if split_individual:
            for idx in indices:
                new_pdf = pdfium.PdfDocument.new()
                new_pdf.import_pages(pdf, [idx])
                
                out_file = output_dir / f"{base_name}_page_{idx+1}.pdf"
                new_pdf.save(str(out_file))
                new_pdf.close()
                print(f"  ✅ Saved: {out_file}")
        else:
            new_pdf = pdfium.PdfDocument.new()
            new_pdf.import_pages(pdf, indices)
            
            out_file = output_dir / f"{base_name}_pages_{start_page}_to_{end_page}.pdf"
            new_pdf.save(str(out_file))
            new_pdf.close()
            print(f"  ✅ Saved: {out_file}")
            
    except Exception as e:
        print(f"❌ Error during split: {e}")
    finally:
        pdf.close()

    print("\n🎉 Done! All files were saved to:")
    print(f"   {output_dir.absolute()}")

if __name__ == "__main__":
    try:
        split_pdf_interactive()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled.")
        sys.exit(0)
