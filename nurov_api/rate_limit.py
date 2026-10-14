import time
from collections import defaultdict, deque

from .errors import ApiError

_attempts = defaultdict(deque)


def check(key, *, limit=10, window_s=900):
    now = time.monotonic()
    q = _attempts[key]
    while q and now - q[0] > window_s:
        q.popleft()
    if len(q) >= limit:
        raise ApiError("TOO MANY ATTEMPTS", "Too many attempts. Try again later.", 429)


def record_failure(key, *, window_s=900):
    _attempts[key].append(time.monotonic())


def clear(key):
    _attempts.pop(key, None)
