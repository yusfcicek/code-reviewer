# Level 12 — Evaluation Harness

## Problem statement

Eleven levels have made this agent stricter, safer and better structured. Not
one of them can tell you whether it reviews code *well*.

Everything measured so far is a proxy. Coverage says the code ran. The metrics
export says how many findings were produced, at what severity, in how long.
The dogfooding test says the package does not block itself. None of these
answers the question a team actually asks before turning the gate on: *when
this thing reports a vulnerability, is it there — and when it stays quiet, is
the file clean?*

- **There is no ground truth.** Every analyzer test asserts that one fixture
  produces one finding. That verifies a rule; it does not measure a suite.
  Precision and recall are not computed anywhere, so "the SAST analyzer is
  noisy" is an opinion nobody can settle (C-01).
- **A prompt or model change ships unmeasured.** Level 7 replaced the agent
  loop. Level 8 rewrote the system prompt around a trust boundary. Both were
  verified by asserting on the *shape* of the output. Neither could have
  detected a change that made reviews worse, because nothing scores a review
  (C-03).
- **Regressions in the other direction are equally invisible.** Two commits in
  Level 11 fixed false positives — the N+1 rule firing on `dict.get`, an
  unbounded DES pattern. Each was found by a human reading a report. Nothing
  stops either from returning, because a false positive that a fixture does not
  happen to contain is a false positive nobody tests for (C-02).
- **"Continuous optimisation" has no baseline to optimise against.** Tuning a
  threshold, adding a rule, or swapping a model are all currently changes made
  in the dark and defended by argument.

Capabilities addressed: **C-01, C-02, C-03**.

## Goals

1. A dataset of annotated cases exists, in which each case states what the
   suite is expected to find and what it must not.
2. Running the suite over that dataset produces precision, recall and F1 —
   overall and per rule.
3. A threshold on those numbers is enforceable, with its own exit code, so CI
   can block a change that makes review quality worse.
4. Findings the dataset does not grade are counted and reported, so narrowing
   what is graded cannot quietly improve the score.

## Non-goals

- **Evaluating the model's prose.** The reviewer's narration is unstructured
  and its quality is a judgement, not a match. This level grades the
  deterministic half — findings — where ground truth is writable. Scoring
  narration needs a judge model and belongs with the tracing work at Level 16.
- **A statistically meaningful corpus.** Eight annotated cases will not
  characterise the analyzers' true precision. They will detect a change in it,
  which is what a regression gate needs. The dataset is designed to grow.
- **Benchmark harnesses from the literature** (SWE-bench, HumanEval and kin).
  They measure a model's ability to write code. Nothing here writes code.
- **Tuning any rule.** This level builds the instrument. Pointing it at the
  analyzers and acting on what it says is the next level's problem, and the
  thresholds are therefore set from the measured baseline rather than from an
  aspiration.

## Behavioural contracts

### C-1 — A case declares expected findings (C-01)
An evaluation case names a source fixture and lists the findings the suite
should produce on it: a rule id, a line, and optionally a severity. A case may
also supply a diff, so the semantic analyzer — which only runs against one —
can be graded.

### C-2 — A produced finding matches an expectation by rule and place (C-01)
A finding matches an expectation when the rule ids are equal and the line
numbers are within the case's tolerance (zero by default). Matching is
one-to-one: an expectation consumes at most one finding, and a finding
satisfies at most one expectation. When several findings are eligible, the
closest line wins; on a tie, the lower line number, so the result does not
depend on the order the analyzers ran in.

### C-3 — A severity mismatch is a miss, not a match (C-01)
When an expectation states a severity and the matching finding carries a
different one, the expectation is unmet. The finding is consumed rather than
also counted as spurious — the failure is "the rule fired at the wrong grade",
and charging it twice would make one defect move two numbers.

### C-4 — Unexpected findings inside the graded scope are false positives (C-02)
A case declares a scope: the rule-id globs it takes responsibility for,
defaulting to everything. An in-scope finding that no expectation claims is a
false positive. This is what makes a noisy rule visible.

### C-5 — Findings outside the scope are counted, never dropped (C-02)
Out-of-scope findings are reported as *ungraded*, with their count and their
rule ids. Narrowing a scope therefore trades a possible false positive for a
visible admission that something is not being graded — which is the same
bargain suppression makes at Level 11, and it is made the same way: in the
open, with a number attached.

### C-6 — A case can forbid a finding outright (C-02)
`expect_absent` names a rule that must not fire on the fixture, at a given line
or anywhere in it. A forbidden finding is a false positive regardless of scope.
This is where a fixed false positive is pinned so it cannot return.

### C-7 — Scores are computed per rule as well as overall (C-01)
The report carries a confusion matrix for the whole run and one per rule id.
An overall F1 of 0.9 hiding a rule at 0.2 is the failure mode a single number
has; the per-rule table is what makes it visible.

### C-8 — A threshold produces an exit code (C-03)
The evaluation command accepts minimum precision, recall and F1. Below any of
them, it exits 1 and names each shortfall. This is the same split Level 10
introduced: 1 means *the thing measured is not good enough*, 2 means *the
measurement could not be taken* — an unreadable dataset, a missing fixture, an
analyzer that raised.

### C-9 — An analyzer that raises fails the run (C-03)
A case whose analysis raises is recorded as an error and exits 2. It is not
scored as zero findings: "the analyzer crashed" and "the analyzer found
nothing" are different facts, and only one of them is a measurement
(the same rule Level 9 applied to the review path).

### C-10 — The result is emitted as markdown and as JSON (C-02)
Markdown for a human reading a CI log, JSON for a pipeline that wants to plot
F1 over time. The JSON is the artefact that makes "continuous optimisation"
mean something later.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | An expectation matched exactly yields one true positive | Unit test |
| AC-2 | A line within tolerance matches; outside it does not | Unit test |
| AC-3 | Two eligible findings resolve to the closest line, deterministically | Unit test |
| AC-4 | A severity mismatch counts as a false negative and consumes the finding | Unit test |
| AC-5 | An unexpected in-scope finding is a false positive | Unit test |
| AC-6 | An out-of-scope finding is ungraded, and its rule id is reported | Unit test |
| AC-7 | A forbidden finding is a false positive even when out of scope | Unit test |
| AC-8 | Precision, recall and F1 are correct, including the empty and zero-division cases | Unit + property test |
| AC-9 | Per-rule matrices sum to the overall matrix | Property test |
| AC-10 | The dataset loader reads a case directory, and rejects a malformed case | Unit test |
| AC-11 | A case naming a missing fixture exits 2 | Unit test on the CLI |
| AC-12 | An analyzer raising on a case exits 2 | Unit test |
| AC-13 | Scores below the threshold exit 1 and name the shortfall | Unit test on the CLI |
| AC-14 | Scores at or above the threshold exit 0 | Unit test on the CLI |
| AC-15 | The shipped dataset scores at or above the thresholds committed to CI | Dataset test |
| AC-16 | The evaluation gate runs in CI | `.gitlab-ci.yml`, GitHub workflow |
| AC-17 | The five checks stay green and coverage holds at its floor | `ruff`, `mypy`, `pytest --cov`, audit |

## Decisions taken

**D-1 — Grading lives in the domain.** Whether a produced finding satisfies an
expectation is a rule about findings, not about files or YAML. It needs no
filesystem, no model and no analyzer to test. `domain/evaluation.py` sits
beside `gate.py` for the same reason: both turn findings into a verdict.

**D-2 — The dataset is data on disk, not Python.** A case written as a test
function can only be run by the test runner, and cannot be extended by someone
who is not editing this repository. YAML cases beside fixture files can be
generated, contributed and — eventually — exported from a real review. That is
the difference between a fixture set and a dataset.

**D-3 — Scope defaults to everything.** The permissive default is the strict
direction: a case that says nothing grades every finding the suite produces,
so an author must actively narrow the scope and the narrowing shows up as an
ungraded count. Defaulting to "grade only what is listed" would have made a
noisy analyzer invisible by omission.

**D-4 — Thresholds are set from the measured baseline.** Committing an
aspirational F1 that the suite does not meet would leave CI red on day one and
train everyone to pass `--no-eval`. The committed floor is what the analyzers
score today, minus a margin; raising it is the next level's work, and lowering
it to make a build green is the thing this level exists to prevent.

**D-5 — A separate console entry point, not a subcommand.** `ai-code-review`
is invoked by pipelines with a fixed argument list. Converting its parser to
subcommands would break every one of them for no gain. `ai-code-review-eval`
is a second entry point over the same package.

**D-6 — The harness grades static analysis only, for now.** The `StaticAnalysis`
port is what it drives, so the evaluation service is model-free, network-free
and fast enough to run on every push. When Level 15 introduces specialist
agents, they arrive behind a port too, and the same harness grades them without
changing shape.
