# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\puzzles\p2_conditions.py
__doc__ = '\nPay to conditions\n\nIn this puzzle program, the solution is ignored. The reveal of the puzzle\nreturns a fixed list of conditions. This roughly corresponds to OP_SECURETHEBAG\nin bitcoin.\n\nThis is a pretty useless most of the time. But some (most?) solutions\nrequire a delegated puzzle program, so in those cases, this is just what\nthe doctor ordered.\n'
from chia.types.blockchain_format.program import Program
from .load_clvm import load_clvm
MOD = load_clvm('p2_conditions.clvm')

def puzzle_for_conditions(conditions) -> Program:
    return MOD.run([conditions])


def solution_for_conditions(conditions) -> Program:
    return Program.to([puzzle_for_conditions(conditions), 0])