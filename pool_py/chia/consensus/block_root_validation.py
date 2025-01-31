# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\consensus\block_root_validation.py
from typing import Dict, List, Optional
from chia.types.blockchain_format.coin import Coin, hash_coin_list
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.errors import Err
from chia.util.merkle_set import MerkleSet

def validate_block_merkle_roots(block_additions_root: bytes32, block_removals_root: bytes32, tx_additions: List[Coin]=None, tx_removals: List[bytes32]=None) -> Optional[Err]:
    if tx_removals is None:
        tx_removals = []
    if tx_additions is None:
        tx_additions = []
    removal_merkle_set = MerkleSet()
    addition_merkle_set = MerkleSet()
    for coin_name in tx_removals:
        removal_merkle_set.add_already_hashed(coin_name)

    puzzlehash_coins_map = {}
    for coin in tx_additions:
        if coin.puzzle_hash in puzzlehash_coins_map:
            puzzlehash_coins_map[coin.puzzle_hash].append(coin)
        else:
            puzzlehash_coins_map[coin.puzzle_hash] = [
             coin]

    for puzzle, coins in puzzlehash_coins_map.items():
        addition_merkle_set.add_already_hashed(puzzle)
        addition_merkle_set.add_already_hashed(hash_coin_list(coins))

    additions_root = addition_merkle_set.get_root()
    removals_root = removal_merkle_set.get_root()
    if block_additions_root != additions_root:
        return Err.BAD_ADDITION_ROOT
    if block_removals_root != removals_root:
        return Err.BAD_REMOVAL_ROOT