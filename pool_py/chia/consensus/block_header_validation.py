# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\consensus\block_header_validation.py
import dataclasses, logging, time
from typing import Optional, Tuple
from blspy import AugSchemeMPL, G1Element, G2Element
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.constants import ConsensusConstants
from chia.consensus.deficit import calculate_deficit
from chia.consensus.difficulty_adjustment import can_finish_sub_and_full_epoch
from chia.consensus.get_block_challenge import final_eos_is_already_included, get_block_challenge
import chia.consensus.make_sub_epoch_summary as make_sub_epoch_summary
from chia.consensus.pot_iterations import calculate_ip_iters, calculate_iterations_quality, calculate_sp_interval_iters, calculate_sp_iters, is_overflow_block
from chia.consensus.vdf_info_computation import get_signage_point_vdf_info
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.slots import ChallengeChainSubSlot, RewardChainSubSlot, SubSlotProofs
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.header_block import HeaderBlock
from chia.types.unfinished_header_block import UnfinishedHeaderBlock
from chia.util.errors import Err, ValidationError
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64, uint128
log = logging.getLogger(__name__)

def validate_unfinished_header_block(constants: ConsensusConstants, blocks: BlockchainInterface, header_block: UnfinishedHeaderBlock, check_filter: bool, expected_difficulty: uint64, expected_sub_slot_iters: uint64, skip_overflow_last_ss_validation: bool=False, skip_vdf_is_valid: bool=False, check_sub_epoch_summary=True) -> Tuple[(Optional[uint64], Optional[ValidationError])]:
    """
    Validates an unfinished header block. This is a block without the infusion VDFs (unfinished)
    and without transactions and transaction info (header). Returns (required_iters, error).

    This method is meant to validate only the unfinished part of the block. However, the finished_sub_slots
    refers to all sub-slots that were finishes from the previous block's infusion point, up to this blocks
    infusion point. Therefore, in the case where this is an overflow block, and the last sub-slot is not yet
    released, header_block.finished_sub_slots will be missing one sub-slot. In this case,
    skip_overflow_last_ss_validation must be set to True. This will skip validation of end of slots, sub-epochs,
    and lead to other small tweaks in validation.
    """
    prev_b = blocks.try_block_record(header_block.prev_header_hash)
    genesis_block = prev_b is None
    if genesis_block:
        if header_block.prev_header_hash != constants.GENESIS_CHALLENGE:
            return (
             None, ValidationError(Err.INVALID_PREV_BLOCK_HASH))
    overflow = is_overflow_block(constants, header_block.reward_chain_block.signage_point_index)
    if skip_overflow_last_ss_validation and overflow:
        if final_eos_is_already_included(header_block, blocks, expected_sub_slot_iters):
            skip_overflow_last_ss_validation = False
            finished_sub_slots_since_prev = len(header_block.finished_sub_slots)
        else:
            finished_sub_slots_since_prev = len(header_block.finished_sub_slots) + 1
    else:
        finished_sub_slots_since_prev = len(header_block.finished_sub_slots)
    new_sub_slot = finished_sub_slots_since_prev > 0
    can_finish_se = False
    can_finish_epoch = False
    if genesis_block:
        height = uint32(0)
        assert expected_difficulty == constants.DIFFICULTY_STARTING
        assert expected_sub_slot_iters == constants.SUB_SLOT_ITERS_STARTING
    else:
        assert prev_b is not None
        height = uint32(prev_b.height + 1)
        if new_sub_slot:
            can_finish_se, can_finish_epoch = can_finish_sub_and_full_epoch(constants, blocks, prev_b.height, prev_b.prev_hash, prev_b.deficit, prev_b.sub_epoch_summary_included is not None)
        else:
            can_finish_se = False
            can_finish_epoch = False
    ses_hash = None
    if new_sub_slot and not skip_overflow_last_ss_validation:
        for finished_sub_slot_n, sub_slot in enumerate(header_block.finished_sub_slots):
            challenge_hash = sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.challenge
            if finished_sub_slot_n == 0:
                if genesis_block:
                    if challenge_hash != constants.GENESIS_CHALLENGE:
                        return (None, ValidationError(Err.INVALID_PREV_CHALLENGE_SLOT_HASH))
                else:
                    assert prev_b is not None
                    curr = prev_b
                    while not curr.first_in_sub_slot:
                        curr = blocks.block_record(curr.prev_hash)

                    assert curr.finished_challenge_slot_hashes is not None
                    if not curr.finished_challenge_slot_hashes[-1] == challenge_hash:
                        print(curr.finished_challenge_slot_hashes[-1], challenge_hash)
                        return (
                         None, ValidationError(Err.INVALID_PREV_CHALLENGE_SLOT_HASH))
            else:
                if not header_block.finished_sub_slots[finished_sub_slot_n - 1].challenge_chain.get_hash() == challenge_hash:
                    return (
                     None, ValidationError(Err.INVALID_PREV_CHALLENGE_SLOT_HASH))
                if genesis_block:
                    if sub_slot.infused_challenge_chain is not None:
                        return (None, ValidationError(Err.SHOULD_NOT_HAVE_ICC))
                else:
                    assert prev_b is not None
                    icc_iters_committed = None
                    icc_iters_proof = None
                    icc_challenge_hash = None
                    icc_vdf_input = None
                    if prev_b.deficit < constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                        if finished_sub_slot_n == 0:
                            curr = prev_b
                            while not curr.is_challenge_block(constants):
                                if not curr.first_in_sub_slot:
                                    curr = blocks.block_record(curr.prev_hash)

                            if curr.is_challenge_block(constants):
                                icc_challenge_hash = curr.challenge_block_info_hash
                                icc_iters_committed = uint64(prev_b.sub_slot_iters - curr.ip_iters(constants))
                            else:
                                assert curr.finished_infused_challenge_slot_hashes is not None
                                icc_challenge_hash = curr.finished_infused_challenge_slot_hashes[-1]
                                icc_iters_committed = prev_b.sub_slot_iters
                            icc_iters_proof = uint64(prev_b.sub_slot_iters - prev_b.ip_iters(constants))
                            if prev_b.is_challenge_block(constants):
                                icc_vdf_input = ClassgroupElement.get_default_element()
                            else:
                                icc_vdf_input = prev_b.infused_challenge_vdf_output
                        else:
                            if header_block.finished_sub_slots[finished_sub_slot_n - 1].reward_chain.deficit < constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                                finished_ss = header_block.finished_sub_slots[finished_sub_slot_n - 1]
                                assert finished_ss.infused_challenge_chain is not None
                                icc_challenge_hash = finished_ss.infused_challenge_chain.get_hash()
                                icc_iters_committed = prev_b.sub_slot_iters
                                icc_iters_proof = icc_iters_committed
                                icc_vdf_input = ClassgroupElement.get_default_element()
                    assert (sub_slot.infused_challenge_chain is None) == (icc_challenge_hash is None)
                    if sub_slot.infused_challenge_chain is not None:
                        assert icc_vdf_input is not None
                        assert icc_iters_proof is not None
                        assert icc_challenge_hash is not None
                        assert sub_slot.proofs.infused_challenge_chain_slot_proof is not None
                        target_vdf_info = VDFInfo(icc_challenge_hash, icc_iters_proof, sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.output)
                        if sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf != dataclasses.replace(target_vdf_info,
                          number_of_iterations=icc_iters_committed):
                            return (
                             None, ValidationError(Err.INVALID_ICC_EOS_VDF))
                        if not skip_vdf_is_valid:
                            if not sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity:
                                if not sub_slot.proofs.infused_challenge_chain_slot_proof.is_valid(constants, icc_vdf_input, target_vdf_info, None):
                                    return (
                                     None, ValidationError(Err.INVALID_ICC_EOS_VDF))
                            if sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity:
                                if not sub_slot.proofs.infused_challenge_chain_slot_proof.is_valid(constants, ClassgroupElement.get_default_element(), sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf):
                                    return (
                                     None, ValidationError(Err.INVALID_ICC_EOS_VDF))
                        if sub_slot.reward_chain.deficit == constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                            if sub_slot.infused_challenge_chain.get_hash() != sub_slot.challenge_chain.infused_challenge_chain_sub_slot_hash:
                                return (
                                 None, ValidationError(Err.INVALID_ICC_HASH_CC))
                        else:
                            if sub_slot.challenge_chain.infused_challenge_chain_sub_slot_hash is not None:
                                return (None, ValidationError(Err.INVALID_ICC_HASH_CC))
                        if sub_slot.infused_challenge_chain.get_hash() != sub_slot.reward_chain.infused_challenge_chain_sub_slot_hash:
                            return (
                             None, ValidationError(Err.INVALID_ICC_HASH_RC))
                    else:
                        if sub_slot.challenge_chain.infused_challenge_chain_sub_slot_hash is not None:
                            return (None, ValidationError(Err.INVALID_ICC_HASH_CC))
                        if sub_slot.reward_chain.infused_challenge_chain_sub_slot_hash is not None:
                            return (None, ValidationError(Err.INVALID_ICC_HASH_RC))
                if sub_slot.challenge_chain.subepoch_summary_hash is not None:
                    assert ses_hash is None
                    ses_hash = sub_slot.challenge_chain.subepoch_summary_hash
                if finished_sub_slot_n != 0:
                    if sub_slot.challenge_chain.subepoch_summary_hash is not None:
                        return (None, ValidationError(Err.INVALID_SUB_EPOCH_SUMMARY_HASH))
                if can_finish_epoch and sub_slot.challenge_chain.subepoch_summary_hash is not None:
                    if sub_slot.challenge_chain.new_sub_slot_iters != expected_sub_slot_iters:
                        return (None, ValidationError(Err.INVALID_NEW_SUB_SLOT_ITERS))
                    if sub_slot.challenge_chain.new_difficulty != expected_difficulty:
                        return (None, ValidationError(Err.INVALID_NEW_DIFFICULTY))
                else:
                    if sub_slot.challenge_chain.new_sub_slot_iters is not None:
                        return (None, ValidationError(Err.INVALID_NEW_SUB_SLOT_ITERS))
                    if sub_slot.challenge_chain.new_difficulty is not None:
                        return (None, ValidationError(Err.INVALID_NEW_DIFFICULTY))
                if sub_slot.challenge_chain.get_hash() != sub_slot.reward_chain.challenge_chain_sub_slot_hash:
                    return (
                     None,
                     ValidationError(Err.INVALID_CHALLENGE_SLOT_HASH_RC, 'sub-slot hash in reward sub-slot mismatch'))
                eos_vdf_iters = expected_sub_slot_iters
                cc_start_element = ClassgroupElement.get_default_element()
                cc_eos_vdf_challenge = challenge_hash
                if genesis_block:
                    if finished_sub_slot_n == 0:
                        rc_eos_vdf_challenge = constants.GENESIS_CHALLENGE
                        cc_eos_vdf_challenge = constants.GENESIS_CHALLENGE
                    else:
                        rc_eos_vdf_challenge = header_block.finished_sub_slots[finished_sub_slot_n - 1].reward_chain.get_hash()
                else:
                    assert prev_b is not None
                    if finished_sub_slot_n == 0:
                        rc_eos_vdf_challenge = prev_b.reward_infusion_new_challenge
                        eos_vdf_iters = uint64(prev_b.sub_slot_iters - prev_b.ip_iters(constants))
                        cc_start_element = prev_b.challenge_vdf_output
                    else:
                        rc_eos_vdf_challenge = header_block.finished_sub_slots[finished_sub_slot_n - 1].reward_chain.get_hash()
                target_vdf_info = VDFInfo(rc_eos_vdf_challenge, eos_vdf_iters, sub_slot.reward_chain.end_of_slot_vdf.output)
                if not skip_vdf_is_valid:
                    if not sub_slot.proofs.reward_chain_slot_proof.is_valid(constants, ClassgroupElement.get_default_element(), sub_slot.reward_chain.end_of_slot_vdf, target_vdf_info):
                        return (
                         None, ValidationError(Err.INVALID_RC_EOS_VDF))
                partial_cc_vdf_info = VDFInfo(cc_eos_vdf_challenge, eos_vdf_iters, sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.output)
                if genesis_block:
                    cc_eos_vdf_info_iters = constants.SUB_SLOT_ITERS_STARTING
                else:
                    assert prev_b is not None
                    if finished_sub_slot_n == 0:
                        cc_eos_vdf_info_iters = prev_b.sub_slot_iters
                    else:
                        cc_eos_vdf_info_iters = expected_sub_slot_iters
                if sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf != dataclasses.replace(partial_cc_vdf_info,
                  number_of_iterations=cc_eos_vdf_info_iters):
                    return (
                     None, ValidationError(Err.INVALID_CC_EOS_VDF, 'wrong challenge chain end of slot vdf'))
                return skip_vdf_is_valid or sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity or sub_slot.proofs.challenge_chain_slot_proof.is_valid(constants, cc_start_element, partial_cc_vdf_info, None) or (
                 None, ValidationError(Err.INVALID_CC_EOS_VDF))
            if sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity:
                if not sub_slot.proofs.challenge_chain_slot_proof.is_valid(constants, ClassgroupElement.get_default_element(), sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf):
                    return (
                     None, ValidationError(Err.INVALID_CC_EOS_VDF))
                if genesis_block:
                    if sub_slot.reward_chain.deficit != constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                        return (
                         None,
                         ValidationError(Err.INVALID_DEFICIT, f"genesis, expected deficit {constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK}"))
                else:
                    assert prev_b is not None
                    if prev_b.deficit == 0:
                        if sub_slot.reward_chain.deficit != constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                            log.error(constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK)
                            return (
                             None,
                             ValidationError(Err.INVALID_DEFICIT, f"expected deficit {constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK}, saw {sub_slot.reward_chain.deficit}"))
                    else:
                        if sub_slot.reward_chain.deficit != prev_b.deficit:
                            return (None, ValidationError(Err.INVALID_DEFICIT, 'deficit is wrong at slot end'))

        if not skip_overflow_last_ss_validation:
            if ses_hash is not None:
                if genesis_block:
                    return (
                     None,
                     ValidationError(Err.INVALID_SUB_EPOCH_SUMMARY_HASH, 'genesis with sub-epoch-summary hash'))
                assert prev_b is not None
                if not (new_sub_slot and can_finish_se):
                    return (
                     None,
                     ValidationError(Err.INVALID_SUB_EPOCH_SUMMARY_HASH, f"new sub-slot: {new_sub_slot} finishes sub-epoch {can_finish_se}"))
                if check_sub_epoch_summary:
                    expected_sub_epoch_summary = make_sub_epoch_summary(constants, blocks, height, blocks.block_record(prev_b.prev_hash), expected_difficulty if can_finish_epoch else None, expected_sub_slot_iters if can_finish_epoch else None)
                    expected_hash = expected_sub_epoch_summary.get_hash()
                    if expected_hash != ses_hash:
                        log.error(f"{expected_sub_epoch_summary}")
                        return (
                         None,
                         ValidationError(Err.INVALID_SUB_EPOCH_SUMMARY, f"expected ses hash: {expected_hash} got {ses_hash} "))
    else:
        pass
    if new_sub_slot and not genesis_block:
        if can_finish_se or can_finish_epoch:
            return (
             None,
             ValidationError(Err.INVALID_SUB_EPOCH_SUMMARY, 'block finishes sub-epoch but ses-hash is None'))
        if not new_sub_slot:
            if not genesis_block:
                assert prev_b is not None
                num_blocks = 2
                curr = prev_b
                while not curr.first_in_sub_slot:
                    num_blocks += 1
                    curr = blocks.block_record(curr.prev_hash)

                if num_blocks > constants.MAX_SUB_SLOT_BLOCKS:
                    return (None, ValidationError(Err.TOO_MANY_BLOCKS))
        challenge = get_block_challenge(constants, header_block, blocks, genesis_block, overflow, skip_overflow_last_ss_validation)
        if challenge != header_block.reward_chain_block.pos_ss_cc_challenge_hash:
            log.error(f"Finished slots: {header_block.finished_sub_slots}")
            log.error(f"Data: {genesis_block} {overflow} {skip_overflow_last_ss_validation} {header_block.total_iters} {header_block.reward_chain_block.signage_point_index}Prev: {prev_b}")
            log.error(f"Challenge {challenge} provided {header_block.reward_chain_block.pos_ss_cc_challenge_hash}")
            return (
             None, ValidationError(Err.INVALID_CC_CHALLENGE))
        if header_block.reward_chain_block.challenge_chain_sp_vdf is None:
            cc_sp_hash = challenge
        else:
            cc_sp_hash = header_block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()
        q_str = header_block.reward_chain_block.proof_of_space.verify_and_get_quality_string(constants, challenge, cc_sp_hash)
        if q_str is None:
            return (None, ValidationError(Err.INVALID_POSPACE))
        if header_block.reward_chain_block.signage_point_index >= constants.NUM_SPS_SUB_SLOT:
            return (None, ValidationError(Err.INVALID_SP_INDEX))
        required_iters = calculate_iterations_quality(constants.DIFFICULTY_CONSTANT_FACTOR, q_str, header_block.reward_chain_block.proof_of_space.size, expected_difficulty, cc_sp_hash)
        if required_iters >= calculate_sp_interval_iters(constants, expected_sub_slot_iters):
            return (None, ValidationError(Err.INVALID_REQUIRED_ITERS))
        if (header_block.reward_chain_block.signage_point_index == 0) != (header_block.reward_chain_block.challenge_chain_sp_vdf is None):
            return (
             None, ValidationError(Err.INVALID_SP_INDEX))
        if (header_block.reward_chain_block.signage_point_index == 0) != (header_block.reward_chain_block.reward_chain_sp_vdf is None):
            return (
             None, ValidationError(Err.INVALID_SP_INDEX))
        sp_iters = calculate_sp_iters(constants, expected_sub_slot_iters, header_block.reward_chain_block.signage_point_index)
        ip_iters = calculate_ip_iters(constants, expected_sub_slot_iters, header_block.reward_chain_block.signage_point_index, required_iters)
        if header_block.reward_chain_block.challenge_chain_sp_vdf is None:
            assert not overflow
        if overflow:
            if can_finish_epoch:
                if finished_sub_slots_since_prev < 2:
                    return (None, ValidationError(Err.NO_OVERFLOWS_IN_FIRST_SUB_SLOT_NEW_EPOCH))
        if genesis_block:
            total_iters = uint128(expected_sub_slot_iters * finished_sub_slots_since_prev)
        else:
            assert prev_b is not None
            if new_sub_slot:
                total_iters = prev_b.total_iters
                total_iters = uint128(total_iters + prev_b.sub_slot_iters - prev_b.ip_iters(constants))
                total_iters = uint128(total_iters + expected_sub_slot_iters * (finished_sub_slots_since_prev - 1))
            else:
                total_iters = uint128(prev_b.total_iters - prev_b.ip_iters(constants))
        total_iters = uint128(total_iters + ip_iters)
        if total_iters != header_block.reward_chain_block.total_iters:
            return (
             None,
             ValidationError(Err.INVALID_TOTAL_ITERS, f"expected {total_iters} got {header_block.reward_chain_block.total_iters}"))
        sp_total_iters = uint128(total_iters - ip_iters + sp_iters - (expected_sub_slot_iters if overflow else 0))
        if overflow and skip_overflow_last_ss_validation:
            dummy_vdf_info = VDFInfo(bytes32([0] * 32), uint64(1), ClassgroupElement.get_default_element())
            dummy_sub_slot = EndOfSubSlotBundle(ChallengeChainSubSlot(dummy_vdf_info, None, None, None, None), None, RewardChainSubSlot(dummy_vdf_info, bytes32([0] * 32), None, uint8(0)), SubSlotProofs(VDFProof(uint8(0), b'', False), None, VDFProof(uint8(0), b'', False)))
            sub_slots_to_pass_in = header_block.finished_sub_slots + [dummy_sub_slot]
        else:
            sub_slots_to_pass_in = header_block.finished_sub_slots
        cc_vdf_challenge, rc_vdf_challenge, cc_vdf_input, rc_vdf_input, cc_vdf_iters, rc_vdf_iters = get_signage_point_vdf_info(constants, sub_slots_to_pass_in, overflow, prev_b, blocks, sp_total_iters, sp_iters)
        if sp_iters != 0:
            if not (header_block.reward_chain_block.reward_chain_sp_vdf is not None and header_block.reward_chain_sp_proof is not None):
                raise AssertionError
            target_vdf_info = VDFInfo(rc_vdf_challenge, rc_vdf_iters, header_block.reward_chain_block.reward_chain_sp_vdf.output)
            if not skip_vdf_is_valid:
                if not header_block.reward_chain_sp_proof.is_valid(constants, rc_vdf_input, header_block.reward_chain_block.reward_chain_sp_vdf, target_vdf_info):
                    return (
                     None, ValidationError(Err.INVALID_RC_SP_VDF))
            rc_sp_hash = header_block.reward_chain_block.reward_chain_sp_vdf.output.get_hash()
        else:
            assert overflow is not None
            if header_block.reward_chain_block.reward_chain_sp_vdf is not None:
                return (None, ValidationError(Err.INVALID_RC_SP_VDF))
            if new_sub_slot:
                rc_sp_hash = header_block.finished_sub_slots[-1].reward_chain.get_hash()
            else:
                if genesis_block:
                    rc_sp_hash = constants.GENESIS_CHALLENGE
                else:
                    assert prev_b is not None
                    curr = prev_b
                    while not curr.first_in_sub_slot:
                        curr = blocks.block_record(curr.prev_hash)

                    assert curr.finished_reward_slot_hashes is not None
                    rc_sp_hash = curr.finished_reward_slot_hashes[-1]
        if not AugSchemeMPL.verify(header_block.reward_chain_block.proof_of_space.plot_public_key, rc_sp_hash, header_block.reward_chain_block.reward_chain_sp_signature):
            return (
             None, ValidationError(Err.INVALID_RC_SIGNATURE))
        if sp_iters != 0:
            assert header_block.reward_chain_block.challenge_chain_sp_vdf is not None
            assert header_block.challenge_chain_sp_proof is not None
            target_vdf_info = VDFInfo(cc_vdf_challenge, cc_vdf_iters, header_block.reward_chain_block.challenge_chain_sp_vdf.output)
            if header_block.reward_chain_block.challenge_chain_sp_vdf != dataclasses.replace(target_vdf_info,
              number_of_iterations=sp_iters):
                return (
                 None, ValidationError(Err.INVALID_CC_SP_VDF))
            if not skip_vdf_is_valid:
                if not header_block.challenge_chain_sp_proof.normalized_to_identity:
                    if not header_block.challenge_chain_sp_proof.is_valid(constants, cc_vdf_input, target_vdf_info, None):
                        return (
                         None, ValidationError(Err.INVALID_CC_SP_VDF))
                if header_block.challenge_chain_sp_proof.normalized_to_identity and not header_block.challenge_chain_sp_proof.is_valid(constants, ClassgroupElement.get_default_element(), header_block.reward_chain_block.challenge_chain_sp_vdf):
                    return (
                     None, ValidationError(Err.INVALID_CC_SP_VDF))
                else:
                    assert overflow is not None
                    if header_block.reward_chain_block.challenge_chain_sp_vdf is not None:
                        return (None, ValidationError(Err.INVALID_CC_SP_VDF))
            if not AugSchemeMPL.verify(header_block.reward_chain_block.proof_of_space.plot_public_key, cc_sp_hash, header_block.reward_chain_block.challenge_chain_sp_signature):
                return (
                 None, ValidationError(Err.INVALID_CC_SIGNATURE, 'invalid cc sp sig'))
            if genesis_block:
                if header_block.foliage.foliage_transaction_block_hash is None:
                    return (None, ValidationError(Err.INVALID_IS_TRANSACTION_BLOCK, 'invalid genesis'))
            else:
                assert prev_b is not None
                curr = prev_b
                while not curr.is_transaction_block:
                    curr = blocks.block_record(curr.prev_hash)

                if overflow:
                    our_sp_total_iters = uint128(total_iters - ip_iters + sp_iters - expected_sub_slot_iters)
                else:
                    our_sp_total_iters = uint128(total_iters - ip_iters + sp_iters)
                if (our_sp_total_iters > curr.total_iters) != (header_block.foliage.foliage_transaction_block_hash is not None):
                    return (None, ValidationError(Err.INVALID_IS_TRANSACTION_BLOCK))
                if (our_sp_total_iters > curr.total_iters) != (header_block.foliage.foliage_transaction_block_signature is not None):
                    return (
                     None, ValidationError(Err.INVALID_IS_TRANSACTION_BLOCK))
            if not AugSchemeMPL.verify(header_block.reward_chain_block.proof_of_space.plot_public_key, header_block.foliage.foliage_block_data.get_hash(), header_block.foliage.foliage_block_data_signature):
                return (
                 None, ValidationError(Err.INVALID_PLOT_SIGNATURE))
            if header_block.foliage.foliage_transaction_block_hash is not None:
                if not AugSchemeMPL.verify(header_block.reward_chain_block.proof_of_space.plot_public_key, header_block.foliage.foliage_transaction_block_hash, header_block.foliage.foliage_transaction_block_signature):
                    return (
                     None, ValidationError(Err.INVALID_PLOT_SIGNATURE))
                if header_block.reward_chain_block.get_hash() != header_block.foliage.foliage_block_data.unfinished_reward_block_hash:
                    return (
                     None, ValidationError(Err.INVALID_URSB_HASH))
            if header_block.foliage.foliage_block_data.pool_target.max_height != 0:
                if header_block.foliage.foliage_block_data.pool_target.max_height < height:
                    return (
                     None, ValidationError(Err.OLD_POOL_TARGET))
        if genesis_block:
            if header_block.foliage.foliage_block_data.pool_target.puzzle_hash != constants.GENESIS_PRE_FARM_POOL_PUZZLE_HASH:
                log.error(f"Pool target {header_block.foliage.foliage_block_data.pool_target} hb {header_block}")
                return (
                 None, ValidationError(Err.INVALID_PREFARM))
            if header_block.foliage.foliage_block_data.farmer_reward_puzzle_hash != constants.GENESIS_PRE_FARM_FARMER_PUZZLE_HASH:
                return (
                 None, ValidationError(Err.INVALID_PREFARM))
    else:
        if header_block.reward_chain_block.proof_of_space.pool_public_key is not None:
            assert header_block.reward_chain_block.proof_of_space.pool_contract_puzzle_hash is None
            if not AugSchemeMPL.verify(header_block.reward_chain_block.proof_of_space.pool_public_key, bytes(header_block.foliage.foliage_block_data.pool_target), header_block.foliage.foliage_block_data.pool_signature):
                pool_target_Hash = std_hash(bytes(header_block.foliage.foliage_block_data.pool_target))
                return AugSchemeMPL.verify(header_block.reward_chain_block.proof_of_space.plot_public_key, pool_target_Hash, header_block.foliage.foliage_block_data.pool_signature) or (
                 None, ValidationError(Err.INVALID_POOL_SIGNATURE))
        else:
            assert header_block.reward_chain_block.proof_of_space.pool_contract_puzzle_hash is not None
        if header_block.foliage.foliage_block_data.pool_target.puzzle_hash != header_block.reward_chain_block.proof_of_space.pool_contract_puzzle_hash:
            pool_target_Hash = std_hash(bytes(header_block.foliage.foliage_block_data.pool_target))
            if not AugSchemeMPL.verify(header_block.reward_chain_block.proof_of_space.plot_public_key, pool_target_Hash, header_block.foliage.foliage_block_data.pool_signature):
                return (
                 None, ValidationError(Err.INVALID_POOL_TARGET))
            if (header_block.foliage.foliage_transaction_block_hash is not None) != (header_block.foliage_transaction_block is not None):
                return (
                 None, ValidationError(Err.INVALID_FOLIAGE_BLOCK_PRESENCE))
            if (header_block.foliage.foliage_transaction_block_signature is not None) != (header_block.foliage_transaction_block is not None):
                return (
                 None, ValidationError(Err.INVALID_FOLIAGE_BLOCK_PRESENCE))
            if header_block.foliage_transaction_block is not None:
                if header_block.foliage_transaction_block.get_hash() != header_block.foliage.foliage_transaction_block_hash:
                    return (None, ValidationError(Err.INVALID_FOLIAGE_BLOCK_HASH))
                if genesis_block:
                    if header_block.foliage_transaction_block.prev_transaction_block_hash != constants.GENESIS_CHALLENGE:
                        return (None, ValidationError(Err.INVALID_PREV_BLOCK_HASH))
                else:
                    assert prev_b is not None
                    curr_b = prev_b
                    while not curr_b.is_transaction_block:
                        curr_b = blocks.block_record(curr_b.prev_hash)

                    if not header_block.foliage_transaction_block.prev_transaction_block_hash == curr_b.header_hash:
                        log.error(f"Prev BH: {header_block.foliage_transaction_block.prev_transaction_block_hash} {curr_b.header_hash} curr sb: {curr_b}")
                        return (
                         None, ValidationError(Err.INVALID_PREV_BLOCK_HASH))
                if check_filter:
                    if header_block.foliage_transaction_block.filter_hash != std_hash(header_block.transactions_filter):
                        return (None, ValidationError(Err.INVALID_TRANSACTIONS_FILTER_HASH))
                if header_block.foliage_transaction_block.timestamp > int(time.time() + constants.MAX_FUTURE_TIME):
                    return (None, ValidationError(Err.TIMESTAMP_TOO_FAR_IN_FUTURE))
                if prev_b is not None:
                    prev_transaction_b = blocks.block_record(header_block.foliage_transaction_block.prev_transaction_block_hash)
                    assert prev_transaction_b.timestamp is not None
                    if header_block.foliage_transaction_block.timestamp <= prev_transaction_b.timestamp:
                        return (None, ValidationError(Err.TIMESTAMP_TOO_FAR_IN_PAST))
            return (
             required_iters, None)


def validate_finished_header_block(constants: ConsensusConstants, blocks: BlockchainInterface, header_block: HeaderBlock, check_filter: bool, expected_difficulty: uint64, expected_sub_slot_iters: uint64, check_sub_epoch_summary=True) -> Tuple[(Optional[uint64], Optional[ValidationError])]:
    """
    Fully validates the header of a block. A header block is the same  as a full block, but
    without transactions and transaction info. Returns (required_iters, error).
    """
    unfinished_header_block = UnfinishedHeaderBlock(header_block.finished_sub_slots, header_block.reward_chain_block.get_unfinished(), header_block.challenge_chain_sp_proof, header_block.reward_chain_sp_proof, header_block.foliage, header_block.foliage_transaction_block, header_block.transactions_filter)
    required_iters, validate_unfinished_err = validate_unfinished_header_block(constants,
      blocks,
      unfinished_header_block,
      check_filter,
      expected_difficulty,
      expected_sub_slot_iters,
      False,
      check_sub_epoch_summary=check_sub_epoch_summary)
    genesis_block = False
    if validate_unfinished_err is not None:
        return (None, validate_unfinished_err)
    assert required_iters is not None
    if header_block.height == 0:
        prev_b = None
        genesis_block = True
    else:
        prev_b = blocks.block_record(header_block.prev_header_hash)
    new_sub_slot = len(header_block.finished_sub_slots) > 0
    ip_iters = calculate_ip_iters(constants, expected_sub_slot_iters, header_block.reward_chain_block.signage_point_index, required_iters)
    if not genesis_block:
        assert prev_b is not None
        if header_block.height != prev_b.height + 1:
            return (None, ValidationError(Err.INVALID_HEIGHT))
        if header_block.weight != prev_b.weight + expected_difficulty:
            log.error(f"INVALID WEIGHT: {header_block} {prev_b} {expected_difficulty}")
            return (
             None, ValidationError(Err.INVALID_WEIGHT))
    else:
        if header_block.height != uint32(0):
            return (None, ValidationError(Err.INVALID_HEIGHT))
        if header_block.weight != constants.DIFFICULTY_STARTING:
            return (None, ValidationError(Err.INVALID_WEIGHT))
        if header_block.prev_header_hash != constants.GENESIS_CHALLENGE:
            return (None, ValidationError(Err.INVALID_PREV_BLOCK_HASH))
    if genesis_block:
        cc_vdf_output = ClassgroupElement.get_default_element()
        ip_vdf_iters = ip_iters
        if new_sub_slot:
            rc_vdf_challenge = header_block.finished_sub_slots[-1].reward_chain.get_hash()
        else:
            rc_vdf_challenge = constants.GENESIS_CHALLENGE
    else:
        assert prev_b is not None
        if new_sub_slot:
            rc_vdf_challenge = header_block.finished_sub_slots[-1].reward_chain.get_hash()
            ip_vdf_iters = ip_iters
            cc_vdf_output = ClassgroupElement.get_default_element()
        else:
            rc_vdf_challenge = prev_b.reward_infusion_new_challenge
            ip_vdf_iters = uint64(header_block.reward_chain_block.total_iters - prev_b.total_iters)
            cc_vdf_output = prev_b.challenge_vdf_output
    if new_sub_slot:
        cc_vdf_challenge = header_block.finished_sub_slots[-1].challenge_chain.get_hash()
    else:
        if genesis_block:
            cc_vdf_challenge = constants.GENESIS_CHALLENGE
        else:
            assert prev_b is not None
            curr = prev_b
            while curr.finished_challenge_slot_hashes is None:
                curr = blocks.block_record(curr.prev_hash)

            cc_vdf_challenge = curr.finished_challenge_slot_hashes[-1]
    cc_target_vdf_info = VDFInfo(cc_vdf_challenge, ip_vdf_iters, header_block.reward_chain_block.challenge_chain_ip_vdf.output)
    if header_block.reward_chain_block.challenge_chain_ip_vdf != dataclasses.replace(cc_target_vdf_info,
      number_of_iterations=ip_iters):
        expected = dataclasses.replace(cc_target_vdf_info,
          number_of_iterations=ip_iters)
        log.error(f"{header_block.reward_chain_block.challenge_chain_ip_vdf}. expected {expected}")
        log.error(f"Block: {header_block}")
        return (
         None, ValidationError(Err.INVALID_CC_IP_VDF))
    if not header_block.challenge_chain_ip_proof.normalized_to_identity:
        if not header_block.challenge_chain_ip_proof.is_valid(constants, cc_vdf_output, cc_target_vdf_info, None):
            log.error(f"Did not validate, output {cc_vdf_output}")
            log.error(f"Block: {header_block}")
            return (
             None, ValidationError(Err.INVALID_CC_IP_VDF))
    if header_block.challenge_chain_ip_proof.normalized_to_identity:
        if not header_block.challenge_chain_ip_proof.is_valid(constants, ClassgroupElement.get_default_element(), header_block.reward_chain_block.challenge_chain_ip_vdf):
            return (
             None, ValidationError(Err.INVALID_CC_IP_VDF))
        rc_target_vdf_info = VDFInfo(rc_vdf_challenge, ip_vdf_iters, header_block.reward_chain_block.reward_chain_ip_vdf.output)
        if not header_block.reward_chain_ip_proof.is_valid(constants, ClassgroupElement.get_default_element(), header_block.reward_chain_block.reward_chain_ip_vdf, rc_target_vdf_info):
            return (
             None, ValidationError(Err.INVALID_RC_IP_VDF))
        if not genesis_block:
            overflow = is_overflow_block(constants, header_block.reward_chain_block.signage_point_index)
            deficit = calculate_deficit(constants, header_block.height, prev_b, overflow, len(header_block.finished_sub_slots))
            if header_block.reward_chain_block.infused_challenge_chain_ip_vdf is None:
                if deficit < constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1:
                    return (None, ValidationError(Err.INVALID_ICC_VDF))
            else:
                assert header_block.infused_challenge_chain_ip_proof is not None
                if deficit >= constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1:
                    return (
                     None,
                     ValidationError(Err.INVALID_ICC_VDF, f"icc vdf and deficit is bigger or equal to {constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1}"))
                if new_sub_slot:
                    last_ss = header_block.finished_sub_slots[-1]
                    assert last_ss.infused_challenge_chain is not None
                    icc_vdf_challenge = last_ss.infused_challenge_chain.get_hash()
                    icc_vdf_input = ClassgroupElement.get_default_element()
                else:
                    assert prev_b is not None
                    if prev_b.is_challenge_block(constants):
                        icc_vdf_input = ClassgroupElement.get_default_element()
                    else:
                        icc_vdf_input = prev_b.infused_challenge_vdf_output
                    curr = prev_b
                    while curr.finished_infused_challenge_slot_hashes is None:
                        if not curr.is_challenge_block(constants):
                            curr = blocks.block_record(curr.prev_hash)

                    if curr.is_challenge_block(constants):
                        icc_vdf_challenge = curr.challenge_block_info_hash
                    else:
                        assert curr.finished_infused_challenge_slot_hashes is not None
                        icc_vdf_challenge = curr.finished_infused_challenge_slot_hashes[-1]
                icc_target_vdf_info = VDFInfo(icc_vdf_challenge, ip_vdf_iters, header_block.reward_chain_block.infused_challenge_chain_ip_vdf.output)
                if not (icc_vdf_input is None or header_block.infused_challenge_chain_ip_proof.is_valid(constants, icc_vdf_input, header_block.reward_chain_block.infused_challenge_chain_ip_vdf, icc_target_vdf_info)):
                    return (
                     None, ValidationError(Err.INVALID_ICC_VDF, 'invalid icc proof'))
        else:
            if header_block.infused_challenge_chain_ip_proof is not None:
                return (None, ValidationError(Err.INVALID_ICC_VDF))
        if header_block.foliage.reward_block_hash != header_block.reward_chain_block.get_hash():
            return (None, ValidationError(Err.INVALID_REWARD_BLOCK_HASH))
        if (header_block.foliage.foliage_transaction_block_hash is not None) != header_block.reward_chain_block.is_transaction_block:
            return (None, ValidationError(Err.INVALID_FOLIAGE_BLOCK_PRESENCE))
        return (
         required_iters, None)