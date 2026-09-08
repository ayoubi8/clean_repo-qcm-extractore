from unittest.mock import patch

from modules.step2_qcm_extract_batch import Step2QCMExtractBatch


class _Tracker:
    def log_api_call(self, *args, **kwargs):
        pass


class _Client:
    def __init__(self):
        self.calls = []

    def generate_completion(self, prompt, model, max_tokens):
        self.calls.append(model)
        if model == "primary/model":
            raise RuntimeError("primary unavailable")
        return {
            "content": '[{"number": 1, "text": "Q", "propositions": {"a": "A"}}]',
            "usage": {},
            "cost": 0.0,
        }

    @staticmethod
    def estimate_cost(model, usage):
        return 0.0


def test_step2_promotes_fallback_for_remaining_chunks_after_primary_failure():
    extractor = Step2QCMExtractBatch.__new__(Step2QCMExtractBatch)
    extractor.client = _Client()
    extractor.cost_tracker = _Tracker()
    extractor._step2_promoted_to_fallback = False

    with patch.dict(
        "os.environ",
        {
            "STEP2_MODEL": "primary/model",
            "STEP2_FALLBACK_MODEL": "fallback/model",
            "STEP2_MAX_RETRIES": "3",
        },
        clear=False,
    ):
        first = extractor._extract_all_qcms_batch("page one", 1, 1, {})
        second = extractor._extract_all_qcms_batch("page two", 2, 2, {})

    assert first and second
    assert extractor.client.calls == [
        "primary/model",
        "fallback/model",
        "fallback/model",
    ]
