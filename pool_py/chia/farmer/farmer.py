# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\farmer\farmer.py
import asyncio, json, logging, time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import traceback, aiohttp
from blspy import AugSchemeMPL, G1Element, G2Element, PrivateKey
import chia.server.ws_connection as ws
from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.consensus.constants import ConsensusConstants
from chia.pools.pool_config import PoolWalletConfig, load_pool_config
from chia.protocols import farmer_protocol, harvester_protocol
from chia.protocols.pool_protocol import ErrorResponse, get_current_authentication_token, GetFarmerResponse, PoolErrorCode, PostFarmerPayload, PostFarmerRequest, PutFarmerPayload, PutFarmerRequest, AuthenticationPayload
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import NodeType, make_msg
from chia.server.server import ssl_context_for_root
from chia.server.ws_connection import WSChiaConnection
from chia.ssl.create_ssl import get_mozilla_ca_crt
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32, bytes48
from chia.util.bech32m import decode_puzzle_hash, bech32_decode
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config, save_config, config_path_for_filename
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint16, uint32, uint64
from chia.util.keychain import Keychain
from chia.wallet.derive_keys import master_sk_to_farmer_sk, master_sk_to_pool_sk, master_sk_to_wallet_sk, find_authentication_sk, find_owner_sk
from chia.wallet.puzzles.singleton_top_layer import SINGLETON_MOD
singleton_mod_hash = SINGLETON_MOD.get_tree_hash()
log = logging.getLogger(__name__)
UPDATE_POOL_INFO_INTERVAL: int = 3600
UPDATE_POOL_FARMER_INFO_INTERVAL: int = 300
UPDATE_HARVESTER_CACHE_INTERVAL: int = 90

class HarvesterCacheEntry:

    def __init__(self):
        self.data = None
        self.last_update = 0

    def bump_last_update(self):
        self.last_update = time.time()

    def set_data(self, data):
        self.data = data
        self.bump_last_update()

    def needs_update(self):
        return time.time() - self.last_update > UPDATE_HARVESTER_CACHE_INTERVAL

    def expired(self):
        return time.time() - self.last_update > UPDATE_HARVESTER_CACHE_INTERVAL * 10


class Farmer:

    def __init__(self, root_path, farmer_config, pool_config, keychain, consensus_constants):
        self._root_path = root_path
        self.config = farmer_config
        self.sps = {}
        self.proofs_of_space = {}
        self.quality_str_to_identifiers = {}
        self.number_of_responses = {}
        self.cache_add_time = {}
        self.lastChannageTime = 0
        self
        self
        self.constants = consensus_constants
        self._shut_down = False
        self.server = None
        self.keychain = keychain
        self.state_changed_callback = None
        self.log = log
        self.all_root_sks = [sk for sk, _ in self.keychain.get_all_private_keys()]
        self._private_keys = [master_sk_to_farmer_sk(sk) for sk in self.all_root_sks] + [master_sk_to_pool_sk(sk) for sk in self.all_root_sks]
        if len(self.get_public_keys()) == 0:
            error_str = "No keys exist. Please run 'chia keys generate' or open the UI."
            raise RuntimeError(error_str)
        self.farmer_target_encoded = self.config['xch_target_address']
        self.farmer_target = decode_puzzle_hash(self.farmer_target_encoded)
        self.pool_public_keys = [G1Element.from_bytes(bytes.fromhex(pk)) for pk in self.config['pool_public_keys']]
        self.pool_target_encoded = pool_config['xch_target_address']
        self.pool_target = decode_puzzle_hash(self.pool_target_encoded)
        self.pool_sks_map = {}
        for key in self.get_private_keys():
            self.pool_sks_map[bytes(key.get_g1())] = key

        assert len(self.farmer_target) == 32
        assert len(self.pool_target) == 32
        if len(self.pool_sks_map) == 0:
            error_str = "No keys exist. Please run 'chia keys generate' or open the UI."
            raise RuntimeError(error_str)
        self.pool_state = {}
        self.pool_state_map_chia_to_rose_contract = {}
        self.pool_state_map_ppky_to_rose_contract = {}
        self.pool_state_map_rose_to_chia = {}
        self.pool_state_map_rose_to_ppky_contract = {}
        self.authentication_keys = {}
        self.last_config_access_time = uint64(0)
        self.harvester_cache = {}

    async def _start(self):
        self.update_pool_state_task = asyncio.create_task(self._periodically_update_pool_state_task())
        self.cache_clear_task = asyncio.create_task(self._periodically_clear_cache_and_refresh_task())

    def _close(self):
        self._shut_down = True

    async def _await_closed(self):
        await self.cache_clear_task
        await self.update_pool_state_task

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

    async def on_connect(self, peer: WSChiaConnection):
        self.state_changed('add_connection', {})
        handshake = harvester_protocol.HarvesterHandshake(self.get_public_keys(), self.pool_public_keys)
        if peer.connection_type is NodeType.HARVESTER:
            msg = make_msg(ProtocolMessageTypes.harvester_handshake, handshake)
            await peer.send_message(msg)

    def set_server(self, server):
        self.server = server

    def state_changed(self, change: str, data: Dict[(str, Any)]):
        if self.state_changed_callback is not None:
            self.state_changed_callback(change, data)

    def handle_failed_pool_response(self, p2_singleton_puzzle_hash: bytes32, error_message: str):
        self.log.error(error_message)
        self.pool_state[p2_singleton_puzzle_hash]['pool_errors_24h'].append(ErrorResponse(uint16(PoolErrorCode.REQUEST_FAILED.value), error_message).to_json_dict())

    def on_disconnect(self, connection: ws.WSChiaConnection):
        self.log.info(f"peer disconnected {connection.get_peer_info()}")
        self.state_changed('close_connection', {})

    async def _pool_get_pool_info(self, pool_config: PoolWalletConfig) -> Optional[Dict]:
        try:
            async with aiohttp.ClientSession(trust_env=True) as session:
                async with session.get(f"{pool_config.pool_url}/pool_info",
                  ssl=(ssl_context_for_root(get_mozilla_ca_crt()))) as resp:
                    if resp.ok:
                        response = json.loads(await resp.text())
                        self.log.info(f"GET /pool_info response: {response}")
                        return response
                    self.handle_failed_pool_response(pool_config.p2_singleton_puzzle_hash, f"Error in GET /pool_info {pool_config.pool_url}, {resp.status}")
        except Exception as e:
            try:
                self.handle_failed_pool_response(pool_config.p2_singleton_puzzle_hash, f"Exception in GET /pool_info {pool_config.pool_url}, {e}")
            finally:
                e = None
                del e

    async def _pool_get_farmer(self, pool_config: PoolWalletConfig, authentication_token_timeout: uint8, authentication_sk: PrivateKey) -> Optional[Dict]:
        assert authentication_sk.get_g1() == pool_config.authentication_public_key
        authentication_token = get_current_authentication_token(authentication_token_timeout)
        message = std_hash(AuthenticationPayload('get_farmer', pool_config.launcher_id, pool_config.target_puzzle_hash, authentication_token))
        signature = AugSchemeMPL.sign(authentication_sk, message)
        get_farmer_params = {'launcher_id':pool_config.launcher_id.hex(), 
         'authentication_token':authentication_token, 
         'signature':bytes(signature).hex()}
        try:
            async with aiohttp.ClientSession(trust_env=True) as session:
                async with session.get(f"{pool_config.pool_url}/farmer",
                  params=get_farmer_params,
                  ssl=(ssl_context_for_root(get_mozilla_ca_crt()))) as resp:
                    if resp.ok:
                        response = json.loads(await resp.text())
                        self.log.info(f"GET /farmer response: {response}")
                        if 'error_code' in response:
                            self.pool_state[pool_config.p2_singleton_puzzle_hash]['pool_errors_24h'].append(response)
                        return response
                    self.handle_failed_pool_response(pool_config.p2_singleton_puzzle_hash, f"Error in GET /farmer {pool_config.pool_url}, {resp.status}")
        except Exception as e:
            try:
                self.handle_failed_pool_response(pool_config.p2_singleton_puzzle_hash, f"Exception in GET /farmer {pool_config.pool_url}, {e}")
            finally:
                e = None
                del e

    async def _pool_post_farmer(self, pool_config: PoolWalletConfig, authentication_token_timeout: uint8, owner_sk: PrivateKey) -> Optional[Dict]:
        post_farmer_payload = PostFarmerPayload(pool_config.launcher_id, get_current_authentication_token(authentication_token_timeout), pool_config.authentication_public_key, pool_config.payout_instructions, None)
        assert owner_sk.get_g1() == pool_config.owner_public_key
        signature = AugSchemeMPL.sign(owner_sk, post_farmer_payload.get_hash())
        post_farmer_request = PostFarmerRequest(post_farmer_payload, signature)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{pool_config.pool_url}/farmer",
                  json=(post_farmer_request.to_json_dict()),
                  ssl=(ssl_context_for_root(get_mozilla_ca_crt()))) as resp:
                    if resp.ok:
                        response = json.loads(await resp.text())
                        self.log.info(f"POST /farmer response: {response}")
                        if 'error_code' in response:
                            self.pool_state[pool_config.p2_singleton_puzzle_hash]['pool_errors_24h'].append(response)
                        return response
                    self.handle_failed_pool_response(pool_config.p2_singleton_puzzle_hash, f"Error in POST /farmer {pool_config.pool_url}, {resp.status}")
        except Exception as e:
            try:
                self.handle_failed_pool_response(pool_config.p2_singleton_puzzle_hash, f"Exception in POST /farmer {pool_config.pool_url}, {e}")
            finally:
                e = None
                del e

    async def _pool_put_farmer(self, pool_config: PoolWalletConfig, authentication_token_timeout: uint8, owner_sk: PrivateKey) -> Optional[Dict]:
        put_farmer_payload = PutFarmerPayload(pool_config.launcher_id, get_current_authentication_token(authentication_token_timeout), pool_config.authentication_public_key, pool_config.payout_instructions, None)
        assert owner_sk.get_g1() == pool_config.owner_public_key
        signature = AugSchemeMPL.sign(owner_sk, put_farmer_payload.get_hash())
        put_farmer_request = PutFarmerRequest(put_farmer_payload, signature)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(f"{pool_config.pool_url}/farmer",
                  json=(put_farmer_request.to_json_dict()),
                  ssl=(ssl_context_for_root(get_mozilla_ca_crt()))) as resp:
                    if resp.ok:
                        response = json.loads(await resp.text())
                        self.log.info(f"PUT /farmer response: {response}")
                        if 'error_code' in response:
                            self.pool_state[pool_config.p2_singleton_puzzle_hash]['pool_errors_24h'].append(response)
                        return response
                    self.handle_failed_pool_response(pool_config.p2_singleton_puzzle_hash, f"Error in PUT /farmer {pool_config.pool_url}, {resp.status}")
        except Exception as e:
            try:
                self.handle_failed_pool_response(pool_config.p2_singleton_puzzle_hash, f"Exception in PUT /farmer {pool_config.pool_url}, {e}")
            finally:
                e = None
                del e

    async def update_pool_state(self):
        config = load_config(self._root_path, 'config.yaml')
        pool_config_list = load_pool_config(self._root_path)
        for pool_config in pool_config_list:
            p2_singleton_puzzle_hash = pool_config.p2_singleton_puzzle_hash
            try:
                authentication_sk = await find_authentication_sk(self.all_root_sks, pool_config.authentication_public_key)
                if authentication_sk is None:
                    self.log.error(f"Could not find authentication sk for pk: {pool_config.authentication_public_key}")
                    continue
                else:
                    if p2_singleton_puzzle_hash not in self.pool_state:
                        self.authentication_keys[bytes(pool_config.authentication_public_key)] = authentication_sk
                        self.pool_state[p2_singleton_puzzle_hash] = {'points_found_since_start':0, 
                         'points_found_24h':[],  'points_acknowledged_since_start':0, 
                         'points_acknowledged_24h':[],  'next_farmer_update':0, 
                         'next_pool_info_update':0, 
                         'current_points':0, 
                         'current_difficulty':None, 
                         'pool_errors_24h':[],  'authentication_token_timeout':None}
                        self.log.info(f"Added pool: {pool_config}")
                        if pool_config.p2_chia_contract_or_pool_public_key is not None:
                            hrpgot, data = bech32_decode(pool_config.p2_chia_contract_or_pool_public_key)
                            if data is not None:
                                p2_chia_contract = decode_puzzle_hash(pool_config.p2_chia_contract_or_pool_public_key)
                                if p2_chia_contract is not None:
                                    self.pool_state_map_rose_to_chia[p2_singleton_puzzle_hash] = p2_chia_contract
                                    self.pool_state_map_chia_to_rose_contract[p2_chia_contract] = p2_singleton_puzzle_hash
                            else:
                                if len(pool_config.p2_chia_contract_or_pool_public_key) > 40:
                                    pk_bytes = hexstr_to_bytes(pool_config.p2_chia_contract_or_pool_public_key)
                                    if pk_bytes is not None:
                                        self.pool_state_map_ppky_to_rose_contract[pk_bytes] = p2_singleton_puzzle_hash
                                        self.pool_state_map_rose_to_ppky_contract[p2_singleton_puzzle_hash] = pk_bytes
                    pool_state = self.pool_state[p2_singleton_puzzle_hash]
                    pool_state['pool_config'] = pool_config
                if pool_config.pool_url == '':
                    continue
                else:
                    if time.time() >= pool_state['next_pool_info_update']:
                        pool_info = await self._pool_get_pool_info(pool_config)
                        if pool_info is not None:
                            if 'error_code' not in pool_info:
                                pool_state['authentication_token_timeout'] = pool_info['authentication_token_timeout']
                                pool_state['next_pool_info_update'] = time.time() + UPDATE_POOL_INFO_INTERVAL
                                if pool_state['current_difficulty'] is None:
                                    pool_state['current_difficulty'] = pool_info['minimum_difficulty']
                    if time.time() >= pool_state['next_farmer_update']:
                        authentication_token_timeout = pool_state['authentication_token_timeout']

                        async def update_pool_farmer_info():
                            response = await self._pool_get_farmer(pool_config, authentication_token_timeout, authentication_sk)
                            farmer_response = None
                            farmer_known = None
                            if response is not None:
                                if 'error_code' not in response:
                                    farmer_response = GetFarmerResponse.from_json_dict(response)
                                    if farmer_response is not None:
                                        pool_state['current_difficulty'] = farmer_response.current_difficulty
                                        pool_state['current_points'] = farmer_response.current_points
                                        pool_state['next_farmer_update'] = time.time() + UPDATE_POOL_FARMER_INFO_INTERVAL
                                else:
                                    farmer_known = response['error_code'] != PoolErrorCode.FARMER_NOT_KNOWN.value
                                    self.log.error(f"update_pool_farmer_info failed: {response['error_code']}, {response['error_message']}")
                            return (
                             farmer_response, farmer_known)

                        if authentication_token_timeout is not None:
                            farmer_info, farmer_is_known = await update_pool_farmer_info()
                            if not farmer_info is None or farmer_is_known is not None:
                                if not farmer_is_known:
                                    owner_sk = await find_owner_sk(self.all_root_sks, pool_config.owner_public_key)
                                    post_response = await self._pool_post_farmer(pool_config, authentication_token_timeout, owner_sk)
                                    if post_response is not None:
                                        if 'error_code' not in post_response:
                                            self.log.info(f"Welcome message from {pool_config.pool_url}: {post_response['welcome_message']}")
                                            farmer_info, farmer_is_known = await update_pool_farmer_info()
                                            if farmer_info is None:
                                                if not farmer_is_known:
                                                    self.log.error('Failed to update farmer info after POST /farmer.')
                                if not farmer_info is not None or pool_config.payout_instructions.lower() != farmer_info.payout_instructions.lower():
                                    owner_sk = await find_owner_sk(self.all_root_sks, pool_config.owner_public_key)
                                    put_farmer_response_dict = await self._pool_put_farmer(pool_config, authentication_token_timeout, owner_sk)
                                    try:
                                        if put_farmer_response_dict['payout_instructions']:
                                            self.log.info(f"Farmer information successfully updated on the pool {pool_config.pool_url}")
                                        else:
                                            raise Exception
                                    except Exception:
                                        self.log.error(f"Failed to update farmer information on the pool {pool_config.pool_url}")

                        else:
                            self.log.warning(f"No pool specific authentication_token_timeout has been set for {p2_singleton_puzzle_hash}, check communication with the pool.")
            except Exception as e:
                try:
                    tb = traceback.format_exc()
                    self.log.error(f"Exception in update_pool_state for {pool_config.pool_url}, {e} {tb}")
                finally:
                    e = None
                    del e

    def get_public_keys(self):
        return [child_sk.get_g1() for child_sk in self._private_keys]

    def get_private_keys(self):
        return self._private_keys

    def get_rose_hash_by_proof(self, proof: ProofOfSpace) -> bytes32:
        p2_singleton_rose_puzzle_hash = None
        if proof.pool_contract_puzzle_hash is not None:
            if proof.pool_contract_puzzle_hash not in self.pool_state:
                if proof.pool_contract_puzzle_hash in self.pool_state_map_chia_to_rose_contract:
                    p2_singleton_rose_puzzle_hash = self.pool_state_map_chia_to_rose_contract[proof.pool_contract_puzzle_hash]
        if proof.pool_contract_puzzle_hash is None:
            if proof.pool_public_key is not None:
                if bytes(proof.pool_public_key) in self.pool_state_map_ppky_to_rose_contract:
                    p2_singleton_rose_puzzle_hash = self.pool_state_map_ppky_to_rose_contract[bytes(proof.pool_public_key)]
        return p2_singleton_rose_puzzle_hash

    def get_reward_targets(self, search_for_private_key: bool) -> Dict:
        if search_for_private_key:
            all_sks = self.keychain.get_all_private_keys()
            stop_searching_for_farmer, stop_searching_for_pool = (False, False)
            for i in range(500):
                if stop_searching_for_farmer:
                    if stop_searching_for_pool:
                        if i > 0:
                            break
                for sk, _ in all_sks:
                    ph = create_puzzlehash_for_pk(master_sk_to_wallet_sk(sk, uint32(i)).get_g1())
                    if ph == self.farmer_target:
                        stop_searching_for_farmer = True
                    if ph == self.pool_target:
                        stop_searching_for_pool = True

            return {'farmer_target':self.farmer_target_encoded, 
             'pool_target':self.pool_target_encoded, 
             'have_farmer_sk':stop_searching_for_farmer, 
             'have_pool_sk':stop_searching_for_pool}
        return {'farmer_target':self.farmer_target_encoded, 
         'pool_target':self.pool_target_encoded}

    def set_reward_targets(self, farmer_target_encoded: Optional[str], pool_target_encoded: Optional[str]):
        config = load_config(self._root_path, 'config.yaml')
        if farmer_target_encoded is not None:
            self.farmer_target_encoded = farmer_target_encoded
            self.farmer_target = decode_puzzle_hash(farmer_target_encoded)
            config['farmer']['xch_target_address'] = farmer_target_encoded
        if pool_target_encoded is not None:
            self.pool_target_encoded = pool_target_encoded
            self.pool_target = decode_puzzle_hash(pool_target_encoded)
            config['pool']['xch_target_address'] = pool_target_encoded
        save_config(self._root_path, 'config.yaml', config)

    async def set_payout_instructions(self, launcher_id: bytes32, payout_instructions: str):
        for p2_singleton_puzzle_hash, pool_state_dict in self.pool_state.items():
            if launcher_id == pool_state_dict['pool_config'].launcher_id:
                config = load_config(self._root_path, 'config.yaml')
                new_list = []
                for list_element in config['pool']['pool_list']:
                    if hexstr_to_bytes(list_element['launcher_id']) == bytes(launcher_id):
                        list_element['payout_instructions'] = payout_instructions
                    else:
                        new_list.append(list_element)

                config['pool']['pool_list'] = new_list
                save_config(self._root_path, 'config.yaml', config)
                pool_state_dict['next_farmer_update'] = 0
                return

        self.log.warning(f"Launcher id: {launcher_id} not found")

    async def generate_login_link(self, launcher_id: bytes32) -> Optional[str]:
        for pool_state in self.pool_state.values():
            pool_config = pool_state['pool_config']
            if pool_config.launcher_id == launcher_id:
                authentication_sk = await find_authentication_sk(self.all_root_sks, pool_config.authentication_public_key)
                if authentication_sk is None:
                    self.log.error(f"Could not find authentication sk for pk: {pool_config.authentication_public_key}")
                    continue
                else:
                    assert authentication_sk.get_g1() == pool_config.authentication_public_key
                    authentication_token_timeout = pool_state['authentication_token_timeout']
                    authentication_token = get_current_authentication_token(authentication_token_timeout)
                    message = std_hash(AuthenticationPayload('get_login', pool_config.launcher_id, pool_config.target_puzzle_hash, authentication_token))
                    signature = AugSchemeMPL.sign(authentication_sk, message)
                    return pool_config.pool_url + f"/login?launcher_id={launcher_id.hex()}&authentication_token={authentication_token}&signature={bytes(signature).hex()}"

    async def update_cached_harvesters(self) -> bool:
        self.log.debug(f"update_cached_harvesters cache entries: {len(self.harvester_cache)}")
        remove_hosts = []
        for host, host_cache in self.harvester_cache.items():
            remove_peers = []
            for peer_id, peer_cache in host_cache.items():
                if peer_cache.expired():
                    remove_peers.append(peer_id)

            for key in remove_peers:
                del host_cache[key]

            if len(host_cache) == 0:
                self.log.debug(f"update_cached_harvesters remove host: {host}")
                remove_hosts.append(host)

        for key in remove_hosts:
            del self.harvester_cache[key]

        updated = False
        for connection in self.server.get_connections(NodeType.HARVESTER):
            cache_entry = await self.get_cached_harvesters(connection)
            if cache_entry.needs_update():
                self.log.debug(f"update_cached_harvesters update harvester: {connection.peer_node_id}")
                cache_entry.bump_last_update()
                response = await connection.request_plots((harvester_protocol.RequestPlots()),
                  timeout=UPDATE_HARVESTER_CACHE_INTERVAL)
                if response is not None:
                    if isinstance(response, harvester_protocol.RespondPlots):
                        new_data = response.to_json_dict()
                        if cache_entry.data != new_data:
                            updated = True
                            self.log.debug(f"update_cached_harvesters cache updated: {connection.peer_node_id}")
                        else:
                            self.log.debug(f"update_cached_harvesters no changes for: {connection.peer_node_id}")
                        cache_entry.set_data(new_data)
                    else:
                        self.log.error(f"Invalid response from harvester:peer_host {connection.peer_host}, peer_node_id {connection.peer_node_id}")
                else:
                    self.log.error('Harvester did not respond. You might need to update harvester to the latest version')

        return updated

    async def get_cached_harvesters(self, connection: WSChiaConnection) -> HarvesterCacheEntry:
        host_cache = self.harvester_cache.get(connection.peer_host)
        if host_cache is None:
            host_cache = {}
            self.harvester_cache[connection.peer_host] = host_cache
        node_cache = host_cache.get(connection.peer_node_id.hex())
        if node_cache is None:
            node_cache = HarvesterCacheEntry()
            host_cache[connection.peer_node_id.hex()] = node_cache
        return node_cache

    async def get_harvesters(self) -> Dict:
        harvesters = []
        for connection in self.server.get_connections(NodeType.HARVESTER):
            self.log.debug(f"get_harvesters host: {connection.peer_host}, node_id: {connection.peer_node_id}")
            cache_entry = await self.get_cached_harvesters(connection)
            if cache_entry.data is not None:
                harvester_object = dict(cache_entry.data)
                harvester_object['connection'] = {'node_id':connection.peer_node_id.hex(), 
                 'host':connection.peer_host, 
                 'port':connection.peer_port}
                harvesters.append(harvester_object)
            else:
                self.log.debug(f"get_harvesters no cache: {connection.peer_host}, node_id: {connection.peer_node_id}")

        return {'harvesters': harvesters}

    async def _periodically_update_pool_state_task(self):
        time_slept = uint64(0)
        config_path = config_path_for_filename(self._root_path, 'config.yaml')
        while not self._shut_down:
            stat_info = config_path.stat()
            if stat_info.st_mtime > self.last_config_access_time:
                self.all_root_sks = [sk for sk, _ in self.keychain.get_all_private_keys()]
                self.last_config_access_time = stat_info.st_mtime
                await self.update_pool_state()
                time_slept = uint64(0)
            else:
                if time_slept > 60:
                    await self.update_pool_state()
                    time_slept = uint64(0)
            time_slept += 1
            await asyncio.sleep(1)

    async def _periodically_clear_cache_and_refresh_task(self):
        time_slept = uint64(0)
        refresh_slept = 0
        while not self._shut_down:
            try:
                if time_slept > self.constants.SUB_SLOT_TIME_TARGET:
                    now = time.time()
                    removed_keys = []
                    for key, add_time in self.cache_add_time.items():
                        if now - float(add_time) > self.constants.SUB_SLOT_TIME_TARGET * 3:
                            self.sps.pop(key, None)
                            self.proofs_of_space.pop(key, None)
                            self.quality_str_to_identifiers.pop(key, None)
                            self.number_of_responses.pop(key, None)
                            removed_keys.append(key)

                    for key in removed_keys:
                        self.cache_add_time.pop(key, None)

                    time_slept = uint64(0)
                    log.debug(f"Cleared farmer cache. Num sps: {len(self.sps)} {len(self.proofs_of_space)} {len(self.quality_str_to_identifiers)} {len(self.number_of_responses)}")
                time_slept += 1
                refresh_slept += 1
                if refresh_slept >= 30:
                    self.state_changed('add_connection', {})
                    refresh_slept = 0
                if await self.update_cached_harvesters():
                    self.state_changed('new_plots', await self.get_harvesters())
            except Exception:
                log.error(f"_periodically_clear_cache_and_refresh_task failed: {traceback.format_exc()}")

            await asyncio.sleep(1)