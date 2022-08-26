# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\blockchain_format\slots.py
from dataclasses import dataclass
from typing import Optional
from blspy import G2Element
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof
from chia.util.ints import uint8, uint64
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class ChallengeBlockInfo(Streamable):
    proof_of_space: ProofOfSpace
    challenge_chain_sp_vdf: Optional[VDFInfo]
    challenge_chain_sp_signature: G2Element
    challenge_chain_ip_vdf: VDFInfo


@dataclass(frozen=True)
@streamable
class ChallengeChainSubSlot(Streamable):
    challenge_chain_end_of_slot_vdf: VDFInfo
    infused_challenge_chain_sub_slot_hash: Optional[bytes32]
    subepoch_summary_hash: Optional[bytes32]
    new_sub_slot_iters: Optional[uint64]
    new_difficulty: Optional[uint64]


@dataclass(frozen=True)
@streamable
class InfusedChallengeChainSubSlot(Streamable):
    infused_challenge_chain_end_of_slot_vdf: VDFInfo


@dataclass(frozen=True)
@streamable
class RewardChainSubSlot(Streamable):
    end_of_slot_vdf: VDFInfo
    challenge_chain_sub_slot_hash: bytes32
    infused_challenge_chain_sub_slot_hash: Optional[bytes32]
    deficit: uint8


@dataclass(frozen=True)
@streamable
class SubSlotProofs(Streamable):
    challenge_chain_slot_proof: VDFProof
    infused_challenge_chain_slot_proof: Optional[VDFProof]
    reward_chain_slot_proof: VDFProof