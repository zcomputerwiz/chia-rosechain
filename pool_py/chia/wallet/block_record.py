# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\block_record.py
from dataclasses import dataclass
from typing import List
from chia.types.blockchain_format.coin import Coin
from chia.types.header_block import HeaderBlock
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class HeaderBlockRecord(Streamable):
    __doc__ = '\n    These are values that are stored in the wallet database, corresponding to information\n    that the wallet cares about in each block\n    '
    header: HeaderBlock
    additions: List[Coin]
    removals: List[Coin]

    @property
    def header_hash(self):
        return self.header.header_hash

    @property
    def prev_header_hash(self):
        return self.header.prev_header_hash

    @property
    def height(self):
        return self.header.height

    @property
    def transactions_filter(self):
        return self.header.transactions_filter