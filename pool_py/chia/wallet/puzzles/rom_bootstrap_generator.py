# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\puzzles\rom_bootstrap_generator.py
from chia.types.blockchain_format.program import SerializedProgram
from .load_clvm import load_clvm
MOD = SerializedProgram.from_bytes(load_clvm('rom_bootstrap_generator.clvm').as_bin())

def get_generator():
    return MOD