"""Asking a model one question about one section, and reading one word back.

The narrowest model call in this repository, on purpose. Level 21 measures the
reviewer's prose because prose is what a model is for; this is the opposite
case — a place where a model is used for its judgement and nothing else, so the
interface is a classification and the output is discarded except for its first
word.

Two consequences fall out of that shape. The model cannot write anything a
reader sees, so there is no narration to grade and no citation to check. And a
reply this cannot read is `UNSURE` rather than an error: the answer space is
three values, and "the model said something else" is a fourth that would have
to be invented.
"""

import logging

from code_reviewer.application.ports import DriftJudge, LLMProvider
from code_reviewer.domain.drift import DriftCandidate, DriftVerdict

logger = logging.getLogger(__name__)

#: The question. Written to be answerable from the two texts alone and to make
#: "I cannot tell" a first-class answer rather than a failure — a model forced
#: to choose between stale and current will choose, and the choice it makes
#: when it does not know is noise wearing a verdict's clothes.
PROMPT = """You are checking whether a piece of documentation is still accurate.

Below is a change to a source file, and a section of documentation that may or
may not describe the code that changed.

Answer with exactly one word:
- `stale` if the change makes something the section says wrong or out of date
- `current` if the section is still accurate after the change
- `unsure` if the section is about something else, or you cannot tell

Answer with the single word and nothing else.

--- CHANGE TO {source_path} ---
{diff}

--- DOCUMENTATION: {path}, section "{heading}" ---
{section}
"""

#: Characters of the diff and of the section sent to the model. A whole diff of
#: a thousand lines answers the same question as its first hundred, and costs
#: fifteen times as much to ask.
MAX_DIFF_CHARS = 4_000
MAX_SECTION_CHARS = 4_000


class ModelDriftJudge(DriftJudge):
    """Answers with a model, and confines the answer to three values."""

    def __init__(self, llm_provider: LLMProvider, max_diff_chars: int = MAX_DIFF_CHARS):
        self._model = llm_provider.get_chat_model()
        self._max_diff_chars = max_diff_chars

    def still_describes(self, candidate: DriftCandidate) -> DriftVerdict:
        """One question, one word. Never raises for an ordinary model failure."""
        try:
            reply = self._model.invoke(self._question(candidate))
        except Exception as error:
            logger.warning("Drift judge could not reach the model: %s", error)
            return DriftVerdict.UNSURE

        return DriftVerdict.parse(_text_of(reply))

    def _question(self, candidate: DriftCandidate) -> str:
        return PROMPT.format(
            source_path=candidate.source_path,
            diff=candidate.diff[: self._max_diff_chars],
            path=candidate.path,
            heading=candidate.heading or "(no heading)",
            section=candidate.text[:MAX_SECTION_CHARS],
        )


def _text_of(reply: object) -> str:
    """The reply's text, whatever shape the client returned it in."""
    content = getattr(reply, "content", reply)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # Some clients return a list of content blocks.
        return " ".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content
        )
    return str(content)
