"""Matcher behaviour: correctness of matching, ranking and positions."""

from clipd.search.matcher import SLICE, Matcher


def test_empty_query_matches_nothing_actively() -> None:
    m = Matcher("")
    assert m.empty
    assert m.positions("anything") == []


def test_subsequence_matches() -> None:
    m = Matcher("hlo")
    assert m.score("hello world") is not None
    assert m.score("help lots") is not None
    assert m.score("goodbye") is None


def test_all_terms_must_match() -> None:
    m = Matcher("foo bar")
    assert m.score("foo something bar") is not None
    assert m.score("foo only") is None


def test_smart_case() -> None:
    insensitive = Matcher("readme")
    assert insensitive.score("README.md") is not None
    sensitive = Matcher("README")
    assert sensitive.score("README.md") is not None
    assert sensitive.score("readme.md") is None


def test_consecutive_beats_scattered() -> None:
    m = Matcher("clip")
    tight = m.score("clipboard")
    scattered = m.score("cool lion pit")
    assert tight is not None and scattered is not None
    assert tight > scattered


def test_word_boundary_beats_midword() -> None:
    m = Matcher("net")
    boundary = m.score("net worth")
    midword = m.score("garnet")
    assert boundary is not None and midword is not None
    assert boundary > midword


def test_positions_point_at_matched_chars() -> None:
    m = Matcher("wrd")
    hay = "hello world"
    positions = m.positions(hay)
    assert [hay[i] for i in positions] == ["w", "r", "d"]


def test_positions_tighten_toward_run() -> None:
    # A trailing exact run should be preferred over the scattered prefix.
    m = Matcher("abc")
    hay = "a-b-c then abc"
    positions = m.positions(hay)
    assert positions == [11, 12, 13]


def test_pin_bonus_breaks_ties() -> None:
    m = Matcher("x")
    plain = m.score("x marks")
    pinned = m.score("x marks", pinned=True)
    assert plain is not None and pinned is not None
    assert pinned > plain


def test_unicode_haystack() -> None:
    m = Matcher("caf")
    assert m.score("caf\u00e9 con leche \U0001f389") is not None


def test_huge_haystack_is_sliced() -> None:
    m = Matcher("zzz")
    hay = "a" * (SLICE * 100) + "zzz"  # match lies beyond the slice
    assert m.score(hay) is None
    assert m.score("zzz" + "a" * (SLICE * 100)) is not None


def test_regex_metachars_are_literal() -> None:
    m = Matcher("a.c(")
    assert m.score("a.c( call") is not None
    assert m.score("abc-call") is None


def test_no_combinatorial_blowup() -> None:
    # A subsequence-regex prefilter would backtrack for seconds on this.
    import time

    m = Matcher("aaaab")
    hay = "a" * SLICE
    start = time.perf_counter()
    assert m.score(hay) is None
    assert time.perf_counter() - start < 0.05


def test_length_changing_casefold_keeps_positions_aligned() -> None:
    # 'İ'.lower() is two characters; positions must still index the original.
    hay = "\u0130stanbul kebap"
    m = Matcher("kebap")
    assert [hay[i] for i in m.positions(hay)] == list("kebap")
