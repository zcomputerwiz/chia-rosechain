# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\weight_proof.py
from dataclasses import dataclass
from typing import List, Optional
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.reward_chain_block import RewardChainBlock
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.header_block import HeaderBlock
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class SubEpochData(Streamable):
    reward_chain_hash: bytes32
    num_blocks_overflow: uint8
    new_sub_slot_iters: Optional[uint64]
    new_difficulty: Optional[uint64]


@dataclass(frozen=True)
@streamable
class SubSlotData(Streamable):
    proof_of_space: Optional[ProofOfSpace]
    cc_signage_point: Optional[VDFProof]
    cc_infusion_point: Optional[VDFProof]
    icc_infusion_point: Optional[VDFProof]
    cc_sp_vdf_info: Optional[VDFInfo]
    signage_point_index: Optional[uint8]
    cc_slot_end: Optional[VDFProof]
    icc_slot_end: Optional[VDFProof]
    cc_slot_end_info: Optional[VDFInfo]
    icc_slot_end_info: Optional[VDFInfo]
    cc_ip_vdf_info: Optional[VDFInfo]
    icc_ip_vdf_info: Optional[VDFInfo]
    total_iters: Optional[uint128]

    def is_challenge(self) -> bool:
        if self.proof_of_space is not None:
            return True
        return False

    def is_end_of_slot(self) -> bool:
        if self.cc_slot_end_info is not None:
            return True
        return False


@dataclass(frozen=True)
@streamable
class SubEpochChallengeSegment(Streamable):
    sub_epoch_n: uint32
    sub_slots: List[SubSlotData]
    rc_slot_end_info: Optional[VDFInfo]


@dataclass(frozen=True)
@streamable
class SubEpochSegments(Streamable):
    challenge_segments: List[SubEpochChallengeSegment]


@dataclass(frozen=True)
@streamable
class RecentChainData(Streamable):
    recent_chain_data: List[HeaderBlock]


@dataclass(frozen=True)
@streamable
class ProofBlockHeader(Streamable):
    finished_sub_slots: List[EndOfSubSlotBundle]
    reward_chain_block: RewardChainBlock


@dataclass(frozen=True)
@streamable
class WeightProof(Streamable):
    sub_epochs: List[SubEpochData]
    sub_epoch_segments: List[SubEpochChallengeSegment]
    recent_chain_data: List[HeaderBlock]