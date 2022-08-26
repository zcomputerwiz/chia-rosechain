# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\unfinished_block.py
from dataclasses import dataclass
from typing import List, Optional
from chia.types.blockchain_format.foliage import Foliage, FoliageTransactionBlock, TransactionsInfo
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.blockchain_format.reward_chain_block import RewardChainBlockUnfinished
from chia.types.blockchain_format.vdf import VDFProof
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.util.ints import uint32
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class UnfinishedBlock(Streamable):
    finished_sub_slots: List[EndOfSubSlotBundle]
    reward_chain_block: RewardChainBlockUnfinished
    challenge_chain_sp_proof: Optional[VDFProof]
    reward_chain_sp_proof: Optional[VDFProof]
    foliage: Foliage
    foliage_transaction_block: Optional[FoliageTransactionBlock]
    transactions_info: Optional[TransactionsInfo]
    transactions_generator: Optional[SerializedProgram]
    transactions_generator_ref_list: List[uint32]

    @property
    def prev_header_hash(self):
        return self.foliage.prev_block_hash

    @property
    def partial_hash(self):
        return self.reward_chain_block.get_hash()

    def is_transaction_block(self) -> bool:
        return self.foliage.foliage_transaction_block_hash is not None

    @property
    def total_iters(self):
        return self.reward_chain_block.total_iters