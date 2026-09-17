"""Tests for sharing a document between multiple TextArea widgets.

When multiple `TextArea` widgets are constructed with the same `Document`
instance they share their text and undo/redo history, while each area keeps an
independent cursor, selection, wrapping, scroll position and highlighting.
"""

import pytest

from textual._tree_sitter import TREE_SITTER, get_language
from textual.app import App, ComposeResult
from textual.document import Document
from textual.widgets import TextArea
from textual.widgets.text_area import Selection

_PYTHON_AVAILABLE = TREE_SITTER and get_language("python") is not None
requires_python_syntax = pytest.mark.skipif(
    not _PYTHON_AVAILABLE, reason="requires tree-sitter with the python language"
)

INITIAL_TEXT = "line one\nline two\nline three"


class SharedDocumentApp(App[None]):
    """An app with two TextAreas editing the same document."""

    def __init__(self, text: str = INITIAL_TEXT) -> None:
        super().__init__()
        self.document = Document(text)
        self.language_a: str | None = None
        self.language_b: str | None = None

    def compose(self) -> ComposeResult:
        yield TextArea(document=self.document, id="a", language=self.language_a)
        yield TextArea(document=self.document, id="b", language=self.language_b)


async def test_constructed_areas_share_document_and_history():
    app = SharedDocumentApp()
    async with app.run_test():
        ta1 = app.query_one("#a", TextArea)
        ta2 = app.query_one("#b", TextArea)

        assert ta1.text == INITIAL_TEXT
        assert ta2.text == INITIAL_TEXT
        # The same share and history object links both areas.
        assert ta1.document_share is ta2.document_share
        assert ta1.history is ta2.history
        assert ta1 in ta1.document_share and ta2 in ta1.document_share
        # Per-view state is independently owned.
        assert ta1.wrapped_document is not ta2.wrapped_document
        assert ta1.selection == ta2.selection


async def test_unrelated_areas_are_not_linked():
    class UnrelatedApp(App[None]):
        def compose(self) -> ComposeResult:
            yield TextArea(document=Document("one"), id="a")
            yield TextArea(document=Document("two"), id="b")

    app = UnrelatedApp()
    async with app.run_test():
        ta1 = app.query_one("#a", TextArea)
        ta2 = app.query_one("#b", TextArea)
        assert ta1.document_share is not ta2.document_share
        assert ta1.history is not ta2.history
        ta1.insert("X", location=(0, 0))
        assert ta1.text == "Xone"
        assert ta2.text == "two"


async def test_edit_in_one_area_propagates_to_the_other():
    app = SharedDocumentApp()
    async with app.run_test():
        ta1 = app.query_one("#a", TextArea)
        ta2 = app.query_one("#b", TextArea)

        ta1.insert("X", location=(0, 0))

        assert ta1.text == "X" + INITIAL_TEXT
        assert ta2.text == ta1.text
        for row in range(ta1.document.line_count):
            assert ta2.document[row] == ta1.document[row]


async def test_deletions_and_multiline_edits_propagate():
    app = SharedDocumentApp()
    async with app.run_test():
        ta1 = app.query_one("#a", TextArea)
        ta2 = app.query_one("#b", TextArea)

        ta1.replace("\n", (0, 3), (0, 4))
        assert ta1.text == ta2.text
        ta1.delete((0, 0), (1, 0))
        assert ta1.text == ta2.text
        assert ta1.document.line_count == ta2.document.line_count


async def test_selections_are_independent_between_areas():
    app = SharedDocumentApp()
    async with app.run_test():
        ta1 = app.query_one("#a", TextArea)
        ta2 = app.query_one("#b", TextArea)

        ta1.move_cursor((1, 2))
        # Moving the cursor in one area doesn't move it in the other.
        assert ta2.selection == Selection.cursor((0, 0))

        # An edit before the other area's cursor shifts its cursor along...
        ta2.move_cursor((0, 3))
        ta1.insert("ZZ", location=(0, 0))
        assert ta2.selection == Selection.cursor((0, 5))
        # ...while an edit after the cursor leaves it in place.
        ta1.insert("Q", location=(0, 9))
        assert ta2.selection == Selection.cursor((0, 5))


async def test_multiline_edit_shifts_remote_selection_rows():
    app = SharedDocumentApp()
    async with app.run_test():
        ta1 = app.query_one("#a", TextArea)
        ta2 = app.query_one("#b", TextArea)

        ta2.move_cursor((2, 1))
        ta1.insert("\n", location=(0, 0))
        assert ta2.selection == Selection.cursor((3, 1))


async def test_undo_and_redo_are_shared_across_areas():
    app = SharedDocumentApp("")
    async with app.run_test():
        ta1 = app.query_one("#a", TextArea)
        ta2 = app.query_one("#b", TextArea)

        ta1.insert("a", location=(0, 0))
        ta1.history.checkpoint()
        ta1.insert("b", location=(0, 1))
        assert ta2.text == "ab"

        # Undo from the area that did not make the edit.
        ta2.undo()
        assert ta1.text == "a"
        assert ta2.text == "a"
        ta2.undo()
        assert ta1.text == ""
        assert ta2.text == ""

        # Redo from a different area again.
        ta1.redo()
        assert ta1.text == "a"
        assert ta2.text == "a"
        ta2.redo()
        assert ta1.text == "ab"
        assert ta2.text == "ab"


async def test_continuous_alternating_edits_stay_consistent():
    app = SharedDocumentApp("")
    async with app.run_test():
        ta1 = app.query_one("#a", TextArea)
        ta2 = app.query_one("#b", TextArea)

        for index, character in enumerate("abcdef"):
            area = ta1 if index % 2 == 0 else ta2
            area.history.checkpoint()
            area.insert(character, location=(0, index))
            assert ta1.text == ta2.text == "abcdef"[: index + 1]

        for expected in ("abcde", "abcd", "abc", "ab", "a", ""):
            ta1.undo() if len(expected) % 2 == 0 else ta2.undo()
            assert ta1.text == expected
            assert ta2.text == expected


async def test_load_text_propagates_and_clears_shared_history():
    app = SharedDocumentApp()
    async with app.run_test():
        ta1 = app.query_one("#a", TextArea)
        ta2 = app.query_one("#b", TextArea)

        ta1.insert("edited", location=(0, 0))
        assert ta2.text.startswith("edited")

        ta1.load_text("brand new content")
        assert ta1.text == "brand new content"
        assert ta2.text == "brand new content"

        # The shared history was cleared by loading text.
        ta1.undo()
        ta2.undo()
        assert ta1.text == "brand new content"
        assert ta2.text == "brand new content"


async def test_soft_wrap_settings_are_independent():
    app = SharedDocumentApp("")
    async with app.run_test() as pilot:
        ta1 = app.query_one("#a", TextArea)
        ta2 = app.query_one("#b", TextArea)

        ta1.soft_wrap = False
        ta2.soft_wrap = True
        await pilot.pause()

        assert ta1.wrap_width == 0
        assert ta2.wrap_width > 0

        ta1.insert("x" * 200, location=(0, 0))
        assert ta1.text == ta2.text
        # The wrapped view in ta2 occupies multiple rows, ta1 does not wrap.
        assert ta2.wrapped_document.height > ta1.wrapped_document.height


async def test_scroll_positions_are_independent():
    lines = "\n".join(f"line {index}" for index in range(100))
    app = SharedDocumentApp(lines)
    async with app.run_test() as pilot:
        ta1 = app.query_one("#a", TextArea)
        ta2 = app.query_one("#b", TextArea)

        ta1.scroll_to(y=30, animate=False)
        await pilot.pause()

        assert ta1.scroll_y > 0
        assert ta2.scroll_y == 0
        assert ta1.text == ta2.text


@pytest.mark.syntax
@requires_python_syntax
async def test_highlighting_language_is_independent_per_area():
    app = SharedDocumentApp("print('hi')\n")
    app.language_a = "python"
    app.language_b = None
    async with app.run_test():
        ta1 = app.query_one("#a", TextArea)
        ta2 = app.query_one("#b", TextArea)

        assert ta1.is_syntax_aware
        assert not ta2.is_syntax_aware

        # An edit in the plain-text area is still syntax-highlighted in ta1.
        ta2.insert("x = 1\n", location=(0, 0))
        assert ta1.text == ta2.text
        assert ta1.is_syntax_aware
        assert not ta2.is_syntax_aware
        ta1._build_highlight_map()


async def test_editing_again_inside_change_notification_stays_consistent():
    class ReentrantChangeApp(App[None]):
        def __init__(self) -> None:
            super().__init__()
            self.document = Document("")

        def compose(self) -> ComposeResult:
            yield TextArea(document=self.document, id="a")
            yield TextArea(document=self.document, id="b")

        def on_text_area_changed(self, event: TextArea.Changed) -> None:
            area = event.text_area
            if not self.is_running:
                # Ignore change messages drained while the app is shutting down.
                return
            other = self.query_one("#b" if area.id == "a" else "#a", TextArea)
            # Any change in one area triggers a follow-up edit from the other
            # area, but stop once the marker is present to avoid an infinite
            # handler loop.
            if not area.text.endswith("!"):
                other.insert("!", location=(area.document.end))

    app = ReentrantChangeApp()
    async with app.run_test() as pilot:
        ta1 = app.query_one("#a", TextArea)
        ta2 = app.query_one("#b", TextArea)

        ta1.insert("hello", location=(0, 0))
        await pilot.pause()

        assert ta1.text == "hello!"
        assert ta2.text == "hello!"
        # The nested edit was recorded in the shared history and can be undone
        # consistently from either side. Check synchronously (the app's change
        # handler deliberately treats a missing marker as a change to make).
        ta2.undo()
        assert ta1.text == "hello"
        assert ta2.text == "hello"
        ta1.undo()
        assert ta1.text == ""
        assert ta2.text == ""
        await pilot.pause()


async def test_closing_one_area_keeps_the_others_working():
    app = SharedDocumentApp("")
    async with app.run_test() as pilot:
        ta1 = app.query_one("#a", TextArea)
        ta2 = app.query_one("#b", TextArea)

        ta1.insert("before close", location=(0, 0))
        assert ta2.text == "before close"

        await ta1.remove()
        await pilot.pause()
        assert ta1 not in ta2.document_share
        assert len(ta2.document_share) == 1

        frozen_text = ta1.text
        ta2.insert(" after", location=(0, len(ta2.document[0])))
        # The remaining area keeps editing with shared history...
        assert ta2.text == "before close after"
        # ...while the removed area is untouched by the change.
        assert ta1.text == frozen_text

        # Undo still works on the surviving area.
        ta2.undo()
        assert ta2.text == "before close"


async def test_new_area_can_join_existing_document_later():
    class LateJoinApp(App[None]):
        def __init__(self) -> None:
            super().__init__()
            self.document = Document("original")

        def compose(self) -> ComposeResult:
            yield TextArea(document=self.document, id="a")

    app = LateJoinApp()
    async with app.run_test() as pilot:
        ta1 = app.query_one("#a", TextArea)
        ta3 = TextArea(document=app.document, id="c")
        await app.mount(ta3)
        await pilot.pause()

        assert ta3.text == "original"
        ta1.insert("!", location=(0, 8))
        assert ta3.text == "original!"
        assert ta1.history is ta3.history
