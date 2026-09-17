from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from textual.document._document import EditResult, Location, Selection

if TYPE_CHECKING:
    from textual.widgets import TextArea


def shift_selection(
    selection: Selection, replaced_bottom: Location, new_end: Location
) -> Selection:
    """Shift a selection to account for a replacement performed on a document.

    Locations after the replacement are shifted by the difference between the
    end of the replaced range and the end location of the inserted text.
    Locations on the replacement row are only shifted column-wise if they were
    at or after the replacement's end column.

    This is used both for the `TextArea` performing an edit and for other
    `TextArea` widgets linked to the same document, so every view keeps an
    independent selection that still tracks the change.

    Args:
        selection: The selection to shift.
        replaced_bottom: The end location of the range that was replaced.
        new_end: The end location after the replacement.

    Returns:
        The selection adjusted for the replacement.
    """
    edit_bottom_row, edit_bottom_column = replaced_bottom
    new_edit_to_row, new_edit_to_column = new_end

    column_offset = new_edit_to_column - edit_bottom_column
    row_offset = new_edit_to_row - edit_bottom_row

    def shift(location: Location) -> Location:
        location_row, location_column = location
        target_column = (
            location_column + column_offset
            if edit_bottom_row == location_row
            and edit_bottom_column <= location_column
            else location_column
        )
        target_row = (
            location_row + row_offset
            if edit_bottom_row <= location_row
            else location_row
        )
        return target_row, target_column

    return Selection(shift(selection.start), shift(selection.end))


@dataclass
class Edit:
    """Implements the Undoable protocol to replace text at some range within a document."""

    text: str
    """The text to insert. An empty string is equivalent to deletion."""

    from_location: Location
    """The start location of the insert."""

    to_location: Location
    """The end location of the insert"""

    maintain_selection_offset: bool
    """If True, the selection will maintain its offset to the replacement range."""

    _original_selection: Selection | None = field(init=False, default=None)
    """The Selection when the edit was originally performed, to be restored on undo."""

    _updated_selection: Selection | None = field(init=False, default=None)
    """Where the selection should move to after the replace happens."""

    _edit_result: EditResult | None = field(init=False, default=None)
    """The result of doing the edit."""

    def do(self, text_area: TextArea, record_selection: bool = True) -> EditResult:
        """Perform the edit operation.

        Args:
            text_area: The `TextArea` to perform the edit on.
            record_selection: If True, record the current selection in the TextArea
                so that it may be restored if this Edit is undone in the future.

        Returns:
            An `EditResult` containing information about the replace operation.
        """
        if record_selection:
            self._original_selection = text_area.selection

        text = self.text

        edit_result = text_area.document.replace_range(self.top, self.bottom, text)

        if self.maintain_selection_offset:
            self._updated_selection = shift_selection(
                text_area.selection, self.bottom, edit_result.end_location
            )
        else:
            self._updated_selection = Selection.cursor(edit_result.end_location)

        self._edit_result = edit_result
        return edit_result

    def undo(self, text_area: TextArea) -> EditResult:
        """Undo the edit operation.

        Looks at the data stored in the edit, and performs the inverse operation of `Edit.do`.

        Args:
            text_area: The `TextArea` to undo the insert operation on.

        Returns:
            An `EditResult` containing information about the replace operation.
        """
        replaced_text = self._edit_result.replaced_text
        edit_end = self._edit_result.end_location

        # Replace the span of the edit with the text that was originally there.
        undo_edit_result = text_area.document.replace_range(
            self.top, edit_end, replaced_text
        )
        self._updated_selection = self._original_selection

        return undo_edit_result

    def after(self, text_area: TextArea) -> None:
        """Hook for running code after an Edit has been performed via `Edit.do` *and*
        side effects such as re-wrapping the document and refreshing the display
        have completed.

        For example, we can't record cursor visual offset until we know where the cursor will
        land *after* wrapping has been performed, so we must wait until here to do it.

        Args:
            text_area: The `TextArea` this operation was performed on.
        """
        if self._updated_selection is not None:
            text_area.selection = self._updated_selection
        text_area.record_cursor_width()

    @property
    def top(self) -> Location:
        """The Location impacted by this edit that is nearest the start of the document."""
        return min([self.from_location, self.to_location])

    @property
    def bottom(self) -> Location:
        """The Location impacted by this edit that is nearest the end of the document."""
        return max([self.from_location, self.to_location])
