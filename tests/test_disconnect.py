# based off of test_requests.test_request_disconnect
from __future__ import annotations

from typing import Any

import anyio
import pytest
from anyio.streams.memory import MemoryObjectReceiveStream

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from .test_requests import TestClientFactory


async def _test_helper(app_send: Send, app_receive: Receive) -> bool:
    is_disconnected: bool | None = None

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        nonlocal is_disconnected
        is_disconnected = await request.is_disconnected()

    scope = {"type": "http", "method": "POST", "path": "/"}
    await app_send({"type": "http.disconnect"})

    await app(
        scope,
        app_receive,
        None,  # type: ignore
    )
    assert is_disconnected is not None
    return is_disconnected


@pytest.mark.xfail(reason="this is broken currently")
async def test_disconnect_with_receive_channel_as_receiver(
    anyio_backend_name: str,
    anyio_backend_options: dict[str, Any],
) -> None:
    send_channel, receive_channel = anyio.create_memory_object_stream[Message](1)
    assert await _test_helper(send_channel.send, receive_channel.receive)


class ReceiveWrapper:
    """wraps anyio.MemoryObjectReceiveStream so as not to checkpoint before receiving"""

    def __init__(self, receive_channel: MemoryObjectReceiveStream[Message]) -> None:
        self._receive_channel = receive_channel

    # starlette requires that a receiver does not checkpoint before attempting
    # to return the first event.
    async def receive(self) -> Message:
        try:
            return self._receive_channel.receive_nowait()
        except anyio.WouldBlock:
            pass
        await anyio.lowlevel.checkpoint()
        return await self._receive_channel.receive()


async def test_disconnect_with_receive_channel_as_receiver_workaround(
    anyio_backend_name: str,
    anyio_backend_options: dict[str, Any],
) -> None:
    send_channel, receive_channel = anyio.create_memory_object_stream[Message](1)
    receive_wrapper = ReceiveWrapper(receive_channel)
    assert await _test_helper(send_channel.send, receive_wrapper.receive)


@pytest.mark.xfail(reason="currently is_disconnected() will eat the first message sent")
def test_disconnect_does_not_timeout_or_eat_messages(
    test_client_factory: TestClientFactory,
) -> None:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        # removing the is_disconnected check makes the test pass
        assert not await request.is_disconnected()
        with anyio.fail_after(1):
            body = await request.body()
        response = JSONResponse({"body": body.decode()})
        await response(scope, receive, send)

    client = test_client_factory(app)

    response = client.get("/")
    assert response.json() == {"body": ""}

    response = client.post("/", json={"a": "123"})
    assert response.json() == {"body": '{"a": "123"}'}

    response = client.post("/", data="abc")  # type: ignore
    assert response.json() == {"body": "abc"}
