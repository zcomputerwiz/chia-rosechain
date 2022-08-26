# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\consensus\block_body_validation.py
import collections, logging
from typing import Dict, List, Optional, Set, Tuple, Union, Callable
from blspy import AugSchemeMPL, G1Element
from chiabip158 import PyBIP158
from clvm.casts import int_from_bytes
from chia.consensus.block_record import BlockRecord
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.block_root_validation import validate_block_merkle_roots
from chia.full_node.mempool_check_conditions import mempool_check_conditions_dict
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.coinbase import create_farmer_coin, create_pool_coin
from chia.consensus.constants import ConsensusConstants
from chia.consensus.cost_calculator import NPCResult, calculate_cost_of_program
from chia.consensus.find_fork_point import find_fork_point_in_chain
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator
from chia.types.name_puzzle_condition import NPC
from chia.types.unfinished_block import UnfinishedBlock
from chia.util.condition_tools import pkm_pairs_for_conditions_dict, coin_announcements_names_for_npc, puzzle_announcements_names_for_npc
from chia.util.errors import Err
from chia.util.generator_tools import additions_for_npc, tx_removals_and_additions
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64, uint128
log = logging.getLogger(__name__)

async def validate_block_body(constants: ConsensusConstants, blocks: BlockchainInterface, block_store: BlockStore, coin_store: CoinStore, peak: Optional[BlockRecord], block: Union[(FullBlock, UnfinishedBlock)], height: uint32, npc_result: Optional[NPCResult], fork_point_with_peak: Optional[uint32], get_block_generator: Callable) -> Tuple[(Optional[Err], Optional[NPCResult])]:
    """
    This assumes the header block has been completely validated.
    Validates the transactions and body of the block. Returns None for the first value if everything
    validates correctly, or an Err if something does not validate. For the second value, returns a CostResult
    only if validation succeeded, and there are transactions. In other cases it returns None. The NPC result is
    the result of running the generator with the previous generators refs. It is only present for transaction
    blocks which have spent coins.
    """
    if isinstance(block, FullBlock):
        assert height == block.height
        prev_transaction_block_height = uint32(0)
        if block.foliage.foliage_transaction_block_hash is None:
            if not block.foliage_transaction_block is not None:
                if block.transactions_info is not None or block.transactions_generator is not None:
                    return (
                     Err.NOT_BLOCK_BUT_HAS_DATA, None)
                prev_tb = blocks.block_record(block.prev_header_hash)
                while not prev_tb.is_transaction_block:
                    prev_tb = blocks.block_record(prev_tb.prev_hash)

                assert prev_tb.timestamp is not None
                if prev_tb.timestamp > constants.INITIAL_FREEZE_END_TIMESTAMP:
                    if len(block.transactions_generator_ref_list) > 0:
                        return (
                         Err.NOT_BLOCK_BUT_HAS_DATA, None)
                return (None, None)
        if block.foliage_transaction_block is None or block.transactions_info is None:
            return (Err.IS_TRANSACTION_BLOCK_BUT_NO_DATA, None)
        assert block.foliage_transaction_block is not None
        expected_reward_coins = set()
        if block.foliage_transaction_block.transactions_info_hash != std_hash(block.transactions_info):
            return (Err.INVALID_TRANSACTIONS_INFO_HASH, None)
        if block.foliage.foliage_transaction_block_hash != std_hash(block.foliage_transaction_block):
            return (Err.INVALID_FOLIAGE_BLOCK_HASH, None)
        if height > 0:
            prev_transaction_block = blocks.block_record(block.foliage_transaction_block.prev_transaction_block_hash)
            prev_transaction_block_height = prev_transaction_block.height
            assert prev_transaction_block.fees is not None
            pool_coin = create_pool_coin(prev_transaction_block_height, prev_transaction_block.pool_puzzle_hash, calculate_pool_reward(prev_transaction_block.height), constants.GENESIS_CHALLENGE)
            farmer_coin = create_farmer_coin(prev_transaction_block_height, prev_transaction_block.farmer_puzzle_hash, uint64(calculate_base_farmer_reward(prev_transaction_block.height) + prev_transaction_block.fees), constants.GENESIS_CHALLENGE)
            expected_reward_coins.add(pool_coin)
            expected_reward_coins.add(farmer_coin)
            if prev_transaction_block.height > 0:
                curr_b = blocks.block_record(prev_transaction_block.prev_hash)
                while not curr_b.is_transaction_block:
                    expected_reward_coins.add(create_pool_coin(curr_b.height, curr_b.pool_puzzle_hash, calculate_pool_reward(curr_b.height), constants.GENESIS_CHALLENGE))
                    expected_reward_coins.add(create_farmer_coin(curr_b.height, curr_b.farmer_puzzle_hash, calculate_base_farmer_reward(curr_b.height), constants.GENESIS_CHALLENGE))
                    curr_b = blocks.block_record(curr_b.prev_hash)

        if set(block.transactions_info.reward_claims_incorporated) != expected_reward_coins:
            return (Err.INVALID_REWARD_COINS, None)
        if block.foliage_transaction_block.timestamp > constants.INITIAL_FREEZE_END_TIMESTAMP:
            if len(block.transactions_info.reward_claims_incorporated) != len(expected_reward_coins):
                return (
                 Err.INVALID_REWARD_COINS, None)
        removals = []
        coinbase_additions = list(expected_reward_coins)
        additions = []
        coin_announcement_names = set()
        puzzle_announcement_names = set()
        npc_list = []
        removals_puzzle_dic = {}
        cost = uint64(0)
        if block.foliage_transaction_block.timestamp <= constants.INITIAL_FREEZE_END_TIMESTAMP:
            if block.transactions_generator is not None:
                return (
                 Err.INITIAL_TRANSACTION_FREEZE, None)
        if block.transactions_generator is not None:
            if std_hash(bytes(block.transactions_generator)) != block.transactions_info.generator_root:
                return (Err.INVALID_TRANSACTIONS_GENERATOR_HASH, None)
        else:
            if block.transactions_info.generator_root != bytes([0] * 32):
                return (Err.INVALID_TRANSACTIONS_GENERATOR_HASH, None)
        if block.transactions_generator_ref_list in (None, []):
            if block.transactions_info.generator_refs_root != bytes([1] * 32):
                return (Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT, None)
        else:
            if block.transactions_generator is None:
                return (Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT, None)
            generator_refs_hash = std_hash((b'').join([bytes(i) for i in block.transactions_generator_ref_list]))
            if block.transactions_info.generator_refs_root != generator_refs_hash:
                return (Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT, None)
            if len(block.transactions_generator_ref_list) > constants.MAX_GENERATOR_REF_LIST_SIZE:
                return (Err.TOO_MANY_GENERATOR_REFS, None)
            if any([index >= height for index in block.transactions_generator_ref_list]):
                return (Err.FUTURE_GENERATOR_REFS, None)
        if block.transactions_generator is not None:
            assert npc_result is not None
            cost = calculate_cost_of_program(block.transactions_generator, npc_result, constants.COST_PER_BYTE)
            npc_list = npc_result.npc_list
            log.debug(f"Cost: {cost} max: {constants.MAX_BLOCK_COST_CLVM} percent full: {round(100 * (cost / constants.MAX_BLOCK_COST_CLVM), 2)}%")
            if cost > constants.MAX_BLOCK_COST_CLVM:
                return (Err.BLOCK_COST_EXCEEDS_MAX, None)
            if npc_result.error is not None:
                return (Err(npc_result.error), None)
            for npc in npc_list:
                removals.append(npc.coin_name)
                removals_puzzle_dic[npc.coin_name] = npc.puzzle_hash

            additions = additions_for_npc(npc_list)
            coin_announcement_names = coin_announcements_names_for_npc(npc_list)
            puzzle_announcement_names = puzzle_announcements_names_for_npc(npc_list)
        else:
            assert npc_result is None
        if block.transactions_info.cost != cost:
            return (Err.INVALID_BLOCK_COST, None)
        additions_dic = {}
        for coin in additions + coinbase_additions:
            additions_dic[coin.name()] = coin
            if coin.amount < 0:
                return (Err.COIN_AMOUNT_NEGATIVE, None)
            if coin.amount > constants.MAX_COIN_AMOUNT:
                return (Err.COIN_AMOUNT_EXCEEDS_MAXIMUM, None)

        root_error = validate_block_merkle_roots(block.foliage_transaction_block.additions_root, block.foliage_transaction_block.removals_root, additions + coinbase_additions, removals)
        if root_error:
            return (root_error, None)
        byte_array_tx = []
        for coin in additions + coinbase_additions:
            byte_array_tx.append(bytearray(coin.puzzle_hash))

        for coin_name in removals:
            byte_array_tx.append(bytearray(coin_name))

        bip158 = PyBIP158(byte_array_tx)
        encoded_filter = bytes(bip158.GetEncoded())
        filter_hash = std_hash(encoded_filter)
        if filter_hash != block.foliage_transaction_block.filter_hash:
            return (Err.INVALID_TRANSACTIONS_FILTER_HASH, None)
        addition_counter = collections.Counter((_.name() for _ in additions + coinbase_additions))
        for k, v in addition_counter.items():
            if v > 1:
                return (Err.DUPLICATE_OUTPUT, None)

        removal_counter = collections.Counter(removals)
        for k, v in removal_counter.items():
            if v > 1:
                return (Err.DOUBLE_SPEND, None)

        if peak is None or height == 0:
            fork_h = -1
        else:
            if fork_point_with_peak is not None:
                fork_h = fork_point_with_peak
            else:
                fork_h = find_fork_point_in_chain(blocks, peak, blocks.block_record(block.prev_header_hash))
        additions_since_fork = {}
        removals_since_fork = set()
        if height > 0:
            prev_block = await block_store.get_full_block(block.prev_header_hash)
            reorg_blocks = {}
            curr = prev_block
            assert curr is not None
            while curr.height > fork_h:
                if curr.height == 0:
                    break
                else:
                    curr = await block_store.get_full_block(curr.prev_header_hash)
                    assert curr is not None
                    reorg_blocks[curr.height] = curr

            if fork_h != -1:
                assert len(reorg_blocks) == height - fork_h - 1
                curr = prev_block
                assert curr is not None
                while curr.height > fork_h:
                    if curr.transactions_generator is not None:
                        curr_block_generator = await get_block_generator(curr)
                        if not (curr_block_generator is not None and curr.transactions_info is not None):
                            raise AssertionError
                        curr_npc_result = get_name_puzzle_conditions(curr_block_generator,
                          (min(constants.MAX_BLOCK_COST_CLVM, curr.transactions_info.cost)),
                          cost_per_byte=(constants.COST_PER_BYTE),
                          safe_mode=False)
                        removals_in_curr, additions_in_curr = tx_removals_and_additions(curr_npc_result.npc_list)
                    else:
                        removals_in_curr = []
                        additions_in_curr = []
                    for c_name in removals_in_curr:
                        if not c_name not in removals_since_fork:
                            raise AssertionError
                        else:
                            removals_since_fork.add(c_name)

                    for c in additions_in_curr:
                        if not c.name() not in additions_since_fork:
                            raise AssertionError
                        else:
                            assert curr.foliage_transaction_block is not None
                            additions_since_fork[c.name()] = (c, curr.height, curr.foliage_transaction_block.timestamp)

                    for coinbase_coin in curr.get_included_reward_coins():
                        if not coinbase_coin.name() not in additions_since_fork:
                            raise AssertionError
                        else:
                            assert curr.foliage_transaction_block is not None
                            additions_since_fork[coinbase_coin.name()] = (
                             coinbase_coin,
                             curr.height,
                             curr.foliage_transaction_block.timestamp)

                    if curr.height == 0:
                        break
                    else:
                        curr = reorg_blocks[curr.height - 1]
                    if not curr is not None:
                        raise AssertionError

        removal_coin_records = {}
        for rem in removals:
            if rem in additions_dic:
                rem_coin = additions_dic[rem]
                new_unspent = CoinRecord(rem_coin, height, height, True, False, block.foliage_transaction_block.timestamp)
                removal_coin_records[new_unspent.name] = new_unspent
            else:
                unspent = await coin_store.get_coin_record(rem)
                if unspent is not None and unspent.confirmed_block_index <= fork_h:
                    if unspent.spent == 1:
                        if unspent.spent_block_index <= fork_h:
                            return (
                             Err.DOUBLE_SPEND, None)
                    removal_coin_records[unspent.name] = unspent
                else:
                    if rem not in additions_since_fork:
                        log.error(f"Err.UNKNOWN_UNSPENT: COIN ID: {rem} NPC RESULT: {npc_result}")
                        return (
                         Err.UNKNOWN_UNSPENT, None)
                    new_coin, confirmed_height, confirmed_timestamp = additions_since_fork[rem]
                    new_coin_record = CoinRecord(new_coin, confirmed_height, uint32(0), False, False, confirmed_timestamp)
                    removal_coin_records[new_coin_record.name] = new_coin_record
            if rem in removals_since_fork:
                return (
                 Err.DOUBLE_SPEND_IN_FORK, None)

        removed = 0
        for unspent in removal_coin_records.values():
            removed += unspent.coin.amount

        added = 0
        for coin in additions:
            added += coin.amount

        if removed < added:
            return (Err.MINTING_COIN, None)
        fees = removed - added
        assert fees >= 0
        assert_fee_sum = uint128(0)
        for npc in npc_list:
            if ConditionOpcode.RESERVE_FEE in npc.condition_dict:
                fee_list = npc.condition_dict[ConditionOpcode.RESERVE_FEE]
                for cvp in fee_list:
                    fee = int_from_bytes(cvp.vars[0])
                    if fee < 0:
                        return (Err.RESERVE_FEE_CONDITION_FAILED, None)
                    else:
                        assert_fee_sum = uint128(assert_fee_sum + fee)

        if fees < assert_fee_sum:
            return (Err.RESERVE_FEE_CONDITION_FAILED, None)
        if fees + calculate_base_farmer_reward(height) > constants.MAX_COIN_AMOUNT:
            return (Err.COIN_AMOUNT_EXCEEDS_MAXIMUM, None)
        if block.transactions_info.fees != fees:
            return (Err.INVALID_BLOCK_FEE_AMOUNT, None)
        for unspent in removal_coin_records.values():
            if unspent.coin.puzzle_hash != removals_puzzle_dic[unspent.name]:
                return (Err.WRONG_PUZZLE_HASH, None)

        pairs_pks = []
        pairs_msgs = []
        for npc in npc_list:
            if not height is not None:
                raise AssertionError
            else:
                unspent = removal_coin_records[npc.coin_name]
                error = mempool_check_conditions_dict(unspent, coin_announcement_names, puzzle_announcement_names, npc.condition_dict, prev_transaction_block_height, block.foliage_transaction_block.timestamp)
                if error:
                    return (error, None)
                for pk, m in pkm_pairs_for_conditions_dict(npc.condition_dict, npc.coin_name, constants.AGG_SIG_ME_ADDITIONAL_DATA):
                    pairs_pks.append(pk)
                    pairs_msgs.append(m)

        if not block.transactions_info.aggregated_signature:
            return (Err.BAD_AGGREGATE_SIGNATURE, None)
        if not AugSchemeMPL.aggregate_verify(pairs_pks, pairs_msgs, block.transactions_info.aggregated_signature):
            return (Err.BAD_AGGREGATE_SIGNATURE, None)
        return (
         None, npc_result)