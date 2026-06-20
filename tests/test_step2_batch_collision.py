import os
import sys
import json
import shutil
from pathlib import Path

# Adjust path to import from modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force UTF-8 execution for Windows
sys.stdout.reconfigure(encoding='utf-8')

from modules.step2_qcm_extract_batch import Step2QCMExtractBatch
from modules.utils.cost_tracker import CostTracker

class MockContext:
    def __init__(self, temp_dir: Path):
        self.temp_dir = temp_dir
    def get_path(self, step, status=None):
        p = self.temp_dir / step
        if status:
            p = p / status
        p.mkdir(parents=True, exist_ok=True)
        return p

def test_assign_uids():
    print("Testing _assign_uids...")
    tracker = CostTracker()
    extractor = Step2QCMExtractBatch(tracker)
    
    qcms = [
        {"page": 3, "number": 1, "text": "Q1"},
        {"page": 3, "number": 1, "text": "Q2"},
        {"page": 3, "number": 2, "text": "Q3"}
    ]
    
    res = extractor._assign_uids(qcms)
    assert len(res) == 3
    assert res[0]["uid"] == "3_1_0"
    assert res[1]["uid"] == "3_1_1"
    assert res[2]["uid"] == "3_2_2"
    print("✅ _assign_uids matches expectations.")

def test_save_results_and_migration():
    print("Testing _save_batch_results_accumulate...")
    tracker = CostTracker()
    temp_dir = Path("output/test_step2_batch_temp")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)
    
    context = MockContext(temp_dir)
    extractor = Step2QCMExtractBatch(tracker, project_context=context)
    
    # 1. Save some legacy QCMs (without uids) first to simulate legacy migration
    legacy_file = temp_dir / "step2_qcm/accepted/all_qcms.json"
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    legacy_data = [
        {"page": 1, "number": 1, "text": "Legacy Q1 (page 1, Q1)"},
        {"page": 1, "number": 2, "text": "Legacy Q2 (page 1, Q2)"}
    ]
    with open(legacy_file, "w", encoding="utf-8") as f:
        json.dump(legacy_data, f, indent=2)
        
    # 2. Run save results with duplicates from a two-half page (page 2)
    new_qcms = [
        {"page": 2, "number": 1, "text": "Page 2 Left Q1"},
        {"page": 2, "number": 1, "text": "Page 2 Right Q1"}, # collision on (page, number)
        {"page": 2, "number": 2, "text": "Page 2 Q2"}
    ]
    
    extractor._save_batch_results_accumulate(new_qcms)
    
    # Read output
    with open(legacy_file, "r", encoding="utf-8") as f:
        saved = json.load(f)
        
    print(f"Saved total QCMs count: {len(saved)}")
    # Verify legacy QCMs got migrated with legacy uids and not overwritten
    legacy_uids = [q.get("uid") for q in saved if "legacy" in q.get("uid", "")]
    assert len(legacy_uids) == 2, f"Expected 2 legacy uids, got {legacy_uids}"
    
    # Verify both Page 2 Q1s are kept
    p2_q1s = [q for q in saved if q["page"] == 2 and q["number"] == 1]
    assert len(p2_q1s) == 2, f"Expected 2 QCMs for page 2 number 1, got {len(p2_q1s)}"
    assert p2_q1s[0]["uid"] == "2_1_0"
    assert p2_q1s[1]["uid"] == "2_1_1"
    
    print("✅ _save_batch_results_accumulate and legacy migration matches expectations.")
    shutil.rmtree(temp_dir)

def test_parse_json_truncation():
    print("Testing truncation-safe _parse_json...")
    tracker = CostTracker()
    extractor = Step2QCMExtractBatch(tracker)
    
    # Normal JSON
    normal_json = """
    [
        {"page": 1, "number": 1, "text": "Normal Q1"},
        {"page": 1, "number": 2, "text": "Normal Q2"}
    ]
    """
    res = extractor._parse_json(normal_json)
    assert len(res) == 2
    assert res[0]["text"] == "Normal Q1"
    
    # Truncated JSON - missing closing bracket and truncated last object
    truncated_json = """
    [
        {"page": 1, "number": 1, "text": "Normal Q1"},
        {"page": 1, "number": 2, "text": "Normal Q2"},
        {"page": 1, "number": 3, "text": "Trunc
    """
    res = extractor._parse_json(truncated_json)
    assert len(res) == 2
    assert res[0]["text"] == "Normal Q1"
    assert res[1]["text"] == "Normal Q2"
    
    # Extremely truncated (only raw text)
    bad_json = """
    This is not json at all.
    """
    res = extractor._parse_json(bad_json)
    assert len(res) == 0
    print("✅ _parse_json recovery testing matches expectations.")

if __name__ == "__main__":
    test_assign_uids()
    test_save_results_and_migration()
    test_parse_json_truncation()
    print("\n🎉 ALL TESTS PASSED!")
