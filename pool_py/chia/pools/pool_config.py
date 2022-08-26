# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\pools\pool_config.py
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List
from blspy import G1Element
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config, save_config
from chia.util.streamable import Streamable, streamable
log = logging.getLogger(__name__)

@dataclass(frozen=True)
@streamable
class PoolWalletConfig(Streamable):
    launcher_id: bytes32
    pool_url: str
    payout_instructions: str
    target_puzzle_hash: bytes32
    p2_singleton_puzzle_hash: bytes32
    owner_public_key: G1Element
    authentication_public_key: G1Element
    p2_chia_contract_or_pool_public_key: str


def load_pool_config(root_path: Path) -> List[PoolWalletConfig]:
    config = load_config(root_path, 'config.yaml')
    ret_list = []
    if 'pool_list' in config['pool']:
        for pool_config_dict in config['pool']['pool_list']:
            try:
                p2_chia_contract_or_pool_public_key = pool_config_dict['p2_chia_contract_or_pool_public_key']
                pool_config = PoolWalletConfig(hexstr_to_bytes(pool_config_dict['launcher_id']), pool_config_dict['pool_url'], pool_config_dict['payout_instructions'], hexstr_to_bytes(pool_config_dict['target_puzzle_hash']), hexstr_to_bytes(pool_config_dict['p2_singleton_puzzle_hash']), G1Element.from_bytes(hexstr_to_bytes(pool_config_dict['owner_public_key'])), G1Element.from_bytes(hexstr_to_bytes(pool_config_dict['authentication_public_key'])), p2_chia_contract_or_pool_public_key)
                ret_list.append(pool_config)
            except Exception as e:
                try:
                    log.error(f"Exception loading config: {pool_config_dict} {e}")
                finally:
                    e = None
                    del e

    return ret_list


async def update_pool_config(root_path: Path, pool_config_list: List[PoolWalletConfig]):
    full_config = load_config(root_path, 'config.yaml')
    full_config['pool']['pool_list'] = [c.to_json_dict() for c in pool_config_list]
    save_config(root_path, 'config.yaml', full_config)