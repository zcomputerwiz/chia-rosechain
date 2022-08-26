# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\protocols\protocol_message_types.py
from enum import Enum

class ProtocolMessageTypes(Enum):
    handshake = 2
    harvester_handshake = 4
    new_proof_of_space = 6
    request_signatures = 7
    respond_signatures = 8
    new_signage_point = 9
    declare_proof_of_space = 10
    request_signed_values = 11
    signed_values = 12
    farming_info = 13
    new_peak_timelord = 14
    new_unfinished_block_timelord = 15
    new_infusion_point_vdf = 16
    new_signage_point_vdf = 17
    new_end_of_sub_slot_vdf = 18
    request_compact_proof_of_time = 19
    respond_compact_proof_of_time = 20
    new_peak = 21
    new_transaction = 22
    request_transaction = 23
    respond_transaction = 24
    request_proof_of_weight = 25
    respond_proof_of_weight = 26
    request_block = 27
    respond_block = 28
    reject_block = 29
    request_blocks = 30
    respond_blocks = 31
    reject_blocks = 32
    new_unfinished_block = 33
    request_unfinished_block = 34
    respond_unfinished_block = 35
    new_signage_point_or_end_of_sub_slot = 36
    request_signage_point_or_end_of_sub_slot = 37
    respond_signage_point = 38
    respond_end_of_sub_slot = 39
    request_mempool_transactions = 40
    request_compact_vdf = 41
    respond_compact_vdf = 42
    new_compact_vdf = 43
    request_peers = 44
    respond_peers = 45
    request_puzzle_solution = 46
    respond_puzzle_solution = 47
    reject_puzzle_solution = 48
    send_transaction = 49
    transaction_ack = 50
    new_peak_wallet = 51
    request_block_header = 52
    respond_block_header = 53
    reject_header_request = 54
    request_removals = 55
    respond_removals = 56
    reject_removals_request = 57
    request_additions = 58
    respond_additions = 59
    reject_additions_request = 60
    request_header_blocks = 61
    reject_header_blocks = 62
    respond_header_blocks = 63
    request_peers_introducer = 64
    respond_peers_introducer = 65
    farm_new_block = 66
    new_signage_point_harvester = 67
    request_plots = 68
    respond_plots = 69