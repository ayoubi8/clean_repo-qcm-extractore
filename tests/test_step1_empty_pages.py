"""0 KB Step 1 pages: empty OCR is a failure, blank pages are recognised, later
steps cannot erase text, and a repair OCRs only the pages that need it."""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

import modules.step1_extraction as s1  # noqa: E402
from modules.step1_5_batch_text_fixer import Step1_5BatchTextFixer  # noqa: E402
from modules.step1_6_intelligent_text_fixer import Step1_6IntelligentTextFixer  # noqa: E402
from modules.utils.cost_tracker import CostTracker  # noqa: E402
from modules.utils.page_text import BLANK_PAGE_MARKER, is_safe_rewrite, page_ink_ratio  # noqa: E402
from modules.utils.project_context import ProjectContext  # noqa: E402


def text_page():
    img = Image.new("RGB", (800, 1100), "white")
    draw = ImageDraw.Draw(img)
    for y in range(60, 1040, 28):
        draw.rectangle((60, y, 740, y + 9), fill="black")
    return img


def blank_page():
    return Image.new("RGB", (800, 1100), "white")


class FakeClient:
    replies = []
    calls = []

    def generate_completion(self, prompt, images=None, model=None, max_tokens=0, **kw):
        FakeClient.calls.append(model)
        reply = FakeClient.replies.pop(0) if FakeClient.replies else "page text"
        return {"content": reply, "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                "cost": 0.001, "finish_reason": "stop"}

    def estimate_cost(self, model, usage):
        return 0.0


@pytest.fixture
def step(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(s1, "OpenRouterClient", FakeClient)
    monkeypatch.setattr(s1, "get_model_pair", lambda _: ("primary", "fallback"))
    FakeClient.replies, FakeClient.calls = [], []
    ctx = ProjectContext("u1/p")
    ctx.base_path = tmp_path / "output" / "u1" / "p"
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"%PDF fake")
    extraction = s1.Step1Extraction(CostTracker(), ctx)
    extraction.pdf = str(pdf)
    extraction.dir = ctx.get_path("step1_extraction", "accepted")
    return extraction


def test_empty_reply_uses_fallback(step):
    FakeClient.replies = ["", "recovered"]
    step._extract_with_vision(step.pdf, [text_page()], "guide")
    assert FakeClient.calls == ["primary", "fallback"]
    assert (step.dir / "page_1.txt").read_text(encoding="utf-8") == "recovered"


def test_page_still_empty_holds_the_pdf_and_leaves_no_0kb_file(step):
    (step.dir / "page_2.txt").write_text("", encoding="utf-8")
    FakeClient.replies = ["good"] + [""] * 4
    with pytest.raises(RuntimeError, match="1 of 2 page.*failed OCR: 2"):
        step._extract_with_vision(step.pdf, [text_page(), text_page()], "guide")
    assert not (step.dir / "page_2.txt").exists()
    manifest = json.loads((step.dir.parent / "_page_manifest.json").read_text(encoding="utf-8"))
    assert manifest["missing_pages"] == [2]


def test_blank_page_gets_marker_without_ai_call(step):
    result = step._extract_with_vision(step.pdf, [blank_page()], "guide")
    assert FakeClient.calls == []
    assert result["blank_pages"] == [1]
    assert (step.dir / "page_1.txt").read_text(encoding="utf-8") == BLANK_PAGE_MARKER


def test_a_short_line_of_text_is_not_blank():
    img = blank_page()
    ImageDraw.Draw(img).rectangle((60, 500, 500, 508), fill="black")
    assert page_ink_ratio(img) > 0.0005


def test_repair_ocrs_only_the_empty_page(step):
    (step.dir / "page_1.txt").write_text("already fixed", encoding="utf-8")
    (step.dir / "page_2.txt").write_text("", encoding="utf-8")
    FakeClient.replies = ["new text"]
    step._extract_with_vision(step.pdf, [text_page(), text_page()], "guide", repair_missing=True)
    assert len(FakeClient.calls) == 1
    assert (step.dir / "page_1.txt").read_text(encoding="utf-8") == "already fixed"
    assert (step.dir / "page_2.txt").read_text(encoding="utf-8") == "new text"
    manifest = json.loads((step.dir.parent / "_page_manifest.json").read_text(encoding="utf-8"))
    assert manifest["recovered_pages"] == [2] and manifest["repair"] is True


@pytest.mark.parametrize("old,new,safe", [("x" * 100, "", False), ("x" * 100, "  ", False),
                                          ("x" * 100, "x" * 40, False), ("x" * 100, "x" * 90, True)])
def test_safe_rewrite(old, new, safe):
    assert is_safe_rewrite(old, new) is safe


@pytest.mark.parametrize("reply,finish", [("", "stop"), ("short", "stop"), ("x" * 200, "length")])
def test_step1_6_keeps_page_on_bad_reply(tmp_path, reply, finish):
    page = tmp_path / "page_1.txt"
    page.write_text("x" * 200, encoding="utf-8")
    fixer = Step1_6IntelligentTextFixer.__new__(Step1_6IntelligentTextFixer)
    fixer.cost_tracker = None
    fixer.client = type("C", (), {"generate_completion": lambda self, *a, **k: {
        "content": reply, "usage": {}, "cost": 0.0, "finish_reason": finish}})()
    assert fixer._fix_text_file(page, "m", "f", 100, "") is False
    assert page.read_text(encoding="utf-8") == "x" * 200


def test_step1_5_keeps_page_on_empty_fix_and_sends_full_page(tmp_path):
    page = tmp_path / "page_1.txt"
    page.write_text("y" * 3000, encoding="utf-8")
    other = tmp_path / "page_2.txt"
    other.write_text("z" * 3000, encoding="utf-8")
    fixer = Step1_5BatchTextFixer.__new__(Step1_5BatchTextFixer)
    fixer.fix_log = []
    assert "y" * 3000 in fixer._build_batch_prompt([(1, 2)], [page, other])
    assert fixer._apply_fixes({1: "", 2: "z" * 2900}, [page, other]) == 1
    assert page.read_text(encoding="utf-8") == "y" * 3000


def test_batch_detects_empty_page_and_reenters_step1(tmp_path, monkeypatch):
    import autorun_batch as ab
    monkeypatch.setattr(ab, "_pdir", lambda uid, name: tmp_path / name)
    pages = tmp_path / "p" / "step1_extraction" / "accepted"
    pages.mkdir(parents=True)
    (pages / "page_1.txt").write_text("text", encoding="utf-8")
    (pages / "page_2.txt").write_text("", encoding="utf-8")
    (pages / "page_3.txt").write_text(BLANK_PAGE_MARKER, encoding="utf-8")
    assert ab.step1_empty_pages("u", "p") == [2]
    assert ab.first_not_done_step("u", "p") == "1"


def test_repair_without_new_text_skips_paid_steps(tmp_path, monkeypatch):
    import autorun_batch as ab
    monkeypatch.setattr(ab, "_pdir", lambda uid, name: tmp_path / name)
    monkeypatch.setattr(ab, "first_not_done_step", lambda uid, name: "6")
    monkeypatch.setattr(ab, "_drop_step_cache", lambda uid, names: None)
    manifest = tmp_path / "p" / "step1_extraction" / "_page_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"repair": True, "recovered_pages": []}), encoding="utf-8")
    assert ab._step_after_repair("u", "p") == "6"
    manifest.write_text(json.dumps({"repair": True, "recovered_pages": [2]}), encoding="utf-8")
    assert ab._step_after_repair("u", "p") is None
