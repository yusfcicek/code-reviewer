# Self-review of Level 26

**Method** unchanged: run the recipes against inputs a real file contains, and
count what they get wrong.

This level's own spec says the recipes were *"chosen by mechanism rather than by
ease"*. Three of the four were. The fourth was chosen by imagining what its rule
detects, without reading it.

| # | Severity | What |
|---|---|---|
| S-01 | 🔴 | `except: raise` is rewritten to `except Exception:` — the `raise` is deleted |
| S-02 | 🔴 | A recipe for a shape its rule never reports, whose edit changes nothing |
| S-03 | 🟠 | Only the first URL on a line is upgraded; the fix looks complete |
| S-04 | 🟠 | A `random` call inside a comment yields a suggestion and an unused import |

---

## S-01 — the guard that looked at the wrong lines

```
before:  "    except: raise"
after :  "    except Exception:"
```

The `raise` is gone. A handler that re-raised now swallows the exception, which
is the opposite of a fix and is invisible in a one-line diff.

The recipe *has* a guard for exactly this — it refuses when the handler's body is
a bare `raise` — and the guard looks at the **following** lines. The single-line
form has no following line, so it walks straight past. Worse, the replacement is
built as `indent + "except Exception:"` and discards whatever else was on the
line, so any single-line body would be deleted, not just `raise`.

This is the failure Level 22's whole declining discipline exists to prevent: a
button that changes behaviour silently. It is also a reminder that a guard tested
only against the shape its author pictured is a guard tested against its author.

## S-02 — a recipe that answers a question its rule never asks

`SAST.INSECURE_FILE_OPERATION` fires on exactly two patterns:

```
chmod\s*\([^)]*0?777
open\s*\([^)]+,\s*["\']w["\']
```

Neither is `open(path)` with no mode. The recipe I wrote handles the
one-positional-argument shape — **which this rule never reports** — and its edit
adds `"r"`, which is the default and therefore changes nothing.

Two errors compounding: a fix for a finding that cannot occur, and a fix that
would be a no-op if it did. Applied, it produces a diff whose only effect is to
make a reader believe something was fixed.

The spec for this level says recipes are chosen by asking *does the fix follow
from the finding without a decision*. Answering that question requires reading
what the finding is, and I answered it from the rule's **name**.

## S-03 — the first of two

```
before:  PAIR = ("http://a.example", "http://b.example")
after :  PAIR = ("https://a.example", "http://b.example")
```

`re.search` finds one. A reviewer clicks, sees a green diff, and has half a fix —
and the half that remains is the one nobody will look at again, because the
finding is now closed.

## S-04 — a comment is not code

```
before:  # random.random() is not good enough here
after :  a suggestion, plus `import secrets` the file does not use
```

The rule fires on the comment too — its pattern is `random\.\w+\s*\(` with no
notion of context — so the finding is not wrong to exist. The recipe is wrong to
act on it: rewriting a sentence somebody wrote, and adding an import nothing
uses, is noise with provenance.

The `http` recipe escapes this by accident: its pattern requires quotes, and
comments rarely have them.

---

## What this round says about the level

Three of the four findings are the same mistake at different distances from the
code: **the recipe was written against a mental model of its input** — of the
rule, of the line, of the file — rather than against the input.

Level 25's self-review named the sibling of this in a different form: a number
becomes credible by being formatted like the ones beside it. Here, a recipe
becomes credible by being registered beside ones that work.

The mechanical fix is the same in both cases and it is cheap: read the thing.
The rule's patterns are forty lines away in the same repository.
