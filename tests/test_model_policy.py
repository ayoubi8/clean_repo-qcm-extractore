from unittest.mock import patch

from modules.model_policy import get_model_pair


def test_model_policy_has_primary_and_fallback_for_each_active_slot():
    for slot in (
        "step1_ocr",
        "step6_text",
        "step6_all_pages",
        "step6_auto_detect",
        "step6_reasoning",
    ):
        primary, fallback = get_model_pair(slot)
        assert primary
        assert fallback
        assert primary != fallback


def test_model_policy_respects_deployment_environment_overrides():
    with patch.dict(
        "os.environ",
        {
            "STEP6_TEXT_MODEL": "provider/cheap-primary",
            "STEP6_TEXT_FALLBACK_MODEL": "provider/strong-fallback",
        },
        clear=False,
    ):
        assert get_model_pair("step6_text") == (
            "provider/cheap-primary",
            "provider/strong-fallback",
        )


def test_auto_detect_uses_the_same_configured_all_pages_pair():
    with patch.dict(
        "os.environ",
        {
            "STEP6_ALL_PAGES_MODEL": "provider/layout-primary",
            "STEP6_ALL_PAGES_FALLBACK_MODEL": "provider/layout-fallback",
        },
        clear=False,
    ):
        assert get_model_pair("step6_auto_detect") == (
            "provider/layout-primary",
            "provider/layout-fallback",
        )


def test_model_policy_rejects_unknown_slots():
    try:
        get_model_pair("unknown")
    except KeyError:
        return
    raise AssertionError("Unknown model slots must raise KeyError")
