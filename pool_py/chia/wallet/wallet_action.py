# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\wallet_action.py
from dataclasses import dataclass
from typing import Optional
from chia.util.ints import uint32
from chia.wallet.util.wallet_types import WalletType

@dataclass(frozen=True)
class WalletAction:
    __doc__ = '\n    This object represents the wallet action as it is stored in the database.\n\n    Purpose:\n    Some wallets require wallet node to perform a certain action when event happens.\n    For Example, coloured coin wallet needs to fetch solutions once it receives a coin.\n    In order to be safe from losing connection, closing the app, etc, those actions need to be persisted.\n\n    id: auto-incremented for every added action\n    name: Specified by the wallet\n    Wallet_id: ID of the wallet that created this action\n    type: Type of the wallet that created this action\n    wallet_callback: Name of the callback function in the wallet that created this action, if specified it will\n    get called when action has been performed.\n    done: Indicates if the action has been performed\n    data: JSON encoded string containing any data wallet or a wallet_node needs for this specific action.\n    '
    id: uint32
    name: str
    wallet_id: int
    type: WalletType
    wallet_callback: Optional[str]
    done: bool
    data: str