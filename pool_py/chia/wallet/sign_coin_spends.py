# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\sign_coin_spends.py
import inspect
from typing import List, Any
import blspy
from blspy import AugSchemeMPL
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict

async def sign_coin_spends(coin_spends: List[CoinSpend], secret_key_for_public_key_f: Any, additional_data: bytes, max_cost: int) -> SpendBundle:
    signatures = []
    pk_list = []
    msg_list = []
    for coin_spend in coin_spends:
        err, conditions_dict, cost = conditions_dict_for_solution(coin_spend.puzzle_reveal, coin_spend.solution, max_cost)
        if err or conditions_dict is None:
            error_msg = f"Sign transaction failed, con:{conditions_dict}, error: {err}"
            raise ValueError(error_msg)
        else:
            for pk, msg in pkm_pairs_for_conditions_dict(conditions_dict, bytes(coin_spend.coin.name()), additional_data):
                pk_list.append(pk)
                msg_list.append(msg)
                if inspect.iscoroutinefunction(secret_key_for_public_key_f):
                    secret_key = await secret_key_for_public_key_f(pk)
                else:
                    secret_key = secret_key_for_public_key_f(pk)
                if secret_key is None:
                    e_msg = f"no secret key for {pk}"
                    raise ValueError(e_msg)
                else:
                    assert bytes(secret_key.get_g1()) == bytes(pk)
                    signature = AugSchemeMPL.sign(secret_key, msg)
                    assert AugSchemeMPL.verify(pk, msg, signature)
                    signatures.append(signature)

    aggsig = AugSchemeMPL.aggregate(signatures)
    assert AugSchemeMPL.aggregate_verify(pk_list, msg_list, aggsig)
    return SpendBundle(coin_spends, aggsig)