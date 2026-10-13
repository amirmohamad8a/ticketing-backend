import time
from collections import deque


class MessageRateLimiter:
    def __init__(self, limit, window_seconds):
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits = deque()

    def allow(self):
        now = time.monotonic()
        cutoff = now - self.window_seconds
        while self._hits and self._hits[0] <= cutoff:
            self._hits.popleft()
        if len(self._hits) >= self.limit:
            return False
        self._hits.append(now)
        return True
