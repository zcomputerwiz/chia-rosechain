# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\condition_opcodes.py
import enum
from typing import Any

class ConditionOpcode(bytes, enum.Enum):
    UNKNOWN = bytes([48])
    AGG_SIG_UNSAFE = bytes([49])
    AGG_SIG_ME = bytes([50])
    CREATE_COIN = bytes([51])
    RESERVE_FEE = bytes([52])
    CREATE_COIN_ANNOUNCEMENT = bytes([60])
    ASSERT_COIN_ANNOUNCEMENT = bytes([61])
    CREATE_PUZZLE_ANNOUNCEMENT = bytes([62])
    ASSERT_PUZZLE_ANNOUNCEMENT = bytes([63])
    ASSERT_MY_COIN_ID = bytes([70])
    ASSERT_MY_PARENT_ID = bytes([71])
    ASSERT_MY_PUZZLEHASH = bytes([72])
    ASSERT_MY_AMOUNT = bytes([73])
    ASSERT_SECONDS_RELATIVE = bytes([80])
    ASSERT_SECONDS_ABSOLUTE = bytes([81])
    ASSERT_HEIGHT_RELATIVE = bytes([82])
    ASSERT_HEIGHT_ABSOLUTE = bytes([83])

    def __bytes__(self) -> bytes:
        return bytes(self.value)

    @classmethod
    def from_bytes(cls: Any, blob: bytes) -> Any:
        assert len(blob) == 1
        return cls(blob)