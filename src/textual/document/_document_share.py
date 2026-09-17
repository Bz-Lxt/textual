from __future__ import annotations

from typing import TYPE_CHECKING

from textual.document._history import EditHistory

if TYPE_CHECKING:
    from textual.document._document import DocumentBase
    from textual.widgets._text_area import TextArea

_SHARE_ATTRIBUTE = "_textual_document_share"
"""Attribute set on a shared `Document` instance pointing at its `DocumentShare`."""

DEFAULT_CHECKPOINT_TIMER = 2.0
DEFAULT_CHECKPOINT_MAX_CHARACTERS = 100


class DocumentShare:
    """Coordinates a group of [`TextArea`][textual.widgets.TextArea] widgets
    which display and edit the same content.

    Every linked `TextArea` edits its own (kept identical) `Document`, allowing
    per-view configuration such as language/highlighting and soft wrapping. The
    share is the single source of truth for the undo/redo history, and it keeps
    track of the currently linked text areas so edits can be fanned out to all
    of them.

    Linking is handled automatically when a `TextArea` is constructed with the
    same `Document` instance; application code generally does not need to use
    this class directly.
    """

    def __init__(self, max_checkpoints: int = 50) -> None:
        """Initialise the share.

        Args:
            max_checkpoints: The maximum number of undo history checkpoints
                retained for every linked `TextArea`.
        """
        self.history: EditHistory = EditHistory(
            max_checkpoints=max_checkpoints,
            checkpoint_timer=DEFAULT_CHECKPOINT_TIMER,
            checkpoint_max_characters=DEFAULT_CHECKPOINT_MAX_CHARACTERS,
        )
        """The single undo/redo history shared by every linked `TextArea`."""

        self._text_areas: set[TextArea] = set()

    def add(self, text_area: TextArea) -> None:
        """Link a `TextArea` to this share.

        Args:
            text_area: The text area to link.
        """
        self._text_areas.add(text_area)

    def discard(self, text_area: TextArea) -> None:
        """Unlink a `TextArea` from this share.

        After unlinking (e.g. when the text area is unmounted/closed) edits in
        other areas no longer touch it, and the remaining areas keep working.

        Args:
            text_area: The text area to unlink.
        """
        self._text_areas.discard(text_area)

    def members(self) -> list[TextArea]:
        """All text areas currently linked to this share.

        Returns:
            A list of the linked text areas.
        """
        return list(self._text_areas)

    def others(self, text_area: TextArea) -> list[TextArea]:
        """All linked text areas apart from the given one.

        Args:
            text_area: The text area to exclude.

        Returns:
            The other linked text areas.
        """
        return [area for area in self._text_areas if area is not text_area]

    def __len__(self) -> int:
        return len(self._text_areas)

    def __contains__(self, text_area: object) -> bool:
        return text_area in self._text_areas


def get_document_share(
    document: DocumentBase, max_checkpoints: int = 50
) -> DocumentShare:
    """Get the share associated with a document, creating one if necessary.

    The share is cached on the document itself, so constructing several
    `TextArea` widgets with the same `Document` instance links them together.

    Args:
        document: The document whose share should be retrieved.
        max_checkpoints: The maximum number of undo history checkpoints to use
            when creating a new share.

    Returns:
        The share associated with the document.
    """
    share = getattr(document, _SHARE_ATTRIBUTE, None)
    if share is None:
        share = DocumentShare(max_checkpoints)
        try:
            setattr(document, _SHARE_ATTRIBUTE, share)
        except (AttributeError, TypeError):
            # If the document cannot carry the attribute (e.g. it uses
            # __slots__), callers will still hold a direct reference.
            pass
    return share
