# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\wallet_info.py
from dataclasses import dataclass
from typing import List
from chia.util.ints import uint8, uint32
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class WalletInfo(Streamable):
    __doc__ = '\n    This object represents the wallet data as it is stored in DB.\n    ID: Main wallet (Standard) is stored at index 1, every wallet created after done has auto incremented id.\n    Name: can be a user provided or default generated name. (can be modified)\n    Type: is specified during wallet creation and should never be changed.\n    Data: this filed is intended to be used for storing any wallet specific information required for it.\n    (RL wallet stores origin_id, admin/user pubkey, rate limit, etc.)\n    This data should be json encoded string.\n    '
    id: uint32
    name: str
    type: uint8
    data: str


@dataclass(frozen=True)
@streamable
class WalletInfoBackup(Streamable):
    __doc__ = '\n    Used for transforming list of WalletInfo objects into bytes.\n    '
    wallet_list: List[WalletInfo]