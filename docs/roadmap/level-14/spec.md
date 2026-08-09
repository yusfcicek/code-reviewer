# Level 14 — Long-term memory across reviews

## Problem statement

Every review starts from zero.

`SmartMemoryStrategy` carries findings from one *file* to the next inside a
single run, and then the process exits and takes everything with it. The agent
that reviewed this repository yesterday and the one reviewing it today share
nothing at all.

The cost of that shows up in four places.

- **A rule that fires on every merge request looks new every time.** Nothing
  distinguishes "this file has a hardcoded secret" from "this file has had a
  hardcoded secret reported on it eleven times and nobody has acted on it". The
  second sentence is a different, and more useful, review comment (C-08).
- **A settled argument is re-litigated.** A team suppresses a rule on a line
  with a written reason. The next review has never heard of it — the
  suppression still works, but the report says nothing about it having been a
  deliberate decision six weeks ago, so the same conversation happens again.
- **The agent cannot say what is normal for this project.** "This is the third
  time a resource leak has been reported in `storage/`" is a claim only a
  system with a history can make, and it is exactly the kind of claim a
  reviewer is paid for.
- **Nothing improves with use.** A tool that has run 400 times on a repository
  should know something the tool that ran once does not. Today it does not.

Capabilities addressed: **C-08**.

## Goals

1. What a review found survives the process, keyed to the repository it found
   it in.
2. The next review recalls what is relevant to the files it is looking at, and
   the reviewer is told.
3. Repetition is visible: a finding that has been reported before is marked as
   recurring, with how often and since when.
4. Memory forgets. A fact nobody has seen for a long time stops competing with
   one from last week.

## Non-goals

- **Memory changing the verdict.** The gate decides from findings
  ([ADR 0004](../../adr/0004-findings-drive-the-gate.md)), and it will keep
  doing so. A recurring finding is not more severe than a new one; it is more
  *interesting*, and that belongs in the prose and the report, not in the exit
  code. The opposite — letting a long history downgrade a finding — is the
  failure mode where a tool learns to stop complaining.
- **Storing anything the contributor wrote.** Remembered facts are identifiers
  and counts: rule id, path, line, severity, and how many times. No evidence
  lines, no diff excerpts, no model prose. A memory file that accumulates
  attacker-controlled text is an injection channel with a longer half-life
  than a prompt, and it would also quietly collect whatever secret a diff
  happened to contain.
- **A database.** One JSON file per repository, written atomically. A review
  agent that requires a datastore to be provisioned before it can run is a
  review agent nobody rolls out.
- **Cross-repository learning.** What is normal in one codebase is not
  evidence about another, and a shared memory is a way to leak one team's file
  names into another team's review.
- **Semantic search over the memory.** See D-2.

## Behavioural contracts

### C-1 — A remembered fact has an identity, and repeats consolidate (C-08)
A recollection is identified by what kind it is, which file it concerns and
which rule produced it. Seeing the same fact again increments its count and
moves its "last seen" forward; it does not append a second entry. Memory that
grows linearly with the number of reviews is a log, not a memory.

### C-2 — Salience is occurrences discounted by age (C-08)
How much a recollection deserves the reviewer's attention is its number of
occurrences, decayed by how long it has been since it was last seen, and
weighted by the severity it carried. Two facts seen the same number of times
are ordered by which is more recent.

### C-3 — Memory forgets (C-08)
Below a salience floor, a recollection is dropped. The store is also bounded:
past a maximum, the least salient are forgotten first. A memory with no
forgetting is a file that grows until someone deletes it, and the thing they
delete is the whole history rather than the stale part of it.

### C-4 — Recall is scoped to the files under review (C-08)
The reviewer is given what is remembered about *this* file, plus what is
remembered about the directory it is in, ranked by salience and capped. The
whole memory is not injected into every prompt; that is how a context window
gets spent on the wrong repository.

### C-5 — Recollections reach the prompt as identifiers, not as prose
They are rendered as a compact table of rule, location, count and age, inside
the trust boundary like everything else. Nothing in a recollection originates
with the contributor (see non-goals), and rendering them inside the boundary
anyway is cheaper than being wrong about that later.

### C-6 — A recurring finding is marked in the report (C-08)
A finding whose rule and location have been reported before is annotated with
how many times and since when. The severity is unchanged and the gate is
unchanged: this is information, not a verdict.

### C-7 — A suppression is remembered as a decision (C-08)
When a `review-ignore` directive silences a rule, that is recorded with its
reason. A later review can then state that the rule is deliberately silent
here and why, instead of leaving the next reader to find the comment.

### C-8 — Memory never blocks a review (C-08)
An unreadable store, a corrupt file, a disk that will not accept a write: each
is logged and the review proceeds. This is retrieval's rule, not analysis's —
a review with no history is exactly what every review before Level 14 was.

### C-9 — Writing is atomic, and a corrupt file is not fatal
The store is written to a temporary file and moved into place, so a run killed
mid-write leaves the previous memory intact rather than a truncated one. A file
that cannot be parsed is reported and treated as empty; it is not deleted, so
whoever wants to look at it still can.

### C-10 — Memory is optional and switchable off
`--no-memory` runs the agent exactly as Level 13 left it, and `--memory-path`
says where the file lives. A team that does not want a state file in its
checkout must be able to say so in one flag.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | Two occurrences of one fact consolidate into one entry with a count of two | Unit test |
| AC-2 | Consolidation keeps the earliest first-seen and the latest last-seen | Unit test |
| AC-3 | Salience rises with occurrences and falls with age | Unit + property test |
| AC-4 | A CRITICAL recollection outranks an INFO one seen equally often | Unit test |
| AC-5 | A recollection below the floor is forgotten | Unit test |
| AC-6 | A store past its cap keeps the most salient | Unit + property test |
| AC-7 | Recall returns this file's facts before its directory's | Unit test |
| AC-8 | Recall is capped and ordered by salience | Unit test |
| AC-9 | A suppression is recorded with its reason and rule | Unit test |
| AC-10 | A recurring finding is marked in the report with its count | Unit test on the renderer |
| AC-11 | The gate result is identical with and without memory | Unit test |
| AC-12 | Recollections reach the prompt inside the trust boundary | Unit test on the agent |
| AC-13 | No evidence line, diff excerpt or model prose is ever stored | Unit test on the store |
| AC-14 | A corrupt store file is reported and treated as empty, not deleted | Unit test |
| AC-15 | A failed write leaves the previous file intact | Unit test |
| AC-16 | A store that raises does not fail the review | Unit test on the workflow |
| AC-17 | `--no-memory` produces the Level 13 behaviour exactly | Unit test on the CLI |
| AC-18 | The six checks stay green, coverage holds, the eval floors hold | `ruff`, `mypy`, `pytest --cov`, audit, eval |

## Decisions taken

**D-1 — Memory lives in the domain; the file does not.** Whether two facts are
the same fact, how salience is computed, and what is forgotten are rules about
review history. They need no filesystem and every edge case in them is
arithmetic. Reading and writing JSON is an adapter.

**D-2 — Memory is a keyed store, not a second index.** The roadmap said this
level would "reuse Level 13's index rather than inventing a second one". On
contact with the problem that was wrong, and it is worth saying why rather than
quietly doing something else. Recall here is a *lookup* — what is known about
`storage/repository.py`, and about `storage/` — over a few hundred entries with
exact keys. Embedding them to answer a question their key already answers would
be slower, fuzzier and impossible to explain in a report. Level 13's index
answers "what code is like this"; this answers "what happened here before", and
they are different questions with different access patterns.

**D-3 — Only identifiers are stored.** Rule id, path, line, severity, counts,
timestamps, and a suppression's written reason. Never an evidence line, never a
diff excerpt, never model output. Two reasons, and either alone would be
enough: a diff is attacker-controlled, so a memory file that accumulates it is
a stored injection with a long half-life; and a diff may contain a secret, so a
memory file that accumulates it is a secret store nobody declared.

**D-4 — Memory informs; it never decides.** No recollection changes a severity,
a gate result or an exit code. The tempting version of this feature —
"downgrade a finding the team has ignored 11 times" — is a tool learning to
stop complaining, and the honest reading of eleven ignored reports is that
either the rule is wrong or the debt is real. Both of those are decisions for a
person.

**D-5 — Decay is exponential in days, with a half-life.** Linear decay makes an
old fact worth zero at an arbitrary point; a half-life says "this matters half
as much every N days" and never quite reaches zero, so the floor is what
forgets rather than the arithmetic.

**D-6 — One file per repository, written atomically.** A temporary file and a
rename, so a run killed mid-write leaves the previous memory rather than a
truncated one. No lock: two reviews of the same repository racing will have one
overwrite the other's increment, and losing one count from a decaying score is
not worth a lock file that can be left behind.
