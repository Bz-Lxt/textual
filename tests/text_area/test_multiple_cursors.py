"""Tests for maintaining multiple cursors/selections in the TextArea.

These tests cover editing (typing, pasting, deleting) with multiple cursors,
normalisation of overlapping/duplicate selections, undo/redo consistency,
read-only rejection, and interaction with line wrapping.
"""

import pytest

from textual.app import App, ComposeResult
from textual.events import Paste
from textual.widgets import TextArea
from textual.widgets.text_area import Selection


TEXT = """\
AAA
BBB
CCC
DDD
"""


class TextAreaApp(App):
    def compose(self) -> ComposeResult:
        text_area = TextArea()
        text_area.load_text(TEXT)
        yield text_area


def cursor(row: int, column: int) -> Selection:
    return Selection((row, column), (row, column))


async def test_selections_normalised_sorted_and_primary():
    app = TextAreaApp()
    async with app.run_test():
        text_area = app.query_one(TextArea)
        text_area.selections = [
            cursor(2, 1),
            cursor(0, 0),
            cursor(1, 2),
        ]
        rows = [selection.end[0] for selection in text_area.selections]
        assert rows == [0, 1, 2]
        # The last selection provided becomes primary.
        assert text_area.selection == cursor(2, 1)


async def test_duplicate_cursors_are_deduped():
    app = TextAreaApp()
    async with app.run_test():
        text_area = app.query_one(TextArea)
        text_area.selections = [cursor(1, 1), cursor(1, 1)]
        assert text_area.selections == (cursor(1, 1),)


async def test_clamped_to_visitable_locations():
    app = TextAreaApp()
    async with app.run_test():
        text_area = app.query_one(TextArea)
        # `TEXT` ends with a trailing newline, so the visitable end is the
        # empty row 4.
        text_area.selections = [cursor(99, 99)]
        assert text_area.selections == (cursor(4, 0),)


async def test_overlapping_selections_merge_with_primary_identity():
    app = TextAreaApp()
    async with app.run_test():
        text_area = app.query_one(TextArea)
        # Two ranges touching at column 2, plus a cursor inside the merged range.
        text_area.selections = [
            Selection((0, 0), (0, 2)),
            cursor(0, 1),
            Selection((0, 2), (0, 3)),
        ]
        assert text_area.selections == (Selection((0, 0), (0, 3)),)
        assert text_area.selection == Selection((0, 0), (0, 3))


async def test_assigning_selection_collapses_to_single_cursor():
    app = TextAreaApp()
    async with app.run_test():
        text_area = app.query_one(TextArea)
        text_area.selections = [cursor(0, 0), cursor(1, 0)]
        text_area.selection = cursor(2, 2)
        assert text_area.selections == (cursor(2, 2),)


async def test_empty_selections_rejected():
    app = TextAreaApp()
    async with app.run_test():
        text_area = app.query_one(TextArea)
        with pytest.raises(ValueError):
            text_area.selections = []


async def test_typing_inserts_at_every_cursor():
    app = TextAreaApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(TextArea)
        text_area.selections = [cursor(0, 1), cursor(1, 1), cursor(2, 1)]
        await pilot.press("x")
        assert text_area.text == "AxAA\nBxBB\nCxCC\nDDD\n"
        assert text_area.selections == (
            cursor(0, 2),
            cursor(1, 2),
            cursor(2, 2),
        )
        # The primary cursor is the last selection in document order here.
        assert text_area.selection == cursor(2, 2)


async def test_newline_at_every_cursor():
    app = TextAreaApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(TextArea)
        text_area.selections = [cursor(0, 1), cursor(2, 1)]
        await pilot.press("enter")
        assert text_area.text == "A\nAA\nBBB\nC\nCC\nDDD\n"
        assert text_area.selections == (cursor(1, 0), cursor(3, 0))


async def test_typing_with_overlapping_selections_edits_once():
    app = TextAreaApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(TextArea)
        text_area.selections = [
            Selection((0, 0), (0, 2)),
            Selection((0, 1), (0, 3)),
        ]
        await pilot.press("x")
        # The overlapping ranges merge, so "AAA" is replaced by a single "x".
        assert text_area.text == "x\nBBB\nCCC\nDDD\n"
        assert text_area.selections == (cursor(0, 1),)


async def test_delete_left_at_every_cursor():
    app = TextAreaApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(TextArea)
        text_area.selections = [cursor(0, 1), cursor(1, 1)]
        await pilot.press("backspace")
        assert text_area.text == "AA\nBB\nCCC\nDDD\n"
        assert text_area.selections == (cursor(0, 0), cursor(1, 0))


async def test_delete_right_at_every_cursor():
    app = TextAreaApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(TextArea)
        text_area.selections = [cursor(0, 0), cursor(2, 0)]
        await pilot.press("delete")
        assert text_area.text == "AA\nBBB\nCC\nDDD\n"
        assert text_area.selections == (cursor(0, 0), cursor(2, 0))


async def test_delete_word_left_at_every_cursor():
    app = App()
    text_area = TextArea()
    async with app.run_test():
        app.mount(text_area)
        text_area.load_text("foo bar\nbaz qux\n")
        text_area.selections = [cursor(0, 7), cursor(1, 7)]
        text_area.action_delete_word_left()
        assert text_area.text == "foo \nbaz \n"
        assert text_area.selections == (cursor(0, 4), cursor(1, 4))


async def test_delete_to_end_of_line_at_every_cursor():
    app = App()
    text_area = TextArea()
    async with app.run_test():
        await app.mount(text_area)
        text_area.load_text(TEXT)
        text_area.selections = [cursor(0, 1), cursor(2, 1)]
        text_area.action_delete_to_end_of_line()
        assert text_area.text == "A\nBBB\nC\nDDD\n"
        assert text_area.selections == (cursor(0, 1), cursor(2, 1))


async def test_delete_line_at_every_cursor():
    app = App()
    text_area = TextArea()
    async with app.run_test():
        await app.mount(text_area)
        text_area.load_text(TEXT)
        text_area.selections = [cursor(0, 0), cursor(2, 2)]
        text_area.action_delete_line()
        assert text_area.text == "BBB\nDDD\n"
        assert text_area.selections == (cursor(0, 0), cursor(1, 2))


async def test_paste_at_every_cursor():
    app = TextAreaApp()
    async with app.run_test():
        text_area = app.query_one(TextArea)
        text_area.selections = [cursor(0, 0), cursor(2, 0)]
        await text_area._on_paste(Paste("XY"))
        assert text_area.text == "XYAAA\nBBB\nXYCCC\nDDD\n"
        assert text_area.selections == (cursor(0, 2), cursor(2, 2))


async def test_undo_restores_all_cursors_and_text():
    app = TextAreaApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(TextArea)
        text_area.selections = [cursor(0, 1), cursor(1, 1), cursor(2, 1)]
        await pilot.press("x")
        assert text_area.text == "AxAA\nBxBB\nCxCC\nDDD\n"

        await pilot.press("ctrl+z")
        assert text_area.text == TEXT
        assert text_area.selections == (
            cursor(0, 1),
            cursor(1, 1),
            cursor(2, 1),
        )
        assert text_area.selection == cursor(2, 1)


async def test_redo_restores_all_cursors_and_text():
    app = TextAreaApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(TextArea)
        text_area.selections = [cursor(0, 1), cursor(1, 1)]
        await pilot.press("x")
        await pilot.press("ctrl+z")
        await pilot.press("ctrl+y")
        assert text_area.text == "AxAA\nBxBB\nCCC\nDDD\n"
        assert text_area.selections == (cursor(0, 2), cursor(1, 2))


async def test_consecutive_typing_undoes_as_single_batch():
    app = TextAreaApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(TextArea)
        text_area.selections = [cursor(0, 0), cursor(1, 0)]
        await pilot.press("x", "y")
        assert text_area.text == "xyAAA\nxyBBB\nCCC\nDDD\n"
        await pilot.press("ctrl+z")
        assert text_area.text == TEXT
        assert len(text_area.selections) == 2


async def test_read_only_rejects_multi_cursor_edits():
    app = TextAreaApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(TextArea)
        text_area.selections = [cursor(0, 0), cursor(1, 0)]
        text_area.read_only = True
        await pilot.press("x")
        await pilot.press("backspace")
        assert text_area.text == TEXT
        assert text_area.selections == (cursor(0, 0), cursor(1, 0))


async def test_escape_collapses_multiple_cursors():
    app = TextAreaApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(TextArea)
        text_area.selections = [cursor(0, 0), cursor(1, 0)]
        await pilot.press("escape")
        assert text_area.selections == (cursor(1, 0),)


async def test_plain_movement_moves_all_cursors():
    app = TextAreaApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(TextArea)
        text_area.selections = [cursor(0, 1), cursor(1, 1)]
        await pilot.press("down")
        # Arrow keys move every cursor simultaneously (clicking still collapses).
        assert text_area.selections == (cursor(1, 1), cursor(2, 1))
        assert text_area.selection == cursor(2, 1)


async def test_shift_movement_extends_primary_keeping_other_cursors():
    app = TextAreaApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(TextArea)
        text_area.selections = [cursor(0, 0), cursor(2, 0)]
        await pilot.press("shift+right")
        assert len(text_area.selections) == 2
        assert Selection((0, 0), (0, 1)) in text_area.selections
        # The primary (last) selection is extended.
        assert text_area.selection == Selection((2, 0), (2, 1))


async def test_add_cursor_below_action():
    app = TextAreaApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(TextArea)
        text_area.cursor_location = (0, 1)
        await pilot.press("ctrl+alt+down")
        assert text_area.selections == (cursor(0, 1), cursor(1, 1))
        assert text_area.selection == cursor(1, 1)


async def test_cursors_consistent_after_wrapping_change():
    app = TextAreaApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(TextArea)
        text_area.soft_wrap = False
        text_area.selections = [cursor(0, 1), cursor(2, 1)]
        await pilot.press("x")
        # Enabling wrapping re-flows the document, but the document-space
        # cursor locations must remain correct.
        text_area.soft_wrap = True
        assert text_area.selections == (cursor(0, 2), cursor(2, 2))
        await pilot.press("y")
        assert text_area.text == "AxyAA\nBBB\nCxyCC\nDDD\n"
        assert text_area.selections == (cursor(0, 3), cursor(2, 3))
        await pilot.press("ctrl+z")
        assert text_area.text == "AxAA\nBBB\nCxCC\nDDD\n"
        assert text_area.selections == (cursor(0, 2), cursor(2, 2))
        await pilot.press("ctrl+z")
        assert text_area.text == TEXT
        assert text_area.selections == (cursor(0, 1), cursor(2, 1))


async def test_copy_with_multiple_selections():
    app = App()
    text_area = TextArea()
    async with app.run_test():
        await app.mount(text_area)
        text_area.load_text(TEXT)
        text_area.selections = [
            Selection((0, 0), (0, 3)),
            Selection((2, 0), (2, 3)),
        ]
        text_area.action_copy()
        assert app.clipboard == "AAA\nCCC"


async def test_cut_with_multiple_selections():
    app = App()
    text_area = TextArea()
    async with app.run_test():
        await app.mount(text_area)
        text_area.load_text(TEXT)
        text_area.selections = [
            Selection((0, 0), (0, 3)),
            Selection((2, 0), (2, 3)),
        ]
        text_area.action_cut()
        assert text_area.text == "\nBBB\n\nDDD\n"
        assert app.clipboard == "AAA\nCCC"
        assert text_area.selections == (cursor(0, 0), cursor(2, 0))
        # A single undo restores both cuts and both cursors.
        text_area.undo()
        assert text_area.text == TEXT
        assert text_area.selections == (
            Selection((0, 0), (0, 3)),
            Selection((2, 0), (2, 3)),
        )


async def test_read_only_paste_is_noop():
    app = TextAreaApp()
    async with app.run_test():
        text_area = app.query_one(TextArea)
        text_area.selections = [cursor(0, 0), cursor(1, 0)]
        text_area.read_only = True
        await text_area._on_paste(Paste("XY"))
        assert text_area.text == TEXT
        assert text_area.selections == (cursor(0, 0), cursor(1, 0))
