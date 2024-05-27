from struct import pack
from typing import Union

from ..signature import Signature, Variant, parse_signature


class Marshaller:
    def __init__(self, signature: Union[Signature, str], body):
        if isinstance(signature, str):
            signature = parse_signature(signature)
        signature.verify(body)
        self.signature = signature

        self.buffer = bytearray()
        self.body = body

        self.writers = {
            "y": self.write_byte,
            "b": self.write_boolean,
            "n": self.write_int16,
            "q": self.write_uint16,
            "i": self.write_int32,
            "u": self.write_uint32,
            "x": self.write_int64,
            "t": self.write_uint64,
            "d": self.write_double,
            "h": self.write_uint32,
            "o": self.write_string,
            "s": self.write_string,
            "g": self.write_signature,
            "a": self.write_array,
            "(": self.write_struct,
            "r": self.write_struct,
            "{": self.write_dict_entry,
            "v": self.write_variant,
        }

    def align(self, n):
        offset = n - len(self.buffer) % n
        if offset == 0 or offset == n:
            return 0
        self.buffer.extend(bytes(offset))
        return offset

    def write_byte(self, byte, _=None):
        self.buffer.append(byte)
        return 1

    def write_boolean(self, boolean, _=None):
        if boolean:
            return self.write_uint32(1)
        else:
            return self.write_uint32(0)

    def write_int16(self, int16, _=None):
        written = self.align(2)
        self.buffer.extend(pack("<h", int16))
        return written + 2

    def write_uint16(self, uint16, _=None):
        written = self.align(2)
        self.buffer.extend(pack("<H", uint16))
        return written + 2

    def write_int32(self, int32, _):
        written = self.align(4)
        self.buffer.extend(pack("<i", int32))
        return written + 4

    def write_uint32(self, uint32, _=None):
        written = self.align(4)
        self.buffer.extend(pack("<I", uint32))
        return written + 4

    def write_int64(self, int64, _=None):
        written = self.align(8)
        self.buffer.extend(pack("<q", int64))
        return written + 8

    def write_uint64(self, uint64, _=None):
        written = self.align(8)
        self.buffer.extend(pack("<Q", uint64))
        return written + 8

    def write_double(self, double, _=None):
        written = self.align(8)
        self.buffer.extend(pack("<d", double))
        return written + 8

    def write_signature(self, signature: Union[Signature, str], _=None):
        if isinstance(signature, Signature):
            signature = signature.text
        signature = signature.encode("ASCII")
        signature_len = len(signature)
        self.buffer.append(signature_len)
        self.buffer.extend(signature)
        self.buffer.append(0)
        return signature_len + 2

    def write_string(self, value: str, _=None):
        value = value.encode()
        value_len = len(value)
        written = self.write_uint32(value_len)
        self.buffer.extend(value)
        written += value_len
        self.buffer.append(0)
        written += 1
        return written

    def write_variant(self, variant: Variant, _=None):
        written = self.write_signature(variant.signature)
        written += self.write_single(variant.signature, variant.value)
        return written

    def write_array(self, array, signature: Signature):
        # TODO max array size is 64MiB (67108864 bytes)
        written = self.align(4)
        # length placeholder
        offset = len(self.buffer)
        written += self.write_uint32(0)
        child_type = signature.children[0]

        if child_type.type_code in "xtd{(r":
            # the first alignment is not included in array size
            written += self.align(8)

        array_len = 0
        if child_type.type_code == "{":
            for key, value in array.items():
                array_len += self.write_dict_entry([key, value], child_type)
        elif child_type.type_code == "y":
            array_len = len(array)
            self.buffer.extend(array)
        else:
            for value in array:
                array_len += self.write_single(child_type, value)

        array_len_packed = pack("<I", array_len)
        for i in range(offset, offset + 4):
            self.buffer[i] = array_len_packed[i - offset]

        return written + array_len

    def write_struct(self, array, signature: Signature):
        written = self.align(8)
        for signature, value in zip(signature.children, array):
            written += self.write_single(signature, value)
        return written

    def write_dict_entry(self, dict_entry, signature: Signature):
        written = self.align(8)
        written += self.write_single(signature.children[0], dict_entry[0])
        written += self.write_single(signature.children[1], dict_entry[1])
        return written

    def write_single(self, signature: Signature, body):
        t = signature.type_code

        if t not in self.writers:
            raise NotImplementedError(f"type isn't implemented yet: {t!r}")

        return self.writers[t](body, signature)

    def marshall(self):
        self.buffer.clear()
        for signature, value in zip(self.signature.children, self.body):
            self.write_single(signature, value)
        return self.buffer
