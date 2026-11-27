# Reviewer benchmark: `scan`

`contexer bench --suite reviewer --agent scan`: the scan alone, no model. 0 s. Written by the command; do not edit.

A planted issue is **flagged** when a note points at its file with a fitting category; the note's wording is not judged. A **false high** is a high-severity note on a clean diff. Method: [README.md](../README.md#the-reviewer-suite).

| Planted | Flagged | by the scan | by the model | Clean diffs | Clean diffs with a false high | False high notes | Notes on clean diffs | Tokens in / out | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 12 | 6 | 6 | 0 | 12 | 0 | 0 | 0 | 0 / 0 | not reported |

Rates: planted issues flagged 6/12, 50% (95% interval 25% to 75%); clean diffs with a false high 0/12, 0% (95% interval 0% to 24%).

Not flagged: `admin-check-removed`, `hard-coded-for-the-check`, `off-by-one-page`, `query-built-from-input`, `test-rewritten-to-match-bug`, `user-text-as-html`.
Flagged: `confirmation-removed` (scan), `debug-left-in` (scan), `deleted-test` (scan), `focused-test` (scan), `secret-in-source` (scan), `validation-removed` (scan).
Clean diffs with a false high: none.
