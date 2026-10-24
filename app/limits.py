"""ASGI middleware that caps the request body by counting the bytes actually received (QA W2).

It rejects early on Content-Length and also cuts off chunked requests (no Content-Length)
once the received bytes pass the limit, answering with 413 {error, message}.
FastAPI turns exceptions raised while reading the body into its own 400, so after an
overflow this middleware replaces whatever the app responds with by a 413.
"""
from __future__ import annotations

import json
from typing import Callable


class BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app, limit_for: Callable[[str], int]):
        self.app = app
        self.limit_for = limit_for

    @staticmethod
    async def _send_413(send, limit: int):
        body = json.dumps({"error": "payload_too_large",
                           "message": f"요청 본문이 너무 큽니다(최대 {limit // (1024 * 1024)} MB)."},
                          ensure_ascii=False).encode("utf-8")
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode()),
                                (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.limit_for(scope.get("path", ""))
        cl = dict(scope.get("headers") or []).get(b"content-length")
        if cl is not None and cl.isdigit() and int(cl) > limit:
            return await self._send_413(send, limit)

        state = {"received": 0, "over": False, "started": False}

        async def limited_receive():
            msg = await receive()
            if msg["type"] == "http.request":
                state["received"] += len(msg.get("body", b""))
                if state["received"] > limit:
                    state["over"] = True
                    raise BodyTooLarge()
            return msg

        async def guarded_send(msg):
            if state["over"]:
                if msg["type"] == "http.response.start" and not state["started"]:
                    state["started"] = True
                    await self._send_413(send, limit)
                return  # drop the app's own response after an overflow
            if msg["type"] == "http.response.start":
                state["started"] = True
            await send(msg)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if state["over"]:
                if not state["started"]:
                    state["started"] = True
                    await self._send_413(send, limit)
                return
            raise
