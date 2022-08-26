# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\blockchain_format\reward_chain_block.py
from dataclasses import dataclass
from typing import Optional
from blspy import G2Element
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.vdf import VDFInfo
from chia.util.ints import uint8, uint32, uint128
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class RewardChainBlockUnfinished(Streamable):
    total_iters: uint128
    signage_point_index: uint8
    pos_ss_cc_challenge_hash: bytes32
    proof_of_space: ProofOfSpace
    challenge_chain_sp_vdf: Optional[VDFInfo]
    challenge_chain_sp_signature: G2Element
    reward_chain_sp_vdf: Optional[VDFInfo]
    reward_chain_sp_signature: G2Element


@dataclass(frozen=True)
@streamable
class RewardChainBlock(Streamable):
    weight: uint128
    height: uint32
    total_iters: uint128
    signage_point_index: uint8
    pos_ss_cc_challenge_hash: bytes32
    proof_of_space: ProofOfSpace
    challenge_chain_sp_vdf: Optional[VDFInfo]
    challenge_chain_sp_signature: G2Element
    challenge_chain_ip_vdf: VDFInfo
    reward_chain_sp_vdf: Optional[VDFInfo]
    reward_chain_sp_signature: G2Element
    reward_chain_ip_vdf: VDFInfo
    infused_challenge_chain_ip_vdf: Optional[VDFInfo]
    is_transaction_block: bool

    def get_unfinished(self) -> RewardChainBlockUnfinished:
        return RewardChainBlockUnfinished(self.total_iters, self.signage_point_index, self.pos_ss_cc_challenge_hash, self.proof_of_space, self.challenge_chain_sp_vdf, self.challenge_chain_sp_signature, self.reward_chain_sp_vdf, self.reward_chain_sp_signature)