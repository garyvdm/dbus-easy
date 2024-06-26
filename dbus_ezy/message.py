import dataclasses
from typing import Any, List

from ._private.constants import LITTLE_ENDIAN, PROTOCOL_VERSION, HeaderField
from ._private.marshaller import Marshaller
from .constants import ErrorType, MessageFlag, MessageType
from .errors import InvalidMessageError
from .signature import Signature, Variant, parse_signature
from .validators import (
    assert_bus_name_valid,
    assert_interface_name_valid,
    assert_member_name_valid,
    assert_object_path_valid,
)

REQUIRED_FIELDS = {
    MessageType.METHOD_CALL: ("path", "member"),
    MessageType.SIGNAL: ("path", "member", "interface"),
    MessageType.ERROR: ("error_name", "reply_serial"),
    MessageType.METHOD_RETURN: ("reply_serial",),
}


@dataclasses.dataclass
class Message:
    """A class for sending and receiving messages through the
    :class:`MessageBus <dbus_ezy.message_bus.BaseMessageBus>` with the
    low-level api.

    A ``Message`` can be constructed by the user to send over the message bus.
    When messages are received, such as from method calls or signal emissions,
    they will use this class as well.

    :ivar destination: The address of the client for which this message is intended.
    :vartype destination: str
    :ivar path: The intended object path exported on the destination bus.
    :vartype path: str
    :ivar interface: The intended interface on the object path.
    :vartype interface: str
    :ivar member: The intended member on the interface.
    :vartype member: str
    :ivar message_type: The type of this message. A method call, signal, method return, or error.
    :vartype message_type: :class:`MessageType`
    :ivar flags: Flags that affect the behavior of this message.
    :vartype flags: :class:`MessageFlag`
    :ivar error_name: If this message is an error, the name of this error. Must be a valid interface name.
    :vartype error_name: str
    :ivar reply_serial: If this is a return type, the serial this message is in reply to.
    :vartype reply_serial: int
    :ivar sender: The address of the sender of this message. Will be a unique name.
    :vartype sender: str
    :ivar unix_fds: A list of unix fds that were sent in the header of this message.
    :vartype unix_fds: list(int)
    :ivar signature: The signature of the body of this message.
    :vartype signature: str
    :ivar signature_tree: The signature parsed as a signature tree.
    :vartype signature_tree: :class:`Signature`
    :ivar body: The body of this message. Must match the signature.
    :vartype body: list(Any)
    :ivar serial: The serial of the message. Will be automatically set during message sending if not present. Use the ``new_serial()`` method of the bus to generate a serial.
    :vartype serial: int

    :raises:
        - :class:`InvalidMessageError` - If the message is malformed or missing fields for the message type.
        - :class:`InvalidSignatureError` - If the given signature is not valid.
        - :class:`InvalidObjectPathError` - If ``path`` is not a valid object path.
        - :class:`InvalidBusNameError` - If ``destination`` is not a valid bus name.
        - :class:`InvalidMemberNameError` - If ``member`` is not a valid member name.
        - :class:`InvalidInterfaceNameError` - If ``error_name`` or ``interface`` is not a valid interface name.
    """

    destination: str = None
    path: str = None
    interface: str = None
    member: str = None
    message_type: MessageType = MessageType.METHOD_CALL
    flags: MessageFlag = MessageFlag.NONE
    error_name: str = None
    reply_serial: int = None
    sender: str = None
    unix_fds: List[int] = dataclasses.field(default_factory=list)
    signature: Signature = parse_signature("")

    body: List[Any] = dataclasses.field(default_factory=list)
    serial: int = 0

    def __post_init__(self):
        self.flags = (
            self.flags if type(self.flags) is MessageFlag else MessageFlag(bytes([self.flags]))
        )
        self.error_name = (
            self.error_name if type(self.error_name) is not ErrorType else self.error_name.value
        )
        if isinstance(self.signature, str):
            self.signature = parse_signature(self.signature)

        if self.destination is not None:
            assert_bus_name_valid(self.destination)
        if self.interface is not None:
            assert_interface_name_valid(self.interface)
        if self.path is not None:
            assert_object_path_valid(self.path)
        if self.member is not None:
            assert_member_name_valid(self.member)
        if self.error_name is not None:
            assert_interface_name_valid(self.error_name)

        required_fields = REQUIRED_FIELDS.get(self.message_type)
        if not required_fields:
            raise InvalidMessageError(f"got unknown message type: {self.message_type}")
        for field in required_fields:
            if not getattr(self, field):
                raise InvalidMessageError(f"missing required field: {field}")

    @staticmethod
    def new_error(msg: "Message", error_name: str, error_text: str) -> "Message":
        """A convenience constructor to create an error message in reply to the given message.

        :param msg: The message this error is in reply to.
        :type msg: :class:`Message`
        :param error_name: The name of this error. Must be a valid interface name.
        :type error_name: str
        :param error_text: Human-readable text for the error.

        :returns: The error message.
        :rtype: :class:`Message`

        :raises:
            - :class:`InvalidInterfaceNameError` - If the error_name is not a valid interface name.
        """
        return Message(
            message_type=MessageType.ERROR,
            reply_serial=msg.serial,
            destination=msg.sender,
            error_name=error_name,
            signature="s",
            body=[error_text],
        )

    @staticmethod
    def new_method_return(
        msg: "Message", signature: str = "", body: List[Any] = [], unix_fds: List[int] = []
    ) -> "Message":
        """A convenience constructor to create a method return to the given method call message.

        :param msg: The method call message this is a reply to.
        :type msg: :class:`Message`
        :param signature: The signature for the message body.
        :type signature: str
        :param body: The body of this message. Must match the signature.
        :type body: list(Any)
        :param unix_fds: List integer file descriptors to send with this message.
        :type body: list(int)

        :returns: The method return message
        :rtype: :class:`Message`

        :raises:
            - :class:`InvalidSignatureError` - If the signature is not a valid signature.
        """
        return Message(
            message_type=MessageType.METHOD_RETURN,
            reply_serial=msg.serial,
            destination=msg.sender,
            signature=signature,
            body=body,
            unix_fds=unix_fds,
        )

    @staticmethod
    def new_signal(
        path: str,
        interface: str,
        member: str,
        signature: str = "",
        body: List[Any] = None,
        unix_fds: List[int] = None,
    ) -> "Message":
        """A convenience constructor to create a new signal message.

        :param path: The path of this signal.
        :type path: str
        :param interface: The interface of this signal.
        :type interface: str
        :param member: The member name of this signal.
        :type member: str
        :param signature: The signature of the signal body.
        :type signature: str
        :param body: The body of this signal message.
        :type body: list(Any)
        :param unix_fds: List integer file descriptors to send with this message.
        :type body: list(int)

        :returns: The signal message.
        :rtype: :class:`Message`

        :raises:
            - :class:`InvalidSignatureError` - If the signature is not a valid signature.
            - :class:`InvalidObjectPathError` - If ``path`` is not a valid object path.
            - :class:`InvalidInterfaceNameError` - If ``interface`` is not a valid interface name.
            - :class:`InvalidMemberNameError` - If ``member`` is not a valid member name.
        """
        body = body if body else []
        return Message(
            message_type=MessageType.SIGNAL,
            interface=interface,
            path=path,
            member=member,
            signature=signature,
            body=body,
            unix_fds=unix_fds,
        )

    def _matches(self, **kwargs):
        for attr, val in kwargs.items():
            if getattr(self, attr) != val:
                return False

        return True

    def _marshall(self, negotiate_unix_fd=False):
        # TODO maximum message size is 134217728 (128 MiB)
        body_block = Marshaller(self.signature, self.body)
        body_block.marshall()

        fields = []

        if self.path:
            fields.append([HeaderField.PATH.value, Variant("o", self.path)])
        if self.interface:
            fields.append([HeaderField.INTERFACE.value, Variant("s", self.interface)])
        if self.member:
            fields.append([HeaderField.MEMBER.value, Variant("s", self.member)])
        if self.error_name:
            fields.append([HeaderField.ERROR_NAME.value, Variant("s", self.error_name)])
        if self.reply_serial:
            fields.append([HeaderField.REPLY_SERIAL.value, Variant("u", self.reply_serial)])
        if self.destination:
            fields.append([HeaderField.DESTINATION.value, Variant("s", self.destination)])
        if self.signature.children:
            fields.append([HeaderField.SIGNATURE.value, Variant("g", self.signature)])
        if self.unix_fds and negotiate_unix_fd:
            fields.append([HeaderField.UNIX_FDS.value, Variant("u", len(self.unix_fds))])

        header_body = [
            LITTLE_ENDIAN,
            self.message_type.value,
            self.flags.value,
            PROTOCOL_VERSION,
            len(body_block.buffer),
            self.serial,
            fields,
        ]
        header_block = Marshaller("yyyyuua(yv)", header_body)
        header_block.marshall()
        header_block.align(8)
        return header_block.buffer + body_block.buffer
