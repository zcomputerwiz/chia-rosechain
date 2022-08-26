# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\header_block.py
from dataclasses import dataclass
from typing import List, Optional
from chia.types.blockchain_format.foliage import Foliage, FoliageTransactionBlock, TransactionsInfo
from chia.types.blockchain_format.reward_chain_block import RewardChainBlock
from chia.types.blockchain_format.vdf import VDFProof
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class HeaderBlock(Streamable):
    finished_sub_slots: List[EndOfSubSlotBundle]
    reward_chain_block: RewardChainBlock
    challenge_chain_sp_proof: Optional[VDFProof]
    challenge_chain_ip_proof: VDFProof
    reward_chain_sp_proof: Optional[VDFProof]
    reward_chain_ip_proof: VDFProof
    infused_challenge_chain_ip_proof: Optional[VDFProof]
    foliage: Foliage
    foliage_transaction_block: Optional[FoliageTransactionBlock]
    transactions_filter: bytes
    transactions_info: Optional[TransactionsInfo]

    @property
    def prev_header_hash(self):
        return self.foliage.prev_block_hash

    @property
    def prev_hash(self):
        return self.foliage.prev_block_hash

    @property
    def height(self):
        return self.reward_chain_block.height

    @property
    def weight(self):
        return self.reward_chain_block.weight

    @property
    def header_hash(self):
        return self.foliage.get_hash()

    @property
    def total_iters(self):
        return self.reward_chain_block.total_iters

    @property
    def log_string(self):
        return 'block ' + str(self.header_hash) + ' sb_height ' + str(self.height) + ' '

    @property
    def is_transaction_block(self) -> bool:
        return self.reward_chain_block.is_transaction_block

    @property
    def first_in_sub_slot(self) -> bool:
        return self.finished_sub_slots is not None and len(self.finished_sub_slots) > 0