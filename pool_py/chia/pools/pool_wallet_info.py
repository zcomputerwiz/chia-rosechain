# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\pools\pool_wallet_info.py
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Dict
from blspy import G1Element
from chia.protocols.pool_protocol import POOL_PROTOCOL_VERSION
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint32, uint8
from chia.util.streamable import streamable, Streamable

class PoolSingletonState(IntEnum):
    __doc__ = '\n    From the user\'s point of view, a pool group can be in these states:\n    `SELF_POOLING`: The singleton exists on the blockchain, and we are farming\n        block rewards to a wallet address controlled by the user\n\n    `LEAVING_POOL`: The singleton exists, and we have entered the "escaping" state, which\n        means we are waiting for a number of blocks = `relative_lock_height` to pass, so we can leave.\n\n    `FARMING_TO_POOL`: The singleton exists, and it is assigned to a pool.\n\n    `CLAIMING_SELF_POOLED_REWARDS`: We have submitted a transaction to sweep our\n        self-pooled funds.\n    '
    SELF_POOLING = 1
    LEAVING_POOL = 2
    FARMING_TO_POOL = 3


SELF_POOLING = PoolSingletonState.SELF_POOLING
LEAVING_POOL = PoolSingletonState.LEAVING_POOL
FARMING_TO_POOL = PoolSingletonState.FARMING_TO_POOL

@dataclass(frozen=True)
@streamable
class PoolState(Streamable):
    __doc__ = "\n    `PoolState` is a type that is serialized to the blockchain to track the state of the user's pool singleton\n    `target_puzzle_hash` is either the pool address, or the self-pooling address that pool rewards will be paid to.\n    `target_puzzle_hash` is NOT the p2_singleton puzzle that block rewards are sent to.\n    The `p2_singleton` address is the initial address, and the `target_puzzle_hash` is the final destination.\n    `relative_lock_height` is zero when in SELF_POOLING state\n    "
    version: uint8
    state: uint8
    target_puzzle_hash: bytes32
    owner_pubkey: G1Element
    pool_url: Optional[str]
    relative_lock_height: uint32


def initial_pool_state_from_dict(state_dict, owner_pubkey, owner_puzzle_hash):
    state_str = state_dict['state']
    singleton_state = PoolSingletonState[state_str]
    if singleton_state == SELF_POOLING:
        target_puzzle_hash = owner_puzzle_hash
        pool_url = ''
        relative_lock_height = uint32(0)
    else:
        if singleton_state == FARMING_TO_POOL:
            target_puzzle_hash = bytes32(hexstr_to_bytes(state_dict['target_puzzle_hash']))
            pool_url = state_dict['pool_url']
            relative_lock_height = uint32(state_dict['relative_lock_height'])
        else:
            raise ValueError('Initial state must be SELF_POOLING or FARMING_TO_POOL')
    assert relative_lock_height is not None
    return create_pool_state(singleton_state, target_puzzle_hash, owner_pubkey, pool_url, relative_lock_height)


def create_pool_state(state: PoolSingletonState, target_puzzle_hash: bytes32, owner_pubkey: G1Element, pool_url: Optional[str], relative_lock_height: uint32) -> PoolState:
    if state not in set((s.value for s in PoolSingletonState)):
        raise AssertionError('state {state} is not a valid PoolSingletonState,')
    ps = PoolState(POOL_PROTOCOL_VERSION, uint8(state), target_puzzle_hash, owner_pubkey, pool_url, relative_lock_height)
    return ps


@dataclass(frozen=True)
@streamable
class PoolWalletInfo(Streamable):
    __doc__ = "\n    Internal Pool Wallet state, not destined for the blockchain. This can be completely derived with\n    the Singleton's CoinSpends list, or with the information from the WalletPoolStore.\n    "
    current: PoolState
    target: Optional[PoolState]
    launcher_coin: Coin
    launcher_id: bytes32
    p2_singleton_puzzle_hash: bytes32
    current_inner: Program
    tip_singleton_coin_id: bytes32
    singleton_block_height: uint32
    p2_chia_contract_or_pool_public_key: str