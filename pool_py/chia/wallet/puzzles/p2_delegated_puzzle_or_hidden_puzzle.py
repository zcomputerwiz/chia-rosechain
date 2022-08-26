# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\puzzles\p2_delegated_puzzle_or_hidden_puzzle.py
__doc__ = '\nPay to delegated puzzle or hidden puzzle\n\nIn this puzzle program, the solution must choose either a hidden puzzle or a\ndelegated puzzle on a given public key.\n\nThe given public key is morphed by adding an offset from the hash of the hidden puzzle\nand itself, giving a new so-called "synthetic" public key which has the hidden puzzle\nhidden inside of it.\n\nIf the hidden puzzle path is taken, the hidden puzzle and original public key will be revealed\nwhich proves that it was hidden there in the first place.\n\nThis roughly corresponds to bitcoin\'s taproot.\n'
import hashlib
from typing import Union
from blspy import G1Element, PrivateKey
from clvm.casts import int_from_bytes
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from .load_clvm import load_clvm
from .p2_conditions import puzzle_for_conditions
DEFAULT_HIDDEN_PUZZLE = Program.from_bytes(bytes.fromhex('ff0980'))
DEFAULT_HIDDEN_PUZZLE_HASH = DEFAULT_HIDDEN_PUZZLE.get_tree_hash()
MOD = load_clvm('p2_delegated_puzzle_or_hidden_puzzle.clvm')
SYNTHETIC_MOD = load_clvm('calculate_synthetic_public_key.clvm')
PublicKeyProgram = Union[(bytes, Program)]
GROUP_ORDER = 52435875175126190479447740508185965837690552500527637822603658699938581184513

def calculate_synthetic_offset(public_key: G1Element, hidden_puzzle_hash: bytes32) -> int:
    blob = hashlib.sha256(bytes(public_key) + hidden_puzzle_hash).digest()
    offset = int_from_bytes(blob)
    offset %= GROUP_ORDER
    return offset


def calculate_synthetic_public_key(public_key: G1Element, hidden_puzzle_hash: bytes32) -> G1Element:
    r = SYNTHETIC_MOD.run([bytes(public_key), hidden_puzzle_hash])
    return G1Element.from_bytes(r.as_atom())


def calculate_synthetic_secret_key(secret_key: PrivateKey, hidden_puzzle_hash: bytes32) -> PrivateKey:
    secret_exponent = int.from_bytes(bytes(secret_key), 'big')
    public_key = secret_key.get_g1()
    synthetic_offset = calculate_synthetic_offset(public_key, hidden_puzzle_hash)
    synthetic_secret_exponent = (secret_exponent + synthetic_offset) % GROUP_ORDER
    blob = synthetic_secret_exponent.to_bytes(32, 'big')
    synthetic_secret_key = PrivateKey.from_bytes(blob)
    return synthetic_secret_key


def puzzle_for_synthetic_public_key(synthetic_public_key: G1Element) -> Program:
    return MOD.curry(bytes(synthetic_public_key))


def puzzle_for_public_key_and_hidden_puzzle_hash(public_key: G1Element, hidden_puzzle_hash: bytes32) -> Program:
    synthetic_public_key = calculate_synthetic_public_key(public_key, hidden_puzzle_hash)
    return puzzle_for_synthetic_public_key(synthetic_public_key)


def puzzle_for_public_key_and_hidden_puzzle(public_key: G1Element, hidden_puzzle: Program) -> Program:
    return puzzle_for_public_key_and_hidden_puzzle_hash(public_key, hidden_puzzle.get_tree_hash())


def puzzle_for_pk(public_key: G1Element) -> Program:
    return puzzle_for_public_key_and_hidden_puzzle_hash(public_key, DEFAULT_HIDDEN_PUZZLE_HASH)


def solution_for_delegated_puzzle(delegated_puzzle: Program, solution: Program) -> Program:
    return Program.to([[], delegated_puzzle, solution])


def solution_for_hidden_puzzle(hidden_public_key, hidden_puzzle, solution_to_hidden_puzzle):
    return Program.to([hidden_public_key, hidden_puzzle, solution_to_hidden_puzzle])


def solution_for_conditions(conditions) -> Program:
    delegated_puzzle = puzzle_for_conditions(conditions)
    return solution_for_delegated_puzzle(delegated_puzzle, Program.to(0))