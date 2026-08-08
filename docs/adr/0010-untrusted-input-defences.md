# 10. Untrusted input is defended in four layers, and a refusal is a finding

- **Status**: Accepted
- **Level**: [8](../roadmap/level-8/spec.md)

## Context

The agent's input is written by whoever opened the merge request. That is not a
weakness in the design; it is the design. Everything else follows from taking
it seriously.

Before Level 8 the code took it seriously in exactly one place: `Workspace`
refused paths outside the repository root. That answers *where* the agent may
read. It leaves four other questions unanswered.

The diff went straight into the user message with nothing marking it as data,
so the model's instruction channel and the reviewed content were one channel.
The review text went to a CI log and a public comment unfiltered, so anything
the agent read it could publish. Inside the root, `.env`, `id_rsa` and `*.pem`
were readable, there was no cap on total volume, and no record of what had been
attempted. And a model-supplied `grep` pattern was executed as a regular
expression.

## Decision

Four layers, each of which assumes the ones around it have failed:

1. **Delimitation.** Reviewed content is wrapped in `<untrusted_diff>` and
   `<untrusted_file_content>`, both tag forms escaped inside the content, with
   a trust-boundary section at the top of the system prompt.
2. **Deny-list and budget.** File access is refused by *name* as well as by
   location, and the total volume one review may read is capped.
3. **Fixed-string search.** `grep` runs with `-F` after `--`, bounded, with
   credential-bearing files excluded, and the pattern validated first.
4. **Redaction.** The review text is masked on the way out — values from the
   process environment first, then known secret shapes.

And a fifth thing, which is the one that is not merely defensive:

**A refused access is a `Finding`, at `CRITICAL`, in the `SECURITY` category.**

## Consequences

- An injection attempt can **fail a pipeline**. That is the intent: prose warns
  and findings block ([ADR 0004](0004-findings-drive-the-gate.md)), and "the
  agent was talked into asking for `/etc/passwd`" is a fact about the merge
  request, not a stylistic observation about the review.
- The layers are independent. Delimitation is a request to a model that can be
  talked into anything; the deny-list is not a request. If the first fails the
  fourth still runs, and the model being persuaded does not persuade the
  filesystem.
- `Workspace` reaches the workflow through a new `AccessAuditor` port. The
  application layer may not import infrastructure, and the port carries
  records rather than findings: translating into a domain type belongs to the
  layer that owns the domain.
- `.env.example` is refused along with `.env`, because the glob cannot tell
  them apart. A review that skips an example file is worth less than a leaked
  real one.
- Redaction can in principle mangle a legitimate review. The value layer has a
  length floor and the shape patterns are anchored, and a test asserts ordinary
  prose survives — because a redactor that mangles reviews gets switched off,
  and a switched-off redactor protects nothing.

## What is still not defended

Stated because a threat model that lists only its wins is not a threat model.

- A model that is persuaded to *misjudge* the code. Nothing here makes the
  narration trustworthy; the architecture handles that by not letting the
  narration decide anything ([ADR 0004](0004-findings-drive-the-gate.md)).
- A secret whose shape is unknown and whose value this process does not hold.
- Exfiltration through the review text itself — the model can describe what it
  legitimately read. The deny-list narrows what "legitimately" covers; it does
  not close this.
