# -*- coding: utf-8 -*-
"""
find_excel_files.py
-------------------
Searches all drives on this Windows PC for Excel files (.xls, .xlsx, .xlsm, .xlsb, .xltx, .xltm)
and saves their full paths to a text file named 'excel_files_found.txt'.
"""

import os
import string
import datetime
import ctypes

# ── Configuration ──────────────────────────────────────────────────────────────
OUTPUT_FILE = "excel_files_found.txt"

EXCEL_EXTENSIONS = {
    ".xls", ".xlsx", ".xlsm", ".xlsb",
    ".xltx", ".xltm", ".xlam",
}

# Directories to skip (system folders that are slow / permission-denied noise)
SKIP_DIRS = {
    "Windows", "System32", "SysWOW64", "$Recycle.Bin", "$RECYCLE.BIN",
    "System Volume Information", "Boot", "Recovery",
    "ProgramData\\Microsoft\\Windows Defender",
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def get_available_drives():
    """Return a list of available drive letters on Windows (e.g. ['C:\\', 'D:\\'])."""
    drives = []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for letter in string.ascii_uppercase:
        if bitmask & 1:
            drives.append(f"{letter}:\\")
        bitmask >>= 1
    return drives


def should_skip(dirpath: str) -> bool:
    """Return True if the directory should be skipped."""
    parts = dirpath.replace("/", "\\").split("\\")
    for part in parts:
        if part in SKIP_DIRS:
            return True
    return False


def search_excel_files(roots: list[str]) -> list[str]:
    """Walk all root paths and collect every Excel file path found."""
    found = []
    scanned = 0

    for root in roots:
        if not os.path.exists(root):
            continue
        print(f"  [SCAN]  Scanning drive  {root} ...")

        for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=None):

            # Prune directories we want to skip (modifying dirnames in-place)
            dirnames[:] = [
                d for d in dirnames
                if not should_skip(os.path.join(dirpath, d))
            ]

            for filename in filenames:
                _, ext = os.path.splitext(filename)
                if ext.lower() in EXCEL_EXTENSIONS:
                    full_path = os.path.join(dirpath, filename)
                    found.append(full_path)
                    print(f"     [FOUND]  {full_path}")

            scanned += 1
            if scanned % 5000 == 0:
                print(f"     ... {scanned:,} folders scanned so far, {len(found)} Excel files found ...")

    return found


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    start = datetime.datetime.now()
    print("=" * 70)
    print("  Excel File Finder")
    print(f"  Started at: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    drives = get_available_drives()
    print(f"\n  Drives detected: {', '.join(drives)}\n")

    excel_files = search_excel_files(drives)

    end = datetime.datetime.now()
    elapsed = (end - start).total_seconds()

    # ── Write output ──────────────────────────────────────────────────────────
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"Excel File Search Report\n")
        f.write(f"Generated : {end.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Duration  : {elapsed:.1f} seconds\n")
        f.write(f"Total     : {len(excel_files)} file(s) found\n")
        f.write(f"Drives    : {', '.join(drives)}\n")
        f.write("=" * 70 + "\n\n")

        for i, path in enumerate(excel_files, 1):
            f.write(f"{i:>5}.  {path}\n")

    print("\n" + "=" * 70)
    print(f"  [DONE]  {len(excel_files)} Excel file(s) found in {elapsed:.1f}s")
    print(f"  [FILE]  Results saved to: {os.path.abspath(OUTPUT_FILE)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
