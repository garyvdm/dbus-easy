import codecs
import io
import socket
import sys
from dataclasses import dataclass
from functools import partial
from struct import Struct
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from ..constants import MessageFlag, MessageType
from ..errors import InvalidMessageError
from ..message import Message
from ..signature import Signature, Variant, parse_signature, parse_single_type
from .constants import (
    BIG_ENDIAN,
    LITTLE_ENDIAN,
    PROTOCOL_VERSION,
    HeaderField,
)

# This is unfortunately slower than the version from dbus-next. The reason why version
# from dbus-next is faster is it inlines the align, read_byte, and read_range code,
# hence reducing function calls. For now, I prefer the code reuse, as it makes the
# code more readable.
#
# Potential solutions to get back the performance:
# * Make the BodyReader methods, and the read_xxx methods cython methods.
# * Compile signature into inline python code


class Unmarshaller:
    def __init__(self, stream_or_socket: Union[io.BufferedIOBase, socket.socket]):
        if isinstance(stream_or_socket, io.BufferedIOBase):
            self.read = partial(read_stream, stream_or_socket)
        elif isinstance(stream_or_socket, socket.socket):
            self.read = SocketReader(stream_or_socket)
        else:
            raise TypeError(f"Unsupported type {type(stream_or_socket)} for `stream_or_socket`.")

        # Store header, so if we are not able to read all of the body, we have the header for
        # next time we get called.
        self.header: Header | None = None
        # TODO: get rid of this - lots of test use it
        self.message: Message | None = None
        self.unix_fds: List[int] = []

    def unmarshall(self) -> Optional[Message]:
        """Unmarshall the message.

        The underlying read function will raise BlockingIOError
        if there are not enough bytes in the buffer. This allows unmarshall
        to be resumed when more data comes in over the wire.
        """
        try:
            self.message = None

            if self.header is None:
                header_buffer, unix_fds = self.read(HEADER_SIGNATURE_SIZE)
                self.unix_fds.extend(unix_fds)
                if header_buffer is None:
                    return None
                self.header = read_header(header_buffer)

            body_buffer, unix_fds = self.read(self.header.msg_len)
            self.unix_fds.extend(unix_fds)
            if body_buffer is None:
                return None
            self.message = read_body(body_buffer, self.header, self.unix_fds)
        except BlockingIOError:
            # print("BlockingIOError")
            return None
        else:
            self.header = None
            self.unix_fds = []
            return self.message


def read_stream(stream: io.RawIOBase, size: int) -> Tuple[bytes, Iterable[int]]:
    data = stream.read(size)
    if data == b"":
        raise EOFError()
    return data, ()


MAX_UNIX_FDS = 16
FD_STRUCT = Struct("I")  # What about endian
FD_CMSG_LEN = socket.CMSG_LEN(MAX_UNIX_FDS * FD_STRUCT.size)


class SocketReader:
    # This basically does what socket.SocketIO + BufferedReader does, but:
    # 1. It won't return unless the full requested size is received
    # 2. It handles receiving unix fd's

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.buffer: bytearray = None
        self.view: memoryview = None
        self.unix_fds: List[int] = None
        self.recv_size: int = 0

    def __call__(self, size: int):
        if self.buffer is None:
            self.buffer = bytearray(size)
            self.view = memoryview(self.buffer)
            self.unix_fds = list()
            self.recv_size = 0
        else:
            # Due to the way this get's called by unmarshall, the buffer len should always equal the size
            assert len(self.buffer) == size

        while self.recv_size < size:
            recv_size, ancdata, *_ = self.sock.recvmsg_into(
                (self.view[self.recv_size :],), FD_CMSG_LEN
            )
            if recv_size == 0:
                raise EOFError()
            for level, type_, data in ancdata:
                if level == socket.SOL_SOCKET and type_ == socket.SCM_RIGHTS:
                    for fd_item in FD_STRUCT.iter_unpack(data):
                        self.unix_fds.append(fd_item[0])
            self.recv_size += recv_size
        else:
            ret = self.buffer, self.unix_fds
            self.buffer = None
            self.view = None
            self.unix_fds = None
            return ret


HEADER_SIGNATURE_SIZE = 16
HEADER_FIELD_SIGNATURE = parse_single_type("(yv)")
HEADER_UNPACK_LENGTHS = {BIG_ENDIAN: Struct(">III"), LITTLE_ENDIAN: Struct("<III")}

UTF_8 = codecs.lookup("utf-8")
ASCII = codecs.lookup("ascii")

UNPACK_SYMBOL = {LITTLE_ENDIAN: "<", BIG_ENDIAN: ">"}
STRUCT_BY_ENDIAN_DBUS_TYPE: Dict[Tuple[int, str], Struct] = {
    (endian, dbus_type): Struct(f"{UNPACK_SYMBOL[endian]}{ctype}")
    for endian in (BIG_ENDIAN, LITTLE_ENDIAN)
    for dbus_type, ctype in (
        ("n", "h"),  # int16
        ("q", "H"),  # uint16
        ("i", "i"),  # int32
        ("u", "I"),  # uint32
        ("x", "q"),  # int64
        ("t", "Q"),  # uint64
        ("d", "d"),  # double
        ("h", "I"),  # uint32
    )
}


@dataclass(init=False, **(dict(slots=True) if sys.version_info >= (3, 10) else dict()))
class Header:
    endian: int
    message_type: MessageType
    flag: MessageFlag
    protocol_version: int
    body_len: int
    serial: int
    header_len: int
    msg_len: int


def read_header(buffer: bytes):
    """Read the header of the message."""

    # Signature is of the header is
    # BYTE, BYTE, BYTE, BYTE, UINT32, UINT32, ARRAY of STRUCT of (BYTE,VARIANT)
    header = Header()
    header.endian = buffer[0]
    header.message_type = MessageType(buffer[1])
    header.flag = MessageFlag(buffer[2])
    header.protocol_version = buffer[3]

    if header.endian != LITTLE_ENDIAN and header.endian != BIG_ENDIAN:
        raise InvalidMessageError(
            f"Expecting endianness as the first byte, got {header.endian} from {buffer}"
        )
    if header.protocol_version != PROTOCOL_VERSION:
        raise InvalidMessageError(f"got unknown protocol version: {header.protocol_version}")

    header.body_len, header.serial, header.header_len = HEADER_UNPACK_LENGTHS[
        header.endian
    ].unpack_from(buffer, 4)
    header.msg_len = header.header_len + (-header.header_len & 7) + header.body_len  # align 8
    return header


def read_body(buffer: bytes, header: Header, unix_fds: Sequence[int]):
    """Read the body of the message."""
    body_reader = BodyReader(buffer, header.endian)
    header_fields = dict(body_reader.read_header_fields(header.header_len))
    signature = parse_signature(header_fields.get(HeaderField.SIGNATURE, ""))
    body_reader.align(8)
    body = [body_reader.read_item(t) for t in signature.children] if header.body_len else []

    return Message(
        destination=header_fields.get(HeaderField.DESTINATION),
        path=header_fields.get(HeaderField.PATH),
        interface=header_fields.get(HeaderField.INTERFACE),
        member=header_fields.get(HeaderField.MEMBER),
        message_type=header.message_type,
        flags=header.flag,
        error_name=header_fields.get(HeaderField.ERROR_NAME),
        reply_serial=header_fields.get(HeaderField.REPLY_SERIAL),
        sender=header_fields.get(HeaderField.SENDER),
        unix_fds=unix_fds,
        signature=signature,
        body=body,
        serial=header.serial,
    )


class BodyReader:
    slots = ["buffer", "offset", "endian"]

    def __init__(self, buffer: bytes, endian: int):
        self.buffer = memoryview(buffer)
        self.endian = endian
        self.offset = 0

    def align(self, align: int):
        # Alignment padding is handled with the following formula below
        #
        # For any align value, the correct padding formula is:
        #
        #    (align - (offset % align)) % align
        #
        # However, if align is a power of 2 (always the case here), the slow MOD
        # operator can be replaced by a bitwise AND:
        #
        #    (align - (offset & (align - 1))) & (align - 1)
        #
        # Which can be simplified to:
        #
        #    -offset & (align - 1)
        self.offset += -self.offset & (align - 1)

    def read_range(self, size: int):
        start = self.offset
        self.offset = self.offset + size
        ret = self.buffer[start : self.offset]
        # print(f"read_range {start=:02x} {self.offset=:02x} {ret=}")
        return ret

    def read_byte(self, _=None):
        ret = self.buffer[self.offset]
        # print(f"read_range {self.offset=:02x} {ret=}")
        self.offset += 1
        return ret

    def read_header_fields(self, header_len: int):
        # Header fields are always a(yv)
        while self.offset < header_len - 1:
            field_id, field_value = self.read_struct(HEADER_FIELD_SIGNATURE)
            yield HeaderField(field_id), field_value.value

    def read_uint32(self) -> int:
        struct = STRUCT_BY_ENDIAN_DBUS_TYPE[(self.endian, "u")]
        self.align(struct.size)
        buffer = self.read_range(struct.size)
        return struct.unpack_from(buffer)[0]

    def read_item(self, signature: Signature) -> Any:
        """Dispatch to an argument reader or cast/unpack a C type."""
        type_code = signature.type_code

        if ctype_struct := STRUCT_BY_ENDIAN_DBUS_TYPE.get((self.endian, type_code)):
            self.align(ctype_struct.size)
            buffer = self.read_range(ctype_struct.size)
            return ctype_struct.unpack_from(buffer)[0]

        if complex_reader := self.COMPLEX_PARSERS.get(type_code):
            return complex_reader(self, signature)

    def read_boolean(self, _):
        return bool(self.read_uint32())

    def read_string(self, _):
        string_length = self.read_uint32()
        bytes_ = self.read_range(string_length)
        # Check for the terminating '\0'
        assert self.read_byte() == 0
        return UTF_8.decode(bytes_)[0]

    def read_signature(self, _=None):
        signature_len = self.read_byte()
        bytes_ = self.read_range(signature_len)
        # Check for the terminating '\0'
        assert self.read_byte() == 0
        return ASCII.decode(bytes_)[0]

    def read_variant(self, _=None):
        signature = parse_single_type(self.read_signature())
        # verify in Variant is only useful on construction not unmarshalling
        return Variant(signature, self.read_item(signature), verify=False)

    def read_struct(self, signature: Signature):
        self.align(8)
        return [self.read_item(child_type) for child_type in signature.children]

    def read_array(self, signature: Signature):
        array_length = self.read_uint32()

        child_signature = signature.children[0]

        if child_signature.type_code == "y":
            return self.read_range(array_length).tobytes()

        if child_signature.type_code in "xtd{(":
            # the first alignment is not included in the array size, so align before
            # calculating stop_offset
            self.align(8)

        stop_offset = self.offset + array_length - 1

        if child_signature.type_code == "{":
            result_dict = {}
            while self.offset < stop_offset:
                self.align(8)
                key = self.read_item(child_signature.children[0])
                value = self.read_item(child_signature.children[1])
                result_dict[key] = value
            return result_dict

        result_list = []
        while self.offset < stop_offset:
            result_list.append(self.read_item(child_signature))
        return result_list

    COMPLEX_PARSERS: Dict[str, Callable[["BodyReader", Signature], Any]] = {
        "y": read_byte,
        "b": read_boolean,
        "o": read_string,
        "s": read_string,
        "g": read_signature,
        "a": read_array,
        "(": read_struct,
        "v": read_variant,
    }
