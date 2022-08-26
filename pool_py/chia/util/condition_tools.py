# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\condition_tools.py
from typing import Dict, List, Optional, Tuple, Set
from blspy import G1Element
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.util.clvm import int_from_bytes
from chia.util.errors import ConsensusError, Err
from chia.util.ints import uint64

def parse_sexp_to_condition(sexp: Program) -> Tuple[(Optional[Err], Optional[ConditionWithArgs])]:
    """
    Takes a ChiaLisp sexp and returns a ConditionWithArgs.
    If it fails, returns an Error
    """
    as_atoms = sexp.as_atom_list()
    if len(as_atoms) < 1:
        return (Err.INVALID_CONDITION, None)
    opcode = as_atoms[0]
    try:
        opcode = ConditionOpcode(opcode)
    except ValueError:
        opcode = ConditionOpcode.UNKNOWN

    return (None, ConditionWithArgs(opcode, as_atoms[1:]))


def parse_sexp_to_conditions(sexp: Program) -> Tuple[(Optional[Err], Optional[List[ConditionWithArgs]])]:
    """
    Takes a ChiaLisp sexp (list) and returns the list of ConditionWithArgss
    If it fails, returns as Error
    """
    results = []
    try:
        for _ in sexp.as_iter():
            error, cvp = parse_sexp_to_condition(_)
            if error:
                return (error, None)
            else:
                results.append(cvp)

    except ConsensusError:
        return (
         Err.INVALID_CONDITION, None)
    else:
        return (
         None, results)


def conditions_by_opcode(conditions: List[ConditionWithArgs]) -> Dict[(ConditionOpcode, List[ConditionWithArgs])]:
    """
    Takes a list of ConditionWithArgss(CVP) and return dictionary of CVPs keyed of their opcode
    """
    d = {}
    for cvp in conditions:
        if cvp.opcode not in d:
            d[cvp.opcode] = list()
        else:
            d[cvp.opcode].append(cvp)

    return d


def pkm_pairs_for_conditions_dict(conditions_dict: Dict[(ConditionOpcode, List[ConditionWithArgs])], coin_name: bytes32, additional_data: bytes) -> List[Tuple[(G1Element, bytes)]]:
    assert coin_name is not None
    ret = []
    for cwa in conditions_dict.get(ConditionOpcode.AGG_SIG_UNSAFE, []):
        if not len(cwa.vars) == 2:
            raise AssertionError
        else:
            if not (len(cwa.vars[0]) == 48 and len(cwa.vars[1]) <= 1024):
                raise AssertionError
            if not (cwa.vars[0] is not None and cwa.vars[1] is not None):
                raise AssertionError
            ret.append((G1Element.from_bytes(cwa.vars[0]), cwa.vars[1]))

    for cwa in conditions_dict.get(ConditionOpcode.AGG_SIG_ME, []):
        if not len(cwa.vars) == 2:
            raise AssertionError
        else:
            if not (len(cwa.vars[0]) == 48 and len(cwa.vars[1]) <= 1024):
                raise AssertionError
            if not (cwa.vars[0] is not None and cwa.vars[1] is not None):
                raise AssertionError
            ret.append((G1Element.from_bytes(cwa.vars[0]), cwa.vars[1] + coin_name + additional_data))

    return ret


def created_outputs_for_conditions_dict(conditions_dict: Dict[(ConditionOpcode, List[ConditionWithArgs])], input_coin_name: bytes32) -> List[Coin]:
    output_coins = []
    for cvp in conditions_dict.get(ConditionOpcode.CREATE_COIN, []):
        puzzle_hash, amount_bin = cvp.vars[0], cvp.vars[1]
        amount = int_from_bytes(amount_bin)
        coin = Coin(input_coin_name, puzzle_hash, uint64(amount))
        output_coins.append(coin)

    return output_coins


def coin_announcements_for_conditions_dict(conditions_dict: Dict[(ConditionOpcode, List[ConditionWithArgs])], input_coin: Coin) -> Set[Announcement]:
    output_announcements = set()
    for cvp in conditions_dict.get(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, []):
        message = cvp.vars[0]
        if not len(message) <= 1024:
            raise AssertionError
        else:
            announcement = Announcement(input_coin.name(), message)
            output_announcements.add(announcement)

    return output_announcements


def puzzle_announcements_for_conditions_dict(conditions_dict: Dict[(ConditionOpcode, List[ConditionWithArgs])], input_coin: Coin) -> Set[Announcement]:
    output_announcements = set()
    for cvp in conditions_dict.get(ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, []):
        message = cvp.vars[0]
        if not len(message) <= 1024:
            raise AssertionError
        else:
            announcement = Announcement(input_coin.puzzle_hash, message)
            output_announcements.add(announcement)

    return output_announcements


def coin_announcements_names_for_npc(npc_list) -> Set[bytes32]:
    output_announcements = set()
    for npc in npc_list:
        for condition, cvp_list in npc.conditions:
            if condition == ConditionOpcode.CREATE_COIN_ANNOUNCEMENT:
                for cvp in cvp_list:
                    message = cvp.vars[0]
                    if not len(message) <= 1024:
                        raise AssertionError
                    else:
                        announcement = Announcement(npc.coin_name, message)
                        output_announcements.add(announcement.name())

    return output_announcements


def puzzle_announcements_names_for_npc(npc_list) -> Set[bytes32]:
    output_announcements = set()
    for npc in npc_list:
        for condition, cvp_list in npc.conditions:
            if condition == ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT:
                for cvp in cvp_list:
                    message = cvp.vars[0]
                    if not len(message) <= 1024:
                        raise AssertionError
                    else:
                        announcement = Announcement(npc.puzzle_hash, message)
                        output_announcements.add(announcement.name())

    return output_announcements


def coin_announcement_names_for_conditions_dict(conditions_dict: Dict[(ConditionOpcode, List[ConditionWithArgs])], input_coin: Coin) -> List[bytes32]:
    output = [an.name() for an in coin_announcements_for_conditions_dict(conditions_dict, input_coin)]
    return output


def puzzle_announcement_names_for_conditions_dict(conditions_dict: Dict[(ConditionOpcode, List[ConditionWithArgs])], input_coin: Coin) -> List[bytes32]:
    output = [an.name() for an in puzzle_announcements_for_conditions_dict(conditions_dict, input_coin)]
    return output


def conditions_dict_for_solution(puzzle_reveal: SerializedProgram, solution: SerializedProgram, max_cost: int) -> Tuple[(Optional[Err], Optional[Dict[(ConditionOpcode, List[ConditionWithArgs])]], uint64)]:
    error, result, cost = conditions_for_solution(puzzle_reveal, solution, max_cost)
    if error or result is None:
        return (error, None, uint64(0))
    return (None, conditions_by_opcode(result), cost)


def conditions_for_solution(puzzle_reveal: SerializedProgram, solution: SerializedProgram, max_cost: int) -> Tuple[(Optional[Err], Optional[List[ConditionWithArgs]], uint64)]:
    try:
        cost, r = puzzle_reveal.run_with_cost(max_cost, solution)
        error, result = parse_sexp_to_conditions(r)
        return (
         error, result, uint64(cost))
    except Program.EvalError:
        return (
         Err.SEXP_ERROR, None, uint64(0))