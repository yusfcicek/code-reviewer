# Level 15 — Plan

Branch: `feature/level-15-orchestration`, off `development`, merged with
`--no-ff`.

## Step 1 — What a specialism is

*Tests* — `tests/unit/domain/test_specialism.py`

- Each specialism declares a name, a weight and the tools it may call.
- `ARCHITECTURE` is the generalist: it owns the summary, and its tool set is a
  superset of nothing in particular — it is declared, not derived.
- The weights are positive and the security weight is the largest, because the
  spec says budget must be spendable where it matters and a table that does not
  say so is a table nobody checked.
- Tool sets are disjoint from each other only where that is meaningful:
  `read_file` is available to all, `run_sast_scan` only to security. Asserted
  explicitly so a later edit that widens one is visible in a diff.

*Change* — `code_reviewer/domain/orchestration.py`: `Specialism`, and the
`SPECIALIST_TOOLS` / `SPECIALIST_WEIGHTS` tables beside it.

## Step 2 — Who reviews what

*Tests* — `tests/unit/domain/test_assignment.py`

- AC-1: a finding of category `SECURITY` assigns the security specialist.
- AC-2: a manifest path assigns the dependency specialist, with no findings
  needed — the file *is* the evidence.
- AC-3, AC-4: architecture is always assigned, and alone when nothing else
  applies.
- `PERFORMANCE` findings assign the performance specialist.
- A `DEPENDENCY` finding assigns the dependency specialist even in a non-manifest.
- Assignment is idempotent: two security findings assign one security specialist.
- Assignment order is fixed, and the returned plan is a tuple.

*Change* — `plan_assignments(file_path, findings) -> tuple[Specialism, ...]`.

## Step 3 — The budget split

*Tests* — `tests/unit/domain/test_budget.py`

- AC-5: the split sums to the total.
- AC-5: nobody assigned gets zero, even when the total is small and the
  assignment is large.
- Security's share exceeds architecture's for the same total, which is the
  whole point of a weight.
- A remainder is given to the heaviest specialism rather than dropped, because
  a split that loses tokens is a split someone will debug on a Friday.
- Property: for any total ≥ the number of specialists, every share ≥ 1 and the
  shares sum to the total.
- A total below the number of specialists is refused rather than producing
  zeros — that is a misconfiguration, not a rounding case.

*Change* — `split_budget(total, specialisms) -> dict[Specialism, int]`.

## Step 4 — What an agent reports, and how the report is composed

*Tests* — `tests/unit/domain/test_agent_report.py`

- An `AgentReport` carries its specialism, its prose, its cost and whether it
  succeeded.
- A failed report carries a reason and no prose.
- AC-5 (spec C-5): `compose(reports)` orders sections architecture, security,
  performance, dependency — asserted against a shuffled input.
- AC-7: a failed specialist appears as a stated failure, not as an omission.
- AC-8: every specialist failing composes into a document that says so.
- The composition names each section, so a reader can tell which agent said
  what — an unattributed paragraph is the thing multi-agent review is supposed
  to stop producing.
- Composing nothing returns a stated "no agent produced a review" rather than
  an empty string.

*Change* — `AgentReport`, `AgentOutcome`, `compose`.

## Step 5 — The handoff protocol

*Tests* — `tests/unit/domain/test_handoff.py`

- A `Handoff` carries a target specialism and a written reason.
- AC-9: a handoff to an unrun specialism is accepted.
- AC-10: a handoff to one already run is refused, with the refusal recorded.
- AC-11: `accept_handoffs(requests, already_run, depth)` refuses everything at
  depth 1 — the depth is structural, not a counter (decision D-3).
- AC-12: a handoff naming a specialism that does not exist is refused and
  recorded.
- Duplicate requests in one round collapse to one acceptance.
- AC-13 (property): for any set of requests and any already-run set, the
  accepted set is disjoint from the already-run set and no larger than the
  number of specialisms.

*Change* — `Handoff`, `HandoffDecision`, `accept_handoffs`.

## Step 6 — The port and the orchestrator

*Tests* — `tests/unit/application/test_orchestrator.py`

- AC-16: `ReviewOrchestrator` satisfies `Reviewer` and returns a composed
  report.
- Each assigned specialist is called once, with its own budget and its own
  assignment.
- AC-7: a specialist that raises is recorded as failed; the others still run
  and appear.
- AC-9/AC-10/AC-11: an accepted handoff runs the target once; a refused one is
  reported and nothing runs.
- A specialism with no registered specialist is skipped with a stated reason
  rather than an exception — a composition root that forgot to wire one should
  produce a legible report, not a crash.
- The retrieved context and the recalled memory reach every specialist.

*Change* — `Specialist` port in `application/ports.py`;
`application/orchestration_service.py` with `ReviewOrchestrator`.

## Step 7 — The specialist agent

*Tests* — `tests/unit/infrastructure/test_specialist_agent.py`

- AC-14: the security specialist is offered the security tools and not the
  others.
- Its system prompt names its specialism and states the trust boundary — the
  boundary is not something one of four agents may forget.
- It reports a handoff when its response asks for one, in a stated syntax, and
  reports none when the response does not.
- A response that asks for a handoff to nothing in particular is not a handoff.
- Its budget is the one it was given, not the environment's.

*Change* — `infrastructure/llm/specialist_agent.py`.

## Step 8 — Wiring, metrics and the switch

*Tests* — `tests/unit/test_main_wiring.py` (extended),
`tests/unit/infrastructure/test_metrics.py` (extended),
`tests/unit/test_cli.py` (extended)

- AC-17: `--single-agent` builds the Level 14 reviewer.
- The default builds the orchestrator with all four specialists.
- AC-15: per-agent cost reaches the metrics export, labelled by specialism.

*Change* — `cli.py`, `__main__.py`, `metrics/collector.py`,
`application/review_service.py` (carrying the per-agent costs out).

## Step 9 — Documentation

- `docs/adr/0017-an-orchestrator-of-specialists-not-a-framework.md`: D-1, D-3,
  D-4.
- `docs/ARCHITECTURE.md`: the orchestration path, the new port.
- `README.md`: the four specialists, the routing table, the switch.
- `CHANGELOG.md`, `docs/roadmap/README.md`.

## Order and rationale

Steps 1–5 are the entire orchestration logic and none of the models: routing,
budget arithmetic, composition order and the handoff protocol are all decided
against lists and enums before anything can call an LLM. That matters more here
than in any previous level, because the failure mode of multi-agent systems is
that nobody can say what the system will do — and every one of those questions
is answerable here by reading a pure function.

Step 6 is where it becomes a `Reviewer`, and step 7 is the only part that talks
to a model. Step 8 is last because the switch between one agent and four is
only meaningful once both exist.
