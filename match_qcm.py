import json
import os
import re
import sys
import unicodedata
import time
import multiprocessing
from multiprocessing import Pool, cpu_count, freeze_support

import numpy as np
import pandas as pd

try:
    from rapidfuzz import fuzz, process
    from tqdm import tqdm
except ImportError:
    print("Error: Missing libraries. Please run: pip install rapidfuzz tqdm")
    sys.exit(1)


# ---------------------- INPUT HELPERS ---------------------- #

def ask_paths_and_threshold():
    print("--- SMART QCM MATCHER (With ID Support) ---")
    print("Enter path to the MAIN Excel file (the Database):")
    main_path = input("> ").strip().strip('"').strip("'")

    print("\nEnter paths to the EXAM/TARGET Excel files (comma-separated):")
    print("(To scan the main file for duplicates, enter its path here again)")
    exams_str = input("> ").strip()
    exam_paths = [
        p.strip().strip('"').strip("'")
        for p in exams_str.split(",")
        if p.strip()
    ]

    print("\nEnter similarity threshold between 0 and 1 (default 0.88):")
    thr_str = input("> ").strip()
    if thr_str:
        try:
            threshold = float(thr_str)
        except ValueError:
            threshold = 0.88
    else:
        threshold = 0.88

    return main_path, exam_paths, threshold


def get_exam_year(exam_path):
    base = os.path.basename(exam_path)
    detected = None
    m = re.search(r"(20\d{2})", base)
    if m:
        detected = m.group(1)

    print(f"\nProcessing file: {base}")
    if detected:
        print(f"Detected year: {detected}")
    
    # Defaults to 2024 if not detected, to avoid blocking
    return int(detected) if detected else 2024


# ---------------------- TEXT PROCESSING ---------------------- #

def normalize_str(s):
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def build_question_text(row, option_cols):
    parts = []
    # Question text
    if "Text" in row:
        parts.append(normalize_str(row["Text"]))
    # Options
    for col in option_cols:
        if col in row:
            parts.append(normalize_str(row[col]))
    # Correct answer
    if "Correct" in row:
        parts.append(normalize_str(row["Correct"]))
    return " ".join(p for p in parts if p)


# ---------------------- DATA LOADING ---------------------- #

def load_dataframe(path):
    try:
        df = pd.read_excel(path)
    except Exception as exc:
        print(f"Error reading {path}: {exc}", file=sys.stderr)
        sys.exit(1)
    return df

def prepare_dataframe(df):
    possible_option_cols = ["A", "B", "C", "D", "E", "F", "F ", "G", "H"]
    option_cols = [c for c in df.columns if c in possible_option_cols]
    
    # Ensure we work on a copy
    df = df.copy()
    
    # Pre-calculate normalized text for speed
    norm_texts = [build_question_text(row, option_cols) for _, row in df.iterrows()]
    
    df["_norm_text"] = norm_texts
    df["_option_cols"] = [option_cols] * len(df)
    return df, norm_texts


# ---------------------- WORKER FUNCTION ---------------------- #

def match_chunk_worker(args):
    """
    args: (exam_indices, exam_texts_chunk, main_texts, threshold_pct, is_self_scan)
    """
    exam_indices, exam_texts_chunk, main_texts, threshold_pct, is_self_scan = args
    results = []
    
    for i, query_text in zip(exam_indices, exam_texts_chunk):
        if not query_text or len(query_text) < 5:
            results.append((i, []))
            continue
            
        # RapidFuzz extraction
        matches = process.extract(
            query_text, 
            main_texts, 
            scorer=fuzz.ratio, 
            score_cutoff=threshold_pct,
            limit=None 
        )
        
        clean_matches = []
        for m in matches:
            # m = (string, score, index)
            score = m[1]
            match_idx = m[2]
            
            # --- SELF-MATCH FILTER ---
            # If scanning file against itself, ignore when question matches itself
            if is_self_scan and match_idx == i:
                continue
            
            clean_matches.append((match_idx, score / 100.0))
        
        # Sort candidates by score descending
        clean_matches.sort(key=lambda x: x[1], reverse=True)
        results.append((i, clean_matches))
        
    return results


# ---------------------- UTILS ---------------------- #

def question_to_dict(row):
    # Added "ID" to the list of fields to extract
    fields = [
        "ID", "Num", "Text", 
        "A", "B", "C", "D", "E", "F", "F ", "G", "H", 
        "Correct", "tag", "Tag", "Year"
    ]
    data = {}
    for f in fields:
        if f in row:
            val = row[f]
            if not (isinstance(val, float) and np.isnan(val)):
                data[f] = val
    return data

def parse_tag_list(tag_value):
    if tag_value is None or (isinstance(tag_value, float) and np.isnan(tag_value)):
        return []
    if isinstance(tag_value, list):
        return tag_value
    s = str(tag_value).strip()
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            return parsed
        return [parsed]
    except Exception:
        return [s]

def format_tag_list(tags):
    return json.dumps(tags, ensure_ascii=False)

def update_main_row(main_df, main_idx, year, extra_tags=None):
    tag_col = "Tag" if "Tag" in main_df.columns else "tag" if "tag" in main_df.columns else None
    
    if tag_col:
        current_tags = parse_tag_list(main_df.at[main_idx, tag_col])
        new_tags = [t for t in current_tags if not (isinstance(t, str) and re.fullmatch(r"\d{4}", t))]
        
        year_str = str(year)
        if year_str not in new_tags:
            new_tags.append(year_str)
            
        if extra_tags:
            for t in extra_tags:
                if t not in new_tags:
                    new_tags.append(t)
        main_df.at[main_idx, tag_col] = format_tag_list(new_tags)
        
    if "Year" in main_df.columns:
        main_df.at[main_idx, "Year"] = int(year)


# ---------------------- MAIN ---------------------- #

def main():
    freeze_support()
    main_path, exam_paths, threshold = ask_paths_and_threshold()
    
    if not os.path.exists(main_path):
        print("Main file not found.")
        sys.exit(1)

    # 1. Load Main DB
    print(f"\nLoading Main Database: {main_path}")
    main_df = load_dataframe(main_path)
    
    # Ensure Tag cols are objects
    for c in ["Tag", "tag"]:
        if c in main_df.columns:
            main_df[c] = main_df[c].astype("object")

    main_df, main_norm_texts = prepare_dataframe(main_df)

    all_match_records = []
    
    # 2. Process Files
    for exam_path in exam_paths:
        if not os.path.exists(exam_path):
            continue

        exam_year = get_exam_year(exam_path)
        exam_df = load_dataframe(exam_path)
        exam_df, exam_norm_texts = prepare_dataframe(exam_df)

        if len(exam_df) == 0:
            continue

        # Check self-scan
        is_self_scan = (os.path.abspath(main_path) == os.path.abspath(exam_path))
        if is_self_scan:
            print(f"--> Detected Self-Scan. Excluding identical row matches (ID x vs ID x).")

        # 3. Multiprocessing
        n_workers = cpu_count()
        chunk_size = max(1, len(exam_df) // n_workers)
        
        indices = list(range(len(exam_df)))
        chunks = []
        for i in range(0, len(exam_df), chunk_size):
            idx_chunk = indices[i : i + chunk_size]
            txt_chunk = exam_norm_texts[i : i + chunk_size]
            # Passing is_self_scan to the worker
            chunks.append((idx_chunk, txt_chunk, main_norm_texts, threshold * 100, is_self_scan))

        print(f"Matching using {n_workers} cores...")
        
        exam_matches = []
        with Pool(processes=n_workers) as pool:
            results_iter = pool.imap_unordered(match_chunk_worker, chunks)
            for res_chunk in tqdm(results_iter, total=len(chunks), unit="chunk"):
                exam_matches.extend(res_chunk)

        # 4. Process Results & Build JSON
        exam_matches.sort(key=lambda x: x[0]) 
        
        for exam_idx, candidates in exam_matches:
            # Skip if no valid candidates found (e.g. only self-match was found and removed)
            if not candidates:
                continue

            exam_q_dict = question_to_dict(exam_df.iloc[exam_idx])
            
            detailed_candidates = []
            for main_idx, score in candidates:
                detailed_candidates.append({
                    "main_index": int(main_idx),
                    "similarity": float(score),
                    "main_question": question_to_dict(main_df.iloc[main_idx])
                })
            
            all_match_records.append({
                "exam_file": os.path.basename(exam_path),
                "exam_index": int(exam_idx),
                "exam_year": exam_year,
                "exam_question": exam_q_dict,
                "candidates": detailed_candidates
            })

    # 5. Export
    base_main = os.path.splitext(main_path)[0]
    
    # Sort matches by highest similarity
    all_match_records.sort(
        key=lambda r: r["candidates"][0]["similarity"] if r.get("candidates") else 0, 
        reverse=True
    )

    matches_json_path = base_main + "_matches.json"
    with open(matches_json_path, "w", encoding="utf-8") as f:
        json.dump(all_match_records, f, ensure_ascii=False, indent=2, default=str)

    print(f"\nTotal questions with valid candidates: {len(all_match_records)}")
    print(f"Results saved to: {matches_json_path}")

    # 6. Optional Update
    if not all_match_records:
        return

    print("\nDo you want to apply updates (merge tags/years)?")
    ans = input("Apply updates? [y/n]: ").strip().lower()
    if ans in ("y", "yes"):
        count = 0
        for r in all_match_records:
            # Update logic: updates the best match
            best = r["candidates"][0]
            update_main_row(main_df, best["main_index"], r["exam_year"])
            count += 1
            
        out_path = base_main + "_UPDATED.xlsx"
        final_df = main_df.drop(columns=["_norm_text", "_option_cols"], errors="ignore")
        final_df.to_excel(out_path, index=False)
        print(f"Updated {count} rows. Saved to {out_path}")

if __name__ == "__main__":
    main()