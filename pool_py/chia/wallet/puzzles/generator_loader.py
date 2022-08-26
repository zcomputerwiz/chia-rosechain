# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\puzzles\generator_loader.py
from chia.wallet.puzzles.load_clvm import load_serialized_clvm
GENERATOR_FOR_SINGLE_COIN_MOD = load_serialized_clvm('generator_for_single_coin.clvm', package_or_requirement=__name__)