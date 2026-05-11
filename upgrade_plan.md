# Plan Comparison: Vision-Only vs. Hybrid (OCR + DeepSeek Analysis)

## 1. Current System (Vision-Only)
- **Workflow**: 
  1. Sends image of page to Qwen-VL.
  2. Qwen-VL extracts QCMs + Guesses metadata simultaneously.
- **Pros**: Simple architecture (one model). Handles complex layouts/tables well.
- **Cons**: 
  - "Hallucinates" categories often.
  - Hard to enforce strict naming conventions (Bio/Chir tags vs Modules).
  - Can't effectively "ignore" QCS without processing them first.
  - Costly for simple metadata extraction.

## 2. Proposed System (Hybrid / Logic-First)
- **Workflow**:
  1. **OCR/Text Extraction**: Extract raw text from first/last pages (using `pypdfium2` or Vision-OCR).
  2. **Smart Analysis (DeepSeek-R1)**: Send text to `deepseek/deepseek-r1` to:
     - Deduce Source & Year.
     - Identify the **Module context** (e.g., "This is Cardiologie").
     - Classify broad domain (Bio/Chir/Med) for `tagSuggere`.
  3. **User Config**: Present these findings for confirmation.
  4. **Mapping**: Match detected Module to your `modules.json` list.
  5. **Extraction (Vision)**: Used ONLY for extracting questions, with strict rules injected:
     - "Ignore QCS type questions".
     - "Apply category: Cardiologie".
     - "Apply tag: Medecine".

## 3. Why the New Version is Better
1.  **Accuracy**: DeepSeek-R1 (Reasoning model) is far superior at classification logic than a Vision model.
2.  **Strict Typology**: We can enforce your `tagSuggere` (Bio/Chir/Med) vs `categoryName` (Module) rule programmatically.
3.  **Efficiency**: We set the rules *before* starting the expensive extraction batch.

---

# Implementation Plan (Refined)

### Step 1: Pre-Requisites
- **Module File**: Located at `suport/modules-bio-chir-med.json`.
- **Validation**: Ensure file exists and is readable (Verified).

### Step 2: Implement `DeepSeekClient` & `MetadataAnalyzer`
We need a logic-first analyzer before the expensive vision extraction.
1.  **OCR Text**: Use `pypdfium2` (already installed) to get raw text from sample pages.
2.  **DeepSeek Analysis**: Send text to `deepseek/deepseek-r1-distill-llama-70b` (or similar) with this prompt:
    > "Analyze this medical exam text. Identify:
    > 1. Source (University/Exam context)
    > 2. Year
    > 3. Specific Module (e.g., 'Cardiologie', 'Traumatologie')
    > 4. Domain Tag (Biologie, Chirurgie, or Medecine) based on the module."
3.  **Output**: Return this structured data to the terminal.

### Step 3: Interactive Configuration & Rule Injection
Update `user_configuration_dialog` in `main.py` to:
1.  **Present Findings**: Show what DeepSeek found (Source, Year, Module, Tag).
2.  **Confirm/Edit**: User accepts or overrides these values.
3.  **Inject Custom Rules**: Ask the user: *"Enter any specific guidance for the AI (e.g., 'Ignore QCS questions', 'Questions are in column 2', 'Header contains answers'):"*
    - This string is stored as `config['user_guidance']`.

### Step 4: Vision Extraction (The "Smart" Batch)
Update `extract_qcms_batch` to use the injected context:
1.  **Prompt Engineering**:
    - **System Prompt**: "You are a specialized QCM extractor. Your goal is to extract **ALL** questions (QCM and QCS) found on the page."
    - **Context Injection**: Include the `config['user_guidance']` directly in the prompt.
    - **Metadata Injection**: "Context: Module '{Module}', Source '{Source}'."
2.  **Page Processing**:
    - Process pages per batch.
    - Return structure must group results by page (already handled by current JSON struct, but explicitly enforced).

### Step 5: Finalization & Mapping
1.  **Map Category**:
    - Load `suport/modules-bio-chir-med.json`.
    - Match the confirmed "Module" to the correct `categoryName` key in the JSON.
    - Set `tagSuggere` based on the Domain (Bio/Chir/Med).
2.  **Formatting**:
    - Save clean JSON.
    - (QCS filtering is done at extraction level, so no post-filtering needed).
