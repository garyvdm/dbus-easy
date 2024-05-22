import pytest

from dbus_ezy import Message
from dbus_ezy.aio import MessageBus


@pytest.mark.asyncio
async def test_bus_disconnect_before_reply():
    """In this test, the bus disconnects before the reply comes in. Make sure
    the caller receives a reply with the error instead of hanging."""
    bus = MessageBus()
    assert not bus.connected
    await bus.connect()
    assert bus.connected

    ping = bus.call(
        Message(
            destination="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus",
            member="Ping",
        )
    )

    bus.disconnect()

    with pytest.raises((EOFError, BrokenPipeError)):
        await ping

    assert bus._disconnected
    assert not bus.connected
    assert (await bus.wait_for_disconnect()) is None


# This test doesn't make sense to me
# We maybe want to create a test where the dbus sever get's killed.

# @pytest.mark.asyncio
# async def test_unexpected_disconnect():
#     bus = MessageBus()
#     assert not bus.connected
#     await bus.connect()
#     assert bus.connected

#     ping = bus.call(
#         Message(
#             destination="org.freedesktop.DBus",
#             path="/org/freedesktop/DBus",
#             interface="org.freedesktop.DBus",
#             member="Ping",
#         )
#     )

#     print("before close")
#     os.close(bus._fd)
#     print("after close")

#     with pytest.raises(OSError):
#         await ping
#     print("after ping wait")

#     assert bus._disconnected
#     assert not bus.connected

#     with pytest.raises(OSError):
#         await bus.wait_for_disconnect()
