# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\byte_types.py
import io
from typing import Any, BinaryIO

def hexstr_to_bytes(input_str: str) -> bytes:
    """
    Converts a hex string into bytes, removing the 0x if it's present.
    """
    if input_str.startswith('0x') or input_str.startswith('0X'):
        return bytes.fromhex(input_str[2:])
    return bytes.fromhex(input_str)


def make_sized_bytes(size: int):
    """
    Create a streamable type that subclasses "bytes" but requires instances
    to be a certain, fixed size.
    """
    name = 'bytes%d' % size

    def __new__(cls, v):
        v = bytes(v)
        if not isinstance(v, bytes) or len(v) != size:
            raise ValueError('bad %s initializer %s' % (name, v))
        return bytes.__new__(cls, v)

    @classmethod
    def parse(cls, f):
        b = f.read(size)
        assert len(b) == size
        return cls(b)

    def stream(self, f):
        f.write(self)

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

    def __str__(self):
        return self.hex()

    def __repr__(self):
        return '<%s: %s>' % (self.__class__.__name__, str(self))

    namespace = dict(__new__=__new__,
      parse=parse,
      stream=stream,
      from_bytes=from_bytes,
      __bytes__=__bytes__,
      __str__=__str__,
      __repr__=__repr__)
    return type(name, (bytes,), namespace)