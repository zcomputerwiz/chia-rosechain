# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\struct_stream.py
import io, struct
from typing import Any, BinaryIO

class StructStream(int):
    PACK = ''

    def __new__(cls: Any, value: int):
        value = int(value)
        try:
            v1 = struct.unpack(cls.PACK, struct.pack(cls.PACK, value))[0]
            if value != v1:
                raise ValueError(f"Value {value} does not fit into {cls.__name__}")
        except Exception:
            bits = struct.calcsize(cls.PACK) * 8
            raise ValueError(f"Value {value} of size {value.bit_length()} does not fit into {cls.__name__} of size {bits}")

        return int.__new__(cls, value)

    @classmethod
    def parse(cls: Any, f: BinaryIO) -> Any:
        bytes_to_read = struct.calcsize(cls.PACK)
        read_bytes = f.read(bytes_to_read)
        if not (read_bytes is not None and len(read_bytes) == bytes_to_read):
            raise AssertionError
        return cls(*struct.unpack(cls.PACK, read_bytes))

    def stream(self, f):
        f.write(struct.pack(self.PACK, self))

    @classmethod
    def from_bytes(cls: Any, blob: bytes) -> Any:
        f = io.BytesIO(blob)
        result = cls.parse(f)
        assert f.read() == b''
        return result

    def __bytes__(self: Any) -> bytes:
        f = io.BytesIO()
        self.stream(f)
        return bytes(f.getvalue())