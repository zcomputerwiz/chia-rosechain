# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\wallet_state_manager.py
import asyncio, base64, json, logging, time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import aiosqlite
from blspy import AugSchemeMPL, G1Element, PrivateKey
from chiabip158 import PyBIP158
from cryptography.fernet import Fernet
from chia import __version__
from chia.consensus.block_record import BlockRecord
from chia.consensus.coinbase import pool_parent_id, farmer_parent_id
from chia.consensus.constants import ConsensusConstants
from chia.consensus.find_fork_point import find_fork_point_in_chain
from chia.full_node.weight_proof import WeightProofHandler
from chia.pools.pool_puzzles import SINGLETON_LAUNCHER_HASH, solution_to_extra_data
from chia.pools.pool_wallet import PoolWallet
from chia.protocols.wallet_protocol import PuzzleSolutionResponse, RespondPuzzleSolution
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.full_block import FullBlock
from chia.types.header_block import HeaderBlock
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.byte_types import hexstr_to_bytes
from chia.util.db_wrapper import DBWrapper
from chia.util.errors import Err
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64, uint128
from chia.wallet.block_record import HeaderBlockRecord
from chia.wallet.cc_wallet.cc_wallet import CCWallet
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.derive_keys import master_sk_to_backup_sk, master_sk_to_wallet_sk
from chia.wallet.key_val_store import KeyValStore
from chia.wallet.rl_wallet.rl_wallet import RLWallet
from chia.wallet.settings.user_settings import UserSettings
from chia.wallet.trade_manager import TradeManager
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.backup_utils import open_backup_file
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_action import WalletAction
from chia.wallet.wallet_action_store import WalletActionStore
from chia.wallet.wallet_block_store import WalletBlockStore
from chia.wallet.wallet_blockchain import WalletBlockchain
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_coin_store import WalletCoinStore
from chia.wallet.wallet_info import WalletInfo, WalletInfoBackup
from chia.wallet.wallet_interested_store import WalletInterestedStore
from chia.wallet.wallet_pool_store import WalletPoolStore
from chia.wallet.wallet_puzzle_store import WalletPuzzleStore
from chia.wallet.wallet_sync_store import WalletSyncStore
from chia.wallet.wallet_transaction_store import WalletTransactionStore
from chia.wallet.wallet_user_store import WalletUserStore
from chia.server.server import ChiaServer
from chia.wallet.did_wallet.did_wallet import DIDWallet

class WalletStateManager:
    constants: ConsensusConstants
    config: Dict
    tx_store: WalletTransactionStore
    puzzle_store: WalletPuzzleStore
    user_store: WalletUserStore
    action_store: WalletActionStore
    basic_store: KeyValStore
    start_index: int
    lock: asyncio.Lock
    tx_lock: asyncio.Lock
    log: logging.Logger
    sync_mode: bool
    genesis: FullBlock
    state_changed_callback: Optional[Callable]
    pending_tx_callback: Optional[Callable]
    puzzle_hash_created_callbacks = defaultdict(lambda *x: None
)
    puzzle_hash_created_callbacks: Dict
    new_peak_callbacks = defaultdict(lambda *x: None
)
    new_peak_callbacks: Dict
    db_path: Path
    db_connection: aiosqlite.Connection
    db_wrapper: DBWrapper
    main_wallet: Wallet
    wallets: Dict[(uint32, Any)]
    private_key: PrivateKey
    trade_manager: TradeManager
    new_wallet: bool
    user_settings: UserSettings
    blockchain: Any
    block_store: WalletBlockStore
    coin_store: WalletCoinStore
    sync_store: WalletSyncStore
    interested_store: WalletInterestedStore
    pool_store: WalletPoolStore
    weight_proof_handler: Any
    server: ChiaServer
    root_path: Path

    @staticmethod
    async def create(private_key, config, db_path, constants, server, root_path, name=None):
        self = WalletStateManager()
        self.new_wallet = False
        self.config = config
        self.constants = constants
        self.server = server
        self.root_path = root_path
        self.log = logging.getLogger(name if name else __name__)
        self.lock = asyncio.Lock()
        self.log.debug(f"Starting in db path: {db_path}")
        self.db_connection = await aiosqlite.connect(db_path)
        self.db_wrapper = DBWrapper(self.db_connection)
        self.coin_store = await WalletCoinStore.create(self.db_wrapper)
        self.tx_store = await WalletTransactionStore.create(self.db_wrapper)
        self.puzzle_store = await WalletPuzzleStore.create(self.db_wrapper)
        self.user_store = await WalletUserStore.create(self.db_wrapper)
        self.action_store = await WalletActionStore.create(self.db_wrapper)
        self.basic_store = await KeyValStore.create(self.db_wrapper)
        self.trade_manager = await TradeManager.create(self, self.db_wrapper)
        self.user_settings = await UserSettings.create(self.basic_store)
        self.block_store = await WalletBlockStore.create(self.db_wrapper)
        self.interested_store = await WalletInterestedStore.create(self.db_wrapper)
        self.pool_store = await WalletPoolStore.create(self.db_wrapper)
        self.blockchain = await WalletBlockchain.create(self.block_store, self.coin_store, self.tx_store, self.pool_store, self.constants, self.new_transaction_block_callback, self.reorg_rollback, self.lock)
        self.weight_proof_handler = WeightProofHandler(self.constants, self.blockchain)
        self.sync_mode = False
        self.sync_store = await WalletSyncStore.create()
        self.state_changed_callback = None
        self.pending_tx_callback = None
        self.db_path = db_path
        main_wallet_info = await self.user_store.get_wallet_by_id(1)
        assert main_wallet_info is not None
        self.private_key = private_key
        self.main_wallet = await Wallet.create(self, main_wallet_info)
        self.wallets = {main_wallet_info.id: self.main_wallet}
        wallet = None
        for wallet_info in await self.get_all_wallet_info_entries():
            if wallet_info.type == WalletType.STANDARD_WALLET:
                if wallet_info.id == 1:
                    continue
                else:
                    wallet = await Wallet.create(config, wallet_info)
            elif wallet_info.type == WalletType.COLOURED_COIN:
                wallet = await CCWallet.create(self, self.main_wallet, wallet_info)
            else:
                if wallet_info.type == WalletType.RATE_LIMITED:
                    wallet = await RLWallet.create(self, wallet_info)
                else:
                    if wallet_info.type == WalletType.DISTRIBUTED_ID:
                        wallet = await DIDWallet.create(self, self.main_wallet, wallet_info)
                    else:
                        if wallet_info.type == WalletType.POOLING_WALLET:
                            wallet = await PoolWallet.create_from_db(self, self.main_wallet, wallet_info)
            if wallet is not None:
                self.wallets[wallet_info.id] = wallet

        async with self.puzzle_store.lock:
            index = await self.puzzle_store.get_last_derivation_path()
            if index is None or index < self.config['initial_num_public_keys'] - 1:
                await self.create_more_puzzle_hashes(from_zero=True)
        return self

    @property
    def peak(self) -> Optional[BlockRecord]:
        peak = self.blockchain.get_peak()
        return peak

    def get_derivation_index(self, pubkey: G1Element, max_depth: int=1000) -> int:
        for i in range(0, max_depth):
            derived = self.get_public_key(uint32(i))
            if derived == pubkey:
                return i

        return -1

    def get_public_key(self, index: uint32) -> G1Element:
        return master_sk_to_wallet_sk(self.private_key, index).get_g1()

    async def load_wallets(self):
        for wallet_info in await self.get_all_wallet_info_entries():
            if wallet_info.id in self.wallets:
                continue
            if wallet_info.type == WalletType.STANDARD_WALLET:
                if wallet_info.id == 1:
                    continue
                else:
                    wallet = await Wallet.create(self.config, wallet_info)
                    self.wallets[wallet_info.id] = wallet
            else:
                if wallet_info.type == WalletType.COLOURED_COIN:
                    wallet = await CCWallet.create(self, self.main_wallet, wallet_info)
                    self.wallets[wallet_info.id] = wallet
            if wallet_info.type == WalletType.DISTRIBUTED_ID:
                wallet = await DIDWallet.create(self, self.main_wallet, wallet_info)
                self.wallets[wallet_info.id] = wallet

    async def get_keys(self, puzzle_hash: bytes32) -> Optional[Tuple[(G1Element, PrivateKey)]]:
        index_for_puzzlehash = await self.puzzle_store.index_for_puzzle_hash(puzzle_hash)
        if index_for_puzzlehash is None:
            raise ValueError(f"No key for this puzzlehash {puzzle_hash})")
        private = master_sk_to_wallet_sk(self.private_key, index_for_puzzlehash)
        pubkey = private.get_g1()
        return (
         pubkey, private)

    async def create_more_puzzle_hashes(self, from_zero: bool=False, in_transaction=False):
        """
        For all wallets in the user store, generates the first few puzzle hashes so
        that we can restore the wallet from only the private keys.
        """
        targets = list(self.wallets.keys())
        unused = await self.puzzle_store.get_unused_derivation_path()
        if unused is None:
            unused = await self.puzzle_store.get_last_derivation_path()
            if unused is None:
                unused = uint32(0)
        if self.new_wallet:
            to_generate = self.config['initial_num_public_keys_new_wallet']
        else:
            to_generate = self.config['initial_num_public_keys']
        for wallet_id in targets:
            target_wallet = self.wallets[wallet_id]
            last = await self.puzzle_store.get_last_derivation_path_for_wallet(wallet_id)
            start_index = 0
            derivation_paths = []
            if last is not None:
                start_index = last + 1
            else:
                if from_zero:
                    start_index = 0
                for index in range(start_index, unused + to_generate):
                    if WalletType(target_wallet.type()) == WalletType.POOLING_WALLET:
                        continue
                    if WalletType(target_wallet.type()) == WalletType.RATE_LIMITED:
                        if target_wallet.rl_info.initialized is False:
                            break
                        else:
                            wallet_type = target_wallet.rl_info.type
                            if wallet_type == 'user':
                                rl_pubkey = G1Element.from_bytes(target_wallet.rl_info.user_pubkey)
                            else:
                                rl_pubkey = G1Element.from_bytes(target_wallet.rl_info.admin_pubkey)
                            rl_puzzle = target_wallet.puzzle_for_pk(rl_pubkey)
                            puzzle_hash = rl_puzzle.get_tree_hash()
                            rl_index = self.get_derivation_index(rl_pubkey)
                        if rl_index == -1:
                            break
                        else:
                            derivation_paths.append(DerivationRecord(uint32(rl_index), puzzle_hash, rl_pubkey, target_wallet.type(), uint32(target_wallet.id())))
                        break
                    else:
                        pubkey = self.get_public_key(uint32(index))
                        puzzle = target_wallet.puzzle_for_pk(bytes(pubkey))
                    if puzzle is None:
                        self.log.warning(f"Unable to create puzzles with wallet {target_wallet}")
                        break
                    else:
                        puzzlehash = puzzle.get_tree_hash()
                        self.log.info(f"Puzzle at index {index} wallet ID {wallet_id} puzzle hash {puzzlehash.hex()}")
                        derivation_paths.append(DerivationRecord(uint32(index), puzzlehash, pubkey, target_wallet.type(), uint32(target_wallet.id())))

                await self.puzzle_store.add_derivation_paths(derivation_paths, in_transaction)

        if unused > 0:
            await self.puzzle_store.set_used_up_to(uint32(unused - 1), in_transaction)

    async def update_wallet_puzzle_hashes(self, wallet_id):
        derivation_paths = []
        target_wallet = self.wallets[wallet_id]
        last = await self.puzzle_store.get_last_derivation_path_for_wallet(wallet_id)
        unused = await self.puzzle_store.get_unused_derivation_path()
        if unused is None:
            unused = await self.puzzle_store.get_last_derivation_path()
            if unused is None:
                unused = uint32(0)
        for index in range(unused, last):
            pubkey = self.get_public_key(uint32(index))
            puzzle = target_wallet.puzzle_for_pk(bytes(pubkey))
            puzzlehash = puzzle.get_tree_hash()
            self.log.info(f"Generating public key at index {index} puzzle hash {puzzlehash.hex()}")
            derivation_paths.append(DerivationRecord(uint32(index), puzzlehash, pubkey, target_wallet.wallet_info.type, uint32(target_wallet.wallet_info.id)))

        await self.puzzle_store.add_derivation_paths(derivation_paths)

    async def get_unused_derivation_record(self, wallet_id: uint32, in_transaction=False) -> DerivationRecord:
        """
        Creates a puzzle hash for the given wallet, and then makes more puzzle hashes
        for every wallet to ensure we always have more in the database. Never reusue the
        same public key more than once (for privacy).
        """
        async with self.puzzle_store.lock:
            unused = await self.puzzle_store.get_unused_derivation_path()
            if unused is None:
                await self.create_more_puzzle_hashes()
            unused = await self.puzzle_store.get_unused_derivation_path()
            assert unused is not None
            record = await self.puzzle_store.get_derivation_record(unused, wallet_id)
            assert record is not None
            await self.puzzle_store.set_used_up_to((record.index), in_transaction=in_transaction)
            await self.create_more_puzzle_hashes(in_transaction=in_transaction)
            return record

    async def get_current_derivation_record_for_wallet(self, wallet_id: uint32) -> Optional[DerivationRecord]:
        async with self.puzzle_store.lock:
            current = await self.puzzle_store.get_current_derivation_record_for_wallet(wallet_id)
            return current

    def set_callback(self, callback: Callable):
        """
        Callback to be called when the state of the wallet changes.
        """
        self.state_changed_callback = callback

    def set_pending_callback(self, callback: Callable):
        """
        Callback to be called when new pending transaction enters the store
        """
        self.pending_tx_callback = callback

    def set_coin_with_puzzlehash_created_callback(self, puzzlehash: bytes32, callback: Callable):
        """
        Callback to be called when new coin is seen with specified puzzlehash
        """
        self.puzzle_hash_created_callbacks[puzzlehash] = callback

    def set_new_peak_callback(self, wallet_id: int, callback: Callable):
        """
        Callback to be called when blockchain adds new peak
        """
        self.new_peak_callbacks[wallet_id] = callback

    async def puzzle_hash_created(self, coin: Coin):
        callback = self.puzzle_hash_created_callbacks[coin.puzzle_hash]
        if callback is None:
            return
        await callback(coin)

    def state_changed(self, state: str, wallet_id: int=None, data_object=None):
        """
        Calls the callback if it's present.
        """
        if data_object is None:
            data_object = {}
        if self.state_changed_callback is None:
            return
        self.state_changed_callback(state, wallet_id, data_object)

    def tx_pending_changed(self) -> None:
        """
        Notifies the wallet node that there's new tx pending
        """
        if self.pending_tx_callback is None:
            return
        self.pending_tx_callback()

    async def synced(self):
        if self.sync_mode is True:
            return False
        peak = self.blockchain.get_peak()
        if peak is None:
            return False
        curr = peak
        while not curr.is_transaction_block:
            if not curr.height == 0:
                curr = self.blockchain.try_block_record(curr.prev_hash)
                if curr is None:
                    return False

        if curr.is_transaction_block:
            if curr.timestamp > int(time.time()) - 420:
                return True
        return False

    def set_sync_mode(self, mode: bool):
        """
        Sets the sync mode. This changes the behavior of the wallet node.
        """
        self.sync_mode = mode
        self.state_changed('sync_changed')

    async def get_confirmed_spendable_balance_for_wallet(self, wallet_id: int, unspent_records=None) -> uint128:
        """
        Returns the balance amount of all coins that are spendable.
        """
        spendable = await self.get_spendable_coins_for_wallet(wallet_id, unspent_records)
        spendable_amount = uint128(0)
        for record in spendable:
            spendable_amount = uint128(spendable_amount + record.coin.amount)

        return spendable_amount

    async def does_coin_belong_to_wallet(self, coin: Coin, wallet_id: int) -> bool:
        """
        Returns true if we have the key for this coin.
        """
        info = await self.puzzle_store.wallet_info_for_puzzle_hash(coin.puzzle_hash)
        if info is None:
            return False
        coin_wallet_id, wallet_type = info
        if wallet_id == coin_wallet_id:
            return True
        return False

    async def get_confirmed_balance_for_wallet(self, wallet_id: int, unspent_coin_records: Optional[Set[WalletCoinRecord]]=None) -> uint128:
        """
        Returns the confirmed balance, including coinbase rewards that are not spendable.
        """
        if unspent_coin_records is None:
            async with self.lock:
                if unspent_coin_records is None:
                    unspent_coin_records = await self.coin_store.get_unspent_coins_for_wallet(wallet_id)
        amount = uint128(0)
        for record in unspent_coin_records:
            amount = uint128(amount + record.coin.amount)

        return uint128(amount)

    async def get_unconfirmed_balance(self, wallet_id, unspent_coin_records: Optional[Set[WalletCoinRecord]]=None) -> uint128:
        """
        Returns the balance, including coinbase rewards that are not spendable, and unconfirmed
        transactions.
        """
        confirmed = await self.get_confirmed_balance_for_wallet(wallet_id, unspent_coin_records)
        unconfirmed_tx = await self.tx_store.get_unconfirmed_for_wallet(wallet_id)
        removal_amount = 0
        addition_amount = 0
        for record in unconfirmed_tx:
            for removal in record.removals:
                removal_amount += removal.amount

            for addition in record.additions:
                if await self.does_coin_belong_to_wallet(addition, wallet_id):
                    addition_amount += addition.amount

        result = confirmed - removal_amount + addition_amount
        return uint128(result)

    async def unconfirmed_additions_for_wallet(self, wallet_id: int) -> Dict[(bytes32, Coin)]:
        """
        Returns change coins for the wallet_id.
        (Unconfirmed addition transactions that have not been confirmed yet.)
        """
        additions = {}
        unconfirmed_tx = await self.tx_store.get_unconfirmed_for_wallet(wallet_id)
        for record in unconfirmed_tx:
            for coin in record.additions:
                if await self.is_addition_relevant(coin):
                    additions[coin.name()] = coin

        return additions

    async def unconfirmed_removals_for_wallet(self, wallet_id: int) -> Dict[(bytes32, Coin)]:
        """
        Returns new removals transactions that have not been confirmed yet.
        """
        removals = {}
        unconfirmed_tx = await self.tx_store.get_unconfirmed_for_wallet(wallet_id)
        for record in unconfirmed_tx:
            for coin in record.removals:
                removals[coin.name()] = coin

        return removals

    async def new_transaction_block_callback(self, removals: List[Coin], additions: List[Coin], block: BlockRecord, additional_coin_spends: List[CoinSpend]):
        height = block.height
        for coin in additions:
            await self.puzzle_hash_created(coin)

        trade_additions, added = await self.coins_of_interest_added(additions, block)
        trade_removals, removed = await self.coins_of_interest_removed(removals, height)
        if len(trade_additions) > 0 or len(trade_removals) > 0:
            await self.trade_manager.coins_of_interest_farmed(trade_removals, trade_additions, height)
        if len(additional_coin_spends) > 0:
            created_pool_wallet_ids = []
            for cs in additional_coin_spends:
                if cs.coin.puzzle_hash == SINGLETON_LAUNCHER_HASH:
                    already_have = False
                    for wallet_id, wallet in self.wallets.items():
                        if wallet.type() == WalletType.POOLING_WALLET:
                            if (await wallet.get_current_state()).launcher_id == cs.coin.name():
                                self.log.warning('Already have, not recreating')
                                already_have = True

                if not already_have:
                    try:
                        solution_to_extra_data(cs)
                    except Exception as e:
                        try:
                            self.log.debug(f"Not a pool wallet launcher {e}")
                            continue
                        finally:
                            e = None
                            del e

                    self.log.info('Found created launcher. Creating pool wallet')
                    pool_wallet = await PoolWallet.create(self, self.main_wallet, cs.coin.name(), additional_coin_spends, height, True, 'pool_wallet')
                    created_pool_wallet_ids.append(pool_wallet.wallet_id)

            for wallet_id, wallet in self.wallets.items():
                if wallet.type() == WalletType.POOLING_WALLET:
                    await wallet.apply_state_transitions(additional_coin_spends, height)

        added_notified = set()
        removed_notified = set()
        for coin_record in added:
            if coin_record.wallet_id in added_notified:
                continue
            else:
                added_notified.add(coin_record.wallet_id)
                self.state_changed('coin_added', coin_record.wallet_id)

        for coin_record in removed:
            if coin_record.wallet_id in removed_notified:
                continue
            else:
                removed_notified.add(coin_record.wallet_id)
                self.state_changed('coin_removed', coin_record.wallet_id)

        self.tx_pending_changed()

    async def coins_of_interest_added(self, coins: List[Coin], block: BlockRecord) -> Tuple[(List[Coin], List[WalletCoinRecord])]:
        trade_removals, trade_additions = await self.trade_manager.get_coins_of_interest()
        trade_adds = []
        height = block.height
        pool_rewards = set()
        farmer_rewards = set()
        added = []
        prev = await self.blockchain.get_block_record_from_db(block.prev_hash)
        while prev is not None:
            if prev.is_transaction_block:
                break
            else:
                prev = await self.blockchain.get_block_record_from_db(prev.prev_hash)

        if prev is not None:
            pool_parent = pool_parent_id(uint32(prev.height), self.constants.GENESIS_CHALLENGE)
            farmer_parent = farmer_parent_id(uint32(prev.height), self.constants.GENESIS_CHALLENGE)
            pool_rewards.add(pool_parent)
            farmer_rewards.add(farmer_parent)
            prev = await self.blockchain.get_block_record_from_db(prev.prev_hash)
        while prev is not None:
            pool_parent = pool_parent_id(uint32(prev.height), self.constants.GENESIS_CHALLENGE)
            farmer_parent = farmer_parent_id(uint32(prev.height), self.constants.GENESIS_CHALLENGE)
            pool_rewards.add(pool_parent)
            farmer_rewards.add(farmer_parent)
            if prev.is_transaction_block:
                break
            else:
                prev = await self.blockchain.get_block_record_from_db(prev.prev_hash)

        wallet_ids = set()
        for coin in coins:
            info = await self.puzzle_store.wallet_info_for_puzzle_hash(coin.puzzle_hash)
            if info is not None:
                wallet_ids.add(info[0])

        all_outgoing_tx = {}
        for wallet_id in wallet_ids:
            all_outgoing_tx[wallet_id] = await self.tx_store.get_all_transactions_for_wallet(wallet_id, TransactionType.OUTGOING_TX)

        for coin in coins:
            if coin.name() in trade_additions:
                trade_adds.append(coin)
            else:
                is_coinbase = False
                is_fee_reward = False
                if coin.parent_coin_info in pool_rewards:
                    is_coinbase = True
                if coin.parent_coin_info in farmer_rewards:
                    is_fee_reward = True
                info = await self.puzzle_store.wallet_info_for_puzzle_hash(coin.puzzle_hash)
                if info is not None:
                    wallet_id, wallet_type = info
                    added_coin_record = await self.coin_added(coin, is_coinbase, is_fee_reward, uint32(wallet_id), wallet_type, height, all_outgoing_tx.get(wallet_id, []))
                    added.append(added_coin_record)
                else:
                    interested_wallet_id = await self.interested_store.get_interested_puzzle_hash_wallet_id(puzzle_hash=(coin.puzzle_hash))
                    if interested_wallet_id is not None:
                        wallet_type = self.wallets[uint32(interested_wallet_id)].type()
                        added_coin_record = await self.coin_added(coin, is_coinbase, is_fee_reward, uint32(interested_wallet_id), wallet_type, height, all_outgoing_tx.get(interested_wallet_id, []))
                        added.append(added_coin_record)
                derivation_index = await self.puzzle_store.index_for_puzzle_hash(coin.puzzle_hash)
            if derivation_index is not None:
                await self.puzzle_store.set_used_up_to(derivation_index, True)

        return (trade_adds, added)

    async def coins_of_interest_removed(self, coins: List[Coin], height: uint32) -> Tuple[(List[Coin], List[WalletCoinRecord])]:
        if len(coins) > 0:
            self.log.info(f"Coins removed {coins} at height: {height}")
        trade_removals, trade_additions = await self.trade_manager.get_coins_of_interest()
        trade_coin_removed = []
        removed = []
        all_unconfirmed = await self.tx_store.get_all_unconfirmed()
        for coin in coins:
            record = await self.coin_store.get_coin_record(coin.name())
            if coin.name() in trade_removals:
                trade_coin_removed.append(coin)
            if record is None:
                self.log.info(f"Record for removed coin {coin.name()} is None. (ephemeral)")
            else:
                await self.coin_store.set_spent(coin.name(), height)
            for unconfirmed_record in all_unconfirmed:
                for rem_coin in unconfirmed_record.removals:
                    if rem_coin.name() == coin.name():
                        self.log.info(f"Setting tx_id: {unconfirmed_record.name} to confirmed")
                        await self.tx_store.set_confirmed(unconfirmed_record.name, height)

            if record is not None:
                removed.append(record)

        return (trade_coin_removed, removed)

    async def coin_added(self, coin: Coin, coinbase: bool, fee_reward: bool, wallet_id: uint32, wallet_type: WalletType, height: uint32, all_outgoing_transaction_records: List[TransactionRecord]) -> WalletCoinRecord:
        """
        Adding coin to DB
        """
        self.log.info(f"Adding coin: {coin} at {height}")
        farm_reward = False
        if coinbase or fee_reward:
            farm_reward = True
            now = uint64(int(time.time()))
            if coinbase:
                tx_type = TransactionType.COINBASE_REWARD.value
            else:
                tx_type = TransactionType.FEE_REWARD.value
            tx_record = TransactionRecord(confirmed_at_height=(uint32(height)),
              created_at_time=now,
              to_puzzle_hash=(coin.puzzle_hash),
              amount=(coin.amount),
              fee_amount=(uint64(0)),
              confirmed=True,
              sent=(uint32(0)),
              spend_bundle=None,
              additions=[
             coin],
              removals=[],
              wallet_id=wallet_id,
              sent_to=[],
              trade_id=None,
              type=(uint32(tx_type)),
              name=(coin.name()))
            await self.tx_store.add_transaction_record(tx_record, True)
        else:
            records = []
            for record in all_outgoing_transaction_records:
                for add_coin in record.additions:
                    if add_coin.name() == coin.name():
                        records.append(record)

            if len(records) > 0:
                for record in records:
                    if record.confirmed is False:
                        await self.tx_store.set_confirmed(record.name, height)

            else:
                now = uint64(int(time.time()))
                tx_record = TransactionRecord(confirmed_at_height=(uint32(height)),
                  created_at_time=now,
                  to_puzzle_hash=(coin.puzzle_hash),
                  amount=(coin.amount),
                  fee_amount=(uint64(0)),
                  confirmed=True,
                  sent=(uint32(0)),
                  spend_bundle=None,
                  additions=[
                 coin],
                  removals=[],
                  wallet_id=wallet_id,
                  sent_to=[],
                  trade_id=None,
                  type=(uint32(TransactionType.INCOMING_TX.value)),
                  name=(coin.name()))
                if coin.amount > 0:
                    await self.tx_store.add_transaction_record(tx_record, True)
        coin_record = WalletCoinRecord(coin, height, uint32(0), False, farm_reward, wallet_type, wallet_id)
        await self.coin_store.add_coin_record(coin_record)
        if wallet_type == WalletType.COLOURED_COIN or wallet_type == WalletType.DISTRIBUTED_ID:
            wallet = self.wallets[wallet_id]
            await wallet.coin_added(coin, height)
        return coin_record

    async def add_pending_transaction(self, tx_record: TransactionRecord):
        """
        Called from wallet before new transaction is sent to the full_node
        """
        if self.peak is None or int(time.time()) <= self.constants.INITIAL_FREEZE_END_TIMESTAMP:
            raise ValueError('Initial Freeze Period')
        await self.tx_store.add_transaction_record(tx_record, False)
        self.tx_pending_changed()
        self.state_changed('pending_transaction', tx_record.wallet_id)

    async def add_transaction(self, tx_record: TransactionRecord):
        """
        Called from wallet to add transaction that is not being set to full_node
        """
        await self.tx_store.add_transaction_record(tx_record, False)
        self.state_changed('pending_transaction', tx_record.wallet_id)

    async def remove_from_queue(self, spendbundle_id: bytes32, name: str, send_status: MempoolInclusionStatus, error: Optional[Err]):
        """
        Full node received our transaction, no need to keep it in queue anymore
        """
        updated = await self.tx_store.increment_sent(spendbundle_id, name, send_status, error)
        if updated:
            tx = await self.get_transaction(spendbundle_id)
            if tx is not None:
                self.state_changed('tx_update', tx.wallet_id, {'transaction': tx})

    async def get_all_transactions(self, wallet_id: int) -> List[TransactionRecord]:
        """
        Retrieves all confirmed and pending transactions
        """
        records = await self.tx_store.get_all_transactions_for_wallet(wallet_id)
        return records

    async def get_transaction(self, tx_id: bytes32) -> Optional[TransactionRecord]:
        return await self.tx_store.get_transaction_record(tx_id)

    async def get_filter_additions_removals(self, new_block: HeaderBlock, transactions_filter: bytes, fork_point_with_peak: Optional[uint32]) -> Tuple[(List[bytes32], List[bytes32])]:
        """Returns a list of our coin ids, and a list of puzzle_hashes that positively match with provided filter."""
        tx_filter = PyBIP158([b for b in transactions_filter])
        if fork_point_with_peak is not None:
            fork_h = fork_point_with_peak
        else:
            if new_block.prev_header_hash != self.constants.GENESIS_CHALLENGE and self.peak is not None:
                block_record = await self.blockchain.get_block_record_from_db(self.peak.header_hash)
                fork_h = find_fork_point_in_chain(self.blockchain, block_record, new_block)
            else:
                fork_h = 0
        my_coin_records = await self.coin_store.get_unspent_coins_at_height(uint32(fork_h) if fork_h >= 0 else None)
        unspent_coin_names = set()
        for coin in my_coin_records:
            if coin.confirmed_block_height <= fork_h:
                unspent_coin_names.add(coin.name())

        if new_block.height > 0:
            curr = self.blockchain.block_record(new_block.prev_hash)
            reorg_blocks = []
            while curr.height > fork_h:
                header_block_record = await self.block_store.get_header_block_record(curr.header_hash)
                assert header_block_record is not None
                reorg_blocks.append(header_block_record)
                if curr.height == 0:
                    break
                else:
                    curr = await self.blockchain.get_block_record_from_db(curr.prev_hash)

            reorg_blocks.reverse()
            for reorg_block in reorg_blocks:
                for addition in reorg_block.additions:
                    unspent_coin_names.add(addition.name())

                for removal in reorg_block.removals:
                    record = await self.puzzle_store.get_derivation_record_for_puzzle_hash(removal.puzzle_hash)
                    if record is None:
                        continue
                    else:
                        unspent_coin_names.remove(removal)

        my_puzzle_hashes = self.puzzle_store.all_puzzle_hashes
        removals_of_interest = []
        additions_of_interest = []
        trade_removals, trade_additions = await self.trade_manager.get_coins_of_interest()
        for name, trade_coin in trade_removals.items():
            if tx_filter.Match(bytearray(trade_coin.name())):
                removals_of_interest.append(trade_coin.name())

        for name, trade_coin in trade_additions.items():
            if tx_filter.Match(bytearray(trade_coin.puzzle_hash)):
                additions_of_interest.append(trade_coin.puzzle_hash)

        for coin_name in unspent_coin_names:
            if tx_filter.Match(bytearray(coin_name)):
                removals_of_interest.append(coin_name)

        for puzzle_hash in my_puzzle_hashes:
            if tx_filter.Match(bytearray(puzzle_hash)):
                additions_of_interest.append(puzzle_hash)

        for coin_id in await self.interested_store.get_interested_coin_ids():
            if tx_filter.Match(bytearray(coin_id)):
                removals_of_interest.append(coin_id)

        for puzzle_hash, _ in await self.interested_store.get_interested_puzzle_hashes():
            if tx_filter.Match(bytearray(puzzle_hash)):
                additions_of_interest.append(puzzle_hash)

        return (additions_of_interest, removals_of_interest)

    async def is_addition_relevant(self, addition: Coin):
        """
        Check whether we care about a new addition (puzzle_hash). Returns true if we
        control this puzzle hash.
        """
        result = await self.puzzle_store.puzzle_hash_exists(addition.puzzle_hash)
        return result

    async def get_wallet_for_coin(self, coin_id: bytes32) -> Any:
        coin_record = await self.coin_store.get_coin_record(coin_id)
        if coin_record is None:
            return
        wallet_id = uint32(coin_record.wallet_id)
        wallet = self.wallets[wallet_id]
        return wallet

    async def reorg_rollback(self, height: int):
        """
        Rolls back and updates the coin_store and transaction store. It's possible this height
        is the tip, or even beyond the tip.
        """
        await self.coin_store.rollback_to_block(height)
        reorged = await self.tx_store.get_transaction_above(height)
        await self.tx_store.rollback_to_block(height)
        for record in reorged:
            if record.type in [
             TransactionType.OUTGOING_TX,
             TransactionType.OUTGOING_TRADE,
             TransactionType.INCOMING_TRADE]:
                await self.tx_store.tx_reorged(record)

        remove_ids = []
        for wallet_id, wallet in self.wallets.items():
            if wallet.type() == WalletType.POOLING_WALLET.value:
                remove = await wallet.rewind(height)
                if remove:
                    remove_ids.append(wallet_id)

        for wallet_id in remove_ids:
            await self.user_store.delete_wallet(wallet_id, in_transaction=True)
            self.wallets.pop(wallet_id)
            self.new_peak_callbacks.pop(wallet_id)

    async def close_all_stores(self) -> None:
        if self.blockchain is not None:
            self.blockchain.shut_down()
        await self.db_connection.close()

    async def clear_all_stores(self):
        await self.coin_store._clear_database()
        await self.tx_store._clear_database()
        await self.puzzle_store._clear_database()
        await self.user_store._clear_database()
        await self.basic_store._clear_database()

    def unlink_db(self):
        Path(self.db_path).unlink()

    async def get_all_wallet_info_entries(self) -> List[WalletInfo]:
        return await self.user_store.get_all_wallet_info_entries()

    async def get_start_height(self):
        """
        If we have coin use that as starting height next time,
        otherwise use the peak
        """
        first_coin_height = await self.coin_store.get_first_coin_height()
        if first_coin_height is None:
            start_height = self.blockchain.get_peak()
        else:
            start_height = first_coin_height
        return start_height

    async def create_wallet_backup(self, file_path: Path):
        all_wallets = await self.get_all_wallet_info_entries()
        for wallet in all_wallets:
            if wallet.id == 1:
                all_wallets.remove(wallet)
                break

        backup_pk = master_sk_to_backup_sk(self.private_key)
        now = uint64(int(time.time()))
        wallet_backup = WalletInfoBackup(all_wallets)
        backup = {}
        data = wallet_backup.to_json_dict()
        data['version'] = __version__
        data['fingerprint'] = self.private_key.get_g1().get_fingerprint()
        data['timestamp'] = now
        data['start_height'] = await self.get_start_height()
        key_base_64 = base64.b64encode(bytes(backup_pk))
        f = Fernet(key_base_64)
        data_bytes = json.dumps(data).encode()
        encrypted = f.encrypt(data_bytes)
        meta_data = {'timestamp':now, 
         'pubkey':bytes(backup_pk.get_g1()).hex()}
        meta_data_bytes = json.dumps(meta_data).encode()
        signature = bytes(AugSchemeMPL.sign(backup_pk, std_hash(encrypted) + std_hash(meta_data_bytes))).hex()
        backup['data'] = encrypted.decode()
        backup['meta_data'] = meta_data
        backup['signature'] = signature
        backup_file_text = json.dumps(backup)
        file_path.write_text(backup_file_text)

    async def import_backup_info(self, file_path) -> None:
        json_dict = open_backup_file(file_path, self.private_key)
        wallet_list_json = json_dict['data']['wallet_list']
        for wallet_info in wallet_list_json:
            await self.user_store.create_wallet(wallet_info['name'], wallet_info['type'], wallet_info['data'], wallet_info['id'])

        await self.load_wallets()
        await self.user_settings.user_imported_backup()
        await self.create_more_puzzle_hashes(from_zero=True)

    async def get_wallet_for_colour(self, colour):
        for wallet_id in self.wallets:
            wallet = self.wallets[wallet_id]
            if wallet.type() == WalletType.COLOURED_COIN:
                if bytes(wallet.cc_info.my_genesis_checker).hex() == colour:
                    return wallet

    async def add_new_wallet(self, wallet: Any, wallet_id: int, create_puzzle_hashes=True):
        self.wallets[uint32(wallet_id)] = wallet
        if create_puzzle_hashes:
            await self.create_more_puzzle_hashes()

    async def search_blockrecords_for_puzzlehash(self, puzzlehash: bytes32):
        header_hash_of_interest = None
        highest_block_height = 0
        peak = self.blockchain.get_peak()
        if peak is None:
            return (None, None)
        peak_block = await self.blockchain.block_store.get_header_block_record(peak.header_hash)
        while peak_block is not None:
            tx_filter = PyBIP158([b for b in peak_block.header.transactions_filter])
            if tx_filter.Match(bytearray(puzzlehash)) and peak_block.height > highest_block_height:
                header_hash_of_interest = peak_block.header_hash
                highest_block_height = peak_block.height
                break
            else:
                peak_block = await self.blockchain.block_store.get_header_block_record(peak_block.header.prev_header_hash)

        return (
         highest_block_height, header_hash_of_interest)

    async def get_spendable_coins_for_wallet(self, wallet_id: int, records=None) -> Set[WalletCoinRecord]:
        if self.peak is None:
            return set()
        if records is None:
            records = await self.coin_store.get_unspent_coins_for_wallet(wallet_id)
        unconfirmed_tx = await self.tx_store.get_unconfirmed_for_wallet(wallet_id)
        removal_dict = {}
        for tx in unconfirmed_tx:
            for coin in tx.removals:
                if await self.does_coin_belong_to_wallet(coin, wallet_id):
                    removal_dict[coin.name()] = coin

        offer_locked_coins = await self.trade_manager.get_locked_coins()
        filtered = set()
        for record in records:
            if record.coin.name() in offer_locked_coins:
                continue
            if record.coin.name() in removal_dict:
                continue
            else:
                filtered.add(record)

        return filtered

    async def create_action(self, name, wallet_id, wallet_type, callback, done, data, in_transaction):
        await self.action_store.create_action(name, wallet_id, wallet_type, callback, done, data, in_transaction)
        self.tx_pending_changed()

    async def set_action_done(self, action_id: int):
        await self.action_store.action_done(action_id)

    async def generator_received(self, height: uint32, header_hash: uint32, program: Program):
        actions = await self.action_store.get_all_pending_actions()
        for action in actions:
            data = json.loads(action.data)
            action_data = data['data']['action_data']
            if action.name == 'request_generator':
                stored_header_hash = bytes32(hexstr_to_bytes(action_data['header_hash']))
                stored_height = uint32(action_data['height'])
                if stored_header_hash == header_hash:
                    if stored_height == height:
                        if action.done:
                            return
                        else:
                            wallet = self.wallets[uint32(action.wallet_id)]
                            callback_str = action.wallet_callback
                        if callback_str is not None:
                            callback = getattr(wallet, callback_str)
                            await callback(height, header_hash, program, action.id)

    async def puzzle_solution_received(self, response: RespondPuzzleSolution):
        unwrapped = response.response
        actions = await self.action_store.get_all_pending_actions()
        for action in actions:
            data = json.loads(action.data)
            action_data = data['data']['action_data']
            if action.name == 'request_puzzle_solution':
                stored_coin_name = bytes32(hexstr_to_bytes(action_data['coin_name']))
                height = uint32(action_data['height'])
                if stored_coin_name == unwrapped.coin_name:
                    if height == unwrapped.height:
                        if action.done:
                            return
                        else:
                            wallet = self.wallets[uint32(action.wallet_id)]
                            callback_str = action.wallet_callback
                        if callback_str is not None:
                            callback = getattr(wallet, callback_str)
                            await callback(unwrapped, action.id)

    def get_peak(self) -> Optional[BlockRecord]:
        return self.blockchain.get_peak()

    async def get_next_interesting_coin_ids(self, spend: CoinSpend, in_transaction: bool) -> List[bytes32]:
        pool_wallet_interested = PoolWallet.get_next_interesting_coin_ids(spend)
        for coin_id in pool_wallet_interested:
            await self.interested_store.add_interested_coin_id(coin_id, in_transaction)

        return pool_wallet_interested

    async def new_peak(self):
        peak = self.get_peak()
        if peak is None:
            return
        for wallet_id, callback in self.new_peak_callbacks.items():
            await callback(peak)