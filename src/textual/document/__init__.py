"""Documents that can be opened in a [`TextArea`][textual.widgets.TextArea].

A [`Document`][textual.document.Document] holds text content. The same
`Document` instance may be passed to multiple `TextArea` widgets; those widgets
then share their text and undo/redo history, while keeping independent cursors,
selections, wrapping, scroll positions and highlighting.
"""

from textual.document._document import (
    Document,
    DocumentBase,
    EditResult,
    Location,
    Selection,
)
from textual.document._document_share import DocumentShare, get_document_share

__all__ = [
    "Document",
    "DocumentBase",
    "DocumentShare",
    "EditResult",
    "Location",
    "Selection",
    "get_document_share",
]
