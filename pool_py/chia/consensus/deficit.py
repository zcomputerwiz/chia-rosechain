# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\consensus\deficit.py
from typing import Optional
from chia.consensus.block_record import BlockRecord
from chia.consensus.constants import ConsensusConstants
from chia.util.ints import uint8, uint32

def calculate_deficit(constants: ConsensusConstants, height: uint32, prev_b: Optional[BlockRecord], overflow: bool, num_finished_sub_slots: int) -> uint8:
    """
    Returns the deficit of the block to be created at height.

    Args:
        constants: consensus constants being used for this chain
        height: block height of the block that we care about
        prev_b: previous block
        overflow: whether or not this is an overflow block
        num_finished_sub_slots: the number of finished slots between infusion points of prev and current
    """
    if height == 0:
        return uint8(constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1)
    assert prev_b is not None
    prev_deficit = prev_b.deficit
    if prev_deficit == constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
        if overflow:
            if num_finished_sub_slots > 0:
                return uint8(prev_deficit - 1)
            return uint8(prev_deficit)
        return uint8(prev_deficit - 1)
    else:
        if prev_deficit == 0:
            if num_finished_sub_slots == 0:
                return uint8(0)
            if num_finished_sub_slots == 1:
                if overflow:
                    return uint8(constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK)
                return uint8(constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1)
            else:
                return uint8(constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1)
        else:
            return uint8(prev_deficit - 1)