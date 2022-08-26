# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\consensus\block_record.py
from dataclasses import dataclass
from typing import List, Optional
from chia.consensus.constants import ConsensusConstants
from chia.consensus.pot_iterations import calculate_ip_iters, calculate_sp_iters
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class BlockRecord(Streamable):
    __doc__ = '\n    This class is not included or hashed into the blockchain, but it is kept in memory as a more\n    efficient way to maintain data about the blockchain. This allows us to validate future blocks,\n    difficulty adjustments, etc, without saving the whole header block in memory.\n    '
    header_hash: bytes32
    prev_hash: bytes32
    height: uint32
    weight: uint128
    total_iters: uint128
    signage_point_index: uint8
    challenge_vdf_output: ClassgroupElement
    infused_challenge_vdf_output: Optional[ClassgroupElement]
    reward_infusion_new_challenge: bytes32
    challenge_block_info_hash: bytes32
    sub_slot_iters: uint64
    pool_puzzle_hash: bytes32
    farmer_puzzle_hash: bytes32
    required_iters: uint64
    deficit: uint8
    overflow: bool
    prev_transaction_block_height: uint32
    timestamp: Optional[uint64]
    prev_transaction_block_hash: Optional[bytes32]
    fees: Optional[uint64]
    reward_claims_incorporated: Optional[List[Coin]]
    finished_challenge_slot_hashes: Optional[List[bytes32]]
    finished_infused_challenge_slot_hashes: Optional[List[bytes32]]
    finished_reward_slot_hashes: Optional[List[bytes32]]
    sub_epoch_summary_included: Optional[SubEpochSummary]

    @property
    def is_transaction_block(self) -> bool:
        return self.timestamp is not None

    @property
    def first_in_sub_slot(self) -> bool:
        return self.finished_challenge_slot_hashes is not None

    def is_challenge_block(self, constants: ConsensusConstants) -> bool:
        return self.deficit == constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1

    def sp_sub_slot_total_iters(self, constants: ConsensusConstants) -> uint128:
        if self.overflow:
            return uint128(self.total_iters - self.ip_iters(constants) - self.sub_slot_iters)
        return uint128(self.total_iters - self.ip_iters(constants))

    def ip_sub_slot_total_iters(self, constants: ConsensusConstants) -> uint128:
        return uint128(self.total_iters - self.ip_iters(constants))

    def sp_iters(self, constants: ConsensusConstants) -> uint64:
        return calculate_sp_iters(constants, self.sub_slot_iters, self.signage_point_index)

    def ip_iters(self, constants: ConsensusConstants) -> uint64:
        return calculate_ip_iters(constants, self.sub_slot_iters, self.signage_point_index, self.required_iters)

    def sp_total_iters(self, constants: ConsensusConstants):
        return self.sp_sub_slot_total_iters(constants) + self.sp_iters(constants)