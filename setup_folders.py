import os
import sys

# Force UTF-8 execution for Windows
sys.stdout.reconfigure(encoding='utf-8')

folders = [
    "output/step1_extraction/accepted",
    "output/step1_extraction/rejected",
    "output/step2_qcm/accepted",
    "output/step2_qcm/rejected",
    "output/step3_metadata/accepted",
    "output/step3_metadata/rejected",
    "output/step4_format/templates",
    "output/step5_json",
    "output/step6_corrections",
    "output/step7_categories",
    "modules/utils"
]

for folder in folders:
    os.makedirs(folder, exist_ok=True)
    print(f"✓ Created {folder}")

print("\n✅ Folder structure ready")
