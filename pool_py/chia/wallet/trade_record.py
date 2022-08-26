# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\trade_record.py
from dataclasses import dataclass
from typing import List, Optional, Tuple
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint8, uint32, uint64
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class TradeRecord(Streamable):
    __doc__ = '\n    Used for storing transaction data and status in wallets.\n    '
    confirmed_at_index: uint32
    accepted_at_time: Optional[uint64]
    created_at_time: uint64
    my_offer: bool
    sent: uint32
    spend_bundle: SpendBundle
    tx_spend_bundle: Optional[SpendBundle]
    additions: List[Coin]
    removals: List[Coin]
    trade_id: bytes32
    status: uint32
    sent_to: List[Tuple[(str, uint8, Optional[str])]]