# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\full_block.py
from dataclasses import dataclass
from typing import List, Optional, Set
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.foliage import Foliage, FoliageTransactionBlock, TransactionsInfo
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.blockchain_format.reward_chain_block import RewardChainBlock
from chia.types.blockchain_format.vdf import VDFProof
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.util.ints import uint32
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class FullBlock(Streamable):
    finished_sub_slots: List[EndOfSubSlotBundle]
    reward_chain_block: RewardChainBlock
    challenge_chain_sp_proof: Optional[VDFProof]
    challenge_chain_ip_proof: VDFProof
    reward_chain_sp_proof: Optional[VDFProof]
    reward_chain_ip_proof: VDFProof
    infused_challenge_chain_ip_proof: Optional[VDFProof]
    foliage: Foliage
    foliage_transaction_block: Optional[FoliageTransactionBlock]
    transactions_info: Optional[TransactionsInfo]
    transactions_generator: Optional[SerializedProgram]
    transactions_generator_ref_list: List[uint32]

    @property
    def prev_header_hash(self):
        return self.foliage.prev_block_hash

    @property
    def height(self):
        return self.reward_chain_block.height

    @property
    def weight(self):
        return self.reward_chain_block.weight

    @property
    def total_iters(self):
        return self.reward_chain_block.total_iters

    @property
    def header_hash(self):
        return self.foliage.get_hash()

    def is_transaction_block(self) -> bool:
        return self.foliage_transaction_block is not None

    def get_included_reward_coins(self) -> Set[Coin]:
        if not self.is_transaction_block():
            return set()
        assert self.transactions_info is not None
        return set(self.transactions_info.reward_claims_incorporated)

    def is_fully_compactified(self) -> bool:
        for sub_slot in self.finished_sub_slots:
            if not (sub_slot.proofs.challenge_chain_slot_proof.witness_type != 0 or sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity):
                return False
            if sub_slot.proofs.infused_challenge_chain_slot_proof is not None:
                if not sub_slot.proofs.infused_challenge_chain_slot_proof.witness_type != 0 or sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity:
                    return False

        if self.challenge_chain_sp_proof is not None:
            if not (self.challenge_chain_sp_proof.witness_type != 0 or self.challenge_chain_sp_proof.normalized_to_identity):
                return False
            if not (self.challenge_chain_ip_proof.witness_type != 0 or self.challenge_chain_ip_proof.normalized_to_identity):
                return False
            return True