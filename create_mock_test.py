import os
import sys
sys.stdout.reconfigure(encoding='utf-8')

sample_text = """
Residanat 2016 - Biologie

10. Une thrombopénie périphérique peut être secondaire à :
A. Une splénomégalie
B. Une CIVD
C. Une aplasie médullaire
D. Un purpura thrombopénique immunologique
E. Toutes les réponses sont justes

11. La carence martiale se caractérise par :
A. Une anémie hypochrome microcytaire
B. Une élévation de la ferritine
C. Une augmentation de la capacité de fixation de la transferrine
D. Une diminution du fer sérique
E. Les réponses A, C et D sont justes
"""

output_dir = "output/step1_extraction/accepted"
os.makedirs(output_dir, exist_ok=True)
with open(os.path.join(output_dir, "page_1.txt"), "w", encoding="utf-8") as f:
    f.write(sample_text)

print("✅ Created mock page_1.txt for testing.")
