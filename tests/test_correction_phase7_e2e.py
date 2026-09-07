import json
import io
from contextlib import redirect_stdout
from pathlib import Path

from modules.step6_corrections import Step6Corrections


CORPUS_DIR = Path(__file__).parent / "fixtures" / "correction_pages"


def _load_manifest():
    with (CORPUS_DIR / "manifest.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def _deterministic_map(text: str, parser: Step6Corrections):
    with redirect_stdout(io.StringIO()):
        return parser._extract_single_page_corrections(
            text,
            page_num=1,
            deterministic_only=True,
        )


def test_phase7_deterministic_pipeline_covers_every_fixture_case():
    parser = Step6Corrections.__new__(Step6Corrections)

    for case in _load_manifest()["cases"]:
        filenames = case.get("files") or [case["file"]]
        combined = "\n".join(
            (CORPUS_DIR / filename).read_text(encoding="utf-8")
            for filename in filenames
        )
        result = _deterministic_map(combined, parser)

        for question, answer in case["expected_map"].items():
            assert result.get(question) == answer, case["name"]


def test_phase7_normal_question_page_does_not_create_corrections():
    parser = Step6Corrections.__new__(Step6Corrections)
    normal_page = """
    QUESTION 1. Quel est le diagnostic ?
    A. Premiere proposition
    B. Deuxieme proposition
    C. Troisieme proposition
    """

    assert _deterministic_map(normal_page, parser) == {}


def test_phase7_public_contract_remains_flat_question_map():
    parser = Step6Corrections.__new__(Step6Corrections)
    text = (CORPUS_DIR / "visual_multi_column.txt").read_text(encoding="utf-8")

    result = _deterministic_map(text, parser)

    assert result == {"1": "BCD", "26": "ACD", "51": "BD"}
    assert all(isinstance(key, str) for key in result)
    assert all(isinstance(value, str) for value in result.values())
