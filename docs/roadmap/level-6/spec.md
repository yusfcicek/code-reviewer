# Level 6 — Documentation and Productisation

## Problem statement

The code is correct, layered, analysed, observable and gated. What is missing is
everything a person needs to *arrive* at it:

- **The codebase speaks two languages.** Ten modules carry Turkish docstrings
  and comments while the newer code, the README, CONTRIBUTING and every commit
  message are in English. A reader hits the boundary mid-file. Worse, some
  Turkish comments describe behaviour that four levels of work have since
  changed, so they are not merely inconsistent — they are wrong (F-54).
- **There is no architecture document.** The layering exists and a test
  enforces it, but a newcomer has to infer the design from the directory names.
  The reasons for it — why the gate takes findings over prose, why analyzers sit
  in infrastructure, why there is a `CodeForge` port — live in commit messages
  nobody will find (F-46).
- **Decisions have no home.** Level specs record decisions inside the level that
  made them, so a decision taken in Level 1 and still binding in Level 5 is
  three documents away from where it matters.
- **No `SECURITY.md`.** A tool that reads a repository, executes static
  analysis on attacker-influenced input and posts to a public comment thread
  has a threat model worth stating, and no way for anyone to report a hole in
  it (F-46).
- **No `CHANGELOG.md`.** Six levels changed the licence, the package name, the
  CLI entry point and the metric fields. Anyone upgrading has no list (F-46).

Findings addressed: **F-46, F-54**.

## Goals

1. One language throughout the source: English.
2. A reader can understand the architecture and its reasons without reading git
   history.
3. The decisions that still bind are in one place, each with its context and its
   consequences.
4. The security posture and the reporting route are stated.
5. The breaking changes across six levels are listed.

## Non-goals

- Translating the roadmap's level specs. They are a record of how the work went,
  written in English already.
- API reference documentation. The docstrings are the reference; a generated
  site is not worth its maintenance at this size.

## Behavioural contracts

### C-1 — The source is in English (F-54)
No Turkish remains in `code_reviewer/`. Translation is not mechanical: each
comment is checked against what the code does *now*, because several describe
behaviour that Levels 1–5 changed. A comment that is wrong gets corrected, not
translated.

### C-2 — The architecture is documented (F-46)
`docs/ARCHITECTURE.md` covers the layers and their dependency rule, the ports
and their adapters, the path a review takes from a merge request to a verdict,
and where a new analyzer, forge or model provider would go.

### C-3 — Decisions are collected (F-46)
`docs/adr/` holds one file per decision that still binds, in the standard form:
context, decision, consequences. Each links to the level that made it.

### C-4 — The threat model is stated (F-46)
`SECURITY.md` covers what the agent reads, what it can be made to read by
someone who can open a merge request, what confines it, what it posts publicly,
and how to report a vulnerability.

### C-5 — Breaking changes are listed (F-46)
`CHANGELOG.md` follows Keep a Changelog, with one entry per level and an
explicit "Breaking" section: the licence, the import package, the console
script, the removed metric fields.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | No Turkish text in `code_reviewer/` | A test scanning for Turkish-specific characters and common words |
| AC-2 | `docs/ARCHITECTURE.md`, `SECURITY.md`, `CHANGELOG.md` exist and are linked from README | A test checking the links resolve |
| AC-3 | `docs/adr/` contains an ADR per binding decision, each with context, decision, consequences | Same test |
| AC-4 | Every internal Markdown link in the repository resolves | Same test |
| AC-5 | All four checks stay green | `ruff`, `mypy`, `pytest` |

## Decisions taken

**D-1 — English, not Turkish.** The choice is not about which language is
better; it is that a codebase in two languages is worse than one in either. The
project's public surface — README, CONTRIBUTING, commit messages, the review
output the agent posts — is already English, and its dependencies and the
patterns it uses are documented in English. Moving the ten remaining modules is
the smaller change.

**D-2 — Comments are re-derived, not translated.** Several Turkish comments
describe pre-Level-1 behaviour: the gate that could not block, the policy that
was never loaded, the memory context the model never saw. Translating them would
produce fluent English lies. Each is read against the current code.

**D-3 — ADRs are extracted, not invented.** Every ADR records a decision already
taken and already implemented. Writing an ADR for a decision that has not been
made turns the directory into a wish list.

**D-4 — A link test rather than a link checker in CI.** A unit test that walks
the Markdown and resolves relative links needs no network and fails on a laptop.
Checking external URLs would make the suite depend on the internet.
