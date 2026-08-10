"""Step 7c — the narrowest model call in this repository.

One question, one word out. Everything the model says beyond that word is
discarded, which is what makes this the one place a model is used without
anything it wrote reaching a reader.
"""

from code_reviewer.domain.drift import DriftCandidate, DriftVerdict
from code_reviewer.infrastructure.llm.drift_judge import ModelDriftJudge

CANDIDATE = DriftCandidate(
    path="docs/guide.md",
    line=5,
    heading="Suppression",
    text="A directive silences a rule.",
    source_path="code_reviewer/domain/suppression.py",
    diff="@@ -1,1 +1,1 @@\n-old\n+new\n",
)


class _Reply:
    def __init__(self, content):
        self.content = content


class _Model:
    def __init__(self, reply=None, error=None):
        self._reply = reply
        self._error = error
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        if self._error is not None:
            raise self._error
        return self._reply


class _Provider:
    def __init__(self, model):
        self._model = model

    def get_chat_model(self):
        return self._model


def _judge(reply=None, error=None):
    model = _Model(reply=reply, error=error)
    return ModelDriftJudge(_Provider(model)), model


def test_a_one_word_answer_is_the_verdict():
    judge, _ = _judge(_Reply("stale"))

    assert judge.still_describes(CANDIDATE) is DriftVerdict.STALE


def test_a_talkative_answer_is_read_from_its_first_word():
    judge, _ = _judge(_Reply("current — the section still matches the code"))

    assert judge.still_describes(CANDIDATE) is DriftVerdict.CURRENT


def test_an_answer_the_parser_cannot_read_is_unsure():
    judge, _ = _judge(_Reply("It depends on what you mean by accurate."))

    assert judge.still_describes(CANDIDATE) is DriftVerdict.UNSURE


def test_a_model_that_raises_answers_unsure():
    """The tier loses a candidate. The review does not lose anything."""
    judge, _ = _judge(error=RuntimeError("connection reset"))

    assert judge.still_describes(CANDIDATE) is DriftVerdict.UNSURE


def test_a_reply_in_content_blocks_is_read():
    judge, _ = _judge(_Reply([{"type": "text", "text": "stale"}]))

    assert judge.still_describes(CANDIDATE) is DriftVerdict.STALE


def test_a_bare_string_reply_is_read():
    judge, _ = _judge("stale")

    assert judge.still_describes(CANDIDATE) is DriftVerdict.STALE


def test_the_prompt_carries_both_texts_and_names_both_places():
    judge, model = _judge(_Reply("unsure"))

    judge.still_describes(CANDIDATE)
    prompt = model.prompts[0]

    assert "docs/guide.md" in prompt
    assert "Suppression" in prompt
    assert "suppression.py" in prompt
    assert "A directive silences a rule." in prompt
    assert "+new" in prompt


def test_the_prompt_offers_unsure_as_an_answer():
    """A model made to choose between stale and current will choose, and the
    choice it makes when it does not know is noise wearing a verdict's clothes."""
    judge, model = _judge(_Reply("unsure"))

    judge.still_describes(CANDIDATE)

    assert "unsure" in model.prompts[0]


def test_a_very_long_diff_is_truncated():
    judge, model = _judge(_Reply("unsure"))
    long_one = DriftCandidate(
        path="docs/guide.md",
        line=1,
        heading="",
        text="body",
        source_path="app.py",
        diff="+x\n" * 10_000,
    )

    judge.still_describes(long_one)

    assert len(model.prompts[0]) < 12_000


def test_a_candidate_with_no_heading_still_asks():
    judge, model = _judge(_Reply("stale"))
    headless = DriftCandidate(
        path="docs/guide.md", line=1, heading="", text="body", source_path="app.py", diff="+x\n"
    )

    assert judge.still_describes(headless) is DriftVerdict.STALE
    assert "no heading" in model.prompts[0]
