# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\blockchain_format\proof_of_space.py
import logging
from dataclasses import dataclass
from typing import Optional
from bitstring import BitArray
from blspy import G1Element, AugSchemeMPL, PrivateKey
from chiapos import Verifier
from chia.consensus.constants import ConsensusConstants
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.util.ints import uint8
from chia.util.streamable import Streamable, streamable
log = logging.getLogger(__name__)

@dataclass(frozen=True)
@streamable
class ProofOfSpace(Streamable):
    challenge: bytes32
    pool_public_key: Optional[G1Element]
    pool_contract_puzzle_hash: Optional[bytes32]
    plot_public_key: G1Element
    size: uint8
    proof: bytes

    def get_plot_id(self) -> bytes32:
        if not self.pool_public_key is None:
            assert self.pool_contract_puzzle_hash is None
            if self.pool_public_key is None:
                return self.calculate_plot_id_ph(self.pool_contract_puzzle_hash, self.plot_public_key)
            return self.calculate_plot_id_pk(self.pool_public_key, self.plot_public_key)

    def verify_and_get_quality_string(self, constants: ConsensusConstants, original_challenge_hash: bytes32, signage_point: bytes32) -> Optional[bytes32]:
        if self.pool_public_key is None:
            if self.pool_contract_puzzle_hash is None:
                log.error('Fail 1')
                return
        if self.pool_public_key is not None:
            if self.pool_contract_puzzle_hash is not None:
                log.error('Fail 2')
                return
        if self.size < constants.MIN_PLOT_SIZE:
            log.error('Fail 3')
            return
        if self.size > constants.MAX_PLOT_SIZE:
            log.error('Fail 4')
            return
        plot_id = self.get_plot_id()
        new_challenge = ProofOfSpace.calculate_pos_challenge(plot_id, original_challenge_hash, signage_point)
        if new_challenge != self.challenge:
            log.error('New challenge is not challenge')
            return
        if not ProofOfSpace.passes_plot_filter(constants, plot_id, original_challenge_hash, signage_point):
            log.error('Fail 5')
            return
        return self.get_quality_string(plot_id)

    def get_quality_string(self, plot_id: bytes32) -> Optional[bytes32]:
        quality_str = Verifier().validate_proof(plot_id, self.size, self.challenge, bytes(self.proof))
        if not quality_str:
            return
        return bytes32(quality_str)

    @staticmethod
    def passes_plot_filter(constants, plot_id, challenge_hash, signage_point):
        plot_filter = BitArray(ProofOfSpace.calculate_plot_filter_input(plot_id, challenge_hash, signage_point))
        return plot_filter[:constants.NUMBER_ZERO_BITS_PLOT_FILTER].uint == 0

    @staticmethod
    def calculate_plot_filter_input(plot_id, challenge_hash, signage_point):
        return std_hash(plot_id + challenge_hash + signage_point)

    @staticmethod
    def calculate_pos_challenge(plot_id, challenge_hash, signage_point):
        return std_hash(ProofOfSpace.calculate_plot_filter_input(plot_id, challenge_hash, signage_point))

    @staticmethod
    def calculate_plot_id_pk(pool_public_key: G1Element, plot_public_key: G1Element) -> bytes32:
        return std_hash(bytes(pool_public_key) + bytes(plot_public_key))

    @staticmethod
    def calculate_plot_id_ph(pool_contract_puzzle_hash: bytes32, plot_public_key: G1Element) -> bytes32:
        return std_hash(bytes(pool_contract_puzzle_hash) + bytes(plot_public_key))

    @staticmethod
    def generate_taproot_sk(local_pk: G1Element, farmer_pk: G1Element) -> PrivateKey:
        taproot_message = bytes(local_pk + farmer_pk) + bytes(local_pk) + bytes(farmer_pk)
        taproot_hash = std_hash(taproot_message)
        return AugSchemeMPL.key_gen(taproot_hash)

    @staticmethod
    def generate_plot_public_key(local_pk, farmer_pk, include_taproot=False):
        if include_taproot:
            taproot_sk = ProofOfSpace.generate_taproot_sk(local_pk, farmer_pk)
            return local_pk + farmer_pk + taproot_sk.get_g1()
        return local_pk + farmer_pk