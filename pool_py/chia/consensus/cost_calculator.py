# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\consensus\cost_calculator.py
from dataclasses import dataclass
from typing import List, Optional
from chia.consensus.condition_costs import ConditionCost
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.name_puzzle_condition import NPC
from chia.util.ints import uint64, uint16
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class NPCResult(Streamable):
    error: Optional[uint16]
    npc_list: List[NPC]
    clvm_cost: uint64


def calculate_cost_of_program(program, npc_result, cost_per_byte):
    """
    This function calculates the total cost of either a block or a spendbundle
    """
    total_cost = 0
    total_cost += npc_result.clvm_cost
    npc_list = npc_result.npc_list
    for npc in npc_list:
        for condition, cvp_list in npc.condition_dict.items():
            if not condition is ConditionOpcode.AGG_SIG_UNSAFE or condition is ConditionOpcode.AGG_SIG_ME:
                total_cost += len(cvp_list) * ConditionCost.AGG_SIG.value
            else:
                if condition is ConditionOpcode.CREATE_COIN:
                    total_cost += len(cvp_list) * ConditionCost.CREATE_COIN.value
                else:
                    if condition is ConditionOpcode.ASSERT_SECONDS_ABSOLUTE:
                        total_cost += len(cvp_list) * ConditionCost.ASSERT_SECONDS_ABSOLUTE.value
                    else:
                        if condition is ConditionOpcode.ASSERT_SECONDS_RELATIVE:
                            total_cost += len(cvp_list) * ConditionCost.ASSERT_SECONDS_RELATIVE.value
                        else:
                            if condition is ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE:
                                total_cost += len(cvp_list) * ConditionCost.ASSERT_HEIGHT_ABSOLUTE.value
                            else:
                                if condition is ConditionOpcode.ASSERT_HEIGHT_RELATIVE:
                                    total_cost += len(cvp_list) * ConditionCost.ASSERT_HEIGHT_RELATIVE.value
                                else:
                                    if condition is ConditionOpcode.ASSERT_MY_COIN_ID:
                                        total_cost += len(cvp_list) * ConditionCost.ASSERT_MY_COIN_ID.value
                                    else:
                                        if condition is ConditionOpcode.ASSERT_MY_PARENT_ID:
                                            total_cost += len(cvp_list) * ConditionCost.ASSERT_MY_PARENT_ID.value
                                        else:
                                            if condition is ConditionOpcode.ASSERT_MY_PUZZLEHASH:
                                                total_cost += len(cvp_list) * ConditionCost.ASSERT_MY_PUZZLEHASH.value
                                            else:
                                                if condition is ConditionOpcode.ASSERT_MY_AMOUNT:
                                                    total_cost += len(cvp_list) * ConditionCost.ASSERT_MY_AMOUNT.value
                                                else:
                                                    if condition is ConditionOpcode.RESERVE_FEE:
                                                        total_cost += len(cvp_list) * ConditionCost.RESERVE_FEE.value
                                                    else:
                                                        if condition is ConditionOpcode.CREATE_COIN_ANNOUNCEMENT:
                                                            total_cost += len(cvp_list) * ConditionCost.CREATE_COIN_ANNOUNCEMENT.value
                                                        else:
                                                            if condition is ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT:
                                                                total_cost += len(cvp_list) * ConditionCost.ASSERT_COIN_ANNOUNCEMENT.value
                                                            else:
                                                                if condition is ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT:
                                                                    total_cost += len(cvp_list) * ConditionCost.CREATE_PUZZLE_ANNOUNCEMENT.value
            if condition is ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT:
                total_cost += len(cvp_list) * ConditionCost.ASSERT_PUZZLE_ANNOUNCEMENT.value
                continue

    total_cost += len(bytes(program)) * cost_per_byte
    return uint64(total_cost)