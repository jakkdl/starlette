# based off of test_requests.test_request_disconnect
from __future__ import annotations

from typing import Any

import anyio
import pytest
from anyio.streams.memory import MemoryObjectReceiveStream

from starlette.requests import Request
from starlette.types import Message, Receive, Scope, Send


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


@pytest.mark.xfail("this is broken currently")
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
