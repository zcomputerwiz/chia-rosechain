# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\cmds\show.py
from typing import Any, Optional
import click

async def show_async(rpc_port: Optional[int], state: bool, show_connections: bool, exit_node: bool, add_connection: str, remove_connection: str, block_header_hash_by_height: str, block_by_header_hash: str) -> None:
    import aiohttp, time, traceback
    from time import localtime, struct_time
    from typing import List, Optional
    from chia.consensus.block_record import BlockRecord
    from chia.rpc.full_node_rpc_client import FullNodeRpcClient
    from chia.server.outbound_message import NodeType
    from chia.types.full_block import FullBlock
    from chia.util.bech32m import encode_puzzle_hash
    from chia.util.byte_types import hexstr_to_bytes
    from chia.util.config import load_config
    from chia.util.default_root import DEFAULT_ROOT_PATH
    from chia.util.ints import uint16
    from chia.util.misc import format_bytes
    try:
        config = load_config(DEFAULT_ROOT_PATH, 'config.yaml')
        self_hostname = config['self_hostname']
        if rpc_port is None:
            rpc_port = config['full_node']['rpc_port']
        client = await FullNodeRpcClient.create(self_hostname, uint16(rpc_port), DEFAULT_ROOT_PATH, config)
        if state:
            blockchain_state = await client.get_blockchain_state()
            if blockchain_state is None:
                print('There is no blockchain found yet. Try again shortly')
                return
            peak = blockchain_state['peak']
            difficulty = blockchain_state['difficulty']
            sub_slot_iters = blockchain_state['sub_slot_iters']
            synced = blockchain_state['sync']['synced']
            sync_mode = blockchain_state['sync']['sync_mode']
            total_iters = peak.total_iters if peak is not None else 0
            num_blocks = 10
            if synced:
                print('Current Blockchain Status: Full Node Synced')
                print('\nPeak: Hash:', peak.header_hash if peak is not None else '')
            else:
                if peak is not None and sync_mode:
                    sync_max_block = blockchain_state['sync']['sync_tip_height']
                    sync_current_block = blockchain_state['sync']['sync_progress_height']
                    print(f"Current Blockchain Status: Syncing {sync_current_block}/{sync_max_block}.")
                    print('Peak: Hash:', peak.header_hash if peak is not None else '')
                else:
                    if peak is not None:
                        print(f"Current Blockchain Status: Not Synced. Peak height: {peak.height}")
                    else:
                        print('\nSearching for an initial chain\n')
                        print("You may be able to expedite with 'chia show -a host:port' using a known node.\n")
            if peak is not None:
                if peak.is_transaction_block:
                    peak_time = peak.timestamp
                else:
                    peak_hash = peak.header_hash
                    curr = await client.get_block_record(peak_hash)
                    while curr is not None:
                        if not curr.is_transaction_block:
                            curr = await client.get_block_record(curr.prev_hash)

                    peak_time = curr.timestamp
                peak_time_struct = struct_time(localtime(peak_time))
                print('      Time:', (f"{time.strftime('%a %b %d %Y %T %Z', peak_time_struct)}"), f"                 Height: {peak.height:>10}\n")
                print('Estimated network space: ', end='')
                print(format_bytes(blockchain_state['space']))
                print(f"Current difficulty: {difficulty}")
                print(f"Current VDF sub_slot_iters: {sub_slot_iters}")
                print('Total iterations since the start of the blockchain:', total_iters)
                print('')
                print('  Height: |   Hash:')
                added_blocks = []
                curr = await client.get_block_record(peak.header_hash)
                while curr is not None:
                    if len(added_blocks) < num_blocks:
                        if curr.height > 0:
                            added_blocks.append(curr)
                            curr = await client.get_block_record(curr.prev_hash)

                for b in added_blocks:
                    print(f"{b.height:>9} | {b.header_hash}")

            else:
                print('Blockchain has no blocks yet')
            if show_connections:
                print('')
        if show_connections:
            connections = await client.get_connections()
            print('Connections:')
            print('Type      IP                                     Ports       NodeID      Last Connect      MiB Up|Dwn')
            for con in connections:
                last_connect_tuple = struct_time(localtime(con['last_message_time']))
                last_connect = time.strftime('%b %d %T', last_connect_tuple)
                mb_down = con['bytes_read'] / 1048576
                mb_up = con['bytes_written'] / 1048576
                host = con['peer_host']
                if host[0] == '[':
                    host = host[1:39]
                else:
                    if NodeType(con['type']) is NodeType.FULL_NODE:
                        peak_height = con['peak_height']
                        peak_hash = con['peak_hash']
                        if peak_hash is None:
                            peak_hash = 'No Info'
                        if peak_height is None:
                            peak_height = 0
                        con_str = f"{NodeType(con['type']).name:9} {host:38} {con['peer_port']:5}/{con['peer_server_port']:<5} {con['node_id'].hex()[:8]}... {last_connect}  {mb_up:7.1f}|{mb_down:<7.1f}\n                                                 -SB Height: {peak_height:8.0f}    -Hash: {peak_hash[2:10]}..."
                    else:
                        con_str = f"{NodeType(con['type']).name:9} {host:38} {con['peer_port']:5}/{con['peer_server_port']:<5} {con['node_id'].hex()[:8]}... {last_connect}  {mb_up:7.1f}|{mb_down:<7.1f}"
                    print(con_str)

            if state:
                print('')
        if exit_node:
            node_stop = await client.stop_node()
            print(node_stop, 'Node stopped')
        if add_connection:
            if ':' not in add_connection:
                print('Enter a valid IP and port in the following format: 10.5.4.3:8052')
            else:
                ip, port = ':'.join(add_connection.split(':')[:-1]), add_connection.split(':')[-1]
                print(f"Connecting to {ip}, {port}")
                try:
                    await client.open_connection(ip, int(port))
                except Exception:
                    print(f"Failed to connect to {ip}:{port}")

            if remove_connection:
                result_txt = ''
                if len(remove_connection) != 8:
                    result_txt = "Invalid NodeID. Do not include '.'"
                else:
                    connections = await client.get_connections()
                    for con in connections:
                        if remove_connection == con['node_id'].hex()[:8]:
                            print('Attempting to disconnect', 'NodeID', remove_connection)
                            try:
                                await client.close_connection(con['node_id'])
                            except Exception:
                                result_txt = f"Failed to disconnect NodeID {remove_connection}"
                            else:
                                result_txt = f"NodeID {remove_connection}... {NodeType(con['type']).name} "
                                f"{con['peer_host']} disconnected"

                        if result_txt == '':
                            result_txt = f"NodeID {remove_connection}... not found"

                print(result_txt)
            if block_header_hash_by_height != '':
                block_header = await client.get_block_record_by_height(block_header_hash_by_height)
                if block_header is not None:
                    print(f"Header hash of block {block_header_hash_by_height}: {block_header.header_hash.hex()}")
                else:
                    print('Block height', block_header_hash_by_height, 'not found')
            if block_by_header_hash != '':
                block = await client.get_block_record(hexstr_to_bytes(block_by_header_hash))
                full_block = await client.get_block(hexstr_to_bytes(block_by_header_hash))
                if block is not None:
                    assert full_block is not None
                    prev_b = await client.get_block_record(block.prev_hash)
                    if prev_b is not None:
                        difficulty = block.weight - prev_b.weight
                    else:
                        difficulty = block.weight
                    if block.is_transaction_block:
                        assert full_block.transactions_info is not None
                        block_time = struct_time(localtime(full_block.foliage_transaction_block.timestamp if full_block.foliage_transaction_block else None))
                        block_time_string = time.strftime('%a %b %d %Y %T %Z', block_time)
                        cost = str(full_block.transactions_info.cost)
                        tx_filter_hash = 'Not a transaction block'
                        if full_block.foliage_transaction_block:
                            tx_filter_hash = full_block.foliage_transaction_block.filter_hash
                        fees = block.fees
                    else:
                        block_time_string = 'Not a transaction block'
                        cost = 'Not a transaction block'
                        tx_filter_hash = 'Not a transaction block'
                        fees = 'Not a transaction block'
                    address_prefix = config['network_overrides']['config'][config['selected_network']]['address_prefix']
                    farmer_address = encode_puzzle_hash(block.farmer_puzzle_hash, address_prefix)
                    pool_address = encode_puzzle_hash(block.pool_puzzle_hash, address_prefix)
                    pool_pk = full_block.reward_chain_block.proof_of_space.pool_public_key if full_block.reward_chain_block.proof_of_space.pool_public_key is not None else 'Pay to pool puzzle hash'
                    print(f"Block Height           {block.height}\nHeader Hash            0x{block.header_hash.hex()}\nTimestamp              {block_time_string}\nWeight                 {block.weight}\nPrevious Block         0x{block.prev_hash.hex()}\nDifficulty             {difficulty}\nSub-slot iters         {block.sub_slot_iters}\nCost                   {cost}\nTotal VDF Iterations   {block.total_iters}\nIs a Transaction Block?{block.is_transaction_block}\nDeficit                {block.deficit}\nPoSpace 'k' Size       {full_block.reward_chain_block.proof_of_space.size}\nPlot Public Key        0x{full_block.reward_chain_block.proof_of_space.plot_public_key}\nPool Public Key        {pool_pk}\nTx Filter Hash         {tx_filter_hash}\nFarmer Address         {farmer_address}\nPool Address           {pool_address}\nFees Amount            {fees}\n")
                else:
                    print('Block with header hash', block_header_hash_by_height, 'not found')
    except Exception as e:
        try:
            if isinstance(e, aiohttp.ClientConnectorError):
                print(f"Connection error. Check if full node rpc is running at {rpc_port}")
                print('This is normal if full node is still starting up')
            else:
                tb = traceback.format_exc()
                print(f"Exception from 'show' {tb}")
        finally:
            e = None
            del e

    client.close()
    await client.await_closed()


@click.command('show', short_help='Show node information')
@click.option('-p',
  '--rpc-port',
  help='Set the port where the Full Node is hosting the RPC interface. See the rpc_port under full_node in config.yaml',
  type=int,
  default=None)
@click.option('-wp',
  '--wallet-rpc-port',
  help='Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml',
  type=int,
  default=None)
@click.option('-s', '--state', help='Show the current state of the blockchain', is_flag=True, type=bool, default=False)
@click.option('-c',
  '--connections', help='List nodes connected to this Full Node', is_flag=True, type=bool, default=False)
@click.option('-e', '--exit-node', help='Shut down the running Full Node', is_flag=True, default=False)
@click.option('-a', '--add-connection', help='Connect to another Full Node by ip:port', type=str, default='')
@click.option('-r',
  '--remove-connection', help='Remove a Node by the first 8 characters of NodeID', type=str, default='')
@click.option('-bh',
  '--block-header-hash-by-height', help='Look up a block header hash by block height', type=str, default='')
@click.option('-b', '--block-by-header-hash', help='Look up a block by block header hash', type=str, default='')
def show_cmd(rpc_port: Optional[int], wallet_rpc_port: Optional[int], state: bool, connections: bool, exit_node: bool, add_connection: str, remove_connection: str, block_header_hash_by_height: str, block_by_header_hash: str) -> None:
    import asyncio
    asyncio.run(show_async(rpc_port, state, connections, exit_node, add_connection, remove_connection, block_header_hash_by_height, block_by_header_hash))