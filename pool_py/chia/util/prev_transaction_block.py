# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\prev_transaction_block.py
from typing import Tuple
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.util.ints import uint128

def get_prev_transaction_block(curr: BlockRecord, blocks: BlockchainInterface, total_iters_sp: uint128) -> Tuple[(bool, BlockRecord)]:
    prev_transaction_block = curr
    while not curr.is_transaction_block:
        curr = blocks.block_record(curr.prev_hash)

    if total_iters_sp > curr.total_iters:
        prev_transaction_block = curr
        is_transaction_block = True
    else:
        is_transaction_block = False
    return (is_transaction_block, prev_transaction_block)