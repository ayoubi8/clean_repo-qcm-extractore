"""Server-Timing + slow-request log (lag plan Phase 0 / B2).

Pure ASGI middleware (no BaseHTTPMiddleware: it does not buffer streamed
responses and leaves WebSockets alone). Adds to every HTTP response:

    Server-Timing: app;dur=<ms>       time spent inside the API process
    Timing-Allow-Origin: *            lets the browser show it cross-origin

and prints one `[SLOW]` line for requests slower than SLOW_REQUEST_MS
(default 1000). Compare DevTools "Waiting for server response" with `app;dur`
to split network time from server time.
"""
import os
import time


class ServerTimingMiddleware:
    def __init__(self, app):
        self.app = app
        try:
            self.slow_ms = float(os.environ.get("SLOW_REQUEST_MS", "1000"))
        except ValueError:
            self.slow_ms = 1000.0

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()

        async def send_wrapper(message):
            if message.get("type") == "http.response.start":
                dur = (time.perf_counter() - start) * 1000.0
                headers = list(message.get("headers") or [])
                headers.append((b"server-timing", f"app;dur={dur:.1f}".encode()))
                headers.append((b"timing-allow-origin", b"*"))
                message = dict(message, headers=headers)
                if dur >= self.slow_ms:
                    print(f"[SLOW] {scope.get('method')} {scope.get('path')} {dur:.0f} ms")
            await send(message)

        await self.app(scope, receive, send_wrapper)
