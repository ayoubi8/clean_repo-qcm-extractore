import json
from pathlib import Path
from tempfile import TemporaryDirectory

from modules.utils.output_naming import pdf_stem_for_context, result_xlsx_name


def test_result_names_include_count_and_pdf_stem():
    assert result_xlsx_name("qcms", 42, "exam_2026") == "42_qcms_exam_2026.xlsx"
    assert result_xlsx_name("corrections", 37, "exam_2026") == "37_corrections_exam_2026.xlsx"


def test_pdf_stem_uses_original_uploaded_filename():
    with TemporaryDirectory() as directory:
        base = Path(directory)
        (base / "project.json").write_text(
            json.dumps({"pdf_filename": "Medical Exam (June) 2026.pdf"}),
            encoding="utf-8",
        )
        context = type("Context", (), {"base_path": base})()

        assert pdf_stem_for_context(context) == "Medical_Exam_June_2026"


def test_pdf_stem_has_safe_fallback_for_old_projects():
    context = type("Context", (), {"base_path": Path("does-not-exist")})()

    assert pdf_stem_for_context(context) == "source"
