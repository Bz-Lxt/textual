from __future__ import annotations

import asyncio
import sys
import threading
from collections import deque
from typing import IO, Callable, Deque, List, Optional, Union

from typing_extensions import Final

# Maximum size of a single write on Windows.
# Python has problems writing large strings to the console:
# https://github.com/Textualize/textual/issues/2548
# https://github.com/python/cpython/issues/82052
WRITE_CHUNK_SIZE: Final[int] = 8192

# Maximum time (in seconds) we will wait for in-flight writes to reach the
# device when stopping. After this the thread is abandoned (it is a daemon
# thread) so that the caller always converges.
STOP_TIMEOUT: Final[float] = 5.0


class _Control:
    """A write that must be delivered, in order, and is never coalesced."""

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text


class _Frame:
    """A complete frame which may be coalesced with newer pending frames."""

    __slots__ = ("text", "futures")

    def __init__(self, text: str, futures: List[asyncio.Future[bool]]) -> None:
        self.text = text
        self.futures = futures


class _Stop:
    """Sentinel: the thread should finish and exit."""

    __slots__ = ()


class WriterThread(threading.Thread):
    """A thread / file-like to do writes to the output device in the background.

    There are two kinds of writes:

    * Control writes ([`write`][textual.drivers._writer_thread.WriterThread.write])
      are always delivered, in order, and are never coalesced. Use them for
      terminal state changes such as entering the alt screen.
    * Frame writes ([`write_frame`][textual.drivers._writer_thread.WriterThread.write_frame])
      contain a complete rendered frame. Only the latest pending frame is
      retained: if a new frame is submitted while a previous frame has not yet
      been picked up for writing, the previous frame is replaced (its delivery
      futures are merged into the new frame). This bounds the output backlog to
      at most one frame in flight plus one pending frame, and guarantees that
      stale frames are never written to a slow output device.

    All enqueue operations return immediately and never block the calling
    thread (e.g. the asyncio event loop), so input processing stays responsive.
    """

    def __init__(
        self,
        file: IO[str],
        *,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        on_error: Optional[Callable[[BaseException], None]] = None,
    ) -> None:
        """Construct a WriterThread.

        Args:
            file: The file to write to.
            loop: The asyncio event loop, used to resolve frame delivery
                futures. May be `None` if delivery confirmation isn't required.
            on_error: Called (from the writer thread) if a write raises.
                The writer thread terminates after calling this.
        """
        super().__init__(daemon=True, name="textual-output")
        self._file = file
        self._loop = loop
        self._on_error = on_error
        self._condition = threading.Condition()
        self._items: Deque[Union[_Control, _Frame, _Stop]] = deque()
        self._stopping = False
        self._error: Optional[BaseException] = None

    @property
    def error(self) -> Optional[BaseException]:
        """The exception that terminated the writer, or `None`."""
        return self._error

    def write(self, text: str) -> None:
        """Write text. Text will be enqueued for writing.

        Control writes are never coalesced or dropped (while the thread is
        running). This method returns immediately.

        Args:
            text: Text to write to the file.
        """
        with self._condition:
            # If stop has already been requested, insert the control before the
            # stop sentinel so it still gets a chance to be delivered.
            if self._items and isinstance(self._items[-1], _Stop):
                self._items.insert(len(self._items) - 1, _Control(text))
            else:
                self._items.append(_Control(text))
            self._condition.notify()

    def write_frame(self, text: str) -> Optional[asyncio.Future[bool]]:
        """Write a complete frame, coalescing any pending stale frame.

        Args:
            text: Text containing a complete frame.

        Returns:
            A future which resolves to `True` when the frame (or a newer frame
            it was coalesced into) has been written and flushed, `False` if it
            was dropped without being displayed (e.g. the writer was stopped),
            or `None` if no event loop was supplied.
        """
        future = self._loop.create_future() if self._loop is not None else None
        with self._condition:
            if self._stopping:
                self._resolve_futures([future] if future is not None else [], False)
                return future
            items = self._items
            if items and isinstance(items[-1], _Frame):
                # A frame is queued but hasn't started writing; replace it with
                # the newer frame and merge its futures so every waiter is
                # notified when the surviving frame is delivered.
                pending_frame = items[-1]
                pending_frame.text = text
                if future is not None:
                    pending_frame.futures.append(future)
            else:
                items.append(_Frame(text, [future] if future is not None else []))
            self._condition.notify()
        return future

    def isatty(self) -> bool:
        """Pretend to be a terminal.

        Returns:
            True.
        """
        return True

    def fileno(self) -> int:
        """Get file handle number.

        Returns:
            File number of proxied file.
        """
        return self._file.fileno()

    def flush(self) -> None:
        """Flush the file (a no-op, because flush is done in the thread)."""
        return

    def run(self) -> None:
        """Run the thread."""
        write = self._file.write
        flush = self._file.flush
        condition = self._condition

        while True:
            with condition:
                while not self._items:
                    condition.wait()
                item = self._items.popleft()
                queued = bool(self._items)

            if isinstance(item, _Stop):
                break

            if isinstance(item, _Control):
                try:
                    write(item.text)
                    if not queued:
                        # Flush when there is a break, as before.
                        flush()
                except BaseException as error:
                    self._fail(error)
                    return
            else:
                # Complete frame: write (in chunks on Windows), flush, then
                # confirm delivery so callbacks correspond to this frame.
                try:
                    if sys.platform == "win32":
                        for offset in range(0, len(item.text), WRITE_CHUNK_SIZE):
                            write(item.text[offset : offset + WRITE_CHUNK_SIZE])
                    else:
                        write(item.text)
                    flush()
                except BaseException as error:
                    self._resolve_futures(item.futures, False)
                    self._fail(error)
                    return
                else:
                    self._resolve_futures(item.futures, True)

        try:
            flush()
        except BaseException:
            pass

    def _resolve_futures(
        self, futures: List[asyncio.Future[bool]], delivered: bool
    ) -> None:
        """Resolve frame delivery futures from the writer thread.

        Args:
            futures: Futures to resolve.
            delivered: Value to set.
        """
        if not futures or self._loop is None:
            return
        loop = self._loop

        def resolve_all() -> None:
            for future in futures:
                if not future.done():
                    future.set_result(delivered)

        try:
            loop.call_soon_threadsafe(resolve_all)
        except RuntimeError:
            # The event loop is closed.
            pass

    def _fail(self, error: BaseException) -> None:
        """Record a write error, notify the owner and terminate.

        Args:
            error: The exception raised while writing.
        """
        self._error = error
        on_error = self._on_error
        if on_error is not None:
            try:
                on_error(error)
            except BaseException:
                pass

    def stop(self) -> None:
        """Stop the thread, and block until it finished (bounded).

        Pending frames that have not started writing are dropped (their futures
        resolve to `False`); control writes are retained and delivered first.
        The join is bounded by `STOP_TIMEOUT`; if an in-flight write on the
        device does not complete in time, the daemon thread is abandoned so the
        caller still returns.
        """
        with self._condition:
            if not self._stopping:
                self._stopping = True
                retained: Deque[Union[_Control, _Frame, _Stop]] = deque()
                dropped_futures: List[asyncio.Future[bool]] = []
                for item in self._items:
                    if isinstance(item, _Frame):
                        dropped_futures.extend(item.futures)
                    else:
                        retained.append(item)
                retained.append(_Stop())
                self._items = retained
                self._condition.notify_all()
                self._resolve_futures(dropped_futures, False)
        self.join(STOP_TIMEOUT)
