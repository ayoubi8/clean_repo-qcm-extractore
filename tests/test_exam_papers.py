"""Exam papers / sections / numbering — plan docs/plans/exam-papers-sections-numbering-plan.md.

Phase 1 parsers (§5) with the real OCR variants of `gyneco QCM classé 2025.pdf`,
the Step 2 post-pass (§4), the Step 3 finalisation (D1-D6), the clinical-case
chain rule (D7) and Step 6 scoped corrections (P6).
"""
import pytest

from modules.utils import exam_papers as ep


# ── §5.1 origin-line parser — real OCR variants ────────────────────────────

ORIGIN_CASES = [
    ("• Question N° 32, Sec 01 de l'année 2021-2022", 32, "Sec 01", None, 2021, False),
    ("QuestionN° 38, Rattrapage de l'ann6e 2018-2019", 38, "Rattrapage", None, 2018, False),
    ("Question N° 32, Sec 01 de t•ann~ 2021-2022", 32, "Sec 01", None, 2021, False),
    ("• . Question N> 02, Participratique, Sec 01 de l'année 20.17-2018", 2, "Sec 01", "Pratique", 2017, False),
    ("Question N° 07, Partie pratique, Sec 01 de l'ann\" 2021-2022", 7, "Sec 01", "Pratique", 2021, False),
    ("Question N° 401 Rattrapage de l'année 2023-2024", 401, "Rattrapage", None, 2023, True),
    ("QuestionN010, partie pratique, Rattrapage de l' année 2020-2021", 10, "Rattrapage", "Pratique", 2020, False),
    ("Question NO 22, Rattrapagedél'ånnée 2023-2024", 22, "Rattrapage", None, 2023, False),
    ("Question No 23 , Rattrap age de l' année 2023-2024", 23, "Rattrapage", None, 2023, False),
    ("Question N024, Rattrapage del'année 2023-2024", 24, "Rattrapage", None, 2023, False),
    ("• Question No 25, Rattrapage de I' année 2023-2024", 25, "Rattrapage", None, 2023, False),
    ("Question NO 42, Sec 02 de I ' année 2024-2025", 42, "Sec 02", None, 2024, False),
    # harder OCR lines from the PDF's text layer (pages 205-217)
    ("Question N'> 46, Sec 02 de l'année 2024-2025", 46, "Sec 02", None, 2024, False),
    ("Question N° 16, Sec Oi de l'année 2019 .. 2020", 16, "Sec 01", None, 2019, False),
    ("• . Question N° 06,-Soc 01 de rénn\" 2017-2018", 6, "Sec 01", None, 2017, False),
    ("~-- ~ Question N> 291 Sec 01 de l'annie 2019-2020", 291, "Sec 01", None, 2019, True),
    ("• . Question N° 2s.-se 02 ci 'ann~ 2019-2020", 2, "Sec 02", None, 2019, True),
]


@pytest.mark.parametrize("raw,number,period,section,year,suspect", ORIGIN_CASES)
def test_parse_origin_line_real_variants(raw, number, period, section, year, suspect):
    p = ep.parse_origin_line(raw)
    assert p is not None
    assert (p["number"], p["period"], p["section"], p["year"], p["suspect"]) == \
        (number, period, section, year, suspect)
    assert ep.parse_real_origin(raw) is not None


def test_bare_label_is_number_only_not_an_origin_line():
    p = ep.parse_origin_line("QuestionN010")
    assert p["number"] == 10 and p["period"] is None and p["year"] is None
    assert ep.parse_real_origin("QuestionN010") is None
    # an ordinary stem of a normal exam is not an origin line either
    assert ep.parse_real_origin("Question N° 3 : Parmi les causes de syncope") is None
    assert ep.parse_origin_line("29- Quelles sont les étiologies de l'HRP") is None


# ── §5.2 year rule (D1: start year) ────────────────────────────────────────

@pytest.mark.parametrize("raw,year", [
    ("2020-2021", 2020), ("2020/2021", 2020), ("2017 - 2018", 2017),
    ("20.17-2018", 2017), ("2021–2022", 2021), ("2024", 2024), (2019, 2019),
    ("de l'année 2023-2024", 2023), ("1850", None), ("abc", None), (None, None), ("", None),
])
def test_parse_year(raw, year):
    assert ep.parse_year(raw) == year


def test_normalize_year_metadata_context_dash_forms():
    from modules.utils.metadata_context import normalize_year
    assert normalize_year("2025/2026") == "2025"
    assert normalize_year("2020-2021") == "2020"
    assert normalize_year("20.17-2018") == "2017"
    assert normalize_year("2024") == "2024"
    assert normalize_year("n/a") is None


def test_extract_int_labels():
    assert ep.extract_int("QuestionN010") == 10
    assert ep.extract_int("N° 7") == 7
    assert ep.extract_int(12) == 12
    assert ep.extract_int("abc") is None
    assert ep.extract_int(None) is None


def test_session_label_d2():
    assert ep.session_label("Sec 01", "Pratique") == "Sec 01 Pratique"
    assert ep.session_label("Sec 01", "Théorique") == "Sec 01"
    assert ep.session_label("Rattrapage", None) == "Rattrapage"
    assert ep.session_label(None, "Pratique") == "Pratique"
    assert ep.session_label(None, None) is None


# ── §4.1 mode detection ────────────────────────────────────────────────────

def test_detect_mode():
    comp = {
        1: "• Question N° 32, Sec 01 de l'année 2021-2022\n29- Q?\na. x",
        2: "• Question N° 07, Partie pratique, Sec 01 de l'année 2021-2022\n30- Q?",
        3: "• Question No 25, Rattrapage de l'année 2023-2024\n31- Q?",
    }
    assert ep.detect_document_mode(comp) == ep.MODE_COMPILATION
    normal = {1: "Faculté de médecine d'Alger\nEMD 1 2025\n1- Q?\na. x", 2: "2- Q?\na. y"}
    assert ep.detect_document_mode(normal) == ep.MODE_SINGLE
    assert ep.resolve_mode("single_paper", comp) == ep.MODE_SINGLE
    assert ep.resolve_mode("auto", comp) == ep.MODE_COMPILATION


# ── §4.2 scopes ────────────────────────────────────────────────────────────

def _q(page, number, pos, **kw):
    d = {"page": page, "number": number, "uid": f"{page}_{number}_{pos}",
         "text": f"Q{number}", "propositions": {"a": "x", "b": "y"}}
    d.update(kw)
    return d


def test_scopes_header_and_restart():
    qs = [_q(1, 1, 0), _q(1, 2, 1), _q(2, 40, 0),
          _q(2, 1, 1, section_header="Partie pratique"), _q(3, 2, 0)]
    ep.assign_scopes(qs, ep.MODE_SINGLE)
    assert [q["scope"] for q in qs] == ["main", "main", "main", "Pratique", "Pratique"]
    # restart with no header -> inferred part, flagged
    qs = [_q(1, 1, 0), _q(1, 2, 1), _q(2, 30, 0), _q(3, 1, 0), _q(3, 2, 1)]
    ep.assign_scopes(qs, ep.MODE_SINGLE)
    assert [q["scope"] for q in qs] == ["main", "main", "main", "part-2", "part-2"]
    assert "scope_inferred" in qs[3]["review_flags"]


def test_reading_order_beats_number_order():
    qs = [_q(2, 1, 1, section_header="Partie pratique"), _q(2, 40, 0)]
    ordered = sorted(qs, key=ep.reading_order_key)
    assert [q["number"] for q in ordered] == [40, 1]


# ── Step 2 post-pass ───────────────────────────────────────────────────────

def test_annotate_compilation_alignment_and_leak():
    pages = {
        204: ("• Question N° 07, Sec 01 de l'année 2021-2022\n"
              "4- Les signes cliniques de la pré-rupture utérine\na. x\n"
              "• Question N° 32, Sec 01 de l'année 2021-2022\n5- HRP ?\na. y"),
        209: ("• Question N° 07, Partie pratique, Sec 01 de l'année 2021-2022\n"
              "7- Une hypertonie utérine\na. z"),
    }
    qs = [
        # LLM gave origin_raw for the first, missed it for the second
        _q(204, 4, 0, origin_raw="Question N° 07, Sec 01 de l'année 2021-2022",
           propositions={"a": "x", "e": "e text • Question N° 32, Sec 01 de l'année 2021-2022"}),
        _q(204, 5, 1),
        # LLM origin disagrees with the page line -> page wins, flagged
        _q(209, 7, 0, origin_raw="Question N° 08, Sec 02 de l'année 2021-2022"),
    ]
    ep.annotate_qcms(qs, pages, ep.MODE_COMPILATION)
    p0, p1, p2 = (q["papers"][0] for q in qs)
    assert qs[0]["propositions"]["e"] == "e text"            # leak stripped
    assert (p0["number"], p0["period"], p0["year"], p0["section"]) == (7, "Sec 01", 2021, None)
    assert (p1["number"], p1["period"]) == (32, "Sec 01")
    assert (p2["number"], p2["section"]) == (7, "Pratique")
    assert "origin_mismatch" in qs[2]["review_flags"]
    # theory N°7 and pratique N°7 of Sec 01 2021 are NOT duplicates (D2)
    assert "exam_number_duplicate" not in qs[0]["review_flags"]
    assert all(q["exam_mode"] == ep.MODE_COMPILATION for q in qs)
    # document number unchanged
    assert [q["number"] for q in qs] == [4, 5, 7]


def test_annotate_compilation_missing_origin_is_flagged_never_guessed():
    qs = [_q(1, 3, 0)]
    ep.annotate_qcms(qs, {1: "3- Q?\na. x"}, ep.MODE_COMPILATION)
    assert qs[0]["papers"][0]["number"] is None
    assert "exam_number_missing" in qs[0]["review_flags"]


def test_annotate_single_paper_two_parts():
    qs = [_q(1, 1, 0), _q(1, 2, 1), _q(2, 1, 0, section_header="Partie pratique")]
    ep.annotate_qcms(qs, {1: "EMD1\n1- a\n2- b", 2: "Partie pratique\n1- c"}, ep.MODE_SINGLE)
    assert [q["papers"][0]["number"] for q in qs] == [1, 2, 1]
    assert qs[2]["papers"][0]["section"] == "Pratique"
    assert qs[0]["papers"][0]["section"] is None
    assert all(not q["review_flags"] for q in qs)


def test_annotate_is_idempotent():
    pages = {1: "• Question N° 07, Sec 01 de l'année 2021-2022\n1- Q\na. x"}
    qs = [_q(1, 1, 0)]
    ep.annotate_qcms(qs, pages, ep.MODE_COMPILATION)
    first = [dict(q) for q in qs]
    ep.annotate_qcms(qs, pages, ep.MODE_COMPILATION)
    assert qs[0]["papers"] == first[0]["papers"]
    assert qs[0]["review_flags"] == first[0]["review_flags"]


# ── Step 3 finalisation (D1-D6) ────────────────────────────────────────────

def test_finalize_compilation_pratique_tag_number_year():
    q = {"number": 2, "source": "Residanat Blida", "year": "2025",
         "papers": [{"source": None, "period": "Sec 01", "year": 2017, "number": 2,
                     "section": "Pratique", "from": "origin_line", "confidence": "ok"}]}
    ep.finalize_papers(q, doc_period="EMD1")
    assert q["Number"] == 2
    assert q["year"] == "2017"                     # origin line beats the global year
    assert q["tag"] == ["Residanat Blida", "2017", "Sec 01 Pratique"]
    assert q["papers"][0]["period"] == "Sec 01"    # doc period never overrides an origin line
    assert q["Exams"] == "Residanat Blida · Sec 01 Pratique 2017 · N°2"
    assert not any("N°" in t for t in q["tag"])


def test_finalize_normal_exam():
    q = {"number": 12, "source": "Externat Alger", "year": "2024/2025"}
    ep.finalize_papers(q, doc_period="EMD1")
    assert q["Number"] == 12
    assert q["year"] == "2024"
    assert q["tag"] == ["Externat Alger", "2024", "EMD1"]
    assert q["Exams"] == "Externat Alger · EMD1 2024 · N°12"


def test_finalize_missing_year_is_flagged_not_invented():
    q = {"number": 3, "source": "Externat Oran"}
    ep.finalize_papers(q)
    assert q["year"] is None
    assert "missing_year" in q["review_flags"]
    assert q["Exams"] == ""
    assert q["tag"] == ["Externat Oran"]


# ── D7 clinical-case chain ────────────────────────────────────────────────

def _cq(pos, doc_num, number, period, year, cas=None, conf="ok"):
    return {"page": 1, "number": doc_num, "uid": f"1_{doc_num}_{pos}", "cas": cas,
            "papers": [{"period": period, "year": year, "number": number,
                        "section": None, "from": "origin_line", "confidence": conf}]}


def test_cas_chain_user_example_rattrapage_2023():
    case = "CAS CLINIQUE\r\nMme X, 32 ans, hémorragie du post-partum..."
    qs = [_cq(0, 41, 22, "Rattrapage", 2023, case),
          _cq(1, 42, 23, "Rattrapage", 2023, case),
          _cq(2, 43, 24, "Rattrapage", 2023, None),     # LLM missed it -> extended
          _cq(3, 44, 25, "Rattrapage", 2023, case),
          _cq(4, 45, 42, "Sec 02", 2024, case)]         # LLM over-linked -> removed
    stats = ep.enforce_cas_chain(qs)
    assert [bool(q["cas"]) for q in qs] == [True, True, True, True, False]
    assert len({q["cas"] for q in qs[:4]}) == 1                   # byte-identical
    assert "cas_chain_extended" in qs[2]["review_flags"]
    assert "cas_chain_broken" in qs[4]["review_flags"]
    assert stats["removed"] == 1 and stats["extended"] == 1


def test_cas_chain_number_gap_breaks_same_paper():
    case = "CAS\r\nM. Y, 50 ans"
    qs = [_cq(0, 1, 10, "Sec 01", 2021, case), _cq(1, 2, 12, "Sec 01", 2021, case),
          _cq(2, 3, 13, "Sec 01", 2021, case)]
    ep.enforce_cas_chain(qs)
    assert [bool(q["cas"]) for q in qs] == [True, False, False]


def test_cas_chain_unreadable_number_uses_document_positions():
    case = "CAS\r\nM. Z"
    qs = [_cq(0, 5, 20, "Rattrapage", 2020, case),
          _cq(1, 6, 401, "Rattrapage", 2020, case, conf="suspect")]
    ep.enforce_cas_chain(qs)
    assert qs[1]["cas"] == case and "cas_chain_uncertain" in qs[1]["review_flags"]


def test_cas_chain_new_case_starts_fresh():
    a, b = "CAS 1\r\nA", "CAS 2\r\nB"
    qs = [_cq(0, 1, 1, "Sec 01", 2021, a), _cq(1, 2, 2, "Sec 01", 2021, a),
          _cq(2, 3, 3, "Sec 01", 2021, b), _cq(3, 4, 4, "Sec 01", 2021, b)]
    ep.enforce_cas_chain(qs)
    assert [q["cas"] for q in qs] == [a, a, b, b]


# ── P6 scoped corrections ─────────────────────────────────────────────────

def _sq(page, num, scope):
    return {"page": page, "Num": num, "scope": scope}


def test_scoped_corrections_two_parts_two_tables():
    qs = [_sq(1, 1, "main"), _sq(1, 2, "main"), _sq(5, 1, "Pratique"), _sq(5, 2, "Pratique")]
    entries = (ep.entries_from_map({"1": "AB", "2": "C"}, page=4)
               + ep.entries_from_map({"1": "DE", "2": "B"}, page=8))
    ep.apply_scoped_corrections(qs, entries)
    assert [q.get("Correct") for q in qs] == ["AB", "C", "DE", "B"]


def test_scoped_corrections_both_tables_at_the_end():
    qs = [_sq(1, 1, "main"), _sq(5, 1, "Pratique")]
    entries = (ep.entries_from_map({"1": "AB"}, page=10)
               + ep.entries_from_map({"1": "DE"}, page=11))
    ep.apply_scoped_corrections(qs, entries)
    assert [q.get("Correct") for q in qs] == ["AB", "DE"]


def test_scoped_corrections_labelled_key():
    qs = [_sq(1, 1, "main"), _sq(5, 1, "Pratique")]
    ep.apply_scoped_corrections(qs, ep.entries_from_map({"Pratique:1": "E"}))
    assert [q.get("Correct") for q in qs] == [None, "E"]


def test_scoped_corrections_ambiguous_is_not_applied():
    qs = [_sq(1, 1, "main"), _sq(5, 1, "Pratique")]
    stats = ep.apply_scoped_corrections(qs, ep.entries_from_map({"1": "AB"}))
    assert [q.get("Correct") for q in qs] == [None, None]
    assert stats["ambiguous"] == 1
    assert all("correction_ambiguous" in q["review_flags"] for q in qs)


def test_scoped_corrections_single_scope_unchanged_behaviour():
    qs = [_sq(1, 1, "main"), _sq(2, 2, "main"), {"page": 3, "Num": 3}]
    ep.apply_scoped_corrections(qs, ep.entries_from_map({"1": "A", "2": "B", "3": "C", "9": "D"}))
    assert [q.get("Correct") for q in qs] == ["A", "B", "C"]


def test_parse_correction_key():
    assert ep.parse_correction_key("12") == (None, "12")
    assert ep.parse_correction_key("Pratique:3") == ("Pratique", "3")
    assert ep.parse_correction_key("Rattrapage | 07") == ("Rattrapage", "7")
    assert ep.parse_correction_key("abc") == (None, None)


def test_finalize_panel_defaults_fill_only_gaps():
    q = {"number": 4}
    ep.finalize_papers(q, doc_period="EMD1", default_source="Externat Setif", default_year="2025")
    assert q["tag"] == ["Externat Setif", "2025", "EMD1"] and q["Number"] == 4
    # the document's own year / an origin line always win over panel defaults
    q2 = {"number": 2, "source": "Residanat Blida", "year": "2021",
          "papers": [{"period": "Sec 01", "year": 2017, "number": 2, "section": "Pratique",
                      "from": "origin_line", "confidence": "ok"}]}
    ep.finalize_papers(q2, doc_period="EMD1", default_source="X", default_year="2025")
    assert q2["tag"] == ["Residanat Blida", "2017", "Sec 01 Pratique"]
