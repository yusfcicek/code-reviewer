# Level 11 — Verification Depth

## Problem statement

Ten levels of work have made the agent stricter at every turn. Nothing has yet
answered the two questions that strictness raises: *what happens when it is
wrong*, and *does it hold against real code rather than fixtures*.

- **There is no way to suppress a finding.** Every static analyzer produces
  false positives; one that does not is not looking hard enough. Faced with a
  rule that misfires on one line, a team has two options today: turn the rule
  off in the policy, or stop the gate from blocking. Both end the tool's
  usefulness, and both are reached by a team that would have accepted a
  narrower answer (G-07).
- **The agent has never been run against itself.** Every analyzer test uses a
  fixture written to trigger it. Nothing checks the analyzers against a real
  codebase, which is where a rule that fires on every third line becomes
  visible (G-16).
- **No test generates its own input.** Triage and the semantic analyzer read
  attacker-controlled diffs, and malformed input is free to produce. Every
  case they are tested against was imagined by someone (G-17).
- **Two layers are type-checked and none is checked for security patterns.**
  `mypy` covers `domain` and `application`. `infrastructure` — where every
  subprocess call, every path construction and every network client lives — is
  not checked at all. `ruff`'s rule selection covers style, bugs and
  simplification, but not `S`, the family that notices exactly the constructs
  that layer is full of (G-18).

Gaps addressed: **G-07, G-16, G-17, G-18**.

## Goals

1. A false positive can be silenced narrowly, with a reason, and the silence
   is counted rather than invisible.
2. The codebase passes its own gate, and that fact is checked on every push.
3. The components that read untrusted input are tested against input nobody
   wrote by hand.
4. The layer that touches the operating system is type-checked and
   security-linted.

## Non-goals

- **Suppression by severity, by file glob in policy, or with an expiry.** Each
  is a way to silence more at once, which is the failure mode being guarded
  against. One line or one file, named rule, written reason.
- **Making `mypy` strict everywhere.** The five analyzers carry type debt from
  the imported prototype, and closing it in one pass would change behaviour in
  branches with no tests. They are checked, not made strict, and the exemption
  is recorded.
- **Fixing every finding dogfooding surfaces.** A genuine finding is its own
  work item. What this level owes is that the finding is *visible*, not that
  it is resolved by suppressing it.

## Behavioural contracts

### C-1 — A finding can be suppressed at one line (G-07)
A comment carrying `review-ignore: RULE_ID - reason` suppresses a finding for
that rule, at that line. When the comment stands alone on its own line, it
covers the line *following* it, so a directive can sit above the code it
explains rather than trailing it.

`RULE_ID` may name a rule (`SAST.SQL_INJECTION`) or a namespace
(`SAST.*`). `*` alone is not accepted: a directive that suppresses everything
is the second way to disable the tool, arriving through a different door.

### C-2 — A finding can be suppressed for a whole file (G-07)
`review-ignore-file: RULE_ID - reason`, anywhere in the file, suppresses that
rule throughout it. This is what a vendored tree or a generated module needs,
and it is deliberately more visible than the per-line form.

### C-3 — A suppression carries a reason (G-07)
The text after the separator is captured and reported. A directive without one
still suppresses — refusing to would mean a syntax error silently becomes a
blocking finding — but it is reported as unexplained, and the dogfooding test
refuses to accept any.

### C-4 — Suppressed findings are counted, not discarded (G-07)
The analysis result carries what was kept *and* what was suppressed, with the
directive that silenced each. The report states how many were suppressed. A
suppression nobody can see is indistinguishable from a rule that never fired.

### C-5 — The package passes its own gate (G-16)
A test runs the full analysis suite over every module in `code_reviewer/` and
asserts the result is not blocking, with no `CRITICAL` and no `HIGH` findings.
It also caps the number of suppressions and requires every one to carry a
reason, so "passing" cannot be reached by accumulating silences.

### C-6 — Arbitrary diff-shaped input raises nothing (G-17)
Property-based tests generate diff-like text and assert that triage and the
semantic analyzer return a result rather than an exception. "Never raises" is
a weak property, which is what makes it the right one: cheap to state, cheap
to check, and a violation is always a real bug — an exception in either costs
the file its entire review, and after Level 9 it blocks the pipeline.

### C-7 — The whole package is type-checked (G-18)
`mypy` runs over `code_reviewer/`. `domain` and `application` keep their
current settings; `infrastructure` is checked at the default level. Anything
that cannot be typed carries a narrow `type: ignore` with the reason.

### C-8 — Security lint rules are on (G-18)
`ruff`'s `S` family is selected. Findings are fixed where they are real and
exempted with a written reason where they are not — a `# noqa: S…` with no
comment is the same failure as a suppression with no reason.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | A trailing `review-ignore` suppresses the finding on its line | Unit test |
| AC-2 | A standalone `review-ignore` comment covers the next line | Unit test |
| AC-3 | A namespace glob `SAST.*` matches every SAST rule | Unit test |
| AC-4 | A bare `*` is rejected | Unit test |
| AC-5 | An unrelated rule at the same line is not suppressed | Unit test |
| AC-6 | `review-ignore-file` covers every line of the file | Unit test |
| AC-7 | The reason is captured and reported | Unit test |
| AC-8 | Suppressed findings are returned alongside kept ones | Unit test on the suite |
| AC-9 | The report states the suppression count | Unit test on the renderer |
| AC-10 | The package passes its own gate | Dogfooding test |
| AC-11 | Suppressions in the package are capped and each carries a reason | Dogfooding test |
| AC-12 | Arbitrary diff input makes neither triage nor the semantic analyzer raise | Property test |
| AC-13 | `mypy code_reviewer` is clean | CI |
| AC-14 | `ruff check` with `S` selected is clean | CI |
| AC-15 | The five checks stay green and coverage holds at its floor | `ruff`, `mypy`, `pytest --cov`, audit |

## Decisions taken

**D-1 — Suppression lives in the domain.** Whether a directive covers a
finding is a rule of code review, not an adapter concern, and it is testable
without a filesystem or a model. This mirrors `domain/triage.py`, which parses
diffs for the same reason: the parsing is not incidental to the rule, it *is*
the rule's interface.

**D-2 — The scope is one line or one file. Nothing else.** A directive that
takes a range, a severity or a glob of paths is a lever for silencing work
someone has not read. The narrow form makes the cost of a suppression
proportional to what it silences, which is what keeps it honest.

**D-3 — A missing reason suppresses but is reported.** The alternative —
refusing to honour a directive without a reason — turns a typo into a blocking
finding at the exact moment someone is trying to unblock themselves. The
pressure to write reasons belongs in the dogfooding test and in review, not in
a parser.

**D-4 — `StaticAnalysis.analyze` returns a result object, not a list.** The
port's honest contract is now "what I found *and* what I was told to ignore",
and a second method would leave two ways to call it with one of them lossy.
The churn is contained: one implementation and a handful of test fakes.

**D-5 — Dogfooding asserts no HIGH, not zero findings.** A codebase with no
low-severity findings at all would mean the analyzers are not looking, and the
test would then be pinning the wrong thing. The cap on suppressions is what
stops the assertion being met by silence.

**D-6 — `mypy` is widened, not made strict.** Widening finds real errors
today. Making `infrastructure` strict would produce hundreds of annotation
requirements on inherited analyzer code, and a level that ends in a
thousand-line annotation diff has stopped being about verification.
