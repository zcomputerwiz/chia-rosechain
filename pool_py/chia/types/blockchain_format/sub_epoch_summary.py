# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\blockchain_format\sub_epoch_summary.py
from dataclasses import dataclass
from typing import Optional
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint64
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class SubEpochSummary(Streamable):
    prev_subepoch_summary_hash: bytes32
    reward_chain_hash: bytes32
    num_blocks_overflow: uint8
    new_difficulty: Optional[uint64]
    new_sub_slot_iters: Optional[uint64]