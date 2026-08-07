# 1. MIT licence

- **Status**: Accepted
- **Level**: [0](../roadmap/level-0/spec.md)

## Context

The imported repository contained the GNU GPL v3 in `LICENSE` while `README.md`
linked that file as "MIT License" and `pyproject.toml` declared no licence at
all. Three sources, two answers.

The repository had no publication history — Level 0 created its first commit —
so no third party had relied on either text.

## Decision

The project is MIT licensed. `LICENSE` carries the MIT text, `pyproject.toml`
declares `license = "MIT"`, and README links to it.

README's link was the clearest statement of intent, and a permissive licence
matches a tool designed to be embedded in other organisations' pipelines: a
copyleft licence on a CI component raises questions about the code it reviews
that nobody wants to answer.

## Consequences

- Anyone may embed the agent in a proprietary pipeline.
- If the GPL text was deliberate, this is the one decision that must be
  reverted before publication, and reverting it is a single file.
- Contributions are accepted under MIT.
