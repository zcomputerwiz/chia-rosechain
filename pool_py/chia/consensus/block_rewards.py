# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\consensus\block_rewards.py
from chia.util.ints import uint32, uint64
_mojo_per_chia = 1000000000
_blocks_per_year = 1681920

def calculate_pool_reward(height: uint32) -> uint64:
    """
    Returns the pool reward at a certain block height. The pool earns 7/8 of the reward in each block. If the farmer
    is solo farming, they act as the pool, and therefore earn the entire block reward.
    These halving events will not be hit at the exact times
    (3 years, etc), due to fluctuations in difficulty. They will likely come early, if the network space and VDF
    rates increase continuously.
    """
    if height == 0:
        return uint64(int(176496425.0 * _mojo_per_chia))
    if height < 3 * _blocks_per_year:
        return uint64(int(175.0 * _mojo_per_chia))
    if height < 6 * _blocks_per_year:
        return uint64(int(87.5 * _mojo_per_chia))
    if height < 9 * _blocks_per_year:
        return uint64(int(43.75 * _mojo_per_chia))
    if height < 12 * _blocks_per_year:
        return uint64(int(21.875 * _mojo_per_chia))
    if height < 15 * _blocks_per_year:
        return uint64(int(10.9375 * _mojo_per_chia))
    return uint64(int(0.875 * _mojo_per_chia))


def calculate_base_farmer_reward(height: uint32) -> uint64:
    """
    Returns the base farmer reward at a certain block height.
    The base fee reward is 1/8 of total block reward

    Returns the coinbase reward at a certain block height. These halving events will not be hit at the exact times
    (3 years, etc), due to fluctuations in difficulty. They will likely come early, if the network space and VDF
    rates increase continuously.
    """
    if height == 0:
        return uint64(int(25213775.0 * _mojo_per_chia))
    if height < 3 * _blocks_per_year:
        return uint64(int(25.0 * _mojo_per_chia))
    if height < 6 * _blocks_per_year:
        return uint64(int(12.5 * _mojo_per_chia))
    if height < 9 * _blocks_per_year:
        return uint64(int(6.25 * _mojo_per_chia))
    if height < 12 * _blocks_per_year:
        return uint64(int(3.125 * _mojo_per_chia))
    if height < 15 * _blocks_per_year:
        return uint64(int(1.5625 * _mojo_per_chia))
    return uint64(int(0.125 * _mojo_per_chia))