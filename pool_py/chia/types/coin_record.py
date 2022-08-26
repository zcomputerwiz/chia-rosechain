# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\coin_record.py
from dataclasses import dataclass
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class CoinRecord(Streamable):
    __doc__ = '\n    These are values that correspond to a CoinName that are used\n    in keeping track of the unspent database.\n    '
    coin: Coin
    confirmed_block_index: uint32
    spent_block_index: uint32
    spent: bool
    coinbase: bool
    timestamp: uint64

    @property
    def name(self) -> bytes32:
        return self.coin.name()