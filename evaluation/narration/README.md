# The narration corpus

Fourteen cases. Each pairs a file the reviewer was looking at with the prose it
produced about it, and the checks in
[`domain/narration.py`](../../code_reviewer/domain/narration.py) grade the
second against the first.

## What these recordings are, and are not

**They are authored, not captured from a model endpoint.** This repository's CI
has no model, deliberately — Level 12 refused to put one in the loop of a
measurement, and Level 21 refuses it again for the same reason. Every review
here was written by hand in the format the system prompt asks for, to exercise
one behaviour each.

That is stated plainly because the alternative is a corpus that looks like
evidence about a model and is not. What this corpus *does* measure honestly:

- that each check fires when it should and stays quiet when it should not —
  five of the cases declare, in `expect_failures`, the check they are built to
  break;
- that a prompt edit which drops a section, or a rewrite of a check, changes a
  number somebody sees.

What it does not measure: how often a real model actually hallucinates a
citation. That needs recordings from a live endpoint, and until they exist the
`prompt_fingerprint` of every case here is empty — which the report counts as
**stale**, in the column that exists to stop a floor being held by recordings
nobody can attribute.

## Recording a real one

With an endpoint configured:

```
ai-code-review --project-id … --mr-iid … --dry-run   # produces the comment
```

Take the model's section for one file, save it under `review:`, set `file:` to
the path it was about, list the findings the analyzers reported for that file,
and set `prompt_fingerprint:` to the digest the run recorded (it is in the
comment's accountability block, and in the decision record).

## Adding a case

```yaml
name: some-behaviour
file: fixtures/some_file.py
prompt_fingerprint: b6b17025f0c5      # optional; empty means "stale"
expect_failures:                       # optional; omit for a review that should pass
  - citations_are_grounded
findings:                              # what the analyzers reported for that file
  - rule: SAST.SQL_INJECTION
    line: 11
    severity: critical
    title: SQL Injection
review: |
  ## 🔒 Security Analysis
  …
```

The loader is strict: an unknown key, a missing fixture, a finding with no
severity and a review carrying credential-shaped text all refuse to load rather
than becoming a case that grades less than it appears to.
