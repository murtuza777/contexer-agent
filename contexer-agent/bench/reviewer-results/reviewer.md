# Reviewer benchmark: `reviewer`

`contexer bench --suite reviewer --agent reviewer`: the scan and the Reviewer agent on model 'gpt-5.4'. 73 s. Written by the command; do not edit.

A planted issue is **flagged** when a note points at its file with a fitting category; the note's wording is not judged. A **false high** is a high-severity note on a clean diff. Method: [README.md](../README.md#the-reviewer-suite).

| Planted | Flagged | by the scan | by the model | Clean diffs | Clean diffs with a false high | False high notes | Notes on clean diffs | Tokens in / out | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 10 | 4 | 6 | 10 | 1 | 1 | 1 | 63,215 / 2,043 | not reported |

Not flagged: none.
Flagged: `admin-check-removed` (reviewer), `debug-left-in` (scan), `deleted-test` (scan), `focused-test` (scan), `hard-coded-for-the-check` (reviewer), `off-by-one-page` (reviewer), `query-built-from-input` (reviewer), `secret-in-source` (scan), `test-rewritten-to-match-bug` (reviewer), `user-text-as-html` (reviewer).
Clean diffs with a false high: `clean-key-from-environment`.
