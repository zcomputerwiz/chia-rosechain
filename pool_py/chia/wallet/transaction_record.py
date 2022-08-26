# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\transaction_record.py
from dataclasses import dataclass
from typing import List, Optional, Tuple
from chia.consensus.coinbase import pool_parent_id, farmer_parent_id
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint8, uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.util.transaction_type import TransactionType

@dataclass(frozen=True)
@streamable
class TransactionRecord(Streamable):
    __doc__ = '\n    Used for storing transaction data and status in wallets.\n    '
    confirmed_at_height: uint32
    created_at_time: uint64
    to_puzzle_hash: bytes32
    amount: uint64
    fee_amount: uint64
    confirmed: bool
    sent: uint32
    spend_bundle: Optional[SpendBundle]
    additions: List[Coin]
    removals: List[Coin]
    wallet_id: uint32
    sent_to: List[Tuple[(str, uint8, Optional[str])]]
    trade_id: Optional[bytes32]
    type: uint32
    name: bytes32

    def is_in_mempool(self) -> bool:
        for _, mis, _ in self.sent_to:
            if MempoolInclusionStatus(mis) == MempoolInclusionStatus.SUCCESS:
                return True

        return False

    def height_farmed(self, genesis_challenge: bytes32) -> Optional[uint32]:
        if not self.confirmed:
            return
        if self.type == TransactionType.FEE_REWARD or self.type == TransactionType.COINBASE_REWARD:
            for block_index in range(self.confirmed_at_height, self.confirmed_at_height - 100, -1):
                if block_index < 0:
                    return
                else:
                    pool_parent = pool_parent_id(uint32(block_index), genesis_challenge)
                    farmer_parent = farmer_parent_id(uint32(block_index), genesis_challenge)
                    if pool_parent == self.additions[0].parent_coin_info:
                        return uint32(block_index)
                if farmer_parent == self.additions[0].parent_coin_info:
                    return uint32(block_index)