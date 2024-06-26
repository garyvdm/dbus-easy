from contextlib import AsyncExitStack

import pytest

from dbus_ezy import Message, MessageType, aio, glib
from dbus_ezy.service import ServiceInterface, method
from test.util import check_gi_repository, skip_reason_no_gi

has_gi = check_gi_repository()


class ExampleInterface(ServiceInterface):
    def __init__(self):
        super().__init__("example.interface")

    @method()
    def echo_bytes(self, what: "ay") -> "ay":
        return what


@pytest.mark.asyncio
async def test_aio_big_message():
    "this tests that nonblocking reads and writes actually work for aio"
    async with AsyncExitStack() as stack:
        bus1 = await stack.enter_async_context(aio.MessageBus())
        bus2 = await stack.enter_async_context(aio.MessageBus())

        interface = ExampleInterface()
        bus1.export("/test/path", interface)

        # two megabytes
        big_body = [bytes(1000000) * 2]
        result = await bus2.call(
            Message(
                destination=bus1.unique_name,
                path="/test/path",
                interface=interface.name,
                member="echo_bytes",
                signature="ay",
                body=big_body,
            )
        )
        assert result.message_type == MessageType.METHOD_RETURN, result.body[0]
        assert result.body[0] == big_body[0]


@pytest.mark.skipif(not has_gi, reason=skip_reason_no_gi)
def test_glib_big_message():
    "this tests that nonblocking reads and writes actually work for glib"
    bus1 = glib.MessageBus().connect_sync()
    bus2 = glib.MessageBus().connect_sync()
    interface = ExampleInterface()
    bus1.export("/test/path", interface)

    # two megabytes
    big_body = [bytes(1000000) * 2]
    result = bus2.call_sync(
        Message(
            destination=bus1.unique_name,
            path="/test/path",
            interface=interface.name,
            member="echo_bytes",
            signature="ay",
            body=big_body,
        )
    )
    assert result.message_type == MessageType.METHOD_RETURN, result.body[0]
    assert result.body[0] == big_body[0]
