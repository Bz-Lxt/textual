from __future__ import annotations

import pytest

from textual import events
from textual.app import App
from textual.binding import (
    Binding,
    InvalidBinding,
    parse_key_string,
)
from textual.keys import _normalize_key_list
from textual.widget import Widget
from textual.widgets import Input
from textual.widgets._key_panel import BindingsTable, KeyPanel

SEQUENCE_TIMEOUT = App.KEY_SEQUENCE_TIMEOUT + 0.1


class KeyTracker(Widget):
    """A focusable widget that records keys without stopping propagation."""

    can_focus = True
    DEFAULT_CSS = ""

    def __init__(self) -> None:
        super().__init__()
        self.keys: list[str] = []

    def on_key(self, event: events.Key) -> None:
        self.keys.append(event.key)


def make_app(bindings, actions: list[str] | None = None):
    """Create an app recording executed action names."""
    actions = actions if actions is not None else []

    class SequenceApp(App):
        BINDINGS = bindings

        def action_record(self, name: str) -> None:
            actions.append(name)

    return SequenceApp(), actions


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parse_key_string_aliases_and_sequences() -> None:
    assert parse_key_string("a") == [("a",)]
    assert parse_key_string("a, b") == [("a",), ("b",)]
    assert parse_key_string("ctrl+x s") == [("ctrl+x", "s")]
    assert parse_key_string("ctrl+x s, f2") == [("ctrl+x", "s"), ("f2",)]
    # Single characters are normalized to their long form
    assert parse_key_string("? x") == [("question_mark", "x")]


@pytest.mark.parametrize("key_string", ["", ",", "a,", ",a", "a,,b", "a, ,b"])
def test_parse_key_string_rejects_empty(key_string: str) -> None:
    with pytest.raises(InvalidBinding):
        parse_key_string(key_string)


def test_make_bindings_expands_aliases_and_canonicalizes_sequences() -> None:
    bindings = list(
        Binding.make_bindings([Binding("ctrl+x s, f2", "record('save')")])
    )
    assert [binding.key for binding in bindings] == ["ctrl+x s", "f2"]
    assert bindings[0].key_sequence == ("ctrl+x", "s")
    assert bindings[0].is_sequence is True
    assert bindings[1].key_sequence == ("f2",)
    assert bindings[1].is_sequence is False


def test_normalize_key_list_with_sequence() -> None:
    assert _normalize_key_list("? x, a") == "question_mark x,a"


# ---------------------------------------------------------------------------
# Sequence dispatch
# ---------------------------------------------------------------------------


async def test_sequence_fires() -> None:
    app, actions = make_app([Binding("g x", "record('long')")])
    async with app.run_test() as pilot:
        await pilot.press("g", "x")
        await pilot.pause()
        assert actions == ["long"]


async def test_three_key_sequence() -> None:
    app, actions = make_app([Binding("g y z", "record('longer')")])
    async with app.run_test() as pilot:
        await pilot.press("g", "y", "z")
        await pilot.pause()
        assert actions == ["longer"]


async def test_longer_sequence_takes_priority_over_short_binding() -> None:
    app, actions = make_app(
        [Binding("g", "record('short')"), Binding("g x", "record('long')")]
    )
    async with app.run_test() as pilot:
        await pilot.press("g", "x")
        await pilot.pause()
        assert actions == ["long"]


async def test_short_binding_fires_on_timeout() -> None:
    app, actions = make_app(
        [Binding("g", "record('short')"), Binding("g x", "record('long')")]
    )
    async with app.run_test() as pilot:
        await pilot.press("g")
        await pilot.pause()
        assert actions == []
        await pilot.pause(SEQUENCE_TIMEOUT)
        assert actions == ["short"]


async def test_timeout_without_exact_binding_does_not_replay_arming_key() -> None:
    """The arming key was already delivered; timeout must not duplicate it."""
    app, actions = make_app([Binding("g x", "record('long')")])
    async with app.run_test() as pilot:
        tracker = KeyTracker()
        await app.mount(tracker)
        await pilot.pause()
        tracker.focus()
        await pilot.pause()
        await pilot.press("g")
        await pilot.pause()
        assert tracker.keys == ["g"]
        await pilot.pause(SEQUENCE_TIMEOUT)
        assert tracker.keys == ["g"]
        assert actions == []


async def test_unrelated_key_breaks_sequence_and_releases_input() -> None:
    app, actions = make_app(
        [Binding("g", "record('short')"), Binding("g x", "record('long')")]
    )
    async with app.run_test() as pilot:
        tracker = KeyTracker()
        await app.mount(tracker)
        await pilot.pause()
        tracker.focus()
        await pilot.pause()
        await pilot.press("g", "z")
        await pilot.pause()
        # The arming key's complete binding fires (it was deferred by the
        # longer prefix); the breaking key is delivered as ordinary input,
        # and the arming key itself is not delivered twice.
        assert actions == ["short"]
        assert tracker.keys == ["g", "z"]


async def test_escape_cancels_pending_sequence() -> None:
    app, actions = make_app(
        [Binding("g", "record('short')"), Binding("g x", "record('long')")]
    )
    async with app.run_test() as pilot:
        tracker = KeyTracker()
        await app.mount(tracker)
        await pilot.pause()
        tracker.focus()
        await pilot.press("g", "escape")
        await pilot.pause()
        assert tracker.keys == ["g"]
        assert actions == []
        # Nothing fires later when the timeout elapses.
        await pilot.pause(SEQUENCE_TIMEOUT)
        assert actions == []
        assert tracker.keys == ["g"]


async def test_priority_sequence() -> None:
    app, actions = make_app(
        [Binding("ctrl+t w", "record('tw')", priority=True)]
    )
    async with app.run_test() as pilot:
        await pilot.press("ctrl+t", "w")
        await pilot.pause()
        assert actions == ["tw"]


async def test_priority_sequence_break_replays_withheld_keys() -> None:
    """Priority bindings withhold keys pre-dispatch, so all are replayed."""
    recorded: list[str] = []

    class PriorityApp(App):
        BINDINGS = [Binding("ctrl+t w", "record('tw')", priority=True)]

        def action_record(self, name: str) -> None:
            recorded.append(f"action:{name}")

        def on_key(self, event: events.Key) -> None:
            recorded.append(event.key)

    app = PriorityApp()
    async with app.run_test() as pilot:
        await pilot.press("ctrl+t", "z")
        await pilot.pause()
        assert recorded == ["ctrl+t", "z"]


async def test_aliases_both_fire_action() -> None:
    app, actions = make_app([Binding("g x, f2", "record('long')")])
    async with app.run_test() as pilot:
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("g", "x")
        await pilot.pause()
        assert actions == ["long", "long"]


async def test_simulate_key_sequence() -> None:
    app, actions = make_app([Binding("ctrl+x s", "record('save')")])
    async with app.run_test() as pilot:
        app.simulate_key("ctrl+x s")
        await pilot.pause()
        assert actions == ["save"]


# ---------------------------------------------------------------------------
# Interaction with focused widgets
# ---------------------------------------------------------------------------


async def test_printable_prefix_does_not_swallow_input_text() -> None:
    """An Input stops character keys, so app sequences never swallow typing."""
    app, actions = make_app(
        [Binding("g", "record('short')"), Binding("g x", "record('long')")]
    )
    async with app.run_test() as pilot:
        inp = Input()
        await app.mount(inp)
        await pilot.pause()
        inp.focus()
        await pilot.press("g", "x")
        await pilot.pause()
        assert inp.value == "gx"
        assert actions == []


async def test_priority_sequence_break_replays_into_input() -> None:
    app, actions = make_app(
        [Binding("f o o", "record('foo')", priority=True)]
    )
    async with app.run_test() as pilot:
        inp = Input()
        await app.mount(inp)
        await pilot.pause()
        inp.focus()
        await pilot.press("f", "o", "z")
        await pilot.pause()
        assert actions == []
        assert inp.value == "foz"


# ---------------------------------------------------------------------------
# Invalidation on focus / keymap changes
# ---------------------------------------------------------------------------


async def test_focus_change_cancels_pending_sequence() -> None:
    app, actions = make_app(
        [Binding("g", "record('short')"), Binding("g x", "record('long')")]
    )
    async with app.run_test() as pilot:
        first = KeyTracker()
        second = KeyTracker()
        await app.mount_all([first, second])
        await pilot.pause()
        first.focus()
        await pilot.press("g")
        await pilot.pause()
        second.focus()
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()
        assert actions == []
        assert first.keys == ["g"]
        assert second.keys == ["x"]


async def test_keymap_change_cancels_pending_sequence() -> None:
    app, actions = make_app(
        [
            Binding("g x", "record('long')", id="long_binding"),
        ]
    )
    async with app.run_test() as pilot:
        await pilot.press("g")
        await pilot.pause()
        app.set_keymap({"long_binding": "g y"})
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()
        assert actions == []
        # The new keymap applies from the next press onwards.
        await pilot.press("g", "y")
        await pilot.pause()
        assert actions == ["long"]


async def test_dynamic_bind_cancels_pending_sequence() -> None:
    app, actions = make_app([Binding("g x", "record('long')")])
    async with app.run_test() as pilot:
        await pilot.press("g")
        await pilot.pause()
        app.bind("q", "record('cue')", description="Cue")
        await pilot.press("x")
        await pilot.pause()
        assert actions == []
        # The pending sequence was discarded; later presses match afresh.
        await pilot.press("g", "x")
        await pilot.pause()
        assert actions == ["long"]


async def test_focus_change_before_timeout_discards_pending_sequence() -> None:
    app, actions = make_app(
        [Binding("g", "record('short')"), Binding("g x", "record('long')")]
    )
    async with app.run_test() as pilot:
        first = KeyTracker()
        second = KeyTracker()
        await app.mount_all([first, second])
        await pilot.pause()
        first.focus()
        await pilot.pause()
        await pilot.press("g")
        await pilot.pause()
        second.focus()
        await pilot.pause(SEQUENCE_TIMEOUT)
        assert actions == []


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


async def test_get_key_display_formats_sequence_with_spaces() -> None:
    app, _ = make_app([])
    async with app.run_test() as pilot:
        assert app.get_key_display(Binding("g x", "x")) == "g x"
        assert app.get_key_display(Binding("ctrl+x s", "x")) == "^x s"
        # An explicit key_display still wins.
        assert (
            app.get_key_display(Binding("g x", "x", key_display="CUSTOM"))
            == "CUSTOM"
        )


async def test_key_panel_distinguishes_sequences_from_aliases() -> None:
    app, _ = make_app(
        [Binding("g x, f2", "record('long')", "Long action")]
    )
    async with app.run_test() as pilot:
        tracker = KeyTracker()
        await app.mount_all([tracker, KeyPanel()])
        await pilot.pause()
        tracker.focus()
        await pilot.pause()
        table = app.query_one(BindingsTable).render_bindings_table()
        key_cells = [
            cell.plain for cell in table.columns[0].cells if hasattr(cell, "plain")
        ]
    assert "g x, f2" in key_cells
