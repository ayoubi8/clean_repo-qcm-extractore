import json
from pathlib import Path

from modules.step1_extraction import Step1Extraction
from modules.step6_corrections import Step6Corrections


CORPUS_DIR = Path(__file__).parent / "fixtures" / "correction_pages"
MANIFEST_PATH = CORPUS_DIR / "manifest.json"


def load_manifest():
    with MANIFEST_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def test_phase_one_manifest_has_all_fixture_files():
    manifest = load_manifest()

    assert manifest["version"] == 1
    assert len(manifest["cases"]) == 6

    for case in manifest["cases"]:
        filenames = case.get("files") or [case["file"]]
        for filename in filenames:
            fixture = CORPUS_DIR / filename
            assert fixture.is_file(), f"Missing fixture: {fixture}"
            assert fixture.read_text(encoding="utf-8").strip()


def test_phase_one_expected_maps_use_the_public_contract():
    manifest = load_manifest()

    for case in manifest["cases"]:
        expected_map = case["expected_map"]
        assert expected_map
        for question, answer in expected_map.items():
            assert question.isdigit()
            assert answer
            assert set(answer) <= set("ABCDE")


def test_phase_one_corpus_contains_required_failure_modes():
    manifest = load_manifest()
    formats = {case["format"] for case in manifest["cases"]}

    assert {
        "conventional_table",
        "visual_blocks",
        "mixed",
        "split_blocks",
        "degraded_visual_blocks",
        "conflict",
    } <= formats

    visual_text = (CORPUS_DIR / "visual_multi_column.txt").read_text(
        encoding="utf-8"
    )
    assert all(f"QCM {number}:" in visual_text for number in (1, 26, 51))
    assert all(label in visual_text for label in ("R:", "T:", "SCORE:"))

    conflict_case = next(
        case for case in manifest["cases"] if case["format"] == "conflict"
    )
    assert conflict_case["expected_conflicts"] == ["20"]


def test_step_one_prompt_preserves_visual_correction_blocks():
    prompt = Step1Extraction._build_vision_prompt("Keep the page number.")

    assert "multiple independent QCM blocks" in prompt
    assert "question number" in prompt.lower()
    assert "R:" in prompt
    assert "T:" in prompt
    assert "SCORE" in prompt
    assert "do not solve" in prompt.lower()


def test_step_six_extracts_t_values_from_multiple_visual_blocks():
    text = (CORPUS_DIR / "visual_multi_column.txt").read_text(encoding="utf-8")
    parser = Step6Corrections.__new__(Step6Corrections)

    result = parser._parse_visual_correction_blocks(text)

    assert result == {"1": "BCD", "26": "ACD", "51": "BD"}


def test_step_six_prefers_t_over_conflicting_grid_and_r():
    text = (CORPUS_DIR / "conflicting_evidence.txt").read_text(encoding="utf-8")
    parser = Step6Corrections.__new__(Step6Corrections)

    result = parser._parse_visual_correction_blocks(text)

    assert result == {"20": "BD"}


def test_step_six_accepts_common_ocr_variants_for_t_and_r():
    text = (CORPUS_DIR / "ocr_corruption_and_rotation.txt").read_text(
        encoding="utf-8"
    )
    parser = Step6Corrections.__new__(Step6Corrections)

    result = parser._parse_visual_correction_blocks(text)

    assert result == {"8": "AC", "18": "DE"}


def test_step_six_ai_prompt_teaches_correction_document_grammar():
    prompt = Step6Corrections._build_correction_prompt(
        "QCM 1: R: A T: B SCORE: 1.00", page_num=4
    )

    assert "multiple qcm blocks" in prompt.lower()
    assert "T:" in prompt
    assert "R:" in prompt
    assert "strong answer-key evidence" in prompt
    assert "one physical ocr line" in prompt.lower()
    assert "only valid json" in prompt.lower()


def test_step_six_rejects_malformed_answer_values_instead_of_cleaning_them():
    parser = Step6Corrections.__new__(Step6Corrections)

    result = parser._normalise_correction_map(
        {"1": "BCD", "2": "answer B", "3": "B,C", "bad": "A"}
    )

    assert result == {"1": "BCD"}


def test_step_six_detects_partial_results_from_visual_signals():
    text = (CORPUS_DIR / "visual_multi_column.txt").read_text(encoding="utf-8")
    parser = Step6Corrections.__new__(Step6Corrections)

    assert parser._correction_result_is_suspicious(text, {"1": "BCD"})
    assert not parser._correction_result_is_suspicious(
        text, {"1": "BCD", "26": "ACD", "51": "BD"}
    )
