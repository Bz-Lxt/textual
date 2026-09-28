from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from textual.document._document import EditResult, Location, Selection

if TYPE_CHECKING:
    from textual.widgets import TextArea


def _adjust_location_for_edit(
    location: Location,
    edit_bottom: Location,
    new_edit_end: Location,
) -> Location:
    """Map a location in the document to its new position after an edit.

    Locations at or after the edit (in document order) are shifted by the
    amount the edit changed the document by. Locations before the edit are
    unaffected.

    Args:
        location: The location to map.
        edit_bottom: The end location of the range that was replaced.
        new_edit_end: The end location reported by the completed edit.

    Returns:
        The mapped location.
    """
    row, column = location
    edit_bottom_row, edit_bottom_column = edit_bottom
    new_edit_to_row, new_edit_to_column = new_edit_end

    column_offset = new_edit_to_column - edit_bottom_column
    target_column = (
        column + column_offset
        if edit_bottom_row == row and edit_bottom_column <= column
        else column
    )

    row_offset = new_edit_to_row - edit_bottom_row
    target_row = row + row_offset if edit_bottom_row <= row else row

    return target_row, target_column


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
    """The primary Selection when the edit was originally performed, to be restored on undo."""

    _updated_selection: Selection | None = field(init=False, default=None)
    """Where the primary selection should be after the edit is (re)done."""

    _original_selections: tuple[Selection, ...] | None = field(
        init=False, default=None
    )
    """All selections (including multiple cursors) when the edit was originally
    performed, to be restored on undo."""

    _updated_selections: tuple[Selection, ...] | None = field(
        init=False, default=None
    )
    """Where all the selections should be after the edit is (re)done.

    The primary selection is stored separately in `_updated_selection`.
    """

    _restore_selection: Selection | None = field(init=False, default=None)
    """The primary selection `after` should currently restore."""

    _restore_selections: tuple[Selection, ...] | None = field(
        init=False, default=None
    )
    """The full set of selections `after` should currently restore."""

    _primary_edit: bool = field(init=False, default=False)
    """True if this edit corresponds to the primary selection within a group of
    edits performed simultaneously (e.g. editing with multiple cursors)."""

    _edit_result: EditResult | None = field(init=False, default=None)
    """The result of doing the edit."""

    def do(self, text_area: TextArea, record_selection: bool = True) -> EditResult:
        """Perform the edit operation.

        Args:
            text_area: The `TextArea` to perform the edit on.
            record_selection: If True, record the current selection(s) in the
                TextArea so that they may be restored if this Edit is undone in
                the future. When redoing an edit this is False, since the
                selection state to restore is already recorded on the edit.

        Returns:
            An `EditResult` containing information about the replace operation.
        """
        text = self.text

        # This code is mostly handling how we adjust TextArea.selection
        # when an edit is made to the document programmatically.
        # We want a user who is typing away to maintain their relative
        # position in the document even if an insert happens before
        # their cursor position.

        edit_bottom = self.bottom

        edit_result = text_area.document.replace_range(self.top, edit_bottom, text)
        new_edit_end_location = edit_result.end_location

        if record_selection:
            self._original_selection = text_area.selection
            self._original_selections = text_area.selections

            # Map every active selection through the edit so that additional
            # cursors are maintained alongside the primary one.
            original_selections = text_area.selections
            try:
                primary_index = list(original_selections).index(text_area.selection)
            except ValueError:
                primary_index = len(original_selections) - 1

            if self.maintain_selection_offset:
                mapped = [
                    self._map_selection(
                        selection, edit_bottom, new_edit_end_location
                    )
                    for selection in original_selections
                ]
            else:
                # A keyboard-style edit collapses every cursor to the edit end.
                mapped = [Selection.cursor(new_edit_end_location)]

            normalized, primary = text_area._normalize_selections(
                mapped, primary=mapped[primary_index]
            )
            self._updated_selections = normalized
            self._updated_selection = primary

        # Doing the edit (including redoing it) restores the post-edit state.
        # When `record_selection` is False the fields may have been recorded by
        # an earlier call (redo), or may be populated by the caller afterwards
        # (a group of simultaneous edits), so only point the restore targets at
        # them when they exist.
        if self._updated_selections is not None:
            self._restore_selections = self._updated_selections
        if self._updated_selection is not None:
            self._restore_selection = self._updated_selection

        self._edit_result = edit_result
        return edit_result

    @staticmethod
    def _map_selection(
        selection: Selection,
        edit_bottom: Location,
        new_edit_end: Location,
    ) -> Selection:
        """Map both ends of a selection through an edit, preserving orientation.

        Args:
            selection: The selection to map.
            edit_bottom: The end location of the range that was replaced.
            new_edit_end: The end location reported by the completed edit.

        Returns:
            A new selection with both endpoints mapped.
        """
        target_start = _adjust_location_for_edit(
            selection.start, edit_bottom, new_edit_end
        )
        target_end = _adjust_location_for_edit(
            selection.end, edit_bottom, new_edit_end
        )
        return Selection(target_start, target_end)

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

        # Undoing restores the state captured just before the edit.
        self._restore_selection = self._original_selection
        self._restore_selections = self._original_selections

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
        if self._restore_selections is not None:
            # Restore the full set of selections (multi-cursor editing).
            text_area._restore_selections(
                self._restore_selections, self._restore_selection
            )
        elif self._restore_selection is not None:
            text_area.selection = self._restore_selection
        text_area.record_cursor_width()

    @property
    def top(self) -> Location:
        """The Location impacted by this edit that is nearest the start of the document."""
        return min([self.from_location, self.to_location])

    @property
    def bottom(self) -> Location:
        """The Location impacted by this edit that is nearest the end of the document."""
        return max([self.from_location, self.to_location])
