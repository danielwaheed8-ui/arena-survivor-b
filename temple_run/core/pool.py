"""
Object pooling.

Spawning thousands of short-lived particles (and recycling world entities as the
track scrolls) would otherwise churn the garbage collector and cause frame
hitches. A pool keeps a free-list of pre-constructed objects, hands them out on
``acquire`` and takes them back on ``release`` instead of allocating/freeing.

The pool is generic: give it a factory (how to build a fresh object) and,
optionally, a reset function (how to wipe one before reuse). Objects that expose
a ``reset(*args, **kwargs)`` method are reset automatically.
"""

from __future__ import annotations

from typing import Callable, Generic, Iterator, List, Optional, TypeVar

T = TypeVar("T")


class Pool(Generic[T]):
    def __init__(
        self,
        factory: Callable[[], T],
        reset: Optional[Callable[[T], None]] = None,
        prefill: int = 0,
        max_size: Optional[int] = None,
    ):
        self._factory = factory
        self._reset = reset
        self._free: List[T] = []
        self._live: List[T] = []
        self._max_size = max_size
        self.created = 0
        for _ in range(prefill):
            self._free.append(self._make())

    def _make(self) -> T:
        self.created += 1
        return self._factory()

    # -- lifecycle -----------------------------------------------------------
    def acquire(self) -> T:
        """Get an object from the pool (or build one if the free list is empty)."""
        obj = self._free.pop() if self._free else self._make()
        self._live.append(obj)
        return obj

    def release(self, obj: T) -> None:
        """Return an object to the pool."""
        if obj in self._live:
            self._live.remove(obj)
        if self._reset is not None:
            self._reset(obj)
        elif hasattr(obj, "reset"):
            # Best-effort: reset() with no args is common for pooled entities.
            try:
                obj.reset()  # type: ignore[call-arg]
            except TypeError:
                pass
        if self._max_size is None or len(self._free) < self._max_size:
            self._free.append(obj)

    def release_all(self) -> None:
        """Recycle everything currently live."""
        for obj in list(self._live):
            self.release(obj)

    # -- introspection -------------------------------------------------------
    @property
    def live(self) -> List[T]:
        return self._live

    @property
    def free_count(self) -> int:
        return len(self._free)

    @property
    def live_count(self) -> int:
        return len(self._live)

    def __iter__(self) -> Iterator[T]:
        return iter(self._live)

    def __len__(self) -> int:
        return len(self._live)
