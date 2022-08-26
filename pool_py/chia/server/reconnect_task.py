# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\server\reconnect_task.py
import asyncio, socket
from chia.server.server import ChiaServer
from chia.types.peer_info import PeerInfo

def start_reconnect_task(server: ChiaServer, peer_info_arg: PeerInfo, log, auth: bool):
    """
    Start a background task that checks connection and reconnects periodically to a peer.
    """
    peer_info = PeerInfo(socket.gethostbyname(peer_info_arg.host), peer_info_arg.port)

    async def connection_check():
        while 1:
            peer_retry = True
            for _, connection in server.all_connections.items():
                if not connection.get_peer_info() == peer_info:
                    if connection.get_peer_info() == peer_info_arg:
                        pass
                peer_retry = False

            if peer_retry:
                log.info(f"Reconnecting to peer {peer_info}")
                try:
                    await server.start_client(peer_info, None, auth=auth)
                except Exception as e:
                    try:
                        log.info(f"Failed to connect to {peer_info} {e}")
                    finally:
                        e = None
                        del e

                await asyncio.sleep(3)

    return asyncio.create_task(connection_check())