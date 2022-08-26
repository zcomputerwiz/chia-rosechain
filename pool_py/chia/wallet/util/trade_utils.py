# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\util\trade_utils.py
from typing import Dict, Optional, Tuple
from chia.types.blockchain_format.program import Program, INFINITE_COST
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import conditions_dict_for_solution
from chia.wallet.cc_wallet import cc_utils
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.trade_status import TradeStatus

def trade_status_ui_string(status: TradeStatus):
    if status is TradeStatus.PENDING_CONFIRM:
        return 'Pending Confirmation'
    if status is TradeStatus.CANCELED:
        return 'Canceled'
    if status is TradeStatus.CONFIRMED:
        return 'Confirmed'
    if status is TradeStatus.PENDING_CANCEL:
        return 'Pending Cancellation'
    if status is TradeStatus.FAILED:
        return 'Failed'
    if status is TradeStatus.PENDING_ACCEPT:
        return 'Pending'


def trade_record_to_dict(record: TradeRecord) -> Dict:
    """Convenience function to return only part of trade record we care about and show correct status to the ui"""
    result = {}
    result['trade_id'] = record.trade_id.hex()
    result['sent'] = record.sent
    result['my_offer'] = record.my_offer
    result['created_at_time'] = record.created_at_time
    result['accepted_at_time'] = record.accepted_at_time
    result['confirmed_at_index'] = record.confirmed_at_index
    result['status'] = trade_status_ui_string(TradeStatus(record.status))
    success, offer_dict, error = get_discrepancies_for_spend_bundle(record.spend_bundle)
    if success is False or offer_dict is None:
        raise ValueError(error)
    result['offer_dict'] = offer_dict
    return result


def get_output_discrepancy_for_puzzle_and_solution(coin, puzzle, solution):
    discrepancy = coin.amount - get_output_amount_for_puzzle_and_solution(puzzle, solution)
    return discrepancy


def get_output_amount_for_puzzle_and_solution(puzzle: Program, solution: Program) -> int:
    error, conditions, cost = conditions_dict_for_solution(puzzle, solution, INFINITE_COST)
    total = 0
    if conditions:
        for _ in conditions.get(ConditionOpcode.CREATE_COIN, []):
            total += Program.to(_.vars[1]).as_int()

    return total


def get_discrepancies_for_spend_bundle(trade_offer: SpendBundle) -> Tuple[(bool, Optional[Dict], Optional[Exception])]:
    try:
        cc_discrepancies = dict()
        for coinsol in trade_offer.coin_spends:
            puzzle = Program.from_bytes(bytes(coinsol.puzzle_reveal))
            solution = Program.from_bytes(bytes(coinsol.solution))
            r = cc_utils.uncurry_cc(puzzle)
            if r:
                mod_hash, genesis_checker, inner_puzzle = r
                innersol = solution.first()
                total = get_output_amount_for_puzzle_and_solution(inner_puzzle, innersol)
                colour = bytes(genesis_checker).hex()
                if colour in cc_discrepancies:
                    cc_discrepancies[colour] += coinsol.coin.amount - total
                else:
                    cc_discrepancies[colour] = coinsol.coin.amount - total
            else:
                coin_amount = coinsol.coin.amount
                out_amount = get_output_amount_for_puzzle_and_solution(puzzle, solution)
                diff = coin_amount - out_amount
                if 'chia' in cc_discrepancies:
                    cc_discrepancies['chia'] = cc_discrepancies['chia'] + diff
                else:
                    cc_discrepancies['chia'] = diff

        return (
         True, cc_discrepancies, None)
    except Exception as e:
        try:
            return (
             False, None, e)
        finally:
            e = None
            del e