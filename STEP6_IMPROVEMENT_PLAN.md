# 🔧 Step 6 Correction Processing - Improvement Plan

## 🎯 Problems Identified

### Problem 1: Model 404 Error
**Current Issue:**
```
HTTP 404: No matching route found. Model: google/gemma-3-27b-it:free
```

**Root Cause:**
- The model name might be incorrect or the API endpoint has changed
- Need to verify the correct model identifier on OpenRouter

**Solution:**
- Keep using `google/gemma-3-27b-it:free` but investigate the correct model name
- Check OpenRouter documentation for the exact model identifier
- Possible alternatives if name changed:
  - `google/gemma-2-27b-it:free`
  - `google/gemma-27b-it:free`
  - Verify on OpenRouter API models list

**Action Items:**
1. Check OpenRouter models endpoint: `https://openrouter.ai/api/v1/models`
2. Find the correct Gemma 3 27B model identifier
3. Update line 22 with correct model name
4. Add fallback to `nvidia/nemotron-3-nano-30b-a3b:free` if Gemma unavailable

---

### Problem 2: No Automatic Correction Detection
**Current Issue:**
- User must manually specify which pages contain corrections
- No intelligence to find correction pages automatically

**Solution:**
- Add **automatic correction page detection** before asking user
- Scan all extracted pages (step1_extraction/accepted/) for correction indicators
- Use heuristics + AI to identify correction pages

**Detection Strategy:**

1. **Heuristic Scan** (Fast, Free):
   - Look for keywords: "corrigé", "correction", "réponse", "rep.", "answer key"
   - Look for patterns: Multiple lines with format "10 ACE", "11 BD", etc.
   - Look for table structures with QCM numbers and letters
   - Score each page based on correction indicators

2. **AI Validation** (For ambiguous cases):
   - Use Gemma to analyze top 3 candidate pages
   - Ask: "Does this page contain a correction table/answer key?"
   - Return confidence score

3. **User Confirmation**:
   - Show detected pages: "Found corrections on pages: 4, 5, 6"
   - Ask: "Use these pages? [Y/n] or enter different pages:"
   - If user says 'n', prompt for manual input

**Workflow:**
```
Step 6 starts
    ↓
Auto-scan all pages (heuristic)
    ↓
Found candidates? 
    ↓ YES
Show: "Detected correction pages: 4,5,6"
Ask: "Use these? [Y/n]:"
    ↓ User says Y
Load pages 4,5,6
    ↓ User says n or enters "7,8"
Load pages 7,8
    ↓ NO candidates found
Ask: "Enter correction page(s):"
```

---

### Problem 3: Multi-Page Input Support
**Current Issue:**
```python
page_ref = input("Enter page number (e.g., 11) or full path to text file: ").strip()
```
- Only accepts ONE page at a time
- User wants: `4,5,6` (multiple pages with corrections)

**Solution:**
- Accept comma-separated page numbers: `4,5,6`
- Accept page ranges: `4-6`
- Accept mixed input: `4,5,7-9`
- Merge all correction data before applying to QCMs

---

### Problem 4: Step Order Limitation
**Current Workflow:**
```
Step 1 (OCR) → Step 2 (QCM Extract) → ... → Step 6 (Corrections)
```

**User Request:**
- Run Step 6 BEFORE Step 2
- Extract corrections from pages 4,5,6
- Then use corrections during QCM extraction

**Solution:**
- Make Step 6 independent (can run before or after Step 2)
- Store corrections in intermediate file
- Step 2 can optionally load pre-extracted corrections

---

## 📋 Implementation Plan

### Phase 0: Verify Gemma Model ✅ (10 minutes)

**Objective:** Find the correct Gemma 3 27B model identifier

**Steps:**
1. Query OpenRouter API for available models
2. Search for Gemma models in the response
3. Identify the correct free Gemma 3 27B model name
4. Test the model with a simple API call

**Possible Model Names to Test:**
- `google/gemma-3-27b-it:free` (current)
- `google/gemma-2-27b-it:free`
- `google/gemma-27b-it:free`
- Check latest OpenRouter documentation

**Fallback Strategy:**
- If Gemma 3 27B is not available for free, use `nvidia/nemotron-3-nano-30b-a3b:free`
- Add try-catch logic to automatically fallback if primary model fails

**File:** `modules/step6_corrections.py`

**Changes:**
```python
# Line 20-23 - Add model verification and fallback
try:
    self.openrouter.model = "google/gemma-3-27b-it:free"  # Or correct name from API
    # Test the model with a simple call
except:
    print("⚠️ Gemma model unavailable, using Nemotron fallback")
    self.openrouter.model = "nvidia/nemotron-3-nano-30b-a3b:free"
```

**Test:**
- Run a simple API call to verify model works
- Check response and cost tracking

---

### Phase 1: Automatic Correction Page Detection ✅ (45 minutes)

**Objective:** Intelligently detect which pages contain corrections before asking user

**New Function 1: Heuristic Scanner**
```python
def _auto_detect_correction_pages(self) -> List[int]:
    """
    Scan all extracted pages for correction indicators.
    Returns: List of page numbers likely containing corrections
    """
    # Implementation details:
    # 1. Load all page_*.txt files from step1_extraction/accepted/
    # 2. For each page, calculate correction score based on:
    #    - Keyword count: "corrigé", "correction", "réponse", "rep."
    #    - Pattern matches: "10 ACE", "11 BD" format (count occurrences)
    #    - Table indicators: "|", "---", multiple columns
    #    - Density: ratio of correction patterns to total lines
    # 3. Score each page (0-100)
    # 4. Return pages with score > 60
```

**Scoring Algorithm:**
```
Page Score = (keyword_count * 10) + (pattern_matches * 5) + (table_indicators * 3)

If score > 80: High confidence (auto-select)
If score 60-80: Medium confidence (show to user)
If score < 60: Low confidence (ignore)
```

**New Function 2: AI Validator (Optional)**
```python
def _validate_correction_page_with_ai(self, page_text: str, page_num: int) -> Dict:
    """
    Use Gemma to validate if a page contains corrections.
    Only called for medium-confidence pages (score 60-80).
    
    Returns: {"is_correction_page": bool, "confidence": 0-100}
    """
    # Prompt Gemma:
    # "Does this page contain a correction table or answer key for multiple choice questions?
    #  Answer with JSON: {is_correction_page: true/false, confidence: 0-100}"
```

**Modified Function: _extract_from_page_text**
```python
def _extract_from_page_text(self, qcms: List[Dict], auto_mode: bool = False,
                            page_ref: str = None) -> List[Dict]:
    """
    NEW WORKFLOW:
    1. Auto-detect correction pages using heuristics
    2. If high-confidence pages found (score > 80):
       - Show: "🔍 Auto-detected correction pages: 4, 5, 6"
       - Ask: "Use these pages? [Y/n] or enter different pages:"
    3. If medium-confidence pages found (score 60-80):
       - Optionally validate with AI
       - Show results to user for confirmation
    4. If no pages found or user says 'n':
       - Prompt: "Enter correction page(s) (e.g., 4,5,6 or 4-6):"
    5. Parse user input (supports: single, multiple, ranges)
    6. Load and merge all correction pages
    7. Extract corrections using regex + AI fallback
    """
```

**User Experience:**
```
STEP 6: CORRECTION PROCESSING

🔍 Auto-detecting correction pages...
   Scanning 10 pages...
   
✅ Found potential correction pages:
   - Page 4 (Score: 95 - High confidence)
   - Page 5 (Score: 88 - High confidence)
   - Page 6 (Score: 72 - Medium confidence)

Use pages 4, 5, 6? [Y/n] or enter different pages: Y

📄 Loading 3 correction pages...
  ✅ Loaded: page_4.txt
  ✅ Loaded: page_5.txt
  ✅ Loaded: page_6.txt

✅ Found 50 corrections across all pages
✅ Applied 50/50 corrections
```

**Test:**
- Run on exam with corrections on pages 4,5,6
- Verify auto-detection finds correct pages
- Test user override with different page numbers

---

### Phase 2: Multi-Page Input Support ✅ (30 minutes)

**Objective:** Support multiple page inputs in various formats

**New Function:**
```python
def _parse_page_input(self, page_input: str) -> List[int]:
    """
    Parse user input for page numbers.
    
    Supports:
    - Single page: "5" → [5]
    - Multiple pages: "4,5,6" → [4, 5, 6]
    - Range: "4-6" → [4, 5, 6]
    - Mixed: "4,5,7-9" → [4, 5, 7, 8, 9]
    
    Returns: Sorted list of unique page numbers
    """
```

**Modified Logic in _extract_from_page_text:**
```python
# After user input (or auto-detection):
page_numbers = self._parse_page_input(page_ref)

# Load all pages:
all_correction_text = ""
for page_num in page_numbers:
    file_path = get_page_file(page_num)
    all_correction_text += load_file(file_path)

# Parse corrections from merged text:
corrections = extract_corrections(all_correction_text)
```

**Test:**
- Input: `4,5,6` → Should load 3 pages
- Input: `4-6` → Should load 3 pages
- Input: `4,5,7-9` → Should load 5 pages

---

### Phase 3: Standalone Mode (Step 6 Before Step 2) ✅ (25 minutes)

**Objective:** Allow Step 6 to run independently and save correction map for later use

**Modified run() function:**
```python
def run(self, ...):
    # Check if Step 5 output exists
    if not step5_file_exists():
        print("\n⚠️ Step 5 output not found")
        print("   Running in STANDALONE mode")
        print("   Will create correction map for use in Step 2")
        return self._create_standalone_correction_map(auto_mode, config)
    
    # Normal mode: apply corrections to existing QCMs
    # ... existing logic ...
```

**New Function:**
```python
def _create_standalone_correction_map(self, auto_mode: bool, config: Dict) -> Dict:
    """
    Create correction map without QCMs (for use before Step 2).
    
    Workflow:
    1. Auto-detect correction pages (or ask user)
    2. Load and parse corrections
    3. Save to: output/PROJECT/step6_corrections/correction_map.json
    4. Return summary
    """
```

**Output File:** `correction_map.json`
```json
{
  "10": "ACE",
  "11": "BD",
  "12": "A",
  ...
}
```

**Modified Step 2:**
```python
# In step2_qcm_extract_batch.py

def run(self, ...):
    # Check for pre-extracted corrections
    correction_map = self._load_correction_map()
    
    if correction_map:
        print(f"\n✅ Found {len(correction_map)} pre-extracted corrections")
    
    # ... extraction logic ...
    
    # Apply corrections if available
    if correction_map:
        apply_corrections(all_qcms, correction_map)
```

**Test:**
- Run Step 1 (OCR)
- Run Step 6 (creates correction_map.json)
- Run Step 2 (automatically loads and applies corrections)

---

## 🎯 Usage Examples

### Example 1: Auto-Detection Success ✅
```bash
$ python main.py
> 6. Correction Processing

🔍 Auto-detecting correction pages...
✅ Found: pages 4, 5, 6 (High confidence)

Use these? [Y/n]: Y

✅ Applied 50 corrections
```

### Example 2: Auto-Detection with Override
```bash
$ python main.py
> 6. Correction Processing

🔍 Auto-detecting correction pages...
✅ Found: pages 4, 5 (Medium confidence)

Use these? [Y/n]: n
Enter pages: 6,7,8

✅ Applied 50 corrections from pages 6,7,8
```

### Example 3: No Auto-Detection
```bash
$ python main.py
> 6. Correction Processing

🔍 Auto-detecting correction pages...
⚠️ No correction pages detected

Enter correction page(s): 4-6

✅ Applied 50 corrections
```

### Example 4: Standalone Mode (Before Step 2)
```bash
$ python main.py
> 1. Extract text from PDFs
> 6. Correction Processing

⚠️ Step 5 not found - STANDALONE mode

🔍 Auto-detecting correction pages...
✅ Found: pages 4, 5, 6

Use these? [Y/n]: Y

✅ Correction map saved: correction_map.json
   Total: 50 corrections

> 2. Extract QCMs from text

✅ Loaded 50 pre-extracted corrections
✅ Applied automatically
```

---

## 📊 Summary of Changes

| Phase | Feature | Complexity | Time | Priority |
|-------|---------|------------|------|----------|
| **Phase 0** | Verify Gemma model | Low | 10 min | Critical |
| **Phase 1** | Auto-detect corrections | Medium | 45 min | High |
| **Phase 2** | Multi-page support | Low | 30 min | High |
| **Phase 3** | Standalone mode | Medium | 25 min | Medium |

**Total Effort:** ~2 hours

**Files Modified:**
- `modules/step6_corrections.py` (~150 lines added/modified)
- `modules/step2_qcm_extract_batch.py` (~30 lines added)

**Benefits:**
- ✅ Keeps using Gemma 3 27B (free model)
- ✅ Intelligent auto-detection of correction pages
- ✅ Supports multiple page inputs (4,5,6 or 4-6)
- ✅ Can run Step 6 before Step 2
- ✅ Better user experience (less manual work)
- ✅ Fallback to Nemotron if Gemma unavailable

---

## 🚀 Implementation Order

1. **Phase 0** (10 min): Verify Gemma model → Fix 404 error
2. **Phase 1** (45 min): Add auto-detection → Test on real exam
3. **Phase 2** (30 min): Multi-page support → Test with 4,5,6
4. **Phase 3** (25 min): Standalone mode → Test full workflow

**Total Time:** ~2 hours

Ready to implement? 🎯

**File:** `modules/step6_corrections.py`

**Changes:**
```python
# Line 22 - BEFORE:
self.openrouter.model = "google/gemma-3-27b-it:free"

# Line 22 - AFTER:
self.openrouter.model = "nvidia/nemotron-3-nano-30b-a3b:free"
```

**Test:**
- Run Step 6 with option 2 (Specific Page Text)
- Verify AI extraction works without 404 error

---

### Phase 2: Multi-Page Input Support ✅ (30 minutes)

**File:** `modules/step6_corrections.py`

**New Function:**
```python
def _parse_page_input(self, page_input: str) -> List[int]:
    """
    Parse user input for page numbers.
    
    Supports:
    - Single page: "5"
    - Multiple pages: "4,5,6"
    - Range: "4-6"
    - Mixed: "4,5,7-9"
    
    Returns: List of page numbers [4, 5, 6]
    """
    pages = []
    parts = page_input.split(',')
    
    for part in parts:
        part = part.strip()
        
        if '-' in part:
            # Range: "4-6"
            try:
                start, end = map(int, part.split('-'))
                pages.extend(range(start, end + 1))
            except:
                print(f"⚠️ Invalid range: {part}")
        else:
            # Single page: "5"
            try:
                pages.append(int(part))
            except:
                print(f"⚠️ Invalid page number: {part}")
    
    return sorted(set(pages))  # Remove duplicates and sort
```

**Modified Function:**
```python
def _extract_from_page_text(self, qcms: List[Dict], auto_mode: bool = False,
                            page_ref: str = None) -> List[Dict]:
    """
    Extract corrections from multiple text files containing correction tables.
    """
    if auto_mode and page_ref:
        print(f"\n📝 Using pre-configured pages: {page_ref}")
    else:
        print("\n📝 Enter page number(s) for correction extraction:")
        print("   Examples:")
        print("     - Single page: 5")
        print("     - Multiple pages: 4,5,6")
        print("     - Range: 4-6")
        print("     - Mixed: 4,5,7-9")
        page_ref = input("\nPage(s): ").strip()
    
    # Parse page numbers
    if page_ref.replace(',', '').replace('-', '').isdigit():
        page_numbers = self._parse_page_input(page_ref)
    else:
        # Full path to single file
        page_numbers = [page_ref]
    
    print(f"\n📄 Loading {len(page_numbers)} correction page(s)...")
    
    # Collect all correction text
    all_correction_text = ""
    
    for page_num in page_numbers:
        if isinstance(page_num, int):
            if self.context:
                file_path = self.context.get_path("step1_extraction", "accepted") / f"page_{page_num}.txt"
            else:
                file_path = Path(f"output/step1_extraction/accepted/page_{page_num}.txt")
        else:
            file_path = Path(page_num)
        
        if not file_path.exists():
            print(f"⚠️ File not found: {file_path}")
            continue
        
        with open(file_path, 'r', encoding='utf-8') as f:
            page_text = f.read()
        
        all_correction_text += f"\n\n=== PAGE {page_num} ===\n{page_text}"
        print(f"  ✅ Loaded: {file_path.name}")
    
    if not all_correction_text.strip():
        print("❌ No correction text loaded")
        return qcms
    
    # Parse corrections using regex (existing logic)
    pattern1 = r'(?:^|\|)\s*(\d{1,3})\s*[:\s]+([A-E]+)\s*(?:\||$)'
    matches1 = re.findall(pattern1, all_correction_text, re.MULTILINE)
    
    pattern2 = r'(\d{1,3})\s+([A-E]{1,5})(?:\s|$)'
    matches2 = re.findall(pattern2, all_correction_text)
    
    matches = matches1 if len(matches1) >= len(matches2) else matches2
    
    if not matches:
        print("⚠️ No corrections found with regex. Trying AI extraction...")
        return self._extract_corrections_with_ai(all_correction_text, qcms)
    
    # Build correction map
    correction_map = {}
    for num_str, correction in matches:
        num = int(num_str)
        clean_correction = ''.join(c for c in correction.upper() if c in 'ABCDE')
        correction_map[num] = clean_correction
    
    print(f"✅ Found {len(correction_map)} corrections across all pages.")
    
    # Apply corrections to QCMs
    applied_count = 0
    for qcm in qcms:
        qcm_num = qcm.get('Num') or qcm.get('number')
        if qcm_num and int(qcm_num) in correction_map:
            qcm['Correct'] = correction_map[int(qcm_num)]
            applied_count += 1
    
    print(f"\n✅ Applied {applied_count}/{len(qcms)} corrections.")
    return qcms
```

**Test:**
- Run Step 6 with input: `4,5,6`
- Verify all 3 pages are loaded
- Verify corrections are merged correctly

---

### Phase 3: Independent Step 6 Execution ✅ (20 minutes)

**Concept:**
- Step 6 can run BEFORE Step 2
- Saves corrections to intermediate file
- Step 2 can optionally load these corrections

**New File:** `output/PROJECT/step6_corrections/correction_map.json`
```json
{
  "10": "ACE",
  "11": "BD",
  "12": "A",
  ...
}
```

**Modified Step 6:**
```python
def run(self, input_file: str = None, pdf_path: str = "ilovepdf_merged.pdf",
        auto_mode: bool = False, config: Dict = None) -> Dict:
    """Main execution for Step 6."""
    print("\n" + "="*60)
    print("STEP 6: CORRECTION PROCESSING")
    print("="*60)
    
    # Check if Step 5 output exists
    if self.context:
        target_input_file = self.context.get_path("step5_json") / "merged_qcms.json"
    else:
        target_input_file = input_file if input_file else "output/step5_json/merged_qcms.json"
    
    # NEW: If Step 5 doesn't exist, create standalone correction map
    if not Path(target_input_file).exists():
        print("\n⚠️ Step 5 output not found.")
        print("   Running in STANDALONE mode - will create correction map only.")
        return self._create_standalone_correction_map(auto_mode, config)
    
    # Existing logic for full QCM correction
    with open(target_input_file, 'r', encoding='utf-8') as f:
        qcms = json.load(f)
    
    # ... rest of existing code ...
```

**New Function:**
```python
def _create_standalone_correction_map(self, auto_mode: bool = False, 
                                      config: Dict = None) -> Dict:
    """
    Create a correction map without QCMs (for use before Step 2).
    """
    print("\n📝 Enter page number(s) for correction extraction:")
    print("   Examples: 5 or 4,5,6 or 4-6")
    page_ref = input("\nPage(s): ").strip()
    
    page_numbers = self._parse_page_input(page_ref)
    
    # Load all correction pages
    all_correction_text = ""
    for page_num in page_numbers:
        if self.context:
            file_path = self.context.get_path("step1_extraction", "accepted") / f"page_{page_num}.txt"
        else:
            file_path = Path(f"output/step1_extraction/accepted/page_{page_num}.txt")
        
        if file_path.exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                all_correction_text += f"\n\n{f.read()}"
            print(f"  ✅ Loaded: {file_path.name}")
    
    # Parse corrections
    pattern = r'(\d{1,3})\s+([A-E]{1,5})(?:\s|$)'
    matches = re.findall(pattern, all_correction_text)
    
    correction_map = {}
    for num_str, correction in matches:
        num = int(num_str)
        clean_correction = ''.join(c for c in correction.upper() if c in 'ABCDE')
        correction_map[num] = clean_correction
    
    # Save correction map
    if self.context:
        output_dir = self.context.get_path("step6_corrections")
    else:
        output_dir = Path("output/step6_corrections")
        output_dir.mkdir(parents=True, exist_ok=True)
    
    output_path = output_dir / "correction_map.json"
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(correction_map, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Correction map saved: {output_path}")
    print(f"   Total corrections: {len(correction_map)}")
    
    return {"total": len(correction_map), "file": str(output_path)}
```

**Modified Step 2:**
```python
# In step2_qcm_extract_batch.py

def run(self, ...):
    # ... existing code ...
    
    # NEW: Check for pre-extracted corrections
    correction_map = self._load_correction_map()
    
    if correction_map:
        print(f"\n✅ Found {len(correction_map)} pre-extracted corrections")
        print("   Will apply them after QCM extraction")
    
    # ... existing extraction logic ...
    
    # NEW: Apply corrections if available
    if correction_map:
        for qcm in all_qcms:
            qcm_num = qcm.get('number')
            if qcm_num and qcm_num in correction_map:
                qcm['Correct'] = correction_map[qcm_num]

def _load_correction_map(self) -> Dict:
    """Load pre-extracted correction map if it exists."""
    if self.context:
        correction_file = self.context.get_path("step6_corrections") / "correction_map.json"
    else:
        correction_file = Path("output/step6_corrections/correction_map.json")
    
    if correction_file.exists():
        with open(correction_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    return {}
```

---

## 🎯 Usage Examples

### Example 1: Traditional Workflow (Step 6 AFTER Step 2)
```bash
$ python main.py
> 1. Extract text from PDFs (OCR)
> 2. Extract QCMs from text
> ... (Steps 3-5)
> 6. Correction Processing

Select Correction Source:
  2. Specific Page Text
Choice: 2

Enter page(s): 4,5,6

✅ Loaded 3 pages
✅ Found 50 corrections
✅ Applied 50/50 corrections
```

### Example 2: NEW Workflow (Step 6 BEFORE Step 2)
```bash
$ python main.py
> 1. Extract text from PDFs (OCR)

# Run Step 1 first to get page_4.txt, page_5.txt, page_6.txt

> 6. Correction Processing

⚠️ Step 5 output not found.
   Running in STANDALONE mode

Enter page(s): 4,5,6

✅ Loaded 3 pages
✅ Found 50 corrections
✅ Correction map saved: correction_map.json

# Now run Step 2

> 2. Extract QCMs from text

✅ Found 50 pre-extracted corrections
✅ Will apply them after QCM extraction

[Extraction happens...]

✅ Applied 50 corrections automatically
```

---

## 📊 Summary of Changes

| File | Changes | Lines | Complexity |
|------|---------|-------|------------|
| `step6_corrections.py` | Fix model, add multi-page, standalone mode | ~100 | Medium |
| `step2_qcm_extract_batch.py` | Load correction map | ~30 | Low |

**Total Effort:** ~2 hours

**Benefits:**
- ✅ Fixes 404 error
- ✅ Supports multiple correction pages (4,5,6)
- ✅ Allows Step 6 before Step 2
- ✅ More flexible workflow
- ✅ Better user experience

---

## 🚀 Implementation Order

1. **Phase 1** (5 min): Fix model error → Test immediately
2. **Phase 2** (30 min): Add multi-page support → Test with 4,5,6
3. **Phase 3** (20 min): Add standalone mode → Test full workflow

**Total Time:** ~1 hour

Ready to implement? 🎯
