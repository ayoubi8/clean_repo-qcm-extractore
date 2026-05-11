# QCM Extractor v3.0 - User Guide

## Overview
The new **Three-Stage Guided Pipeline** allows you to extract Medical QCMs with high accuracy and low cost.

### Key Features
1.  **Single OCR Pass**: We scan pages once and save the text. You never pay to scan the same page twice.
2.  **Granular Control**: You can Accept, Edit, or Ignore every piece of detected metadata.
3.  **Context-Aware**: You provide hints at each stage to guide the AI.

---

## Workflow Steps

### 🔍 STAGE 1: OCR Extraction
**Goal**: Convert PDF/Images to raw text files.
**When prompted for guidance**:
Describe the visual layout.
*   ✅ *"Questions are in two columns"*
*   ✅ *"Correct answers have a small arrow"*
*   ✅ *"Ignore header text"*

**Output**: Saved to `ocr_output/YYYYMMDD_HHMMSS/`

### 🧠 STAGE 2: Metadata Analysis
**Goal**: Identify Module, Year, and Source.
**Action**:
The AI will present its findings.
*   Press **[A]** to Accept correct values.
*   Press **[E]** to Edit incorrect values (e.g., change "Bio" to "Biologie").
*   Press **[I]** to Ignore fields (they will be null in the JSON).

### 📝 STAGE 3: QCM Parsing
**Goal**: Extract structured questions from the text.
**When prompted for guidance**:
Give extraction rules.
*   ✅ *"Ignore QCS (single choice) questions"*
*   ✅ *"Start extracting from Question 10"*
*   ✅ *"Corrections are at the end of the page"*

---

## Tips for Best Results

*   **Scanned Documents**: Always use the default OCR method.
*   **Complex Layouts**: Be specific in Stage 1 guidance ("Columns", "Tables").
*   **Saving Money**: If you crash or restart, the OCR text is saved! We will add a "Resume" feature soon.

## Troubleshooting

*   **"No JSON found"**: The AI failed to format the response. Try running again with clearer guidance.
*   **"API Key Missing"**: Check your `.env` file for `OPENROUTER_API_KEY` and `DEEPSEEK_API_KEY`.
