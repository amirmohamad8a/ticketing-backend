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


class TypingThrottle:
    def __init__(self, interval_seconds):
        self.interval_seconds = interval_seconds
        self._state = {}

    def allow(self, ticket_id, is_typing):
        now = time.monotonic()
        previous = self._state.get(ticket_id)
        if is_typing:
            if previous is not None and previous[0] and now - previous[1] < self.interval_seconds:
                return False
            self._state[ticket_id] = (True, now)
            return True
        if previous is None or not previous[0]:
            return False
        self._state[ticket_id] = (False, now)
        return True

    def is_typing(self, ticket_id):
        state = self._state.get(ticket_id)
        return state is not None and state[0]

    def active_tickets(self):
        return [ticket_id for ticket_id, (typing_now, _) in self._state.items() if typing_now]

    def clear(self, ticket_id):
        self._state.pop(ticket_id, None)
