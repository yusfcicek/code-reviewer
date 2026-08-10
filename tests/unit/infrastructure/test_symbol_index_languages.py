"""Step 5 — more than one language, and an honest statement of how many.

Level 23's index read Python, so a document naming a symbol in any other
language resolved to nothing and was silently out of scope. Silently is the
problem: the rule reported nothing and there was no way to tell that from
"nothing is wrong".

Declarations, not programs. The index answers *does this name exist*, and a
regex over declaration syntax answers that. It is honest about answering nothing
else, and the languages it covers are a stated constant rather than an
implication.
"""

from code_reviewer.infrastructure.documentation.workspace import (
    COVERED_LANGUAGES,
    build_symbol_index,
)


def _tree(tmp_path, **files):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


GO = """package review

type Verdict struct {
	Blocking bool
}

const MaxFindings = 50

func Evaluate(findings []Finding) Verdict {
	return Verdict{}
}

func (v Verdict) IsBlocking() bool {
	return v.Blocking
}
"""

TYPESCRIPT = """export interface Finding {
  ruleId: string;
}

export type Verdict = "pass" | "fail";

export function evaluate(findings: Finding[]): Verdict {
  return "pass";
}

export class ReviewGate {
  decide(): Verdict {
    return "pass";
  }
}

const MAX_FINDINGS = 50;
"""

JAVA = """package review;

public class ReviewGate {
    private static final int MAX_FINDINGS = 50;

    public Verdict evaluate(List<Finding> findings) {
        return Verdict.PASS;
    }
}

interface Analyzer {
}
"""


class TestGo:
    def test_a_function_resolves(self, tmp_path):
        assert build_symbol_index(_tree(tmp_path, **{"gate.go": GO})).resolves("Evaluate")

    def test_a_type_resolves(self, tmp_path):
        assert build_symbol_index(_tree(tmp_path, **{"gate.go": GO})).resolves("Verdict")

    def test_a_method_with_a_receiver_resolves(self, tmp_path):
        assert build_symbol_index(_tree(tmp_path, **{"gate.go": GO})).resolves("IsBlocking")

    def test_a_constant_resolves(self, tmp_path):
        assert build_symbol_index(_tree(tmp_path, **{"gate.go": GO})).resolves("MaxFindings")


class TestTypeScript:
    def test_an_exported_function_resolves(self, tmp_path):
        assert build_symbol_index(_tree(tmp_path, **{"gate.ts": TYPESCRIPT})).resolves("evaluate")

    def test_a_class_resolves(self, tmp_path):
        assert build_symbol_index(_tree(tmp_path, **{"gate.ts": TYPESCRIPT})).resolves("ReviewGate")

    def test_an_interface_resolves(self, tmp_path):
        assert build_symbol_index(_tree(tmp_path, **{"gate.ts": TYPESCRIPT})).resolves("Finding")

    def test_a_type_alias_resolves(self, tmp_path):
        assert build_symbol_index(_tree(tmp_path, **{"gate.ts": TYPESCRIPT})).resolves("Verdict")

    def test_javascript_is_read_too(self, tmp_path):
        source = "export function decide(a) { return a; }\n"

        assert build_symbol_index(_tree(tmp_path, **{"gate.js": source})).resolves("decide")


class TestJava:
    def test_a_class_resolves(self, tmp_path):
        assert build_symbol_index(_tree(tmp_path, **{"Gate.java": JAVA})).resolves("ReviewGate")

    def test_a_method_resolves(self, tmp_path):
        assert build_symbol_index(_tree(tmp_path, **{"Gate.java": JAVA})).resolves("evaluate")

    def test_an_interface_resolves(self, tmp_path):
        assert build_symbol_index(_tree(tmp_path, **{"Gate.java": JAVA})).resolves("Analyzer")


class TestWhatIsNotCovered:
    def test_the_covered_set_is_stated(self, tmp_path):
        """AC-11. A reader should be able to see what is out of scope without
        reading the patterns."""
        assert ".go" in COVERED_LANGUAGES
        assert ".py" in COVERED_LANGUAGES

    def test_a_language_with_no_pattern_contributes_nothing(self, tmp_path):
        source = "(defn evaluate [findings] :pass)\n"

        assert build_symbol_index(_tree(tmp_path, **{"gate.clj": source})).is_empty

    def test_an_unreadable_file_does_not_stop_the_build(self, tmp_path):
        tree = _tree(tmp_path, **{"broken.go": "func (\n", "gate.go": GO})

        assert build_symbol_index(tree).resolves("Evaluate")

    def test_a_comment_is_not_a_declaration(self, tmp_path):
        """The lesson from self-review 26: a recipe that read a comment as code
        produced noise. The same care, in the same repository."""
        source = "// func Ghost() {}\nfunc Real() {}\n"

        index = build_symbol_index(_tree(tmp_path, **{"gate.go": source}))

        assert index.resolves("Real")
        assert not index.resolves("Ghost")


class TestPythonIsUnchanged:
    def test_a_python_function_still_resolves(self, tmp_path):
        source = "def create_app(config):\n    return config\n"

        assert build_symbol_index(_tree(tmp_path, **{"app.py": source})).resolves("create_app")

    def test_python_still_reports_parameters_and_the_others_do_not(self, tmp_path):
        """The AST gives Python a signature; a regex over declarations does not
        pretend to, so a signature mismatch is only ever claimed about Python."""
        tree = _tree(tmp_path, **{"app.py": "def f(a, b):\n    pass\n", "gate.go": GO})
        index = build_symbol_index(tree)

        assert index.parameters_of("f") == ("a", "b")
        assert index.parameters_of("Evaluate") is None
