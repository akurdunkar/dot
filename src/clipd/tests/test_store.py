"""Store behaviour: dedupe, ordering, pinning, pruning, persistence."""

import time
from pathlib import Path

from clipd.store import KIND_IMAGE, KIND_TEXT, Store


def make(tmp_path: Path) -> Store:
    return Store(tmp_path / "t.sqlite3")


def test_add_and_list(tmp_path: Path) -> None:
    s = make(tmp_path)
    entry, created = s.add(KIND_TEXT, text="hello")
    assert created and entry.id > 0 and entry.text == "hello"
    assert [e.text for e in s.entries()] == ["hello"]


def test_duplicate_bumps_instead_of_inserting(tmp_path: Path) -> None:
    s = make(tmp_path)
    first, _ = s.add(KIND_TEXT, text="dup")
    s.add(KIND_TEXT, text="other")
    bumped, created = s.add(KIND_TEXT, text="dup")
    assert not created and bumped.id == first.id
    assert s.count() == 2
    assert [e.text for e in s.entries()] == ["dup", "other"]  # recency order


def test_pinned_sort_first(tmp_path: Path) -> None:
    s = make(tmp_path)
    s.add(KIND_TEXT, text="old")
    pinned, _ = s.add(KIND_TEXT, text="pinme")
    s.add(KIND_TEXT, text="new")
    s.set_pinned(pinned.id, True)
    assert [e.text for e in s.entries()] == ["pinme", "new", "old"]


def test_prune_keeps_pinned_and_newest(tmp_path: Path) -> None:
    s = make(tmp_path)
    keep, _ = s.add(KIND_TEXT, text="pinned-oldest")
    s.set_pinned(keep.id, True)
    for i in range(10):
        s.add(KIND_TEXT, text=f"e{i}")
        time.sleep(0.001)  # distinct last_used_at
    assert s.prune(3) == 7
    texts = [e.text for e in s.entries()]
    assert texts == ["pinned-oldest", "e9", "e8", "e7"]


def test_image_roundtrip_and_lazy_data(tmp_path: Path) -> None:
    s = make(tmp_path)
    entry, _ = s.add(KIND_IMAGE, data=b"PNGBYTES", thumb=b"THUMB", width=12, height=8)
    listed = s.entries()[0]
    assert listed.thumb == b"THUMB" and listed.width == 12
    assert listed.preview == "Image 12\u00d78"
    assert s.data(entry.id) == b"PNGBYTES"


def test_clear_unpinned_spares_pins(tmp_path: Path) -> None:
    s = make(tmp_path)
    pinned, _ = s.add(KIND_TEXT, text="keep")
    s.set_pinned(pinned.id, True)
    s.add(KIND_TEXT, text="drop")
    assert s.clear_unpinned() == 1
    assert [e.text for e in s.entries()] == ["keep"]


def test_persists_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / "t.sqlite3"
    s = Store(path)
    entry, _ = s.add(KIND_TEXT, text="survivor")
    s.set_pinned(entry.id, True)
    s.close()
    s2 = Store(path)
    survivors = s2.entries()
    assert len(survivors) == 1 and survivors[0].pinned


def test_delete_and_touch(tmp_path: Path) -> None:
    s = make(tmp_path)
    a, _ = s.add(KIND_TEXT, text="a")
    b, _ = s.add(KIND_TEXT, text="b")
    s.touch(a.id)
    assert [e.text for e in s.entries()] == ["a", "b"]
    assert s.delete(b.id)
    assert not s.delete(b.id)
    assert s.count() == 1
