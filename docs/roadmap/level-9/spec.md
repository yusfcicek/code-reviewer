# Level 9 — Fail-Closed Decisions

## Problem statement

Four places where the code, on encountering something it does not understand,
answers *"fine, then"*. Each of them points the same way: towards approval.

- **A crashed analyzer reads as a clean file.** `StaticAnalysisSuite` wraps
  each analyzer in `except Exception: return []`, and `ReviewService._analyse`
  catches a failure of the whole suite, logs it, and returns `None`. Either way
  the file produces zero findings, and zero findings is indistinguishable from
  "we looked and there was nothing" (G-09).
- **An unrecognised policy key is ignored.** The loader logs *"Ignoring unknown
  policy key"* and continues. `block_on_critcal: false` leaves the rule on
  under a name its author believes they turned off; the inverse typo leaves it
  on when they meant to disable it. In both cases the file no longer describes
  the running configuration, and nobody is told (G-10).
- **The same problem is reported twice.** `Finding` is a mutable dataclass, so
  it is neither hashable nor set-deduplicable, and the suite concatenates every
  analyzer's output. Two detectors that flag one line under one rule produce two
  findings — noise in the report, and inflated per-severity counts feeding the
  metrics export and the quality score (G-08).
- **A manifest can be auto-approved on size.** `TriagePolicy` has no notion of
  a file that must always be reviewed. A three-line edit to
  `.github/workflows/ci.yml` trips neither the security-pattern nor the
  API-removal check, falls through to `max_lines_for_auto: 10`, and the guard
  on that branch searches for `if`/`for`/`return`/`def`/`class` — which no YAML
  line contains. `- curl https://… | sh` added to a CI job is auto-approved
  without a model or an analyzer ever seeing it (G-11).

The first two are the same defect as F-01 and F-32 in this repository's own
inventory: a failure path that silently produces the permissive answer. The
fourth is the same shape, arriving through triage rather than through an
exception handler.

Gaps addressed: **G-08, G-09, G-10, G-11**.

## Goals

1. "We could not look" is never reported as "there was nothing to see".
2. A policy file either describes the running configuration or refuses to load.
3. One problem at one place under one rule is one finding.
4. Whether a file is reviewed is decided by what it is, not only by how much of
   it changed.

## Non-goals

- **Making the analyzers more accurate.** Deduplication removes a duplicate
  report of a real problem. Whether the problem is real is Level 11's business.
- **Suppression.** Namespaced rule ids land here because deduplication needs
  stable keys, but the `# review-ignore` mechanism they enable is Level 11.
- **Changing the default blocking severity.** `gate.blocking_severity` stays
  `critical`. This level changes what produces a finding, not how severe a
  finding has to be.

## Behavioural contracts

### C-1 — Rule ids are namespaced (G-08)
Every finding carries a `rule_id` of the form `NAMESPACE.RULE` —
`SAST.SQL_INJECTION`, `QUALITY.SRP`, `PERFORMANCE.N_PLUS_ONE`,
`SEMANTIC.BREAKING_CHANGE`, `SANDBOX.VIOLATION`. `Finding.namespace` exposes
the leading segment. A bare id has no namespace to match a glob against, which
is what Level 11's suppression will need.

### C-2 — `Finding` is immutable and hashable (G-08)
`Finding` is `frozen=True`. `metrics`, the one mutable field, becomes an
immutable mapping. Two findings with the same content are equal and hash alike,
so a set or a dict keyed on them behaves.

### C-3 — One rule at one location yields one finding (G-08)
`StaticAnalysisSuite.analyze` reduces findings keyed on
`(rule_id, file_path, line_number)`. Where two detectors disagree on severity,
the more severe survives; on a tie, the first. Deduplication happens before
sorting, so the ordering the caller sees is of the deduplicated set.

### C-4 — A failed analysis blocks (G-09)
The workflow distinguishes three states for a file, and they are not
interchangeable:

| State | Meaning | Effect |
|---|---|---|
| findings | analysis ran and found things | blocks per `gate.blocking_severity` |
| no findings | analysis ran and found nothing | passes |
| **analysis error** | analysis could not run | **blocks** |

`gate.fail_pipeline_on_analysis_error` governs the third and defaults to
`true`. The blocking reason names the file and the error.

A *narration* failure is deliberately not in that table: static analysis still
ran, the verdict is already known, and only the prose is missing. It warns. A
model that has run out of credit must not be able to stop a clean merge
request — that is how teams end up disabling the gate.

The per-analyzer `except` stays. One analyzer failing out of five is a
different event from the suite failing, and the four that ran are still
evidence.

### C-5 — Policy loading is fail-closed (G-10)
`ReviewPolicyLoader` raises `PolicyLoadError` for: a file named with `--policy`
that does not exist; unparseable YAML; a root that is not a mapping; an unknown
section; an unknown key within a section; a value of the wrong type. Each
message names the source file and the offending key.

The *implicit* discovery path stays permissive: finding no policy file at all
is a valid state that falls back to the bundled default. It is a file that
*says* something unrecognised that must fail. Silence is not a claim; a typo
is.

### C-6 — Manifests and pipeline definitions are always reviewed in full (G-11)
`TriagePolicy.manifest_patterns` names dependency manifests, lock files,
container definitions and CI configuration. A path matching one is decided
`FULL_REVIEW` regardless of diff size, checked after the security and API rules
and before every size rule.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | Every rule id emitted carries a namespace | Unit test over the suite's output |
| AC-2 | `Finding` is hashable and equal by value | Unit test |
| AC-3 | Two detectors on one line under one rule yield one finding | Unit test on the suite |
| AC-4 | The survivor of a dedup is the more severe | Unit test |
| AC-5 | An analyzer suite that raises marks the file unanalysed | Unit test on the workflow |
| AC-6 | An unanalysed file makes the outcome blocking under the default policy | Unit test |
| AC-7 | The blocking reason names the file and the error | Unit test |
| AC-8 | `fail_pipeline_on_analysis_error: false` makes it a warning | Unit test |
| AC-9 | A narration failure still only warns | Unit test |
| AC-10 | An unknown policy key raises, naming key and file | Unit test on the loader |
| AC-11 | An unknown section, bad YAML, and a wrong-typed value each raise | Unit test |
| AC-12 | No policy file at all still loads the bundled default | Unit test |
| AC-13 | A two-line change to `.github/workflows/ci.yml` reaches `FULL_REVIEW` | Unit test on triage |
| AC-14 | A two-line change to `package.json` reaches `FULL_REVIEW` | Unit test |
| AC-15 | The five checks stay green and coverage holds at its floor | `ruff`, `mypy`, `pytest --cov`, audit |

## Decisions taken

**D-1 — Namespaces are added at the adapter, not inside the analyzers.** Each
analyzer keeps its own enum and its own vocabulary; `StaticAnalysisSuite` is
already the anti-corruption layer that translates them into the domain type,
and the namespace is part of that translation. Rewriting five analyzers to
emit domain ids would be a large change with no behavioural gain, and their
own tests pin the current output (this is decision D-2 from Level 3, still
holding).

**D-2 — Dedup keys on location, not on message.** Two detectors describing the
same problem in different words — "used without `with`" and "may not be
properly closed" — are the case this exists for, and their messages differ by
construction. Keying on the message would deduplicate nothing.

**D-3 — Analysis failure blocks; narration failure warns.** The asymmetry is
the whole point and it follows from ADR 0004. Findings are the evidence; when
the evidence could not be gathered, the honest answer is "unknown", and for a
gate "unknown" must not mean "pass". Prose is not evidence, so its absence
costs nothing the decision needed.

**D-4 — Fail-closed on *content*, permissive on *absence*.** A missing policy
file is a deployment that has not configured one, which is a legitimate state
with a documented default. A policy file containing `block_on_critcal` is a
deployment that believes something false about itself. The first is silence;
the second is a wrong claim, and only the second is worth failing over.

**D-5 — Manifest matching is by path pattern, in policy.** Not a hard-coded
list in `triage.py`: which files a team considers supply-chain-critical varies,
and the mechanism that decides it belongs in the same file as the skip
patterns it mirrors.

**D-6 — `metrics` becomes a `MappingProxyType`, not a `frozenset` of items.**
The field is read as a mapping by the report renderer and the metrics
exporter. Changing its type would ripple; making it immutable does not.
