import io
import json
import os
from dataclasses import dataclass
from pprint import pprint

import pytest

from dbus_ezy import Message, MessageFlag, MessageType, Signature, Variant
from dbus_ezy._private.unmarshaller import Unmarshaller
from dbus_ezy.signature import parse_single_type


def hexdump(buffer: bytes):
    lines = []
    for i in range(0, len(buffer), 16):
        line_bytes = bytearray(buffer[i : i + 16])
        line = "{:08x}  {:23}  {:23}  |{:16}|".format(
            i,
            " ".join(("{:02x}".format(x) for x in line_bytes[:8])),
            " ".join(("{:02x}".format(x) for x in line_bytes[8:])),
            "".join((chr(x) if 32 <= x < 127 else "." for x in line_bytes)),
        )
        lines.append(line)
    return "\n".join(lines)


@dataclass
class MessageExample:
    data: bytes
    message: Message

    @staticmethod
    def from_json(item):
        copy = dict(item["message"])
        if "message_type" in copy:
            copy["message_type"] = MessageType(copy["message_type"])
        if "flags" in copy:
            copy["flags"] = MessageFlag(copy["flags"])

        message = Message(**copy)
        body = []
        for i, child in enumerate(message.signature.children):
            body.append(replace_variants(child, message.body[i]))
        message.body = body

        return MessageExample(bytes.fromhex(item["data"]), message)


# variants are an object in the json
def replace_variants(signature: Signature, item):
    if signature.type_code == "v" and type(item) is not Variant:
        item = Variant(
            item["signature"],
            replace_variants(parse_single_type(item["signature"]), item["value"]),
        )
    elif signature.type_code == "a":
        for i, item_child in enumerate(item):
            if signature.children[0].type_code == "{":
                for k, v in item.items():
                    item[k] = replace_variants(signature.children[0].children[1], v)
            else:
                item[i] = replace_variants(signature.children[0], item_child)
    elif signature.type_code == "(":
        for i, item_child in enumerate(item):
            if signature.children[0].type_code == "{":
                assert False
            else:
                item[i] = replace_variants(signature.children[i], item_child)

    return item


# these messages have been verified with another library
messages = [
    MessageExample.from_json(item)
    for item in json.load(open(os.path.dirname(__file__) + "/data/messages.json"))
]


@pytest.mark.parametrize("item", messages)
def test_marshall(item: MessageExample):
    pprint(item.message)
    print()
    print("Expected:")
    print(hexdump(item.data))
    print()

    buf = item.message._marshall()

    print("Marshaled:")
    print(hexdump(bytes(buf)))

    assert buf == item.data


@pytest.mark.parametrize("item", messages)
def test_unmarshall(item: MessageExample):
    print(hexdump(item.data))
    print()
    print("Expected:")
    pprint(item.message)
    print()

    stream = io.BytesIO(item.data)
    unmarshaller = Unmarshaller(stream)
    message = unmarshaller.unmarshall()

    print("Unmarshalled:")
    pprint(message)

    assert message == item.message


def test_unmarshall_can_resume():
    """Verify resume works."""
    bluez_rssi_message = (
        "6c04010134000000e25389019500000001016f00250000002f6f72672f626c75657a2f686369302f6465"
        "765f30385f33415f46325f31455f32425f3631000000020173001f0000006f72672e667265656465736b"
        "746f702e444275732e50726f7065727469657300030173001100000050726f706572746965734368616e"
        "67656400000000000000080167000873617b73767d617300000007017300040000003a312e3400000000"
        "110000006f72672e626c75657a2e446576696365310000000e0000000000000004000000525353490001"
        "6e00a7ff000000000000"
    )
    message_bytes = bytes.fromhex(bluez_rssi_message)

    class SlowStream(io.IOBase):
        """A fake stream that will only give us one byte at a time."""

        def __init__(self):
            self.data = message_bytes
            self.pos = 0

        def read(self, n) -> bytes:
            data = self.data[self.pos : self.pos + 1]
            self.pos += 1
            return data

    stream = SlowStream()
    unmarshaller = Unmarshaller(stream)

    for _ in range(len(bluez_rssi_message)):
        if unmarshaller.unmarshall():
            break
    assert unmarshaller.message is not None


def test_ay_buffer():
    body = [bytes(10000)]
    msg = Message(path="/test", member="test", signature="ay", body=body)
    marshalled = msg._marshall()
    unmarshalled_msg = Unmarshaller(io.BytesIO(marshalled)).unmarshall()
    assert unmarshalled_msg.body[0] == body[0]
