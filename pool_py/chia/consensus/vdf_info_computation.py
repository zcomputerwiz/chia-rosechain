# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\consensus\vdf_info_computation.py
from typing import List, Optional
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.constants import ConsensusConstants
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.util.ints import uint64, uint128

def get_signage_point_vdf_info(constants: ConsensusConstants, finished_sub_slots: List[EndOfSubSlotBundle], overflow: bool, prev_b: Optional[BlockRecord], blocks: BlockchainInterface, sp_total_iters: uint128, sp_iters: uint64):
    """
    Returns the following information, for the VDF of the signage point at sp_total_iters.
    cc and rc challenge hash
    cc and rc input
    cc and rc iterations
    """
    new_sub_slot = len(finished_sub_slots) > 0
    genesis_block = prev_b is None
    if new_sub_slot and not overflow:
        rc_vdf_challenge = finished_sub_slots[-1].reward_chain.get_hash()
        cc_vdf_challenge = finished_sub_slots[-1].challenge_chain.get_hash()
        sp_vdf_iters = sp_iters
        cc_vdf_input = ClassgroupElement.get_default_element()
    else:
        if new_sub_slot and overflow and len(finished_sub_slots) > 1:
            rc_vdf_challenge = finished_sub_slots[-2].reward_chain.get_hash()
            cc_vdf_challenge = finished_sub_slots[-2].challenge_chain.get_hash()
            sp_vdf_iters = sp_iters
            cc_vdf_input = ClassgroupElement.get_default_element()
        else:
            if genesis_block:
                rc_vdf_challenge = constants.GENESIS_CHALLENGE
                cc_vdf_challenge = constants.GENESIS_CHALLENGE
                sp_vdf_iters = sp_iters
                cc_vdf_input = ClassgroupElement.get_default_element()
            else:
                if new_sub_slot and overflow and len(finished_sub_slots) == 1:
                    assert prev_b is not None
                    curr = prev_b
                    while not curr.first_in_sub_slot:
                        if curr.total_iters > sp_total_iters:
                            curr = blocks.block_record(curr.prev_hash)

                    if curr.total_iters < sp_total_iters:
                        sp_vdf_iters = uint64(sp_total_iters - curr.total_iters)
                        cc_vdf_input = curr.challenge_vdf_output
                        rc_vdf_challenge = curr.reward_infusion_new_challenge
                    else:
                        assert curr.finished_reward_slot_hashes is not None
                        sp_vdf_iters = sp_iters
                        cc_vdf_input = ClassgroupElement.get_default_element()
                        rc_vdf_challenge = curr.finished_reward_slot_hashes[-1]
                    while not curr.first_in_sub_slot:
                        curr = blocks.block_record(curr.prev_hash)

                    assert curr.finished_challenge_slot_hashes is not None
                    cc_vdf_challenge = curr.finished_challenge_slot_hashes[-1]
                else:
                    if not new_sub_slot or overflow:
                        assert prev_b is not None
                        curr = prev_b
                        if curr.first_in_sub_slot:
                            assert curr.finished_challenge_slot_hashes is not None
                            assert curr.finished_reward_slot_hashes is not None
                            found_sub_slots = list(reversed(list(zip(curr.finished_challenge_slot_hashes, curr.finished_reward_slot_hashes))))
                        else:
                            found_sub_slots = []
                        sp_pre_sb = None
                        while len(found_sub_slots) < 2:
                            if curr.height > 0:
                                if sp_pre_sb is None:
                                    if curr.total_iters < sp_total_iters:
                                        sp_pre_sb = curr
                                curr = blocks.block_record(curr.prev_hash)
                                if curr.first_in_sub_slot:
                                    if not curr.finished_challenge_slot_hashes is not None:
                                        raise AssertionError
                                    else:
                                        assert curr.finished_reward_slot_hashes is not None
                                        found_sub_slots += list(reversed(list(zip(curr.finished_challenge_slot_hashes, curr.finished_reward_slot_hashes))))

                        if sp_pre_sb is None:
                            if curr.total_iters < sp_total_iters:
                                sp_pre_sb = curr
                        if sp_pre_sb is not None:
                            sp_vdf_iters = uint64(sp_total_iters - sp_pre_sb.total_iters)
                            cc_vdf_input = sp_pre_sb.challenge_vdf_output
                            rc_vdf_challenge = sp_pre_sb.reward_infusion_new_challenge
                        else:
                            sp_vdf_iters = sp_iters
                            cc_vdf_input = ClassgroupElement.get_default_element()
                            rc_vdf_challenge = found_sub_slots[1][1]
                        cc_vdf_challenge = found_sub_slots[1][0]
                    else:
                        if not (new_sub_slot or overflow):
                            assert prev_b is not None
                            curr = prev_b
                            while not curr.first_in_sub_slot:
                                if curr.total_iters > sp_total_iters:
                                    curr = blocks.block_record(curr.prev_hash)

                            if curr.total_iters < sp_total_iters:
                                sp_vdf_iters = uint64(sp_total_iters - curr.total_iters)
                                cc_vdf_input = curr.challenge_vdf_output
                                rc_vdf_challenge = curr.reward_infusion_new_challenge
                            else:
                                assert curr.finished_reward_slot_hashes is not None
                                sp_vdf_iters = sp_iters
                                cc_vdf_input = ClassgroupElement.get_default_element()
                                rc_vdf_challenge = curr.finished_reward_slot_hashes[-1]
                            while not curr.first_in_sub_slot:
                                curr = blocks.block_record(curr.prev_hash)

                            assert curr.finished_challenge_slot_hashes is not None
                            cc_vdf_challenge = curr.finished_challenge_slot_hashes[-1]
                        else:
                            assert False
        return (
         cc_vdf_challenge,
         rc_vdf_challenge,
         cc_vdf_input,
         ClassgroupElement.get_default_element(),
         sp_vdf_iters,
         sp_vdf_iters)