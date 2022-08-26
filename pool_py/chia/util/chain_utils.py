# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\chain_utils.py
from typing import List
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.condition_tools import conditions_dict_for_solution, created_outputs_for_conditions_dict

def additions_for_solution(coin_name: bytes32, puzzle_reveal: SerializedProgram, solution: SerializedProgram, max_cost: int) -> List[Coin]:
    """
    Checks the conditions created by CoinSpend and returns the list of all coins created
    """
    err, dic, cost = conditions_dict_for_solution(puzzle_reveal, solution, max_cost)
    if err or dic is None:
        return []
    return created_outputs_for_conditions_dict(dic, coin_name)