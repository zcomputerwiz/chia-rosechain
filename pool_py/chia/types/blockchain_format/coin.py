# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\blockchain_format\coin.py
from dataclasses import dataclass
from typing import Any, List
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.clvm import int_to_bytes
from chia.util.hash import std_hash
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class Coin(Streamable):
    __doc__ = '\n    This structure is used in the body for the reward and fees genesis coins.\n    '
    parent_coin_info: bytes32
    puzzle_hash: bytes32
    amount: uint64

    def get_hash(self) -> bytes32:
        return std_hash(self.parent_coin_info + self.puzzle_hash + int_to_bytes(self.amount))

    def name(self) -> bytes32:
        return self.get_hash()

    def as_list(self) -> List[Any]:
        return [
         self.parent_coin_info, self.puzzle_hash, self.amount]

    @property
    def name_str(self) -> str:
        return self.name().hex()

    @classmethod
    def from_bytes(cls, blob):
        assert False

    def __bytes__(self) -> bytes:
        assert False


def hash_coin_list(coin_list: List[Coin]) -> bytes32:
    coin_list.sort(key=(lambda x: x.name_str
), reverse=True)
    buffer = bytearray()
    for coin in coin_list:
        buffer.extend(coin.name())

    return std_hash(buffer)