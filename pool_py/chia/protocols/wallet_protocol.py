# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\protocols\wallet_protocol.py
from dataclasses import dataclass
from typing import List, Optional, Tuple
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.header_block import HeaderBlock
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint8, uint32, uint128
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class RequestPuzzleSolution(Streamable):
    coin_name: bytes32
    height: uint32


@dataclass(frozen=True)
@streamable
class PuzzleSolutionResponse(Streamable):
    coin_name: bytes32
    height: uint32
    puzzle: Program
    solution: Program


@dataclass(frozen=True)
@streamable
class RespondPuzzleSolution(Streamable):
    response: PuzzleSolutionResponse


@dataclass(frozen=True)
@streamable
class RejectPuzzleSolution(Streamable):
    coin_name: bytes32
    height: uint32


@dataclass(frozen=True)
@streamable
class SendTransaction(Streamable):
    transaction: SpendBundle


@dataclass(frozen=True)
@streamable
class TransactionAck(Streamable):
    txid: bytes32
    status: uint8
    error: Optional[str]


@dataclass(frozen=True)
@streamable
class NewPeakWallet(Streamable):
    header_hash: bytes32
    height: uint32
    weight: uint128
    fork_point_with_previous_peak: uint32


@dataclass(frozen=True)
@streamable
class RequestBlockHeader(Streamable):
    height: uint32


@dataclass(frozen=True)
@streamable
class RespondBlockHeader(Streamable):
    header_block: HeaderBlock


@dataclass(frozen=True)
@streamable
class RejectHeaderRequest(Streamable):
    height: uint32


@dataclass(frozen=True)
@streamable
class RequestRemovals(Streamable):
    height: uint32
    header_hash: bytes32
    coin_names: Optional[List[bytes32]]


@dataclass(frozen=True)
@streamable
class RespondRemovals(Streamable):
    height: uint32
    header_hash: bytes32
    coins: List[Tuple[(bytes32, Optional[Coin])]]
    proofs: Optional[List[Tuple[(bytes32, bytes)]]]


@dataclass(frozen=True)
@streamable
class RejectRemovalsRequest(Streamable):
    height: uint32
    header_hash: bytes32


@dataclass(frozen=True)
@streamable
class RequestAdditions(Streamable):
    height: uint32
    header_hash: bytes32
    puzzle_hashes: Optional[List[bytes32]]


@dataclass(frozen=True)
@streamable
class RespondAdditions(Streamable):
    height: uint32
    header_hash: bytes32
    coins: List[Tuple[(bytes32, List[Coin])]]
    proofs: Optional[List[Tuple[(bytes32, bytes, Optional[bytes])]]]


@dataclass(frozen=True)
@streamable
class RejectAdditionsRequest(Streamable):
    height: uint32
    header_hash: bytes32


@dataclass(frozen=True)
@streamable
class RequestHeaderBlocks(Streamable):
    start_height: uint32
    end_height: uint32


@dataclass(frozen=True)
@streamable
class RejectHeaderBlocks(Streamable):
    start_height: uint32
    end_height: uint32


@dataclass(frozen=True)
@streamable
class RespondHeaderBlocks(Streamable):
    start_height: uint32
    end_height: uint32
    header_blocks: List[HeaderBlock]