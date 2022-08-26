# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\timelord\iters_from_block.py
from typing import Optional, Tuple, Union
from chia.consensus.pot_iterations import calculate_ip_iters, calculate_iterations_quality, calculate_sp_iters
from chia.types.blockchain_format.reward_chain_block import RewardChainBlock, RewardChainBlockUnfinished
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64

def iters_from_block(constants, reward_chain_block: Union[(RewardChainBlock, RewardChainBlockUnfinished)], sub_slot_iters: uint64, difficulty: uint64) -> Tuple[(uint64, uint64)]:
    if reward_chain_block.challenge_chain_sp_vdf is None:
        assert reward_chain_block.signage_point_index == 0
        cc_sp = reward_chain_block.pos_ss_cc_challenge_hash
    else:
        cc_sp = reward_chain_block.challenge_chain_sp_vdf.output.get_hash()
    quality_string = reward_chain_block.proof_of_space.verify_and_get_quality_string(constants, reward_chain_block.pos_ss_cc_challenge_hash, cc_sp)
    assert quality_string is not None
    required_iters = calculate_iterations_quality(constants.DIFFICULTY_CONSTANT_FACTOR, quality_string, reward_chain_block.proof_of_space.size, difficulty, cc_sp)
    return (
     calculate_sp_iters(constants, sub_slot_iters, reward_chain_block.signage_point_index),
     calculate_ip_iters(constants, sub_slot_iters, reward_chain_block.signage_point_index, required_iters))