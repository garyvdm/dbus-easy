import sys
from dataclasses import InitVar, dataclass
from functools import lru_cache
from typing import Any, List, Mapping, Optional, Sequence, Tuple, Union

from .validators import is_object_path_valid

__all__ = [
    "parse_signature",
    "parse_single_type",
    "Signature",
    "Variant",
    "SignatureBodyMismatchError",
    "InvalidSignatureError",
]


class SignatureBodyMismatchError(ValueError):
    pass


class InvalidSignatureError(ValueError):
    pass


@lru_cache(maxsize=None)
def parse_signature(signature_text: str) -> "Signature":
    children = []
    work_signature_text = signature_text
    while work_signature_text:
        child, work_signature_text = _parse_next(work_signature_text)
        children.append(child)
    return Signature(signature_text, "r", tuple(children))


@lru_cache(maxsize=None)
def parse_single_type(signature_text: str) -> "Signature":
    signature, signature_text = _parse_next(signature_text)
    if signature_text:
        raise InvalidSignatureError(
            f"more than 1 single complete type, remaining: {signature_text!r}"
        )
    return signature


def _remove_work_text(text: str, work_text: str):
    if not work_text:
        return text
    return text[: -len(work_text)]


def _parse_next(signature_text: str) -> Tuple[Optional["Signature"], str]:
    if not signature_text:
        return None, ""

    type_code = signature_text[0]

    if type_code not in TYPE_CODES:
        raise InvalidSignatureError(f'got unexpected type_code: "{type_code}"')

    # container types
    if type_code == "a":
        (child, work_signature_text) = _parse_next(signature_text[1:])
        if not child:
            raise InvalidSignatureError("missing type for array")
        return (
            Signature(_remove_work_text(signature_text, work_signature_text), "a", (child,)),
            work_signature_text,
        )

    if type_code == "(":
        work_signature_text = signature_text[1:]
        children = []
        while True:
            (child, work_signature_text) = _parse_next(work_signature_text)
            children.append(child)
            if not work_signature_text:
                raise InvalidSignatureError('missing closing ")" for struct')
            if work_signature_text[0] == ")":
                work_signature_text = work_signature_text[1:]
                return (
                    Signature(
                        _remove_work_text(signature_text, work_signature_text), "(", tuple(children)
                    ),
                    work_signature_text,
                )

    if type_code == "{":
        work_signature_text = signature_text[1:]
        (key_child, work_signature_text) = _parse_next(work_signature_text)
        if not key_child or len(key_child.children):
            raise InvalidSignatureError("expected a simple type for dict entry key")
        (value_child, work_signature_text) = _parse_next(work_signature_text)
        if not value_child:
            raise InvalidSignatureError("expected a value for dict entry")
        if not work_signature_text or work_signature_text[0] != "}":
            raise InvalidSignatureError('missing closing "}" for dict entry')
        work_signature_text = work_signature_text[1:]
        return (
            Signature(
                _remove_work_text(signature_text, work_signature_text),
                "{",
                (key_child, value_child),
            ),
            work_signature_text,
        )

    # basic type
    return (Signature(type_code, type_code, ()), signature_text[1:])


TYPE_CODES = "ybnqiuxtdsogavh({"


@dataclass(frozen=True, **(dict(slots=True) if sys.version_info >= (3, 10) else dict()))
class Signature:
    """A class that represents a signature, either a list of single complete types, or
    a single complete type.

    This class is not meant to be constructed directly. Use `parse_signature` to instantiate.

    :ivar ~.signature_text: The signature of this complete type.
    :vartype ~.signature_text: str

    :ivar ~.type_code: The type_code of this type.
    :vartype ~.type_code: str

    :ivar children: A list of child types if this is a container type. Arrays \
    have one child type, dict entries have two child types (key and value), and \
    structs have child types equal to the number of struct members.
    :vartype children: Sequence(:class:`Signature`)

    """

    text: str
    type_code: str
    children: Sequence["Signature"] = ()

    # # Comment this out to get the dataclass __repr__ which shows children
    # def __repr__(self) -> str:
    #     return f"<Signature({self.text!r})>"

    def __eq__(self, other):
        if isinstance(other, Signature):
            return (
                self.text == other.text
                and self.type_code == other.type_code
                and other.children == other.children
            )
        if isinstance(other, str):
            return self.text == other
        return NotImplemented

    def __hash__(self):
        return self.text.__hash__()

    def __str__(self) -> str:
        return self.text

    def _verify_byte(self, body):
        BYTE_MIN = 0x00
        BYTE_MAX = 0xFF
        if not isinstance(body, int):
            raise SignatureBodyMismatchError(
                f'DBus BYTE type "y" must be Python type "int", got {type(body)}'
            )
        if body < BYTE_MIN or body > BYTE_MAX:
            raise SignatureBodyMismatchError(
                f"DBus BYTE type must be between {BYTE_MIN} and {BYTE_MAX}"
            )

    def _verify_boolean(self, body):
        if not isinstance(body, bool):
            raise SignatureBodyMismatchError(
                f'DBus BOOLEAN type "b" must be Python type "bool", got {type(body)}'
            )

    def _verify_int16(self, body):
        INT16_MIN = -0x7FFF - 1
        INT16_MAX = 0x7FFF
        if not isinstance(body, int):
            raise SignatureBodyMismatchError(
                f'DBus INT16 type "n" must be Python type "int", got {type(body)}'
            )
        elif body > INT16_MAX or body < INT16_MIN:
            raise SignatureBodyMismatchError(
                f'DBus INT16 type "n" must be between {INT16_MIN} and {INT16_MAX}'
            )

    def _verify_uint16(self, body):
        UINT16_MIN = 0
        UINT16_MAX = 0xFFFF
        if not isinstance(body, int):
            raise SignatureBodyMismatchError(
                f'DBus UINT16 type "q" must be Python type "int", got {type(body)}'
            )
        elif body > UINT16_MAX or body < UINT16_MIN:
            raise SignatureBodyMismatchError(
                f'DBus UINT16 type "q" must be between {UINT16_MIN} and {UINT16_MAX}'
            )

    def _verify_int32(self, body):
        INT32_MIN = -0x7FFFFFFF - 1
        INT32_MAX = 0x7FFFFFFF
        if not isinstance(body, int):
            raise SignatureBodyMismatchError(
                f'DBus INT32 type "i" must be Python type "int", got {type(body)}'
            )
        elif body > INT32_MAX or body < INT32_MIN:
            raise SignatureBodyMismatchError(
                f'DBus INT32 type "i" must be between {INT32_MIN} and {INT32_MAX}'
            )

    def _verify_uint32(self, body):
        UINT32_MIN = 0
        UINT32_MAX = 0xFFFFFFFF
        if not isinstance(body, int):
            raise SignatureBodyMismatchError(
                f'DBus UINT32 type "u" must be Python type "int", got {type(body)}'
            )
        elif body > UINT32_MAX or body < UINT32_MIN:
            raise SignatureBodyMismatchError(
                f'DBus UINT32 type "u" must be between {UINT32_MIN} and {UINT32_MAX}'
            )

    def _verify_int64(self, body):
        INT64_MAX = 9223372036854775807
        INT64_MIN = -INT64_MAX - 1
        if not isinstance(body, int):
            raise SignatureBodyMismatchError(
                f'DBus INT64 type "x" must be Python type "int", got {type(body)}'
            )
        elif body > INT64_MAX or body < INT64_MIN:
            raise SignatureBodyMismatchError(
                f'DBus INT64 type "x" must be between {INT64_MIN} and {INT64_MAX}'
            )

    def _verify_uint64(self, body):
        UINT64_MIN = 0
        UINT64_MAX = 18446744073709551615
        if not isinstance(body, int):
            raise SignatureBodyMismatchError(
                f'DBus UINT64 type "t" must be Python type "int", got {type(body)}'
            )
        elif body > UINT64_MAX or body < UINT64_MIN:
            raise SignatureBodyMismatchError(
                f'DBus UINT64 type "t" must be between {UINT64_MIN} and {UINT64_MAX}'
            )

    def _verify_double(self, body):
        if not isinstance(body, float) and not isinstance(body, int):
            raise SignatureBodyMismatchError(
                f'DBus DOUBLE type "d" must be Python type "float" or "int", got {type(body)}'
            )

    def _verify_unix_fd(self, body):
        try:
            self._verify_uint32(body)
        except SignatureBodyMismatchError:
            raise SignatureBodyMismatchError('DBus UNIX_FD type "h" must be a valid UINT32')

    def _verify_object_path(self, body):
        if not is_object_path_valid(body):
            raise SignatureBodyMismatchError(
                'DBus OBJECT_PATH type "o" must be a valid object path'
            )

    def _verify_string(self, body):
        if not isinstance(body, str):
            raise SignatureBodyMismatchError(
                f'DBus STRING type "s" must be Python type "str", got {type(body)}'
            )

    def _verify_signature(self, body):
        if not isinstance(body, (str, Signature)):
            raise SignatureBodyMismatchError(
                f'DBus SIGNATURE type "g" must be Python type "str" or "Signature, got {type(body)}'
            )
        if isinstance(body, str):
            parse_signature(body)
        if isinstance(body, Signature):
            body = body.text
        if len(body.encode("ASCII")) > 0xFF:
            raise SignatureBodyMismatchError('DBus SIGNATURE type "g" must be less than 256 bytes')

    def _verify_array(self, body):
        child_type = self.children[0]

        if child_type.type_code == "{":
            if not isinstance(body, Mapping):
                raise SignatureBodyMismatchError(
                    'DBus ARRAY type "a" with DICT_ENTRY child must be Python '
                    f'type "Mapping", e.g. "dict", got {type(body)}'
                )
            for key, value in body.items():
                child_type.children[0].verify(key)
                child_type.children[1].verify(value)
        elif child_type.type_code == "y":
            if not isinstance(body, (bytearray, bytes)):
                raise SignatureBodyMismatchError(
                    f'DBus ARRAY type "a" with BYTE child must be Python type "bytes", got {type(body)}'
                )
                # no need to verify children
        else:
            if not isinstance(body, Sequence):
                raise SignatureBodyMismatchError(
                    f'DBus ARRAY type "a" must be Python type "Sequence", e.g. "list", got {type(body)}'
                )
            for member in body:
                child_type.verify(member)

    def _verify_struct(self, body):
        if not isinstance(body, Sequence):
            raise SignatureBodyMismatchError(
                f'DBus STRUCT type "(" must be Python type "Sequence", e.g. "list", got {type(body)}'
            )

        if len(body) != len(self.children):
            raise SignatureBodyMismatchError(
                'DBus STRUCT type "(" must have Python list members equal to the number of struct type members'
            )

        for i, member in enumerate(body):
            self.children[i].verify(member)

    def _verify_variant(self, body):
        # a variant signature and value is valid by construction
        if not isinstance(body, Variant):
            raise SignatureBodyMismatchError(
                f'DBus VARIANT type "v" must be Python type "Variant", got {type(body)}'
            )

    def verify(self, body: Any) -> bool:
        """Verify that the body matches this type.

        :returns: True if the body matches this type.
        :raises:
            :class:`SignatureBodyMismatchError` if the body does not match this type.
        """
        if body is None:
            raise SignatureBodyMismatchError('Cannot serialize Python type "None"')
        validator = self.validators.get(self.type_code)
        if validator:
            validator(self, body)
        else:
            raise Exception(f"cannot verify type with token {self.type_code}")

        return True

    validators = {
        "y": _verify_byte,
        "b": _verify_boolean,
        "n": _verify_int16,
        "q": _verify_uint16,
        "i": _verify_int32,
        "u": _verify_uint32,
        "x": _verify_int64,
        "t": _verify_uint64,
        "d": _verify_double,
        "h": _verify_uint32,
        "o": _verify_string,
        "s": _verify_string,
        "g": _verify_signature,
        "a": _verify_array,
        "(": _verify_struct,
        "r": _verify_struct,
        "v": _verify_variant,
    }


@dataclass
class Variant:
    """A class to represent a DBus variant (type "v").

    This class is used in message bodies to represent variants. The user can
    expect a value in the body with type "v" to use this class and can
    construct this class directly for use in message bodies sent over the bus.

    :ivar signature: The signature for this variant. Must be a single complete type.
    :vartype signature: Signature

    :ivar value: The value of this variant. Must correspond to the signature.
    :vartype value: Any

    :raises:
        :class:`InvalidSignatureError` if the signature is not valid.
        :class:`SignatureBodyMismatchError` if the signature does not match the body.
    """

    signature: Signature
    value: Any
    verify: InitVar[bool] = True

    def __post_init__(self, verify: bool = True):
        if isinstance(self.signature, str):
            self.signature = parse_single_type(self.signature)
        if not isinstance(self.signature, Signature):
            raise TypeError("signature must be a Signature or a string")

        if verify:
            self.signature.verify(self.value)


def signature_contains_type(
    signature: Union[str, Signature],
    body: Sequence[Any],
    type_code: str,
) -> bool:
    """For a given signature and body, check to see if it contains any members
    with the given type_code"""
    if isinstance(signature, str):
        signature = parse_signature(signature)

    queue: List[Signature] = [signature]
    contains_variants = False

    while queue:
        decedent = queue.pop()
        if decedent.type_code == type_code:
            return True
        elif decedent.type_code == "v":
            contains_variants = True
        queue.extend(decedent.children)

    if not contains_variants:
        return False

    body_queue = list(body)

    while body_queue:
        member = body_queue.pop()
        if isinstance(member, Variant):
            if signature_contains_type(member.signature, (member.value,), type_code):
                return True
        elif isinstance(member, list):
            body_queue.extend(member)
        elif isinstance(member, dict):
            body_queue.extend(member.values())

    return False
