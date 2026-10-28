import asyncio
import json
from backend.upload_limits import UploadLimitMiddleware


def test_reject_body_before_parser():
    messages = []
    async def app(scope, receive, send):
        raise AssertionError('parser must not be reached')
    async def receive():
        return {'type': 'http.request', 'body': b'abcdef', 'more_body': False}
    async def send(message):
        messages.append(message)
    middleware = UploadLimitMiddleware(app, max_bytes=5)
    asyncio.run(middleware({'type': 'http', 'method': 'POST', 'path': '/sessions/x/documents'}, receive, send))
    assert messages[0]['status'] == 413


def test_replays_bounded_body():
    seen = []
    async def app(scope, receive, send):
        message = await receive()
        seen.append(message['body'])
        assert not message['more_body']
    async def receive():
        return {'type': 'http.request', 'body': b'abc', 'more_body': False}
    async def send(message):
        pass
    asyncio.run(UploadLimitMiddleware(app, 5)({'type': 'http', 'method': 'POST', 'path': '/documents'}, receive, send))
    assert seen == [b'abc']
