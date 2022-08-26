# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\plotting\plot_tools.py
import logging, threading, time, traceback
from dataclasses import dataclass
from functools import reduce
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union
from concurrent.futures.thread import ThreadPoolExecutor
from blspy import G1Element, PrivateKey
from chiapos import DiskProver
from chia.consensus.pos_quality import UI_ACTUAL_SPACE_CONSTANT_FACTOR, _expected_plot_size
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.config import load_config, save_config
from chia.wallet.derive_keys import master_sk_to_local_sk
log = logging.getLogger(__name__)

@dataclass
class PlotInfo:
    prover: DiskProver
    pool_public_key: Optional[G1Element]
    pool_contract_puzzle_hash: Optional[bytes32]
    plot_public_key: G1Element
    file_size: int
    time_modified: float


def _get_filenames(directory: Path) -> List[Path]:
    try:
        if not directory.exists():
            log.warning(f"Directory: {directory} does not exist.")
            return []
    except OSError as e:
        try:
            log.warning(f"Error checking if directory {directory} exists: {e}")
            return []
        finally:
            e = None
            del e

    all_files = []
    try:
        for child in directory.iterdir():
            if not child.is_dir():
                if child.suffix == '.plot':
                    child.name.startswith('._') or all_files.append(child)
            else:
                log.debug(f"Not checking subdirectory {child}, subdirectories not added by default")

    except Exception as e:
        try:
            log.warning(f"Error reading directory {directory} {e}")
        finally:
            e = None
            del e

    return all_files


def get_plot_filenames(config: Dict) -> Dict[(Path, List[Path])]:
    directory_names = config['plot_directories']
    all_files = {}
    for directory_name in directory_names:
        directory = Path(directory_name).resolve()
        all_files[directory] = _get_filenames(directory)

    return all_files


def parse_plot_info(memo: bytes) -> Tuple[(Union[(G1Element, bytes32)], G1Element, PrivateKey)]:
    if len(memo) == 128:
        return (
         G1Element.from_bytes(memo[:48]),
         G1Element.from_bytes(memo[48:96]),
         PrivateKey.from_bytes(memo[96:]))
    if len(memo) == 112:
        return (
         bytes32(memo[:32]),
         G1Element.from_bytes(memo[32:80]),
         PrivateKey.from_bytes(memo[80:]))
    raise ValueError(f"Invalid number of bytes {len(memo)}")


def stream_plot_info_pk(pool_public_key: G1Element, farmer_public_key: G1Element, local_master_sk: PrivateKey):
    data = bytes(pool_public_key) + bytes(farmer_public_key) + bytes(local_master_sk)
    assert len(data) == 128
    return data


def stream_plot_info_ph(pool_contract_puzzle_hash: bytes32, farmer_public_key: G1Element, local_master_sk: PrivateKey):
    data = pool_contract_puzzle_hash + bytes(farmer_public_key) + bytes(local_master_sk)
    assert len(data) == 112
    return data


def add_plot_directory(str_path: str, root_path: Path) -> Dict:
    config = load_config(root_path, 'config.yaml')
    if str(Path(str_path).resolve()) not in config['harvester']['plot_directories']:
        config['harvester']['plot_directories'].append(str(Path(str_path).resolve()))
    save_config(root_path, 'config.yaml', config)
    return config


def get_plot_directories(root_path: Path) -> List[str]:
    config = load_config(root_path, 'config.yaml')
    return [str(Path(str_path).resolve()) for str_path in config['harvester']['plot_directories']]


def remove_plot_directory(str_path: str, root_path: Path) -> None:
    config = load_config(root_path, 'config.yaml')
    str_paths = config['harvester']['plot_directories']
    if str_path in str_paths:
        str_paths.remove(str_path)
    new_paths = [Path(sp).resolve() for sp in str_paths]
    if Path(str_path).resolve() in new_paths:
        new_paths.remove(Path(str_path).resolve())
    config['harvester']['plot_directories'] = [str(np) for np in new_paths]
    save_config(root_path, 'config.yaml', config)


def load_plots(provers: Dict[(Path, PlotInfo)], failed_to_open_filenames: Dict[(Path, int)], farmer_public_keys: Optional[List[G1Element]], pool_public_keys: Optional[List[G1Element]], match_str: Optional[str], show_memo: bool, root_path: Path, open_no_key_filenames=False) -> Tuple[(bool, Dict[(Path, PlotInfo)], Dict[(Path, int)], Set[Path])]:
    start_time = time.time()
    config_file = load_config(root_path, 'config.yaml', 'harvester')
    changed = False
    no_key_filenames = set()
    log.info(f"Searching directories {config_file['plot_directories']}")
    plot_filenames = get_plot_filenames(config_file)
    all_filenames = []
    for paths in plot_filenames.values():
        all_filenames += paths

    plot_ids = set()
    plot_ids_lock = threading.Lock()
    if match_str is not None:
        log.info(f'Only loading plots that contain "{match_str}" in the file or directory name')

    def process_file(filename):
        nonlocal changed
        new_provers = {}
        filename_str = str(filename)
        if match_str is not None:
            if match_str not in filename_str:
                return (
                 0, new_provers)
        if filename.exists():
            if filename in failed_to_open_filenames:
                if time.time() - failed_to_open_filenames[filename] < 1200:
                    return (
                     0, new_provers)
            if filename in provers:
                try:
                    stat_info = filename.stat()
                except Exception as e:
                    try:
                        log.error(f"Failed to open file {filename}. {e}")
                        return (
                         0, new_provers)
                    finally:
                        e = None
                        del e

                if stat_info.st_mtime == provers[filename].time_modified:
                    with plot_ids_lock:
                        if provers[filename].prover.get_id() in plot_ids:
                            log.warning(f"Have multiple copies of the plot {filename}, not adding it.")
                            return (
                             0, new_provers)
                        plot_ids.add(provers[filename].prover.get_id())
                    new_provers[filename] = provers[filename]
                    return (
                     stat_info.st_size, new_provers)
            try:
                prover = DiskProver(str(filename))
                expected_size = _expected_plot_size(prover.get_size()) * UI_ACTUAL_SPACE_CONSTANT_FACTOR
                stat_info = filename.stat()
                if prover.get_size() >= 30:
                    if stat_info.st_size < 0.98 * expected_size:
                        log.warning(f"Not farming plot {filename}. Size is {stat_info.st_size / 1073741824} GiB, but expected at least: {expected_size / 1073741824} GiB. We assume the file is being copied.")
                        return (
                         0, new_provers)
                pool_public_key_or_puzzle_hash, farmer_public_key, local_master_sk = parse_plot_info(prover.get_memo())
                if not farmer_public_keys is not None or farmer_public_key not in farmer_public_keys:
                    log.warning(f"Plot {filename} has a farmer public key that is not in the farmer's pk list.")
                    no_key_filenames.add(filename)
                    if not open_no_key_filenames:
                        return (0, new_provers)
                    if isinstance(pool_public_key_or_puzzle_hash, G1Element):
                        pool_public_key = pool_public_key_or_puzzle_hash
                        pool_contract_puzzle_hash = None
                    else:
                        assert isinstance(pool_public_key_or_puzzle_hash, bytes32)
                        pool_public_key = None
                        pool_contract_puzzle_hash = pool_public_key_or_puzzle_hash
                    if pool_public_keys is not None:
                        if not pool_public_key is not None or pool_public_key not in pool_public_keys:
                            log.warning(f"Plot {filename} has a pool public key that is not in the farmer's pool pk list.")
                            no_key_filenames.add(filename)
                            if not open_no_key_filenames:
                                return (0, new_provers)
                            stat_info = filename.stat()
                    local_sk = master_sk_to_local_sk(local_master_sk)
                    plot_public_key = ProofOfSpace.generate_plot_public_key(local_sk.get_g1(), farmer_public_key, pool_contract_puzzle_hash is not None)
                    with plot_ids_lock:
                        if prover.get_id() in plot_ids:
                            log.warning(f"Have multiple copies of the plot {filename}, not adding it.")
                            return (
                             0, new_provers)
                        plot_ids.add(prover.get_id())
                    new_provers[filename] = PlotInfo(prover, pool_public_key, pool_contract_puzzle_hash, plot_public_key, stat_info.st_size, stat_info.st_mtime)
                    changed = True
            except Exception as e:
                try:
                    tb = traceback.format_exc()
                    log.error(f"Failed to open file {filename}. {e} {tb}")
                    failed_to_open_filenames[filename] = int(time.time())
                    return (
                     0, new_provers)
                finally:
                    e = None
                    del e

            log.info(f"Found plot {filename} of size {new_provers[filename].prover.get_size()}")
            if show_memo:
                if pool_contract_puzzle_hash is None:
                    plot_memo = stream_plot_info_pk(pool_public_key, farmer_public_key, local_master_sk)
                else:
                    plot_memo = stream_plot_info_ph(pool_contract_puzzle_hash, farmer_public_key, local_master_sk)
                plot_memo_str = plot_memo.hex()
                log.info(f"Memo: {plot_memo_str}")
            return (
             stat_info.st_size, new_provers)
        return (0, new_provers)

    def reduce_function(x: Tuple[(int, Dict)], y: Tuple[(int, Dict)]) -> Tuple[(int, Dict)]:
        total_size1, new_provers1 = x
        total_size2, new_provers2 = y
        return (
         total_size1 + total_size2, {**new_provers1, **new_provers2})

    with ThreadPoolExecutor() as executor:
        initial_value = (
         0, {})
        total_size, new_provers = reduce(reduce_function, executor.map(process_file, all_filenames), initial_value)
    log.info(f"Loaded a total of {len(new_provers)} plots of size {total_size / 1099511627776} TiB, in {time.time() - start_time} seconds")
    return (
     changed, new_provers, failed_to_open_filenames, no_key_filenames)


def find_duplicate_plot_IDs(all_filenames=None) -> None:
    if all_filenames is None:
        all_filenames = []
    plot_ids_set = set()
    duplicate_plot_ids = set()
    all_filenames_str = []
    for filename in all_filenames:
        filename_str = str(filename)
        all_filenames_str.append(filename_str)
        filename_parts = filename_str.split('-')
        plot_id = filename_parts[-1]
        if len(plot_id) == 69:
            if plot_id in plot_ids_set:
                duplicate_plot_ids.add(plot_id)
            else:
                plot_ids_set.add(plot_id)
        else:
            log.warning(f"{filename} does not end with -[64 char plot ID].plot")

    for plot_id in duplicate_plot_ids:
        log_message = plot_id + ' found in multiple files:\n'
        duplicate_filenames = [filename_str for filename_str in all_filenames_str if plot_id in filename_str]
        for filename_str in duplicate_filenames:
            log_message += '\t' + filename_str + '\n'

        log.warning(f"{log_message}")