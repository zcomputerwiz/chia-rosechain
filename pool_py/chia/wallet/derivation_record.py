# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\derivation_record.py
from dataclasses import dataclass
from blspy import G1Element
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32
from chia.wallet.util.wallet_types import WalletType

@dataclass(frozen=True)
class DerivationRecord:
    __doc__ = '\n    These are records representing a puzzle hash, which is generated from a\n    public key, derivation index, and wallet type. Stored in the puzzle_store.\n    '
    index: uint32
    puzzle_hash: bytes32
    pubkey: G1Element
    wallet_type: WalletType
    wallet_id: uint32