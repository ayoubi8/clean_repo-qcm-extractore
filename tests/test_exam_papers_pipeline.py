"""Exam papers through the real pipeline code paths (no network).

Step 1 prompt · Step 2 run() on a fake compilation + a fake normal exam ·
Step 3 finalisation + CC chain · Step 4/5 template mapping (no placeholder
leak) · Step 6 scoped corrections · review xlsx columns.
Plan: docs/plans/exam-papers-sections-numbering-plan.md (phases 0-4).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.step1_extraction import Step1Extraction  # noqa: E402
from modules.step2_qcm_extract_batch import Step2QCMExtractBatch  # noqa: E402
from modules.step3_metadata import Step3Metadata  # noqa: E402
from modules.step5_builder import Step5Builder  # noqa: E402
from modules.step6_corrections import Step6Corrections  # noqa: E402
from modules.post_step3_build import DEFAULT_TEMPLATE_XLSX  # noqa: E402
from modules.utils.xlsx_exporter import export_qcms_to_xlsx  # noqa: E402


class _Tracker:
    def log_api_call(self, *a, **k):
        pass


def _props(e="e"):
    return {"a": "a", "b": "b", "c": "c", "d": "d", "e": e}


# Compilation pages exactly like `gyneco QCM classé 2025.pdf` (pages 204/208/209/212)
COMP_PAGES = {
    1: ("• Question N° 07, Sec 01 de l'année 2021-2022\n"
        "4- Les signes cliniques de la pré-rupture utérine\na. a\nb. b\nc. c\nd. d\ne. e\n"
        "• . Question N> 02, Participratique, Sec 01 de l'année 20.17-2018\n"
        "2- On parle d'hypocinésie\na. a\nb. b\nc. c\nd. d\ne. e"),
    2: ("• Question N° 07, Partie pratique, Sec 01 de l'ann\" 2021-2022\n"
        "7- Une hypertonie utérine\na. a\nb. b\nc. c\nd. d\ne. e\n"
        "• Question N° 02, Sec 01 de l'année 2017-2018\n"
        "5- Les tests au duphaston\na. a\nb. b\nc. c\nd. d\ne. e"),
}
COMP_LLM = {
    1: [  # origin line of Q2 leaked into Q4's proposition e; Q2 has no origin_raw
        {"number": 4, "text": "Les signes cliniques de la pré-rupture utérine",
         "origin_raw": "• Question N° 07, Sec 01 de l'année 2021-2022",
         "propositions": _props("e\n• . Question N> 02, Participratique, Sec 01 de l'année 20.17-2018")},
        {"number": 2, "text": "On parle d'hypocinésie", "propositions": _props()},
    ],
    2: [
        {"number": 7, "text": "Une hypertonie utérine",
         "origin_raw": "• Question N° 07, Partie pratique, Sec 01 de l'ann\" 2021-2022",
         "propositions": _props()},
        {"number": "QuestionN05", "text": "Les tests au duphaston",
         "origin_raw": "• Question N° 02, Sec 01 de l'année 2017-2018", "propositions": _props()},
    ],
}

NORMAL_PAGES = {
    1: "Faculté de médecine d'Alger — EMD1 2024/2025\n1- Q1\na. a\n2- Q2\na. b",
    2: "Partie pratique\n1- P1\na. a\n2- P2\na. b",
}
NORMAL_LLM = {
    1: [{"number": 1, "text": "Q1", "propositions": _props()},
        {"number": 2, "text": "Q2", "propositions": _props()}],
    2: [{"number": 1, "text": "P1", "section_header": "Partie pratique", "propositions": _props()},
        {"number": 2, "text": "P2", "section_header": "Partie pratique", "propositions": _props()}],
}


class _Client:
    def __init__(self, answers):
        self.answers = answers
        self.prompts = []

    def generate_completion(self, prompt, model, max_tokens, **kw):
        self.prompts.append(prompt)
        page = int(prompt.split("=== PAGE ")[1].split(" ===")[0])
        rows = [dict(q, page=page) for q in json.loads(json.dumps(self.answers[page]))]
        return {"content": json.dumps(rows, ensure_ascii=False), "usage": {}, "cost": 0.0,
                "finish_reason": "stop"}

    @staticmethod
    def estimate_cost(model, usage):
        return 0.0


def _run_step2(tmp_path, monkeypatch, pages, answers):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("STEP2_PARALLEL", raising=False)
    monkeypatch.delenv("EXAM_MODE", raising=False)
    d = tmp_path / "output" / "step1_extraction" / "accepted"
    d.mkdir(parents=True)
    for n, t in pages.items():
        (d / f"page_{n}.txt").write_text(t, encoding="utf-8")
    ex = Step2QCMExtractBatch.__new__(Step2QCMExtractBatch)
    ex.client, ex.cost_tracker, ex.context = _Client(answers), _Tracker(), None
    ex._step2_primary_fail_streak = 0
    ex.run(page_range="1-1-1", config={})
    out = tmp_path / "output" / "step2_qcm" / "accepted" / "all_qcms.json"
    return ex, json.loads(out.read_text(encoding="utf-8"))


# ── Step 1 ────────────────────────────────────────────────────────────────

def test_step1_prompt_keeps_origin_lines_verbatim():
    prompt = Step1Extraction._build_vision_prompt("")
    assert "Question N° 32, Sec 01 de l'année 2021-2022" in prompt
    assert "verbatim" in prompt and "BEFORE the question" in prompt


# ── Step 2 ────────────────────────────────────────────────────────────────

def test_step2_compilation_end_to_end(tmp_path, monkeypatch):
    ex, qcms = _run_step2(tmp_path, monkeypatch, COMP_PAGES, COMP_LLM)
    assert ex._exam_mode == "compilation"
    # compilation: no sequential hint, unseen numbers left null for the model
    assert not any("PREVIOUS PAGE QCM NUMBERS" in p for p in ex.client.prompts)
    assert all("origin_raw" in p and "EXAM ORIGIN LINES" in p for p in ex.client.prompts)

    by_text = {q["text"]: q for q in qcms}
    pre = by_text["Les signes cliniques de la pré-rupture utérine"]
    hypo = by_text["On parle d'hypocinésie"]
    hyper = by_text["Une hypertonie utérine"]
    duph = by_text["Les tests au duphaston"]

    assert pre["propositions"]["e"] == "e"                       # leak removed
    assert (pre["papers"][0]["number"], pre["papers"][0]["period"], pre["papers"][0]["year"]) == (7, "Sec 01", 2021)
    # Q2 got the leaked line (also matches the page line by alignment)
    p = hypo["papers"][0]
    assert (p["number"], p["period"], p["section"], p["year"]) == (2, "Sec 01", "Pratique", 2017)
    p = hyper["papers"][0]
    assert (p["number"], p["section"], p["year"]) == (7, "Pratique", 2021)
    p = duph["papers"][0]
    assert (p["number"], p["section"], p["year"]) == (2, None, 2017)
    assert duph["number"] == 5                                   # 'QuestionN05' -> 5 (P3)
    # the two collisions of §12 stay distinct and are not flagged as duplicates
    assert not any("exam_number_duplicate" in q["review_flags"] for q in qcms)
    # reading order kept in the saved file
    assert [q["text"] for q in qcms][:2] == ["Les signes cliniques de la pré-rupture utérine",
                                             "On parle d'hypocinésie"]


def test_step2_normal_exam_two_parts(tmp_path, monkeypatch):
    ex, qcms = _run_step2(tmp_path, monkeypatch, NORMAL_PAGES, NORMAL_LLM)
    assert ex._exam_mode == "single_paper"
    assert "PREVIOUS PAGE QCM NUMBERS" in ex.client.prompts[1]   # sequential hint kept
    assert [q["scope"] for q in qcms] == ["main", "main", "Pratique", "Pratique"]
    assert [q["papers"][0]["number"] for q in qcms] == [1, 2, 1, 2]
    assert [q["papers"][0]["section"] for q in qcms] == [None, None, "Pratique", "Pratique"]
    assert all(q["review_flags"] == [] for q in qcms)


# ── Step 3 ────────────────────────────────────────────────────────────────

def _step3(tmp_path, first_page_text):
    d = tmp_path / "s1"
    d.mkdir(exist_ok=True)
    (d / "page_1.txt").write_text(first_page_text, encoding="utf-8")
    s3 = Step3Metadata.__new__(Step3Metadata)
    return s3, d


def test_step3_compilation_tags_numbers_and_cas_chain(tmp_path):
    s3, d = _step3(tmp_path, "QCM classé gynécologie 2025")
    case = "CAS CLINIQUE\r\nMme X, 32 ans, hémorragie du post-partum"

    def q(pos, doc, n, period, year, cas):
        return {"page": 1, "number": doc, "uid": f"1_{doc}_{pos}", "source": "Residanat Blida",
                "year": "2025", "cas": cas, "exam_mode": "compilation", "review_flags": [],
                "papers": [{"source": None, "period": period, "year": year, "number": n,
                            "section": None, "from": "origin_line", "confidence": "ok"}]}
    qcms = [q(0, 41, 22, "Rattrapage", 2023, case), q(1, 42, 23, "Rattrapage", 2023, case),
            q(2, 43, 24, "Rattrapage", 2023, case), q(3, 44, 25, "Rattrapage", 2023, case),
            q(4, 45, 42, "Sec 02", 2024, case)]
    s3._finalize_exam_papers(qcms, d, "CC")
    assert [x["Number"] for x in qcms] == [22, 23, 24, 25, 42]
    assert [x["year"] for x in qcms] == ["2023"] * 4 + ["2024"]
    assert qcms[0]["tag"] == ["Residanat Blida", "2023", "Rattrapage"]
    assert qcms[4]["tag"] == ["Residanat Blida", "2024", "Sec 02"]
    assert [bool(x["cas"]) for x in qcms] == [True, True, True, True, False]


def test_step3_normal_exam_period_from_header(tmp_path):
    s3, d = _step3(tmp_path, "Faculté de médecine d'Alger\nEMD 1 — 2024/2025\n1- Q1")
    qcms = [{"number": 1, "source": "Externat Alger", "year": "2024/2025", "cas": None},
            {"number": 1, "source": "Externat Alger", "year": "2024", "scope": "Pratique",
             "papers": [{"number": 1, "section": "Pratique", "period": None, "year": None,
                         "from": "document", "confidence": "ok"}]}]
    s3._finalize_exam_papers(qcms, d, "CC")
    assert qcms[0]["tag"] == ["Externat Alger", "2024", "EMD1"]
    assert qcms[1]["tag"] == ["Externat Alger", "2024", "EMD1 Pratique"]
    assert [x["Number"] for x in qcms] == [1, 1]
    assert qcms[0]["cas"] is None                   # CC chain only for compilations


# ── Step 4/5 ──────────────────────────────────────────────────────────────

def test_template_has_no_placeholder_values():
    assert all(v is None for v in DEFAULT_TEMPLATE_XLSX.values())
    assert "Number" in DEFAULT_TEMPLATE_XLSX


def test_map_to_template_no_leak_and_carries_papers():
    b = Step5Builder.__new__(Step5Builder)
    legacy_template = {"Num": 0, "Text": "Question text here...", "Correct": "ABC",
                       "Year": 2024, "Tag": ["Externat", "2024"], "categoryName": "Cardiologie",
                       "Type": "QCS"}
    q = {"number": 3, "text": "T", "Number": 12, "tag": ["Externat Oran", "2023", "Sec 01"],
         "year": "2023", "session": "Sec 01", "scope": "main", "review_flags": ["missing_year"],
         "papers": [{"number": 12}], "Exams": "Externat Oran · Sec 01 2023 · N°12", "page": 4}
    out = b._map_to_template(q, legacy_template)
    assert out["Correct"] is None and out["categoryName"] is None and out["Type"] is None
    assert out["Num"] == 3 and out["Number"] == 12 and out["Year"] == "2023"
    assert out["Tag"] == ["Externat Oran", "2023", "Sec 01"]
    assert out["scope"] == "main" and out["papers"] == [{"number": 12}] and out["page"] == 4
    missing = b._map_to_template({"number": 1, "text": "T"}, dict(DEFAULT_TEMPLATE_XLSX))
    assert missing["Year"] is None and missing["Tag"] is None


# ── Step 6 ────────────────────────────────────────────────────────────────

def test_step6_two_parts_never_share_an_answer():
    s6 = Step6Corrections.__new__(Step6Corrections)
    qcms = [{"Num": 1, "scope": "main", "page": 1}, {"Num": 2, "scope": "main", "page": 1},
            {"Num": 1, "scope": "Pratique", "page": 3}, {"Num": 2, "scope": "Pratique", "page": 3}]
    # flat map (no page info) + labelled keys from the scoped prompt rule
    applied = s6._apply_corrections_with_fallback(qcms, {"Pratique:1": "E", "Pratique:2": "D"})
    assert applied == 2
    assert [q.get("Correct") for q in qcms] == [None, None, "E", "D"]
    # an unlabelled bare number is ambiguous here -> not applied to both
    s6._apply_corrections_with_fallback(qcms, {"1": "AB"})
    assert qcms[0].get("Correct") is None and qcms[2]["Correct"] == "E"
    assert "correction_ambiguous" in qcms[0]["review_flags"]
    assert "Pratique" in Step6Corrections._scope_prompt_rule(qcms)
    assert Step6Corrections._scope_prompt_rule([{"Num": 1}]) == ""


def test_step6_normalise_keeps_part_labels():
    m = Step6Corrections._normalise_correction_map({"01": "ab", "Pratique:3": "E", "x": "A", "4": "Z"})
    assert m == {"1": "AB", "Pratique:3": "E"}


def test_step6_single_scope_behaviour_unchanged():
    s6 = Step6Corrections.__new__(Step6Corrections)
    qcms = [{"Num": 1}, {"Num": 2}, {"Num": 3}]
    applied = s6._apply_corrections_with_fallback(qcms, {"1": "A", "2": "B", "3": "C"})
    assert applied == 3 and [q["Correct"] for q in qcms] == ["A", "B", "C"]


# ── review xlsx ───────────────────────────────────────────────────────────

def test_review_xlsx_columns(tmp_path):
    from openpyxl import load_workbook
    rows = [{"Num": 4, "Number": 7, "Text": "T", "Year": "2021", "Tag": ["Residanat Blida", "2021", "Sec 01"],
             "session": "Sec 01", "Exams": "Residanat Blida · Sec 01 2021 · N°7", "scope": "ch1",
             "origin_line": "Question N° 07, Sec 01 de l'année 2021-2022",
             "review_flags": ["exam_number_suspect", "origin_mismatch"],
             "papers": [{"number": 7}], "exam_mode": "compilation", "origin_raw": "x", "uid": "1_4_0"}]
    path = tmp_path / "r.xlsx"
    assert export_qcms_to_xlsx(rows, path)
    ws = load_workbook(path).active
    header = [c.value for c in ws[1]]
    assert header.index("Number") == header.index("Num") + 1
    for col in ("session", "Exams", "scope", "origin_line", "review_flags"):
        assert col in header
    for hidden in ("papers", "exam_mode", "origin_raw"):
        assert hidden not in header
    flags = ws.cell(row=2, column=header.index("review_flags") + 1).value
    assert flags == "exam_number_suspect, origin_mismatch"
