import asyncio
import logging
import os

import pytest

from dbus_ezy import Message
from dbus_ezy._private.address import parse_address
from dbus_ezy.aio import MessageBus


@pytest.mark.asyncio
async def test_tcp_connection_with_forwarding():
    host = "127.0.0.1"
    port = "55556"

    addr_info = parse_address(os.environ.get("DBUS_SESSION_BUS_ADDRESS"))
    assert addr_info
    if "abstract" in addr_info[0][1]:
        path = f'\0{addr_info[0][1]["abstract"]}'
    elif "path" in addr_info[0][1]:
        path = addr_info[0][1]["path"]

    assert path

    async def handle_connection(tcp_reader: asyncio.StreamReader, tcp_writer: asyncio.StreamWriter):
        unix_reader, unix_writer = await asyncio.open_unix_connection(path)

        async def handle_read():
            try:
                while True:
                    data = await tcp_reader.read(1024)
                    if not data:
                        break
                    unix_writer.write(data)
            finally:
                unix_writer.close()

        async def handle_write():
            try:
                while True:
                    data = await unix_reader.read(1024)
                    if not data:
                        print("unix_reader closed")
                        break
                    tcp_writer.write(data)
            finally:
                tcp_writer.close()

        handle_read_task = asyncio.create_task(handle_read())
        handle_write_task = asyncio.create_task(handle_write())

        try:
            await handle_read_task
        except Exception:
            logging.exception("")

        try:
            await handle_write_task
        except Exception:
            logging.exception("")

    server = await asyncio.start_server(handle_connection, host, port)

    async with server:
        async with MessageBus(bus_address=f"tcp:host={host},port={port}") as bus:
            # basic tests to see if it works
            result = await bus.call(
                Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus.Peer",
                    member="Ping",
                )
            )
            assert result

            intr = await bus.introspect("org.freedesktop.DBus", "/org/freedesktop/DBus")
            obj = bus.get_proxy_object("org.freedesktop.DBus", "/org/freedesktop/DBus", intr)
            iface = obj.get_interface("org.freedesktop.DBus.Peer")
            await iface.call_ping()

            assert bus._sock.getpeername()[0] == host
            assert bus._sock.getsockname()[0] == host
            assert bus._sock.gettimeout() == 0
            assert bus._stream.closed is False

        # yield to event loop to allow handle_connection to finish
        await asyncio.sleep(0)
