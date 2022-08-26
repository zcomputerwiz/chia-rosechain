# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\did_wallet\did_info.py
from dataclasses import dataclass
from typing import List, Optional, Tuple
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.util.streamable import streamable, Streamable
from chia.wallet.lineage_proof import LineageProof
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.coin import Coin

@dataclass(frozen=True)
@streamable
class DIDInfo(Streamable):
    origin_coin: Optional[Coin]
    backup_ids: List[bytes]
    num_of_backup_ids_needed: uint64
    parent_info: List[Tuple[(bytes32, Optional[LineageProof])]]
    current_inner: Optional[Program]
    temp_coin: Optional[Coin]
    temp_puzhash: Optional[bytes32]
    temp_pubkey: Optional[bytes]