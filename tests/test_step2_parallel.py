"""Parallel Step 2 (STEP2_PARALLEL>1): chunks are extracted concurrently and
finish out of order, but numbering repair + saving happen in page order, and
numbers the model could not see are filled deterministically (never guessed)."""
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.step2_qcm_extract_batch import Step2QCMExtractBatch  # noqa: E402


class _Tracker:
    def log_api_call(self, *a, **k):
        pass


PAGES = {  # page -> (delay seconds, QCMs the model returns)
    1: (0.30, [{"number": 1, "text": "Q1"}, {"number": 2, "text": "Q2"}]),
    2: (0.05, [{"number": None, "text": "Q3 (number cropped)"}, {"number": 4, "text": "Q4"}]),
    3: (0.15, [{"number": 5, "text": "Q5"}]),
    4: (0.01, [{"number": "6", "text": "Q6"}]),
}


class _Client:
    def __init__(self):
        self.prompts = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def generate_completion(self, prompt, model, max_tokens):
        page = int(prompt.split("=== PAGE ")[1].split(" ===")[0])
        with self.lock:
            self.prompts.append(prompt)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(PAGES[page][0])
        with self.lock:
            self.active -= 1
        rows = [dict(q, page=page, propositions={k: k for k in "abcde"}) for q in PAGES[page][1]]
        return {"content": json.dumps(rows), "usage": {}, "cost": 0.0, "finish_reason": "stop"}

    @staticmethod
    def estimate_cost(model, usage):
        return 0.0


def test_parallel_loop_saves_in_page_order_and_fills_numbers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STEP2_PARALLEL", "4")
    monkeypatch.setenv("STEP2_MODEL", "p/model")
    monkeypatch.setenv("STEP2_FALLBACK_MODEL", "f/model")
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    files = []
    for n in PAGES:
        f = pages_dir / f"page_{n}.txt"
        f.write_text(f"text of page {n}", encoding="utf-8")
        files.append(f)

    ex = Step2QCMExtractBatch.__new__(Step2QCMExtractBatch)
    ex.client, ex.cost_tracker, ex.context = _Client(), _Tracker(), None
    ex._step2_primary_fail_streak = 0
    saved_batches = []
    monkeypatch.setattr(ex, "_save_batch_results_accumulate", lambda q: saved_batches.append(list(q)))

    t0 = time.time()
    total = ex._run_loop_mode(files, 1, {}, {}, None)
    elapsed = time.time() - t0

    assert total == 6
    assert ex.client.max_active >= 2                      # really ran concurrently
    assert elapsed < sum(d for d, _ in PAGES.values())    # faster than serial
    # Saved strictly in page order even though page 1 finished last.
    assert [b[0]["page"] for b in saved_batches] == [1, 2, 3, 4]
    numbers = [q["number"] for b in saved_batches for q in b]
    assert numbers == [1, 2, 3, 4, 5, 6]                  # cropped Q3 filled, "6" normalised
    # Parallel prompts ask for null instead of a guessed number.
    assert all('"number": null' in p for p in ex.client.prompts)
    assert not any("PREVIOUS PAGE QCM NUMBERS" in p for p in ex.client.prompts)


def test_fill_missing_numbers_continues_from_previous_chunk():
    qcms = [{"number": None}, {"number": 0}, {"number": 12}, {"number": None}]
    out = Step2QCMExtractBatch._fill_missing_numbers(qcms, [7, 8, 9])
    assert [q["number"] for q in out] == [10, 11, 12, 13]


def test_sequential_mode_is_unchanged_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("STEP2_PARALLEL", raising=False)
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    files = []
    for n in (1, 2):
        f = pages_dir / f"page_{n}.txt"
        f.write_text(f"text of page {n}", encoding="utf-8")
        files.append(f)
    ex = Step2QCMExtractBatch.__new__(Step2QCMExtractBatch)
    ex.client, ex.cost_tracker, ex.context = _Client(), _Tracker(), None
    ex._step2_primary_fail_streak = 0
    monkeypatch.setattr(ex, "_save_batch_results_accumulate", lambda q: None)
    ex._run_loop_mode(files, 1, {}, {}, None)
    assert ex.client.max_active == 1
    assert "PREVIOUS PAGE QCM NUMBERS" in ex.client.prompts[1]   # page 2 still gets page 1's numbers
