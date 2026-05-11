# QCM Extractor - Quick User Guide

## Starting the Script

```powershell
python main.py
```

## Workflow Steps

### 1. Create New Project
```
Choice [N/R/X]: N
Enter PDF path: C:\path\to\your\file.pdf
```

### 2. Step 1: Text Extraction
```
Select Step [1-7, A, S, X]: 1
Choice [1-2]: 2  (Vision OCR for scanned PDFs)
Your guidance: [Press Enter or add custom instructions]
```

### 3. Step 2: QCM Extraction
```
Select Step [1-7, A, S, X]: 2
Your guidance: [Press Enter for default]
```

**For each page:**
- `A` = Accept and save
- `S` = Skip this page
- `R` = Retry with new guidance
- `V` = View all QCMs

**After all pages:**
- `C` = Continue to next step
- `R` = Re-extract specific pages (e.g., "3,5,7")

### 4. Step 3: Metadata Detection
```
Select Step [1-7, A, S, X]: 3
```

**Configure fields:**
- Press `1`, `2`, `3`, or `4` to toggle mode
- `G` = Global (one value for all QCMs)
- `P` = Per-QCM (detect from each question)
- `S` = Skip (don't include)
- Press `Enter` to confirm

**Review extracted metadata:**
- `Y` = Edit values
- `N` = Accept as-is

### 5. Step 4: Template Selection
```
Select Step [1-7, A, S, X]: 4
Select template: 6  (Create new)
```

**Toggle fields:**
- Press number to toggle field on/off
- `A` = Select all
- `N` = Select none
- `Enter` = Confirm

Enter template name when prompted.

### 6. Step 5: JSON Building
```
Select Step [1-7, A, S, X]: 5
```
(Automatic - no input needed)

### 7. Step 6: Add Corrections
```
Select Step [1-7, A, S, X]: 6
Choice [1-5]: 2  (Extract from page)
Enter page number: 3
```

**Correction sources:**
1. AI Knowledge (DeepSeek solves)
2. Specific Page (extract from correction page)
3. Extracted Data (auto-detect)
4. Vision AI (detect highlights)
5. Manual Entry

**Tip:** Run Step 6 multiple times for multiple correction pages.

### 8. Step 7: Categorization (Optional)
```
Select Step [1-7, A, S, X]: 7
```
Uses AI to categorize QCMs by medical module.

## Output Location

Final JSON: `output/<project-name>/step6_corrections/corrected_qcms.json`

## Tips

- **Skip pages in Step 2:** Add "skip page 1, 11" in guidance
- **Re-extract bad pages:** Use `R` option after extraction summary
- **Multiple correction pages:** Run Step 6 multiple times
- **Resume later:** Choose `R` at startup, select your project

## Common Issues

**Problem:** OCR fails  
**Solution:** Use Vision OCR (option 2) instead of pypdfium2

**Problem:** Wrong QCM numbers  
**Solution:** Skip and re-extract that page in Step 2

**Problem:** Missing corrections  
**Solution:** Run Step 6 again with different page number

## Keyboard Shortcuts

- `Ctrl+C` = Exit script
- `Enter` = Use default/skip
- `X` = Exit to main menu
