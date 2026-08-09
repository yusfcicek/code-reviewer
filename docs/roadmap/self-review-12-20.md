# Self-review of levels 12–20

Nine levels added twenty-four thousand lines. This is the pass that reads them
as an outsider would: not "does the test suite pass" — it does — but *what does
this claim, and is the claim true when nobody is looking*.

The rule applied throughout is the one this repository has held since Level 0:
**documentation may never claim behaviour the code does not have.** Three of the
findings below are exactly that failure, and two of them are in a README
sentence somebody would reasonably act on.

Findings are numbered `R-NN` and closed in severity order, one per iteration.
Each closed row names the commit that closed it.

| # | Severity | Where | What | Status |
|---|---|---|---|---|
| R-01 | 🔴 High | `serve.py` | Under `gunicorn` — the documented production command — nothing drains the review worker on `SIGTERM`. The drain is wired only into the `wsgiref` entry point. | open |
| R-02 | 🔴 High | `analyzers/suite.py` | An analyzer that raises contributes nothing, silently: no log, no warning in the comment, no field in the decision record. "Unknown" becomes "pass" with nothing saying so. | ✅ closed |
| R-03 | 🟠 Medium | `forge/gitlab_forge.py` | Exception text reaches the merge-request comment un-redacted. The model's prose is redacted; a failure message built from an exception is not. | ✅ closed |
| R-04 | 🟠 Medium | `__main__.py` | `--trace-path` has no test. `_export_trace` is tested directly; nothing asserts the flag reaches it. | open |
| R-05 | 🟡 Low | `concurrency/thread_pool.py` | The group deadline is deliberate, but a task that was about to return is reported "abandoned" once an *earlier* task in the batch has timed out. | open |
| R-06 | 🟡 Low | `http/app.py` | `_read_body` requires `Content-Length`; a chunked request is answered "a body is required". | open |
| R-07 | 🟡 Low | `http/app.py` | `route.auth is OPEN` compares strings by identity. True today because the table is built from the module constants, and silently false the day one is computed. | open |
| R-08 | 🟡 Low | `concurrency/thread_pool.py` | `run_all` is not safe against concurrent calls on one runner instance. A real constraint, documented nowhere. | open |

---

## R-01 — the drain that only works one of the two ways it is run

`README.md` and [ADR 0021](../adr/0021-a-deployment-that-is-tested.md) both say
SIGTERM drains: "the server stops, the review in flight gets a bounded wait, and
the log says which of 'finished' and 'gave up' happened."

That is true of `python -m code_reviewer.serve`, where `main()` calls
`install_signal_handlers` and then `drain`. It was not true of
`gunicorn code_reviewer.serve:create_app` — the command in the `Dockerfile` and
in the deployment manifest. `create_app` started the worker and registered
nothing; the worker thread is a daemon, so the interpreter exits without waiting
and the review in flight dies with its job stuck in `RUNNING`.

The claim was tested — against the entry point nobody deploys.

**Fix** — register the drain with `atexit` inside `create_app`, and by a
test that asserts the registration happens and that what it registered actually
drains the worker.

## R-02 — an analyzer that crashes is a silent pass

`StaticAnalysisSuite` wraps each analyzer in `except Exception: return []`. The
intent is stated and defensible — a syntax error in a half-finished branch is a
reason to say less, not to abort the review.

What was missing is that it said *nothing*. No log record, nothing in the
comment, nothing in the decision record. A security analyzer that crashed on
every file of a merge request produced a clean report, and
[ADR 0011](../adr/0011-unknown-means-blocked.md) — "unknown is not pass" — was
quietly not applied to the one case where it matters most.

**Fix** — name the analyzer that failed: a warning in the log, a line in
the comment's warnings block, and a field in the record. The verdict is
deliberately unchanged — see the decision recorded in the fix.

## R-03 — the one text that reaches the comment unredacted

Since Level 8 the model's output has been redacted on the way out, in two layers
(environment values first, shapes second). A failure message is not model output
and never went through it: `f"{type(error).__name__}: {error}"` from a
specialist, and `str(exc)` from a file that could not be reviewed, are both
rendered into the comment verbatim.

An exception from an HTTP client can carry a URL, a header dump or a response
body. The layer that "cannot produce a false negative" — masking the values this
process holds — was not applied to it.

**Fix** — redact the whole comment body at the publishing boundary, which
is the one choke point every path goes through.
