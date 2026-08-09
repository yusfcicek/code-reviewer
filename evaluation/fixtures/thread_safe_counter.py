"""A lock held for the lifetime of the object that owns it.

Constructing a lock acquires nothing. The rule that said otherwise blocked
this project's own build when Level 17 added three of them.
"""

import threading


class Counter:
    def __init__(self):
        self._lock = threading.Lock()
        self._value = 0

    def increment(self):
        with self._lock:
            self._value += 1
        return self._value
