"""Bound the raw multipart body before Starlette parses/spools its files."""
import tempfile
from starlette.responses import JSONResponse


class UploadLimitMiddleware:
    def __init__(self, app, max_bytes):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST" or not scope.get("path", "").endswith("/documents"):
            return await self.app(scope, receive, send)
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as body:
            size = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                block = message.get("body", b"")
                size += len(block)
                if size > self.max_bytes:
                    response = JSONResponse({"error": {"code": "request_size_limit", "message": "Upload request exceeds the configured aggregate size limit."}}, status_code=413)
                    return await response(scope, receive, send)
                body.write(block)
                if not message.get("more_body", False):
                    break
            body.seek(0)

            async def replay():
                block = body.read(64 * 1024)
                return {"type": "http.request", "body": block, "more_body": body.tell() < size}

            await self.app(scope, replay, send)
