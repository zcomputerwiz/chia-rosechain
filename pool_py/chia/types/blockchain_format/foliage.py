# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\blockchain_format\foliage.py
from dataclasses import dataclass
from typing import List, Optional
from blspy import G2Element
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.pool_target import PoolTarget
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class TransactionsInfo(Streamable):
    generator_root: bytes32
    generator_refs_root: bytes32
    aggregated_signature: G2Element
    fees: uint64
    cost: uint64
    reward_claims_incorporated: List[Coin]


@dataclass(frozen=True)
@streamable
class FoliageTransactionBlock(Streamable):
    prev_transaction_block_hash: bytes32
    timestamp: uint64
    filter_hash: bytes32
    additions_root: bytes32
    removals_root: bytes32
    transactions_info_hash: bytes32


@dataclass(frozen=True)
@streamable
class FoliageBlockData(Streamable):
    unfinished_reward_block_hash: bytes32
    pool_target: PoolTarget
    pool_signature: Optional[G2Element]
    farmer_reward_puzzle_hash: bytes32
    extension_data: bytes32


@dataclass(frozen=True)
@streamable
class Foliage(Streamable):
    prev_block_hash: bytes32
    reward_block_hash: bytes32
    foliage_block_data: FoliageBlockData
    foliage_block_data_signature: G2Element
    foliage_transaction_block_hash: Optional[bytes32]
    foliage_transaction_block_signature: Optional[G2Element]