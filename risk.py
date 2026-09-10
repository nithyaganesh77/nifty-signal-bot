"""
Shared stop-loss sizing helper used by every strategy module.

apply_sl() takes a strategy's raw, book-literal stop-loss level and applies
two adjustments, in order:

  1. buffer (config.SL_BUFFER_POINTS) - pushes the stop further from entry,
     to absorb ordinary wick/spread noise (see config.py's comment).
  2. max_points (config.MAX_SL_POINTS) - caps how far the buffered stop can
     sit from entry. Some strategies derive their stop from an indicator
     (Parabolic SAR, a Fibonacci swing) that can still be "catching up"
     right after a large overnight gap - a live day showed strategy 1's
     SAR sitting 170+ points from entry and strategy 7's Fibonacci stop
     185+ points away, both far outside those strategies' normal 10-30
     point range. The cap keeps a distorted input from producing an
     unmanageable stop; the buffer is applied first so a capped trade
     still gets its full noise cushion.

Where a target is computed as target_rr * risk (risk = abs(entry - sl)),
capping sl here automatically shrinks that target proportionally too,
since risk is computed from the already-capped sl.

Both adjustments default to inert (buffer=0.0, max_points=None) so calling
this with no extra args reproduces the exact book-literal level.
"""

from __future__ import annotations


def apply_sl(
    entry: float,
    raw_sl: float,
    direction: str,
    buffer: float = 0.0,
    max_points: float | None = None,
) -> float:
    if direction == "long":
        sl = raw_sl - buffer
        if max_points is not None and (entry - sl) > max_points:
            sl = entry - max_points
    else:
        sl = raw_sl + buffer
        if max_points is not None and (sl - entry) > max_points:
            sl = entry + max_points
    return sl
