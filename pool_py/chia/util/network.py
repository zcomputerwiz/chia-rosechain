# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\network.py
from ipaddress import ip_address, IPv4Network, IPv6Network
from typing import Iterable, Union, Any
from chia.server.outbound_message import NodeType

def is_in_network(peer_host: str, networks: Iterable[Union[(IPv4Network, IPv6Network)]]) -> bool:
    try:
        peer_host_ip = ip_address(peer_host)
        return any((peer_host_ip in network for network in networks))
    except ValueError:
        return False


def is_localhost(peer_host: str) -> bool:
    return peer_host == '127.0.0.1' or peer_host == 'localhost' or peer_host == '::1' or peer_host == '0:0:0:0:0:0:0:1'


def class_for_type(type: NodeType) -> Any:
    if type is NodeType.FULL_NODE:
        from chia.full_node.full_node_api import FullNodeAPI
        return FullNodeAPI
    if type is NodeType.WALLET:
        from chia.wallet.wallet_node_api import WalletNodeAPI
        return WalletNodeAPI
    if type is NodeType.INTRODUCER:
        from chia.introducer.introducer_api import IntroducerAPI
        return IntroducerAPI
    if type is NodeType.TIMELORD:
        from chia.timelord.timelord_api import TimelordAPI
        return TimelordAPI
    if type is NodeType.FARMER:
        from chia.farmer.farmer_api import FarmerAPI
        return FarmerAPI
    if type is NodeType.HARVESTER:
        from chia.harvester.harvester_api import HarvesterAPI
        return HarvesterAPI
    raise ValueError('No class for type')