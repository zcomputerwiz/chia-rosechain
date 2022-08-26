# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\wallet_node.py
import asyncio, json, logging, socket, time, traceback
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple, Union, Any
from blspy import PrivateKey
from chia.consensus.block_record import BlockRecord
from chia.consensus.constants import ConsensusConstants
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.pools.pool_puzzles import SINGLETON_LAUNCHER_HASH
from chia.protocols import wallet_protocol
from chia.protocols.full_node_protocol import RequestProofOfWeight, RespondProofOfWeight
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.wallet_protocol import RejectAdditionsRequest, RejectRemovalsRequest, RequestAdditions, RequestHeaderBlocks, RespondAdditions, RespondBlockHeader, RespondHeaderBlocks, RespondRemovals
from chia.server.node_discovery import WalletPeers
from chia.server.outbound_message import Message, NodeType, make_msg
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin, hash_coin_list
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.header_block import HeaderBlock
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.peer_info import PeerInfo
from chia.util.byte_types import hexstr_to_bytes
from chia.util.errors import Err, ValidationError
from chia.util.ints import uint32, uint128
from chia.util.keychain import Keychain
from chia.util.lru_cache import LRUCache
from chia.util.merkle_set import MerkleSet, confirm_included_already_hashed, confirm_not_included_already_hashed
from chia.util.path import mkdir, path_from_root
from chia.wallet.block_record import HeaderBlockRecord
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.settings.settings_objects import BackupInitialized
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.backup_utils import open_backup_file
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_action import WalletAction
from chia.wallet.wallet_blockchain import ReceiveBlockResult
from chia.wallet.wallet_state_manager import WalletStateManager
from chia.util.profiler import profile_task

class WalletNode:
    key_config: Dict
    config: Dict
    constants: ConsensusConstants
    server: Optional[ChiaServer]
    log: logging.Logger
    wallet_peers: WalletPeers
    wallet_state_manager: Optional[WalletStateManager]
    short_sync_threshold: int
    _shut_down: bool
    root_path: Path
    state_changed_callback: Optional[Callable]
    syncing: bool
    full_node_peer: Optional[PeerInfo]
    peer_task: Optional[asyncio.Task]
    logged_in: bool
    wallet_peers_initialized: bool

    def __init__(self, config, keychain, root_path, consensus_constants, name=None):
        self.config = config
        self.constants = consensus_constants
        self.root_path = root_path
        self.log = logging.getLogger(name if name else __name__)
        self.cached_blocks = {}
        self.future_block_hashes = {}
        self.keychain = keychain
        self._shut_down = False
        self.proof_hashes = []
        self.header_hashes = []
        self.header_hashes_error = False
        self.short_sync_threshold = 15
        self.potential_blocks_received = {}
        self.potential_header_hashes = {}
        self.state_changed_callback = None
        self.wallet_state_manager = None
        self.backup_initialized = False
        self.server = None
        self.wsm_close_task = None
        self.sync_task = None
        self.logged_in_fingerprint = None
        self.peer_task = None
        self.logged_in = False
        self.wallet_peers_initialized = False
        self.last_new_peak_messages = LRUCache(5)

    def get_key_for_fingerprint(self, fingerprint: Optional[int]) -> Optional[PrivateKey]:
        private_keys = self.keychain.get_all_private_keys()
        if len(private_keys) == 0:
            self.log.warning("No keys present. Create keys with the UI, or with the 'chia keys' program.")
            return
        private_key = None
        if fingerprint is not None:
            for sk, _ in private_keys:
                if sk.get_g1().get_fingerprint() == fingerprint:
                    private_key = sk
                    break

        else:
            private_key = private_keys[0][0]
        return private_key

    async def _start(self, fingerprint: Optional[int]=None, new_wallet: bool=False, backup_file: Optional[Path]=None, skip_backup_import: bool=False) -> bool:
        private_key = self.get_key_for_fingerprint(fingerprint)
        if private_key is None:
            self.logged_in = False
            return False
        if self.config.get('enable_profiler', False):
            asyncio.create_task(profile_task(self.root_path, 'wallet', self.log))
        db_path_key_suffix = str(private_key.get_g1().get_fingerprint())
        db_path_replaced = self.config['database_path'].replace('CHALLENGE', self.config['selected_network']).replace('KEY', db_path_key_suffix)
        path = path_from_root(self.root_path, db_path_replaced)
        mkdir(path.parent)
        self.new_peak_lock = asyncio.Lock()
        assert self.server is not None
        self.wallet_state_manager = await WalletStateManager.create(private_key, self.config, path, self.constants, self.server, self.root_path)
        self.wsm_close_task = None
        assert self.wallet_state_manager is not None
        backup_settings = self.wallet_state_manager.user_settings.get_backup_settings()
        if backup_settings.user_initialized is False:
            if new_wallet is True:
                await self.wallet_state_manager.user_settings.user_created_new_wallet()
                self.wallet_state_manager.new_wallet = True
            else:
                if skip_backup_import is True:
                    await self.wallet_state_manager.user_settings.user_skipped_backup_import()
                else:
                    if backup_file is not None:
                        await self.wallet_state_manager.import_backup_info(backup_file)
                    else:
                        self.backup_initialized = False
                        await self.wallet_state_manager.close_all_stores()
                        self.wallet_state_manager = None
                        self.logged_in = False
                        return False
        self.backup_initialized = True
        if self.wallet_peers_initialized is False:
            asyncio.create_task(self.wallet_peers.start())
            self.wallet_peers_initialized = True
        if backup_file is not None:
            json_dict = open_backup_file(backup_file, self.wallet_state_manager.private_key)
            if 'start_height' in json_dict['data']:
                start_height = json_dict['data']['start_height']
                self.config['starting_height'] = max(0, start_height - self.config['start_height_buffer'])
            else:
                self.config['starting_height'] = 0
        else:
            self.config['starting_height'] = 0
        if self.state_changed_callback is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)
        self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)
        self._shut_down = False
        self.peer_task = asyncio.create_task(self._periodically_check_full_node())
        self.sync_event = asyncio.Event()
        self.sync_task = asyncio.create_task(self.sync_job())
        self.logged_in_fingerprint = fingerprint
        self.logged_in = True
        return True

    def _close(self):
        self.log.info('self._close')
        self.logged_in_fingerprint = None
        self._shut_down = True

    async def _await_closed(self):
        self.log.info('self._await_closed')
        await self.server.close_all_connections()
        asyncio.create_task(self.wallet_peers.ensure_is_closed())
        if self.wallet_state_manager is not None:
            await self.wallet_state_manager.close_all_stores()
            self.wallet_state_manager = None
        if self.sync_task is not None:
            self.sync_task.cancel()
            self.sync_task = None
        if self.peer_task is not None:
            self.peer_task.cancel()
            self.peer_task = None
        self.logged_in = False

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback
        if self.wallet_state_manager is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)
            self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)

    def _pending_tx_handler(self):
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        asyncio.create_task(self._resend_queue())

    async def _action_messages(self) -> List[Message]:
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return []
        actions = await self.wallet_state_manager.action_store.get_all_pending_actions()
        result = []
        for action in actions:
            data = json.loads(action.data)
            action_data = data['data']['action_data']
            if action.name == 'request_puzzle_solution':
                coin_name = bytes32(hexstr_to_bytes(action_data['coin_name']))
                height = uint32(action_data['height'])
                msg = make_msg(ProtocolMessageTypes.request_puzzle_solution, wallet_protocol.RequestPuzzleSolution(coin_name, height))
                result.append(msg)

        return result

    async def _resend_queue(self):
        if self._shut_down or self.server is None or self.wallet_state_manager is None or self.backup_initialized is None:
            return
        for msg, sent_peers in await self._messages_to_resend():
            if self._shut_down or self.server is None or self.wallet_state_manager is None or self.backup_initialized is None:
                return
            else:
                full_nodes = self.server.get_full_node_connections()
                for peer in full_nodes:
                    if peer.peer_node_id in sent_peers:
                        continue
                    else:
                        await peer.send_message(msg)

        for msg in await self._action_messages():
            if self._shut_down or self.server is None or self.wallet_state_manager is None or self.backup_initialized is None:
                return
            else:
                await self.server.send_to_all([msg], NodeType.FULL_NODE)

    async def _messages_to_resend(self) -> List[Tuple[(Message, Set[bytes32])]]:
        if not self.wallet_state_manager is None:
            if self.backup_initialized is False or self._shut_down:
                return []
            messages = []
            records = await self.wallet_state_manager.tx_store.get_not_sent()
            for record in records:
                if record.spend_bundle is None:
                    continue
                else:
                    msg = make_msg(ProtocolMessageTypes.send_transaction, wallet_protocol.SendTransaction(record.spend_bundle))
                    already_sent = set()
                    for peer, status, _ in record.sent_to:
                        if status == MempoolInclusionStatus.SUCCESS.value:
                            already_sent.add(hexstr_to_bytes(peer))

                    messages.append((msg, already_sent))

            return messages

    def set_server(self, server: ChiaServer):
        self.server = server
        DNS_SERVERS_EMPTY = []
        self.wallet_peers = WalletPeers(self.server, self.root_path, self.config['target_peer_count'], self.config['wallet_peers_path'], self.config['introducer_peer'], DNS_SERVERS_EMPTY, self.config['peer_connect_interval'], self.config['selected_network'], None, self.log)

    async def on_connect(self, peer: WSChiaConnection):
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        messages_peer_ids = await self._messages_to_resend()
        self.wallet_state_manager.state_changed('add_connection')
        for msg, peer_ids in messages_peer_ids:
            if peer.peer_node_id in peer_ids:
                continue
            else:
                await peer.send_message(msg)

        if not self.has_full_node():
            if self.wallet_peers is not None:
                asyncio.create_task(self.wallet_peers.on_connect(peer))

    async def _periodically_check_full_node(self) -> None:
        tries = 0
        while not self._shut_down:
            if tries < 5:
                if self.has_full_node():
                    await self.wallet_peers.ensure_is_closed()
                    if self.wallet_state_manager is not None:
                        self.wallet_state_manager.state_changed('add_connection')
                    break
                else:
                    tries += 1
                    await asyncio.sleep(self.config['peer_connect_interval'])

    def has_full_node(self) -> bool:
        if self.server is None:
            return False
        if 'full_node_peer' in self.config:
            full_node_peer = PeerInfo(self.config['full_node_peer']['host'], self.config['full_node_peer']['port'])
            peers = [c.get_peer_info() for c in self.server.get_full_node_connections()]
            full_node_resolved = PeerInfo(socket.gethostbyname(full_node_peer.host), full_node_peer.port)
            if full_node_peer in peers or full_node_resolved in peers:
                self.log.info(f"Will not attempt to connect to other nodes, already connected to {full_node_peer}")
                for connection in self.server.get_full_node_connections():
                    if connection.get_peer_info() != full_node_peer:
                        if connection.get_peer_info() != full_node_resolved:
                            self.log.info(f"Closing unnecessary connection to {connection.get_peer_info()}.")
                            asyncio.create_task(connection.close())

                return True
            return False

    async def complete_blocks(self, header_blocks: List[HeaderBlock], peer: WSChiaConnection):
        if self.wallet_state_manager is None:
            return
        header_block_records = []
        assert self.server
        trusted = self.server.is_trusted_peer(peer, self.config['trusted_peers'])
        async with self.wallet_state_manager.blockchain.lock:
            for block in header_blocks:
                if block.is_transaction_block:
                    additions, removals = await self.wallet_state_manager.get_filter_additions_removals(block, block.transactions_filter, None)
                    added_coins = await self.get_additions(peer, block, additions)
                    if added_coins is None:
                        raise ValueError('Failed to fetch additions')
                    removed_coins = await self.get_removals(peer, block, added_coins, removals)
                    if removed_coins is None:
                        raise ValueError('Failed to fetch removals')
                    additional_coin_spends = await self.get_additional_coin_spends(peer, block, added_coins, removed_coins)
                    hbr = HeaderBlockRecord(block, added_coins, removed_coins)
                else:
                    hbr = HeaderBlockRecord(block, [], [])
                    header_block_records.append(hbr)
                    additional_coin_spends = []
                result, error, fork_h = await self.wallet_state_manager.blockchain.receive_block(hbr,
                  trusted=trusted, additional_coin_spends=additional_coin_spends)
                if result == ReceiveBlockResult.NEW_PEAK:
                    if not self.wallet_state_manager.sync_mode:
                        self.wallet_state_manager.blockchain.clean_block_records()
                    else:
                        self.wallet_state_manager.state_changed('new_block')
                        self.wallet_state_manager.state_changed('sync_changed')
                        await self.wallet_state_manager.new_peak()
                else:
                    if result == ReceiveBlockResult.INVALID_BLOCK:
                        self.log.info(f"Invalid block from peer: {peer.get_peer_info()} {error}")
                        await peer.close()
                        return
                    self.log.debug(f"Result: {result}")

    async def new_peak_wallet(self, peak: wallet_protocol.NewPeakWallet, peer: WSChiaConnection):
        if self.wallet_state_manager is None:
            return
        if self.wallet_state_manager.blockchain.contains_block(peak.header_hash):
            self.log.debug(f"known peak {peak.header_hash}")
            return
        if self.wallet_state_manager.sync_mode:
            self.last_new_peak_messages.put(peer, peak)
            return
        async with self.new_peak_lock:
            curr_peak = self.wallet_state_manager.blockchain.get_peak()
            if curr_peak is not None:
                if curr_peak.weight >= peak.weight:
                    return
            request = wallet_protocol.RequestBlockHeader(peak.height)
            response = await peer.request_block_header(request)
            if response is None or isinstance(response, RespondBlockHeader) and response.header_block is None:
                self.log.warning(f"bad peak response from peer {response}")
                return
            header_block = response.header_block
            curr_peak_height = 0 if curr_peak is None else curr_peak.height
            if curr_peak_height == 0 and peak.height < self.constants.WEIGHT_PROOF_RECENT_BLOCKS or curr_peak_height > peak.height - 200:
                if peak.height <= curr_peak_height + self.config['short_sync_blocks_behind_threshold']:
                    await self.wallet_short_sync_backtrack(header_block, peer)
                else:
                    await self.batch_sync_to_peak(curr_peak_height, peak)
            else:
                if peak.height >= self.constants.WEIGHT_PROOF_RECENT_BLOCKS:
                    weight_request = RequestProofOfWeight(peak.height, peak.header_hash)
                    weight_proof_response = await peer.request_proof_of_weight(weight_request,
                      timeout=360)
                    if weight_proof_response is None:
                        return
                    weight_proof = weight_proof_response.wp
                    if self.wallet_state_manager is None:
                        return
                    if self.server is not None and self.server.is_trusted_peer(peer, self.config['trusted_peers']):
                        valid, fork_point = self.wallet_state_manager.weight_proof_handler.get_fork_point_no_validations(weight_proof)
                    else:
                        valid, fork_point, _ = await self.wallet_state_manager.weight_proof_handler.validate_weight_proof(weight_proof)
                    if not valid:
                        self.log.error(f"invalid weight proof, num of epochs {len(weight_proof.sub_epochs)} recent blocks num ,{len(weight_proof.recent_chain_data)}")
                        self.log.debug(f"{weight_proof}")
                        return
                    self.log.info(f"Validated, fork point is {fork_point}")
                    self.wallet_state_manager.sync_store.add_potential_fork_point(header_block.header_hash, uint32(fork_point))
                    self.wallet_state_manager.sync_store.add_potential_peak(header_block)
                    self.start_sync()

    async def wallet_short_sync_backtrack(self, header_block, peer):
        top = header_block
        blocks = [top]
        while not self.wallet_state_manager.blockchain.contains_block(top.prev_header_hash):
            if top.height > 0:
                request_prev = wallet_protocol.RequestBlockHeader(top.height - 1)
                response_prev = await peer.request_block_header(request_prev)
                if not (response_prev is None or isinstance(response_prev, RespondBlockHeader)):
                    raise RuntimeError('bad block header response from peer while syncing')
                prev_head = response_prev.header_block
                blocks.append(prev_head)
                top = prev_head

        blocks.reverse()
        await self.complete_blocks(blocks, peer)
        await self.wallet_state_manager.create_more_puzzle_hashes()

    async def batch_sync_to_peak(self, fork_height, peak):
        advanced_peak = False
        batch_size = self.constants.MAX_BLOCK_COUNT_PER_REQUESTS
        for i in range(max(0, fork_height - 1), peak.height, batch_size):
            start_height = i
            end_height = min(peak.height, start_height + batch_size)
            peers = self.server.get_full_node_connections()
            added = False
            for peer in peers:
                try:
                    added, advanced_peak = await self.fetch_blocks_and_validate(peer, uint32(start_height), uint32(end_height), None if advanced_peak else fork_height)
                    if added:
                        break
                except Exception as e:
                    try:
                        await peer.close()
                        exc = traceback.format_exc()
                        self.log.error(f"Error while trying to fetch from peer:{e} {exc}")
                    finally:
                        e = None
                        del e

            if not added:
                raise RuntimeError(f"Was not able to add blocks {start_height}-{end_height}")
            else:
                curr_peak = self.wallet_state_manager.blockchain.get_peak()
                assert peak is not None
                self.wallet_state_manager.blockchain.clean_block_record(min(end_height, curr_peak.height) - self.constants.BLOCKS_CACHE_SIZE)

    def start_sync(self) -> None:
        self.log.info('self.sync_event.set()')
        self.sync_event.set()

    async def check_new_peak(self) -> None:
        if self.wallet_state_manager is None:
            return
        current_peak = self.wallet_state_manager.blockchain.get_peak()
        if current_peak is None:
            return
        potential_peaks = self.wallet_state_manager.sync_store.get_potential_peaks_tuples()
        for _, block in potential_peaks:
            if current_peak.weight < block.weight:
                await asyncio.sleep(5)
                self.start_sync()
                return

    async def sync_job(self) -> None:
        while True:
            self.log.info('Loop start in sync job')
            if self._shut_down is True:
                break
            else:
                asyncio.create_task(self.check_new_peak())
                await self.sync_event.wait()
                self.last_new_peak_messages = LRUCache(5)
                self.sync_event.clear()
            if self._shut_down is True:
                break
            else:
                try:
                    try:
                        assert self.wallet_state_manager is not None
                        self.wallet_state_manager.set_sync_mode(True)
                        await self._sync()
                    except Exception as e:
                        try:
                            tb = traceback.format_exc()
                            self.log.error(f"Loop exception in sync {e}. {tb}")
                        finally:
                            e = None
                            del e

                finally:
                    if self.wallet_state_manager is not None:
                        self.wallet_state_manager.set_sync_mode(False)
                    for peer, peak in self.last_new_peak_messages.cache.items():
                        asyncio.create_task(self.new_peak_wallet(peak, peer))

                self.log.info('Loop end in sync job')

    async def _sync(self) -> None:
        """
        Wallet has fallen far behind (or is starting up for the first time), and must be synced
        up to the LCA of the blockchain.
        """
        if self.wallet_state_manager is None or self.backup_initialized is False or self.server is None:
            return
        highest_weight = uint128(0)
        peak_height = uint32(0)
        peak = None
        potential_peaks = self.wallet_state_manager.sync_store.get_potential_peaks_tuples()
        self.log.info(f"Have collected {len(potential_peaks)} potential peaks")
        for header_hash, potential_peak_block in potential_peaks:
            if potential_peak_block.weight > highest_weight:
                highest_weight = potential_peak_block.weight
                peak_height = potential_peak_block.height
                peak = potential_peak_block

        if peak_height is None or peak_height == 0:
            return
        if self.wallet_state_manager.peak is not None:
            if highest_weight <= self.wallet_state_manager.peak.weight:
                self.log.info('Not performing sync, already caught up.')
                return
        peers = self.server.get_full_node_connections()
        if len(peers) == 0:
            self.log.info('No peers to sync to')
            return
        async with self.wallet_state_manager.blockchain.lock:
            fork_height = None
            if peak is not None:
                fork_height = self.wallet_state_manager.sync_store.get_potential_fork_point(peak.header_hash)
                our_peak_height = self.wallet_state_manager.blockchain.get_peak_height()
                ses_heigths = self.wallet_state_manager.blockchain.get_ses_heights()
                if len(ses_heigths) > 2:
                    if our_peak_height is not None:
                        ses_heigths.sort()
                        max_fork_ses_height = ses_heigths[-3]
                        if self.wallet_state_manager.blockchain.get_peak_height() is not None:
                            if fork_height == max_fork_ses_height:
                                peers = self.server.get_full_node_connections()
                                for peer in peers:
                                    potential_height = uint32(our_peak_height + 1)
                                    block_response = await peer.request_header_blocks(wallet_protocol.RequestHeaderBlocks(potential_height, potential_height))
                                    if block_response is not None:
                                        if isinstance(block_response, wallet_protocol.RespondHeaderBlocks):
                                            our_peak = self.wallet_state_manager.blockchain.get_peak()
                                            if our_peak is not None:
                                                if block_response.header_blocks[0].prev_header_hash == our_peak.header_hash:
                                                    fork_height = our_peak_height
                                            break

            if fork_height is None:
                fork_height = uint32(0)
            await self.wallet_state_manager.blockchain.warmup(fork_height)
            await self.batch_sync_to_peak(fork_height, peak)

    async def fetch_blocks_and_validate(self, peer: WSChiaConnection, height_start: uint32, height_end: uint32, fork_point_with_peak: Optional[uint32]) -> Tuple[(bool, bool)]:
        """
        Returns whether the blocks validated, and whether the peak was advanced
        """
        if self.wallet_state_manager is None:
            return (False, False)
        self.log.info(f"Requesting blocks {height_start}-{height_end}")
        request = RequestHeaderBlocks(uint32(height_start), uint32(height_end))
        res = await peer.request_header_blocks(request)
        if not (res is None or isinstance(res, RespondHeaderBlocks)):
            raise ValueError('Peer returned no response')
        header_blocks = res.header_blocks
        advanced_peak = False
        if header_blocks is None:
            raise ValueError(f"No response from peer {peer}")
        assert self.server
        trusted = self.server.is_trusted_peer(peer, self.config['trusted_peers'])
        pre_validation_results = None
        if not trusted:
            pre_validation_results = await self.wallet_state_manager.blockchain.pre_validate_blocks_multiprocessing(header_blocks)
            if pre_validation_results is None:
                return (False, advanced_peak)
            assert len(header_blocks) == len(pre_validation_results)
            for i in range(len(header_blocks)):
                header_block = header_blocks[i]
                if not trusted:
                    if not pre_validation_results is not None or pre_validation_results[i].error is not None:
                        raise ValidationError(Err(pre_validation_results[i].error))
                fork_point_with_old_peak = None if advanced_peak else fork_point_with_peak
                if header_block.is_transaction_block:
                    additions, removals = await self.wallet_state_manager.get_filter_additions_removals(header_block, header_block.transactions_filter, fork_point_with_old_peak)
                    added_coins = await self.get_additions(peer, header_block, additions)
                    if added_coins is None:
                        raise ValueError('Failed to fetch additions')
                    removed_coins = await self.get_removals(peer, header_block, added_coins, removals)
                    if removed_coins is None:
                        raise ValueError('Failed to fetch removals')
                    additional_coin_spends = await self.get_additional_coin_spends(peer, header_block, added_coins, removed_coins)
                    header_block_record = HeaderBlockRecord(header_block, added_coins, removed_coins)
                else:
                    header_block_record = HeaderBlockRecord(header_block, [], [])
                    additional_coin_spends = []
                start_t = time.time()
                if trusted:
                    result, error, fork_h = await self.wallet_state_manager.blockchain.receive_block(header_block_record,
                      None,
                      trusted,
                      fork_point_with_old_peak,
                      additional_coin_spends=additional_coin_spends)
                else:
                    assert pre_validation_results is not None
                    result, error, fork_h = await self.wallet_state_manager.blockchain.receive_block(header_block_record,
                      (pre_validation_results[i]),
                      trusted,
                      fork_point_with_old_peak,
                      additional_coin_spends=additional_coin_spends)
                self.log.debug(f"Time taken to validate {header_block.height} with fork {fork_point_with_old_peak}: {time.time() - start_t}")
                if result == ReceiveBlockResult.NEW_PEAK:
                    advanced_peak = True
                    self.wallet_state_manager.state_changed('new_block')
                if result == ReceiveBlockResult.INVALID_BLOCK:
                    raise ValueError('Value error peer sent us invalid block')

            if advanced_peak:
                await self.wallet_state_manager.create_more_puzzle_hashes()
            return (True, advanced_peak)

    def validate_additions(self, coins: List[Tuple[(bytes32, List[Coin])]], proofs: Optional[List[Tuple[(bytes32, bytes, Optional[bytes])]]], root):
        if proofs is None:
            additions_merkle_set = MerkleSet()
            for puzzle_hash, coins_l in coins:
                additions_merkle_set.add_already_hashed(puzzle_hash)
                additions_merkle_set.add_already_hashed(hash_coin_list(coins_l))

            additions_root = additions_merkle_set.get_root()
            if root != additions_root:
                return False
        else:
            for i in range(len(coins)):
                if not coins[i][0] == proofs[i][0]:
                    raise AssertionError
                else:
                    coin_list_1 = coins[i][1]
                    puzzle_hash_proof = proofs[i][1]
                    coin_list_proof = proofs[i][2]
                if len(coin_list_1) == 0:
                    not_included = confirm_not_included_already_hashed(root, coins[i][0], puzzle_hash_proof)
                    if not_included is False:
                        return False
                try:
                    included = confirm_included_already_hashed(root, hash_coin_list(coin_list_1), coin_list_proof)
                    if included is False:
                        return False
                except AssertionError:
                    return False
                else:
                    try:
                        included = confirm_included_already_hashed(root, coins[i][0], puzzle_hash_proof)
                        if included is False:
                            return False
                    except AssertionError:
                        return False

        return True

    def validate_removals(self, coins, proofs, root):
        if proofs is None:
            removals_merkle_set = MerkleSet()
            for name_coin in coins:
                name, coin = name_coin
                if coin is not None:
                    removals_merkle_set.add_already_hashed(coin.name())

            removals_root = removals_merkle_set.get_root()
            if root != removals_root:
                return False
        else:
            if len(coins) != len(proofs):
                return False
            for i in range(len(coins)):
                if coins[i][0] != proofs[i][0]:
                    return False
                else:
                    coin = coins[i][1]
                if coin is None:
                    not_included = confirm_not_included_already_hashed(root, coins[i][0], proofs[i][1])
                    if not_included is False:
                        return False
                if coins[i][0] != coin.name():
                    return False
                else:
                    included = confirm_included_already_hashed(root, coin.name(), proofs[i][1])
                if included is False:
                    return False

        return True

    async def fetch_puzzle_solution(self, peer, height: uint32, coin: Coin) -> CoinSpend:
        solution_response = await peer.request_puzzle_solution(wallet_protocol.RequestPuzzleSolution(coin.name(), height))
        if not (solution_response is None or isinstance(solution_response, wallet_protocol.RespondPuzzleSolution)):
            raise ValueError(f"Was not able to obtain solution {solution_response}")
        return CoinSpend(coin, solution_response.response.puzzle, solution_response.response.solution)

    async def get_additional_coin_spends(self, peer, block, added_coins: List[Coin], removed_coins: List[Coin]) -> List[CoinSpend]:
        assert self.wallet_state_manager is not None
        additional_coin_spends = []
        if len(removed_coins) > 0:
            removed_coin_ids = set([coin.name() for coin in removed_coins])
            all_added_coins = await self.get_additions(peer, block, [], get_all_additions=True)
            assert all_added_coins is not None
            if all_added_coins is not None:
                for coin in all_added_coins:
                    if coin.puzzle_hash == SINGLETON_LAUNCHER_HASH:
                        if coin.parent_coin_info in removed_coin_ids:
                            cs = await self.fetch_puzzle_solution(peer, block.height, coin)
                            additional_coin_spends.append(cs)
                            await self.wallet_state_manager.get_next_interesting_coin_ids(cs, False)

                all_removed_coins = await self.get_removals(peer,
                  block, added_coins, removed_coins, request_all_removals=True)
                assert all_removed_coins is not None
                all_removed_coins_dict = {coin.name(): coin for coin in all_removed_coins}
                keep_searching = True
                while keep_searching:
                    keep_searching = False
                    interested_ids = await self.wallet_state_manager.interested_store.get_interested_coin_ids()
                    for coin_id in interested_ids:
                        if coin_id in all_removed_coins_dict:
                            coin = all_removed_coins_dict[coin_id]
                            cs = await self.fetch_puzzle_solution(peer, block.height, coin)
                            await self.wallet_state_manager.get_next_interesting_coin_ids(cs, False)
                            additional_coin_spends.append(cs)
                            keep_searching = True
                            all_removed_coins_dict.pop(coin_id)
                            break

        return additional_coin_spends

    async def get_additions(self, peer: WSChiaConnection, block_i, additions: Optional[List[bytes32]], get_all_additions: bool=False) -> Optional[List[Coin]]:
        if additions is not None and len(additions) > 0 or get_all_additions:
            if get_all_additions:
                additions = None
            additions_request = RequestAdditions(block_i.height, block_i.header_hash, additions)
            additions_res = await peer.request_additions(additions_request)
            if additions_res is None:
                await peer.close()
                return
            if isinstance(additions_res, RespondAdditions):
                validated = self.validate_additions(additions_res.coins, additions_res.proofs, block_i.foliage_transaction_block.additions_root)
                if not validated:
                    await peer.close()
                    return
                added_coins = []
                for ph_coins in additions_res.coins:
                    ph, coins = ph_coins
                    added_coins.extend(coins)

                return added_coins
            if isinstance(additions_res, RejectRemovalsRequest):
                await peer.close()
                return
            return
        return []

    async def get_removals(self, peer: WSChiaConnection, block_i, additions, removals, request_all_removals=False) -> Optional[List[Coin]]:
        assert self.wallet_state_manager is not None
        for coin in additions:
            puzzle_store = self.wallet_state_manager.puzzle_store
            record_info = await puzzle_store.get_derivation_record_for_puzzle_hash(coin.puzzle_hash.hex())
            if record_info is not None:
                if record_info.wallet_type == WalletType.COLOURED_COIN:
                    request_all_removals = True
                    break
            if record_info is not None:
                if record_info.wallet_type == WalletType.DISTRIBUTED_ID:
                    request_all_removals = True
                    break

        if len(removals) > 0 or request_all_removals:
            if request_all_removals:
                removals_request = wallet_protocol.RequestRemovals(block_i.height, block_i.header_hash, None)
            else:
                removals_request = wallet_protocol.RequestRemovals(block_i.height, block_i.header_hash, removals)
            removals_res = await peer.request_removals(removals_request)
            if removals_res is None:
                return
            if isinstance(removals_res, RespondRemovals):
                validated = self.validate_removals(removals_res.coins, removals_res.proofs, block_i.foliage_transaction_block.removals_root)
                if validated is False:
                    await peer.close()
                    return
                removed_coins = []
                for _, coins_l in removals_res.coins:
                    if coins_l is not None:
                        removed_coins.append(coins_l)

                return removed_coins
            if isinstance(removals_res, RejectRemovalsRequest):
                return
            return
        else:
            return []