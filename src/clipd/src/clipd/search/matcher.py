"""fzf-style fuzzy matching with match positions for highlighting.

Each term gets a greedy forward scan (a chain of C-speed str.find calls,
linear time, which doubles as the cheap non-match rejection) plus a
backward-tightening pass — fzf's v1 algorithm — yielding both a score and
the matched indices. A few successive windows are tried and the best-
scoring one wins, so a tight run later in the text beats scattered chars
at the start. A regex-prefilter variant was rejected: subsequence regexes
backtrack combinatorially on inputs like 'aaa…a' vs 'aaab'.

Queries are split on whitespace; every term must match (AND). A term
containing an uppercase letter matches case-sensitively, otherwise matching
is case-insensitive (smart case). Only the first `SLICE` characters of an
entry are searched so pathological megabyte pastes cannot stall the UI.
"""

from __future__ import annotations

SLICE = 512  # characters of an entry considered for matching

_BOUNDARY_BONUS = 16  # match starts a word or camelHump
_CONSECUTIVE_BONUS = 8  # adjacent to the previous matched char
_GAP_PENALTY = 1  # per skipped char between matches, capped
_GAP_CAP = 3
_EXACT_BONUS = 32  # haystack contains the term verbatim
_PIN_BONUS = 4  # nudges pinned entries up between close scores
_WINDOW_TRIES = 4  # alternative match windows examined per term


def _is_boundary(hay: str, i: int) -> bool:
    if i == 0:
        return True
    prev, ch = hay[i - 1], hay[i]
    return not prev.isalnum() or (ch.isupper() and prev.islower())


def _match_window(hay: str, term: str, start: int) -> tuple[int, list[int]] | None:
    """Score the first match window at or after `start`."""
    # Forward pass: earliest subsequence embedding.
    forward: list[int] = []
    pos = start - 1
    for ch in term:
        pos = hay.find(ch, pos + 1)
        if pos < 0:
            return None
        forward.append(pos)
    # Backward pass: pull every char as close to the end anchor as possible,
    # which tightens the window and rewards consecutive runs.
    positions = [0] * len(term)
    positions[-1] = hi = forward[-1]
    for k in range(len(term) - 2, -1, -1):
        hi = hay.rfind(term[k], forward[k], hi)
        positions[k] = hi

    score = 0
    prev = -2
    run_bonus = 0  # consecutive chars inherit the bonus of the run's start
    for p in positions:
        bonus = _BOUNDARY_BONUS if _is_boundary(hay, p) else 0
        if p == prev + 1:
            run_bonus = max(run_bonus, bonus, _CONSECUTIVE_BONUS)
        else:
            run_bonus = bonus
            if prev >= 0:
                score -= min(p - prev - 1, _GAP_CAP) * _GAP_PENALTY
        score += run_bonus
        prev = p
    return score - positions[0] // 8, positions  # earlier matches win ties


def _match_term(hay: str, term: str) -> tuple[int, list[int]] | None:
    """Best window for one term; both strings already case-folded as needed."""
    best: tuple[int, list[int]] | None = None
    start = 0
    for _ in range(_WINDOW_TRIES):
        window = _match_window(hay, term, start)
        if window is None:
            break
        if best is None or window[0] > best[0]:
            best = window
        start = window[1][0] + 1
    if best is not None and len(term) > 1 and term in hay:
        best = (best[0] + _EXACT_BONUS, best[1])
    return best


def _lowered(hay: str) -> str:
    """Length-preserving lowercase, so positions map 1:1 onto the original.

    A handful of codepoints (e.g. 'İ') lower to multiple characters, which
    would shift every subsequent highlight index; fold those per character.
    """
    low = hay.lower()
    if len(low) == len(hay):
        return low
    return "".join(ch.lower()[0] for ch in hay)


class Matcher:
    """One parsed query, applied to many haystacks."""

    def __init__(self, query: str) -> None:
        self._terms: list[tuple[str, bool]] = []
        for raw in query.split():
            sensitive = raw != raw.lower()
            self._terms.append((raw if sensitive else raw.lower(), sensitive))

    @property
    def empty(self) -> bool:
        return not self._terms

    def score(self, hay: str, *, pinned: bool = False) -> int | None:
        """Combined score across terms, or None when any term misses."""
        hay = hay[:SLICE]
        lowered = _lowered(hay)
        total = _PIN_BONUS if pinned else 0
        for term, sensitive in self._terms:
            matched = _match_term(hay if sensitive else lowered, term)
            if matched is None:
                return None
            total += matched[0]
        return total

    def positions(self, hay: str) -> list[int]:
        """Merged, sorted character indices to highlight. Lazy: call per visible row."""
        hay = hay[:SLICE]
        lowered = _lowered(hay)
        merged: set[int] = set()
        for term, sensitive in self._terms:
            matched = _match_term(hay if sensitive else lowered, term)
            if matched is not None:
                merged.update(matched[1])
        return sorted(merged)
