from contextlib import AsyncExitStack

import pytest

from dbus_ezy import Message
from dbus_ezy.aio import MessageBus
from dbus_ezy.constants import RequestNameReply
from dbus_ezy.introspection import Node
from dbus_ezy.message_bus import current_message
from dbus_ezy.service import ServiceInterface, signal


class ExampleInterface(ServiceInterface):
    def __init__(self):
        super().__init__("test.interface")

    @signal()
    def SomeSignal(self) -> "s":
        return "hello"

    @signal()
    def SignalMultiple(self) -> "ss":
        return ["hello", "world"]


@pytest.mark.asyncio
async def test_signals():
    async with AsyncExitStack() as stack:
        bus1 = await stack.enter_async_context(MessageBus())
        bus2 = await stack.enter_async_context(MessageBus())

        bus_intr = await bus1.introspect("org.freedesktop.DBus", "/org/freedesktop/DBus")
        bus_obj = bus1.get_proxy_object("org.freedesktop.DBus", "/org/freedesktop/DBus", bus_intr)
        stats = bus_obj.get_interface("org.freedesktop.DBus.Debug.Stats")

        await bus1.request_name("test.signals.name")
        service_interface = ExampleInterface()
        bus1.export("/test/path", service_interface)

        obj = bus2.get_proxy_object(
            "test.signals.name", "/test/path", bus1._introspect_export_path("/test/path")
        )
        interface = obj.get_interface(service_interface.name)

        async def ping():
            await bus2.call(
                Message(
                    destination=bus1.unique_name,
                    interface="org.freedesktop.DBus.Peer",
                    path="/test/path",
                    member="Ping",
                )
            )

        err = None

        single_counter = 0

        def single_handler(value):
            try:
                nonlocal single_counter
                nonlocal err
                assert value == "hello"
                assert current_message.sender
                single_counter += 1
            except Exception as e:
                err = e

        multiple_counter = 0

        def multiple_handler(value1, value2):
            nonlocal multiple_counter
            nonlocal err
            try:
                assert value1 == "hello"
                assert value2 == "world"
                assert current_message.sender
                multiple_counter += 1
            except Exception as e:
                err = e

        await ping()
        match_rules = await stats.call_get_all_match_rules()
        assert bus2.unique_name in match_rules
        bus_match_rules = match_rules[bus2.unique_name]
        # the bus connection itself takes a rule on NameOwnerChange after the high
        # level client is initialized
        assert len(bus_match_rules) == 1
        assert len(bus2._user_message_handlers) == 0

        interface.on_some_signal(single_handler)
        interface.on_signal_multiple(multiple_handler)

        # Interlude: adding a signal handler with `on_[signal]` should add a match rule and
        # message handler. Removing a signal handler with `off_[signal]` should
        # remove the match rule and message handler to avoid memory leaks.
        await ping()
        match_rules = await stats.call_get_all_match_rules()
        assert bus2.unique_name in match_rules
        bus_match_rules = match_rules[bus2.unique_name]
        # test the match rule and user handler has been added
        assert len(bus_match_rules) == 2
        assert (
            "type='signal',interface='test.interface',path='/test/path',sender='test.signals.name'"
            in bus_match_rules
        )
        assert len(bus2._user_message_handlers) == 1

        service_interface.SomeSignal()
        await ping()
        assert err is None
        assert single_counter == 1

        service_interface.SignalMultiple()
        await ping()
        assert err is None
        assert multiple_counter == 1

        # special case: another bus with the same path and interface but on a
        # different name and connection will trigger the match rule of the first
        # (happens with mpris)
        bus3 = await stack.enter_async_context(MessageBus())
        await bus3.request_name("test.signals.name2")
        service_interface2 = ExampleInterface()
        bus3.export("/test/path", service_interface2)

        obj = bus2.get_proxy_object(
            "test.signals.name2", "/test/path", bus3._introspect_export_path("/test/path")
        )
        # we have to add a dummy handler to add the match rule
        iface2 = obj.get_interface(service_interface2.name)

        def dummy_signal_handler(what):
            pass

        iface2.on_some_signal(dummy_signal_handler)
        await ping()

        service_interface2.SomeSignal()
        await ping()
        # single_counter is not incremented for signals of the second interface
        assert single_counter == 1

        interface.off_some_signal(single_handler)
        interface.off_signal_multiple(multiple_handler)
        iface2.off_some_signal(dummy_signal_handler)

        # After `off_[signal]`, the match rule and user handler should be removed
        await ping()
        match_rules = await stats.call_get_all_match_rules()
        assert bus2.unique_name in match_rules
        bus_match_rules = match_rules[bus2.unique_name]
        assert len(bus_match_rules) == 1
        assert (
            "type='signal',interface='test.interface',path='/test/path',sender='test.signals.name'"
            not in bus_match_rules
        )
        assert len(bus2._user_message_handlers) == 0


@pytest.mark.asyncio
async def test_signals_with_changing_owners():
    well_known_name = "test.signals.changing.name"

    async with AsyncExitStack() as stack:
        client_bus = await stack.enter_async_context(MessageBus())
        # not using context manger - will be disconnect manually.
        service_bus1 = await MessageBus().connect()
        service_bus2 = await stack.enter_async_context(MessageBus())

        async def ping():
            await client_bus.call(
                Message(
                    destination=client_bus.unique_name,
                    interface="org.freedesktop.DBus.Peer",
                    path="/test/path",
                    member="Ping",
                )
            )

        service_interface = ExampleInterface()
        introspection = Node.default()
        introspection.interfaces.append(service_interface.introspect())

        # get the interface before export
        obj = client_bus.get_proxy_object(well_known_name, "/test/path", introspection)
        iface = obj.get_interface("test.interface")
        counter = 0

        def handler(what):
            nonlocal counter
            counter += 1

        iface.on_some_signal(handler)
        await ping()

        # now export and get the name
        service_bus1.export("/test/path", service_interface)
        result = await service_bus1.request_name(well_known_name)
        assert result is RequestNameReply.PRIMARY_OWNER

        # the signal should work
        service_interface.SomeSignal()
        await ping()
        assert counter == 1
        counter = 0

        # now queue up a transfer of the name
        service_interface2 = ExampleInterface()
        service_bus2.export("/test/path", service_interface2)
        result = await service_bus2.request_name(well_known_name)
        assert result is RequestNameReply.IN_QUEUE

        # if it doesn't own the name, the signal shouldn't work here
        service_interface2.SomeSignal()
        await ping()
        assert counter == 0

        # now transfer over the name and it should work
        service_bus1.disconnect()
        await ping()

        service_interface2.SomeSignal()
        await ping()
        assert counter == 1
        counter = 0
