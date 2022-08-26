# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\consensus\constants.py
import dataclasses
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint8, uint32, uint64, uint128

@dataclasses.dataclass(frozen=True)
class ConsensusConstants:
    SLOT_BLOCKS_TARGET: uint32
    MIN_BLOCKS_PER_CHALLENGE_BLOCK: uint8
    MAX_SUB_SLOT_BLOCKS: uint32
    NUM_SPS_SUB_SLOT: uint32
    SUB_SLOT_ITERS_STARTING: uint64
    DIFFICULTY_CONSTANT_FACTOR: uint128
    DIFFICULTY_STARTING: uint64
    DIFFICULTY_CHANGE_MAX_FACTOR: uint32
    SUB_EPOCH_BLOCKS: uint32
    EPOCH_BLOCKS: uint32
    SIGNIFICANT_BITS: int
    DISCRIMINANT_SIZE_BITS: int
    NUMBER_ZERO_BITS_PLOT_FILTER: int
    MIN_PLOT_SIZE: int
    MAX_PLOT_SIZE: int
    SUB_SLOT_TIME_TARGET: int
    NUM_SP_INTERVALS_EXTRA: int
    MAX_FUTURE_TIME: int
    NUMBER_OF_TIMESTAMPS: int
    GENESIS_CHALLENGE: bytes32
    AGG_SIG_ME_ADDITIONAL_DATA: bytes
    GENESIS_PRE_FARM_POOL_PUZZLE_HASH: bytes32
    GENESIS_PRE_FARM_FARMER_PUZZLE_HASH: bytes32
    MAX_VDF_WITNESS_SIZE: int
    MEMPOOL_BLOCK_BUFFER: int
    MAX_COIN_AMOUNT: int
    MAX_BLOCK_COST_CLVM: int
    COST_PER_BYTE: int
    WEIGHT_PROOF_THRESHOLD: uint8
    WEIGHT_PROOF_RECENT_BLOCKS: uint32
    MAX_BLOCK_COUNT_PER_REQUESTS: uint32
    INITIAL_FREEZE_END_TIMESTAMP: uint64
    BLOCKS_CACHE_SIZE: uint32
    NETWORK_TYPE: int
    MAX_GENERATOR_SIZE: uint32
    MAX_GENERATOR_REF_LIST_SIZE: uint32
    POOL_SUB_SLOT_ITERS: uint64

    def replace(self, **changes) -> 'ConsensusConstants':
        return (dataclasses.replace)(self, **changes)

    def replace_str_to_bytes(self, **changes) -> 'ConsensusConstants':
        """
        Overrides str (hex) values with bytes.
        """
        for k, v in changes.items():
            if isinstance(v, str):
                changes[k] = hexstr_to_bytes(v)

        return (dataclasses.replace)(self, **changes)