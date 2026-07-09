"""Pure active-path + version-map logic for message versioning (no DB)."""
import datetime
from types import SimpleNamespace

from backend.features.chat import versioning


def _m(mid, parent, active, secs, role="user"):
    return SimpleNamespace(
        id=mid, parent_id=parent, active=active, role=role,
        created_at=datetime.datetime(2026, 1, 1, 0, 0, secs),
    )


def test_linear_chain_is_the_active_path():
    msgs = [_m("a", None, True, 1), _m("b", "a", True, 2), _m("c", "b", True, 3)]
    assert [m.id for m in versioning.active_path(msgs)] == ["a", "b", "c"]


def test_regenerated_reply_follows_the_active_sibling():
    # user 'a' -> assistant 'b1' (old, inactive) and 'b2' (regenerated, active)
    msgs = [
        _m("a", None, True, 1, "user"),
        _m("b1", "a", False, 2, "assistant"),
        _m("b2", "a", True, 3, "assistant"),
    ]
    assert [m.id for m in versioning.active_path(msgs)] == ["a", "b2"]


def test_inactive_subtree_is_excluded_but_kept_for_switching():
    # a -> b1(inactive, has its own child c1) ; a -> b2(active)
    msgs = [
        _m("a", None, True, 1, "user"),
        _m("b1", "a", False, 2, "assistant"),
        _m("c1", "b1", True, 3, "user"),          # lives under the inactive branch
        _m("b2", "a", True, 4, "assistant"),
    ]
    path = [m.id for m in versioning.active_path(msgs)]
    assert path == ["a", "b2"]  # c1 is not on the active path
    vm = versioning.version_map(msgs)
    assert vm["b1"]["versions"] == 2 and vm["b2"]["versions"] == 2
    assert vm["b2"]["siblings"] == ["b1", "b2"]      # ordered by time
    assert vm["b2"]["active_sibling"] == "b2"


def test_version_indices_are_one_based_in_time_order():
    msgs = [
        _m("a", None, True, 1, "user"),
        _m("r1", "a", False, 2, "assistant"),
        _m("r2", "a", False, 3, "assistant"),
        _m("r3", "a", True, 4, "assistant"),
    ]
    vm = versioning.version_map(msgs)
    assert (vm["r1"]["version"], vm["r2"]["version"], vm["r3"]["version"]) == (1, 2, 3)
    assert vm["r3"]["versions"] == 3
    assert [m.id for m in versioning.active_path(msgs)] == ["a", "r3"]


def test_no_active_flag_falls_back_to_newest_sibling():
    msgs = [
        _m("a", None, True, 1, "user"),
        _m("b1", "a", False, 2, "assistant"),
        _m("b2", "a", False, 3, "assistant"),  # none active → newest wins
    ]
    assert [m.id for m in versioning.active_path(msgs)] == ["a", "b2"]


def test_empty_conversation():
    assert versioning.active_path([]) == []
    assert versioning.version_map([]) == {}


def test_leaf_id_is_the_active_path_tip():
    msgs = [
        _m("a", None, True, 1, "user"),
        _m("b1", "a", False, 2, "assistant"),
        _m("b2", "a", True, 3, "assistant"),
    ]
    assert versioning.leaf_id(msgs) == "b2"
    assert versioning.leaf_id([]) is None


def test_ancestors_returns_root_to_target_even_off_the_active_path():
    msgs = [
        _m("a", None, True, 1, "user"),
        _m("b1", "a", False, 2, "assistant"),   # inactive old version
        _m("b2", "a", True, 3, "assistant"),
        _m("c", "b2", True, 4, "user"),
    ]
    assert [m.id for m in versioning.ancestors(msgs, "b1")] == ["a", "b1"]
    assert [m.id for m in versioning.ancestors(msgs, "c")] == ["a", "b2", "c"]


def test_ancestors_of_unknown_or_missing_target_is_empty():
    msgs = [_m("a", None, True, 1)]
    assert versioning.ancestors(msgs, "zz") == []
    assert versioning.ancestors([], "a") == []
