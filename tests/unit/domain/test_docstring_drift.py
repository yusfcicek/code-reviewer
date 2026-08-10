"""Step 4 — the half of the problem that lives inside the source file.

A docstring is documentation with the shortest possible distance to the code it
describes, which is exactly why it goes stale unnoticed: the reader's eye is on
the signature two lines below, and the reviewer's diff shows both as one hunk.

The self-review of levels 12–20 found one of these in this repository — a
docstring in `governance/identity.py` claiming a drift test that did not exist.
"""

from code_reviewer.domain.documentation import docstring_defects


def _rules(source):
    return [defect.rule for defect in docstring_defects(source)]


UNDOCUMENTED_PARAMETER = '''
def render(version, outcome):
    """Renders it.

    Args:
        version: the policy version.
    """
    return version
'''

INVENTED_PARAMETER = '''
def render(version):
    """Renders it.

    Args:
        version: the policy version.
        outcome: the thing that no longer exists.
    """
    return version
'''

CORRECT = '''
def render(version, outcome):
    """Renders it.

    Args:
        version: the policy version.
        outcome: what the review decided.

    Returns:
        The rendered body.
    """
    return version + outcome
'''


def test_a_documented_parameter_the_signature_does_not_have_is_reported():
    assert _rules(INVENTED_PARAMETER) == ["DOCSTRING_DRIFT"]


def test_the_defect_names_the_function_and_the_parameter():
    defect = docstring_defects(INVENTED_PARAMETER)[0]

    assert defect.subject == "render"
    assert "outcome" in defect.detail


def test_a_parameter_missing_from_a_documented_list_is_reported():
    assert _rules(UNDOCUMENTED_PARAMETER) == ["DOCSTRING_DRIFT"]


def test_a_docstring_that_documents_no_parameters_is_left_alone():
    """A one-line docstring is a style choice, not a defect."""
    source = '\ndef render(version, outcome):\n    """Renders it."""\n    return version\n'

    assert _rules(source) == []


def test_self_is_never_expected_in_a_docstring():
    source = '''
class Renderer:
    def render(self, version):
        """Renders it.

        Args:
            version: the policy version.
        """
        return version
'''

    assert _rules(source) == []


def test_a_documented_exception_the_body_never_raises_is_reported():
    source = '''
def read(path):
    """Reads it.

    Raises:
        FileNotFoundError: when the path is absent.
    """
    return path
'''

    assert _rules(source) == ["DOCSTRING_DRIFT"]


def test_a_documented_exception_the_body_raises_is_not_reported():
    source = '''
def read(path):
    """Reads it.

    Raises:
        ValueError: when the path is empty.
    """
    if not path:
        raise ValueError(path)
    return path
'''

    assert _rules(source) == []


def test_a_function_that_re_raises_is_not_reported():
    """A bare `raise` re-raises whatever was caught, which this cannot name."""
    source = '''
def read(path):
    """Reads it.

    Raises:
        OSError: when the read fails.
    """
    try:
        return open(path)
    except OSError:
        raise
'''

    assert _rules(source) == []


def test_a_documented_return_from_a_function_that_returns_nothing_is_reported():
    source = '''
def write(path):
    """Writes it.

    Returns:
        The number of bytes written.
    """
    print(path)
'''

    assert _rules(source) == ["DOCSTRING_DRIFT"]


def test_a_generator_documenting_a_return_is_not_reported():
    """`yield` is a return value by another name."""
    source = '''
def lines(path):
    """Reads it.

    Returns:
        Each line in turn.
    """
    yield path
'''

    assert _rules(source) == []


def test_sphinx_style_parameters_are_read_too():
    source = '''
def render(version):
    """Renders it.

    :param version: the policy version.
    :param outcome: the thing that no longer exists.
    """
    return version
'''

    assert _rules(source) == ["DOCSTRING_DRIFT"]


def test_a_correct_docstring_yields_nothing():
    assert docstring_defects(CORRECT) == []


def test_a_file_that_does_not_parse_yields_nothing():
    assert docstring_defects("def (:\n") == []


def test_an_empty_file_yields_nothing():
    assert docstring_defects("") == []


def test_no_defect_carries_a_sentence_from_the_docstring():
    """AC-14, inside the source file this time."""
    for defect in docstring_defects(INVENTED_PARAMETER):
        assert "no longer exists" not in defect.detail


class TestAStubDocumentsAContract:
    """Self-review S-04 — a 33 % false-positive rate on the only real corpus.

    Run over this repository the rule produced three findings, and one was
    `JobStore.submit` — an `@abstractmethod` whose body is a docstring,
    documenting `Raises: QueueFull`. That is not drift. It is the contract every
    implementer must honour, and the declaration is the only place to state it.

    A body that does nothing cannot contradict anything, so a stub is not
    examined for what its body does. What it *says about its own signature* is
    still checked: a documented parameter the signature lacks is wrong wherever
    it is written.
    """

    ABSTRACT = '''
from abc import ABC, abstractmethod


class Store(ABC):
    @abstractmethod
    def submit(self, job, max_queued):
        """Adds it.

        Raises:
            QueueFull: when accepting it would exceed max_queued.

        Returns:
            The job now in flight.
        """
'''

    def test_a_documented_exception_on_a_stub_is_not_reported(self):
        assert _rules(self.ABSTRACT) == []

    def test_a_documented_return_on_a_stub_is_not_reported(self):
        source = '''
def read(path):
    """Reads it.

    Returns:
        The bytes.
    """
'''

        assert _rules(source) == []

    def test_an_ellipsis_body_is_a_stub_too(self):
        source = '''
def read(path):
    """Reads it.

    Raises:
        OSError: when it fails.
    """
    ...
'''

        assert _rules(source) == []

    def test_a_pass_body_is_a_stub_too(self):
        source = '''
def read(path):
    """Reads it.

    Returns:
        The bytes.
    """
    pass
'''

        assert _rules(source) == []

    def test_a_stub_is_still_checked_against_its_own_signature(self):
        """The half a stub can still get wrong."""
        source = '''
def read(path):
    """Reads it.

    Args:
        path: where.
        mode: no longer a parameter.
    """
'''

        assert _rules(source) == ["DOCSTRING_DRIFT"]

    def test_a_raising_body_is_not_a_stub(self):
        source = '''
def read(path):
    """Reads it.

    Raises:
        OSError: when it fails.
    """
    raise NotImplementedError
'''

        assert _rules(source) == []

    def test_a_real_body_is_still_examined(self):
        source = '''
def read(path):
    """Reads it.

    Returns:
        The bytes.
    """
    print(path)
'''

        assert _rules(source) == ["DOCSTRING_DRIFT"]
