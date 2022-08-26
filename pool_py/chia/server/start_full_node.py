# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\server\start_full_node.py
from chia.util.ints import int32
import logging, pathlib
from multiprocessing import freeze_support
from typing import Dict
from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.rpc.full_node_rpc_api import FullNodeRpcApi
from chia.server.outbound_message import NodeType
from chia.server.start_service import run_service
from chia.util.config import load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.byte_types import make_sized_bytes
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import decode_puzzle_hash, bech32_decode
from blspy import AugSchemeMPL, G1Element, G2Element
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config, save_config
''.encode('idna')
SERVICE_NAME = 'full_node'
log = logging.getLogger(__name__)

def service_kwargs_for_full_node(root_path: pathlib.Path, config: Dict, consensus_constants: ConsensusConstants) -> Dict:
    full_node = FullNode(config,
      root_path=root_path,
      consensus_constants=consensus_constants)
    api = FullNodeAPI(full_node)
    upnp_list = []
    if config['enable_upnp']:
        upnp_list = [
         config['port']]
    network_id = config['selected_network']
    kwargs = dict(root_path=root_path,
      node=(api.full_node),
      peer_api=api,
      node_type=(NodeType.FULL_NODE),
      advertised_port=(config['port']),
      service_name=SERVICE_NAME,
      upnp_ports=upnp_list,
      server_listen_ports=[
     config['port']],
      on_connect_callback=(full_node.on_connect),
      network_id=network_id)
    if config['start_rpc_server']:
        kwargs['rpc_info'] = (
         FullNodeRpcApi, config['rpc_port'])
    return kwargs


def main() -> None:
    config = load_config_cli(DEFAULT_ROOT_PATH, 'config.yaml', SERVICE_NAME)
    overrides = config['network_overrides']['constants'][config['selected_network']]
    updated_constants = (DEFAULT_CONSTANTS.replace_str_to_bytes)(**overrides)
    kwargs = service_kwargs_for_full_node(DEFAULT_ROOT_PATH, config, updated_constants)
    return run_service(**kwargs)


if __name__ == '__main__':
    freeze_support()
    main()