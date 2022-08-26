# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\server\rate_limits.py
import dataclasses, logging, time
from collections import Counter
from typing import Optional
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import Message
log = logging.getLogger(__name__)

@dataclasses.dataclass(frozen=True)
class RLSettings:
    frequency: int
    max_size: int
    max_total_size = None
    max_total_size: Optional[int]


DEFAULT_SETTINGS = RLSettings(100, 1048576, 104857600)
NON_TX_FREQ = 1000
NON_TX_MAX_TOTAL_SIZE = 104857600
rate_limits_tx = {ProtocolMessageTypes.new_transaction: RLSettings(5000, 100, 500000), 
 ProtocolMessageTypes.request_transaction: RLSettings(5000, 100, 500000), 
 ProtocolMessageTypes.respond_transaction: RLSettings(5000, 1048576, 20971520), 
 ProtocolMessageTypes.send_transaction: RLSettings(5000, 1048576), 
 ProtocolMessageTypes.transaction_ack: RLSettings(5000, 2048)}
rate_limits_other = {ProtocolMessageTypes.handshake: RLSettings(5, 10240, 51200), 
 ProtocolMessageTypes.harvester_handshake: RLSettings(5, 1048576), 
 ProtocolMessageTypes.new_signage_point_harvester: RLSettings(100, 1024), 
 ProtocolMessageTypes.new_proof_of_space: RLSettings(100, 2048), 
 ProtocolMessageTypes.request_signatures: RLSettings(100, 2048), 
 ProtocolMessageTypes.respond_signatures: RLSettings(100, 2048), 
 ProtocolMessageTypes.new_signage_point: RLSettings(200, 2048), 
 ProtocolMessageTypes.declare_proof_of_space: RLSettings(100, 10240), 
 ProtocolMessageTypes.request_signed_values: RLSettings(100, 512), 
 ProtocolMessageTypes.farming_info: RLSettings(100, 1024), 
 ProtocolMessageTypes.signed_values: RLSettings(100, 1024), 
 ProtocolMessageTypes.new_peak_timelord: RLSettings(100, 20480), 
 ProtocolMessageTypes.new_unfinished_block_timelord: RLSettings(100, 10240), 
 ProtocolMessageTypes.new_signage_point_vdf: RLSettings(100, 102400), 
 ProtocolMessageTypes.new_infusion_point_vdf: RLSettings(100, 102400), 
 ProtocolMessageTypes.new_end_of_sub_slot_vdf: RLSettings(100, 102400), 
 ProtocolMessageTypes.request_compact_proof_of_time: RLSettings(100, 10240), 
 ProtocolMessageTypes.respond_compact_proof_of_time: RLSettings(100, 102400), 
 ProtocolMessageTypes.new_peak: RLSettings(200, 512), 
 ProtocolMessageTypes.request_proof_of_weight: RLSettings(5, 100), 
 ProtocolMessageTypes.respond_proof_of_weight: RLSettings(5, 52428800, 104857600), 
 ProtocolMessageTypes.request_block: RLSettings(200, 100), 
 ProtocolMessageTypes.reject_block: RLSettings(200, 100), 
 ProtocolMessageTypes.request_blocks: RLSettings(100, 100), 
 ProtocolMessageTypes.respond_blocks: RLSettings(100, 52428800, 262144000), 
 ProtocolMessageTypes.reject_blocks: RLSettings(100, 100), 
 ProtocolMessageTypes.respond_block: RLSettings(200, 2097152, 20971520), 
 ProtocolMessageTypes.new_unfinished_block: RLSettings(200, 100), 
 ProtocolMessageTypes.request_unfinished_block: RLSettings(200, 100), 
 ProtocolMessageTypes.respond_unfinished_block: RLSettings(200, 2097152, 20971520), 
 ProtocolMessageTypes.new_signage_point_or_end_of_sub_slot: RLSettings(200, 200), 
 ProtocolMessageTypes.request_signage_point_or_end_of_sub_slot: RLSettings(200, 200), 
 ProtocolMessageTypes.respond_signage_point: RLSettings(200, 51200), 
 ProtocolMessageTypes.respond_end_of_sub_slot: RLSettings(100, 51200), 
 ProtocolMessageTypes.request_mempool_transactions: RLSettings(5, 1048576), 
 ProtocolMessageTypes.request_compact_vdf: RLSettings(200, 1024), 
 ProtocolMessageTypes.respond_compact_vdf: RLSettings(200, 102400), 
 ProtocolMessageTypes.new_compact_vdf: RLSettings(100, 1024), 
 ProtocolMessageTypes.request_peers: RLSettings(10, 100), 
 ProtocolMessageTypes.respond_peers: RLSettings(10, 1048576), 
 ProtocolMessageTypes.request_puzzle_solution: RLSettings(100, 100), 
 ProtocolMessageTypes.respond_puzzle_solution: RLSettings(100, 1048576), 
 ProtocolMessageTypes.reject_puzzle_solution: RLSettings(100, 100), 
 ProtocolMessageTypes.new_peak_wallet: RLSettings(200, 300), 
 ProtocolMessageTypes.request_block_header: RLSettings(500, 100), 
 ProtocolMessageTypes.respond_block_header: RLSettings(500, 512000), 
 ProtocolMessageTypes.reject_header_request: RLSettings(500, 100), 
 ProtocolMessageTypes.request_removals: RLSettings(500, 51200, 10485760), 
 ProtocolMessageTypes.respond_removals: RLSettings(500, 1048576, 10485760), 
 ProtocolMessageTypes.reject_removals_request: RLSettings(500, 100), 
 ProtocolMessageTypes.request_additions: RLSettings(500, 1048576, 10485760), 
 ProtocolMessageTypes.respond_additions: RLSettings(500, 1048576, 10485760), 
 ProtocolMessageTypes.reject_additions_request: RLSettings(500, 100), 
 ProtocolMessageTypes.request_header_blocks: RLSettings(500, 100), 
 ProtocolMessageTypes.reject_header_blocks: RLSettings(100, 100), 
 ProtocolMessageTypes.respond_header_blocks: RLSettings(500, 2097152, 104857600), 
 ProtocolMessageTypes.request_peers_introducer: RLSettings(100, 100), 
 ProtocolMessageTypes.respond_peers_introducer: RLSettings(100, 1048576), 
 ProtocolMessageTypes.farm_new_block: RLSettings(200, 200), 
 ProtocolMessageTypes.request_plots: RLSettings(10, 10485760), 
 ProtocolMessageTypes.respond_plots: RLSettings(10, 104857600)}

class RateLimiter:
    incoming: bool
    reset_seconds: int
    current_minute: int
    message_counts: Counter
    message_cumulative_sizes: Counter
    percentage_of_limit: int
    non_tx_message_counts = 0
    non_tx_message_counts: int
    non_tx_cumulative_size = 0
    non_tx_cumulative_size: int

    def __init__(self, incoming: bool, reset_seconds=60, percentage_of_limit=100):
        """
        The incoming parameter affects whether counters are incremented
        unconditionally or not. For incoming messages, the counters are always
        incremeneted. For outgoing messages, the counters are only incremented
        if they are allowed to be sent by the rate limiter, since we won't send
        the messages otherwise.
        """
        self.incoming = incoming
        self.reset_seconds = reset_seconds
        self.current_minute = time.time() // reset_seconds
        self.message_counts = Counter()
        self.message_cumulative_sizes = Counter()
        self.percentage_of_limit = percentage_of_limit
        self.non_tx_message_counts = 0
        self.non_tx_cumulative_size = 0

    def process_msg_and_check(self, message: Message) -> bool:
        """
        Returns True if message can be processed successfully, false if a rate limit is passed.
        """
        current_minute = int(time.time() // self.reset_seconds)
        if current_minute != self.current_minute:
            self.current_minute = current_minute
            self.message_counts = Counter()
            self.message_cumulative_sizes = Counter()
            self.non_tx_message_counts = 0
            self.non_tx_cumulative_size = 0
        try:
            message_type = ProtocolMessageTypes(message.type)
        except Exception as e:
            try:
                log.warning(f"Invalid message: {message.type}, {e}")
                return True
            finally:
                e = None
                del e

        new_message_counts = self.message_counts[message_type] + 1
        new_cumulative_size = self.message_cumulative_sizes[message_type] + len(message.data)
        new_non_tx_count = self.non_tx_message_counts
        new_non_tx_size = self.non_tx_cumulative_size
        proportion_of_limit = self.percentage_of_limit / 100
        ret = False
        try:
            limits = DEFAULT_SETTINGS
            if message_type in rate_limits_tx:
                limits = rate_limits_tx[message_type]
            else:
                if message_type in rate_limits_other:
                    limits = rate_limits_other[message_type]
                    new_non_tx_count = self.non_tx_message_counts + 1
                    new_non_tx_size = self.non_tx_cumulative_size + len(message.data)
                    if new_non_tx_count > NON_TX_FREQ * proportion_of_limit:
                        return False
                    if new_non_tx_size > NON_TX_MAX_TOTAL_SIZE * proportion_of_limit:
                        return False
                else:
                    log.warning(f"Message type {message_type} not found in rate limits")
            if limits.max_total_size is None:
                limits = dataclasses.replace(limits, max_total_size=(limits.frequency * limits.max_size))
            assert limits.max_total_size is not None
            if new_message_counts > limits.frequency * proportion_of_limit:
                return False
            if len(message.data) > limits.max_size:
                return False
            if new_cumulative_size > limits.max_total_size * proportion_of_limit:
                return False
            ret = True
            return True
        finally:
            if self.incoming or ret:
                self.message_counts[message_type] = new_message_counts
                self.message_cumulative_sizes[message_type] = new_cumulative_size
                self.non_tx_message_counts = new_non_tx_count
                self.non_tx_cumulative_size = new_non_tx_size