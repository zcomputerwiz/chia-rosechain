# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\spend_bundle.py
import dataclasses, warnings
from dataclasses import dataclass
from typing import List
from blspy import AugSchemeMPL, G2Element
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.streamable import Streamable, dataclass_from_dict, recurse_jsonify, streamable
import chia.wallet.util.debug_spend_bundle as debug_spend_bundle
from .coin_spend import CoinSpend

@dataclass(frozen=True)
@streamable
class SpendBundle(Streamable):
    __doc__ = '\n    This is a list of coins being spent along with their solution programs, and a single\n    aggregated signature. This is the object that most closely corresponds to a bitcoin\n    transaction (although because of non-interactive signature aggregation, the boundaries\n    between transactions are more flexible than in bitcoin).\n    '
    coin_spends: List[CoinSpend]
    aggregated_signature: G2Element

    @property
    def coin_solutions(self):
        return self.coin_spends

    @classmethod
    def aggregate(cls, spend_bundles) -> 'SpendBundle':
        coin_spends = []
        sigs = []
        for bundle in spend_bundles:
            coin_spends += bundle.coin_spends
            sigs.append(bundle.aggregated_signature)

        aggregated_signature = AugSchemeMPL.aggregate(sigs)
        return cls(coin_spends, aggregated_signature)

    def additions(self) -> List[Coin]:
        items = []
        for coin_spend in self.coin_spends:
            items.extend(coin_spend.additions())

        return items

    def removals(self) -> List[Coin]:
        """This should be used only by wallet"""
        return [_.coin for _ in self.coin_spends]

    def fees(self) -> int:
        """Unsafe to use for fees validation!!!"""
        amount_in = sum((_.amount for _ in self.removals()))
        amount_out = sum((_.amount for _ in self.additions()))
        return amount_in - amount_out

    def name(self) -> bytes32:
        return self.get_hash()

    def debug(self, agg_sig_additional_data=bytes([3] * 32)):
        debug_spend_bundle(self, agg_sig_additional_data)

    def not_ephemeral_additions(self):
        all_removals = self.removals()
        all_additions = self.additions()
        result = []
        for add in all_additions:
            if add in all_removals:
                continue
            else:
                result.append(add)

        return result

    @classmethod
    def from_json_dict(cls, json_dict):
        if 'coin_solutions' in json_dict:
            if 'coin_spends' not in json_dict:
                json_dict = dict(aggregated_signature=(json_dict['aggregated_signature']),
                  coin_spends=(json_dict['coin_solutions']))
                warnings.warn('`coin_solutions` is now `coin_spends` in `SpendBundle.from_json_dict`')
            else:
                raise ValueError('JSON contains both `coin_solutions` and `coin_spends`, just use `coin_spends`')
        return dataclass_from_dict(cls, json_dict)

    def to_json_dict(self, include_legacy_keys: bool=True, exclude_modern_keys: bool=True):
        if include_legacy_keys is False:
            if exclude_modern_keys is True:
                raise ValueError('`coin_spends` not included in legacy or modern outputs')
        d = dataclasses.asdict(self)
        if include_legacy_keys:
            d['coin_solutions'] = d['coin_spends']
        if exclude_modern_keys:
            del d['coin_spends']
        return recurse_jsonify(d)