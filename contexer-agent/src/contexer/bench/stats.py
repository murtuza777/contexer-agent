"""Rates with intervals, so a benchmark result says how sure it is.

Every suite reports counts: bugs caught of bugs seeded, clean runs with a
false alarm of clean runs. A count from a few dozen runs is one draw: 25 of
40 found puts the rate somewhere between 47% and 76%, and a second run that
finds 22 has not shown a regression. So each rate is written with its 95%
Wilson score interval, and two results are compared with Newcombe's interval
for the difference of two proportions (built from the two Wilson intervals):
when it contains zero, the two cannot be told apart.

Both treat every run as an independent trial of one rate. Seeded bugs differ
in difficulty, and a repeat of the same bug is not independent of the first,
so the intervals are a guide to the noise and not an exact error bar.
"""

from __future__ import annotations

import math
from typing import NamedTuple

# The normal quantile for a two-sided 95% interval.
Z95 = 1.959964


class Rate(NamedTuple):
    """``k`` of ``n`` runs."""

    k: int
    n: int

    def interval(self) -> tuple[float, float] | None:
        """The 95% Wilson score interval, or None when nothing ran."""
        if self.n <= 0:
            return None
        p, z2 = self.k / self.n, Z95 * Z95
        scale = 1 + z2 / self.n
        centre = (p + z2 / (2 * self.n)) / scale
        half = Z95 * math.sqrt(p * (1 - p) / self.n + z2 / (4 * self.n * self.n)) / scale
        return max(0.0, centre - half), min(1.0, centre + half)

    def text(self) -> str:
        """``40/40, 100% (95% interval 91% to 100%)``."""
        bounds = self.interval()
        if bounds is None:
            return f"{self.k}/{self.n}, nothing ran"
        return f"{self.k}/{self.n}, {self.k / self.n:.0%} (95% interval {bounds[0]:.0%} to {bounds[1]:.0%})"


def difference(new: Rate, old: Rate) -> tuple[float, float] | None:
    """The 95% interval for ``new - old`` (Newcombe 1998, method 10), or None when either has no runs."""
    a, b = new.interval(), old.interval()
    if a is None or b is None:
        return None
    p1, p2 = new.k / new.n, old.k / old.n
    low = (p1 - p2) - math.sqrt((p1 - a[0]) ** 2 + (b[1] - p2) ** 2)
    high = (p1 - p2) + math.sqrt((a[1] - p1) ** 2 + (p2 - b[0]) ** 2)
    return low, high


def compare(new: Rate, old: Rate) -> str:
    """Whether ``new`` is higher or lower than ``old``, or the two cannot be told apart."""
    bounds = difference(new, old)
    if bounds is None:
        return "not compared: one of the two has no runs"
    low, high = bounds
    word = "higher" if low > 0 else "lower" if high < 0 else "cannot be told apart"
    return f"{word} (95% interval for the difference: {low * 100:+.0f} to {high * 100:+.0f} points)"


def sentence(rates: dict[str, Rate]) -> str:
    """Every rate with its interval, on one line, for a results page."""
    return "; ".join(f"{name} {rate.text()}" for name, rate in rates.items())
