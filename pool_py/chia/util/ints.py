# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\ints.py
from typing import Any, BinaryIO
from chia.util.struct_stream import StructStream

class int8(StructStream):
    PACK = '!b'


class uint8(StructStream):
    PACK = '!B'


class int16(StructStream):
    PACK = '!h'


class uint16(StructStream):
    PACK = '!H'


class int32(StructStream):
    PACK = '!l'


class uint32(StructStream):
    PACK = '!L'


class int64(StructStream):
    PACK = '!q'


class uint64(StructStream):
    PACK = '!Q'


class uint128(int):

    def __new__(cls: Any, value: int):
        value = int(value)
        if value > 2 ** 128 - 1 or value < 0:
            raise ValueError(f"Value {value} of does not fit into uin128")
        return int.__new__(cls, value)

    @classmethod
    def parse(cls, f: BinaryIO) -> Any:
        read_bytes = f.read(16)
        assert len(read_bytes) == 16
        n = int.from_bytes(read_bytes, 'big', signed=False)
        if not (n <= 2 ** 128 - 1 and n >= 0):
            raise AssertionError
        return cls(n)

    def stream(self, f):
        if not (self <= 2 ** 128 - 1 and self >= 0):
            raise AssertionError
        f.write(self.to_bytes(16, 'big', signed=False))


class int512(int):

    def __new__(cls: Any, value: int):
        value = int(value)
        if value >= 2 ** 512 or value <= -2 ** 512:
            raise ValueError(f"Value {value} of does not fit into in512")
        return int.__new__(cls, value)

    @classmethod
    def parse(cls, f: BinaryIO) -> Any:
        read_bytes = f.read(65)
        assert len(read_bytes) == 65
        n = int.from_bytes(read_bytes, 'big', signed=True)
        if not (n < 2 ** 512 and n > -2 ** 512):
            raise AssertionError
        return cls(n)

    def stream(self, f):
        if not (self < 2 ** 512 and self > -2 ** 512):
            raise AssertionError
        f.write(self.to_bytes(65, 'big', signed=True))