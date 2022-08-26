# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\server\server.py
import asyncio, logging, ssl, time, traceback
from ipaddress import IPv6Address, ip_address, ip_network, IPv4Network, IPv6Network
from pathlib import Path
from secrets import token_bytes
from typing import Any, Callable, Dict, List, Optional, Union, Set, Tuple
from aiohttp import ClientSession, ClientTimeout, ServerDisconnectedError, WSCloseCode, client_exceptions, web
from aiohttp.web_app import Application
from aiohttp.web_runner import TCPSite
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import protocol_version
from chia.server.introducer_peers import IntroducerPeers
from chia.server.outbound_message import Message, NodeType
from chia.server.ssl_context import private_ssl_paths, public_ssl_paths
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.errors import Err, ProtocolError
from chia.util.ints import uint16
from chia.util.network import is_localhost, is_in_network

def ssl_context_for_server(ca_cert: Path, ca_key: Path, private_cert_path: Path, private_key_path: Path) -> Optional[ssl.SSLContext]:
    ssl_context = ssl._create_unverified_context(purpose=(ssl.Purpose.SERVER_AUTH), cafile=(str(ca_cert)))
    ssl_context.check_hostname = False
    ssl_context.load_cert_chain(certfile=(str(private_cert_path)), keyfile=(str(private_key_path)))
    ssl_context.verify_mode = ssl.CERT_REQUIRED
    return ssl_context


def ssl_context_for_root(ca_cert_file: str) -> Optional[ssl.SSLContext]:
    ssl_context = ssl.create_default_context(purpose=(ssl.Purpose.SERVER_AUTH), cafile=ca_cert_file)
    return ssl_context


def ssl_context_for_client(ca_cert: Path, ca_key: Path, private_cert_path: Path, private_key_path: Path) -> Optional[ssl.SSLContext]:
    ssl_context = ssl._create_unverified_context(purpose=(ssl.Purpose.SERVER_AUTH), cafile=(str(ca_cert)))
    ssl_context.check_hostname = False
    ssl_context.load_cert_chain(certfile=(str(private_cert_path)), keyfile=(str(private_key_path)))
    ssl_context.verify_mode = ssl.CERT_REQUIRED
    return ssl_context


class ChiaServer:

    def __init__(self, port: int, node: Any, api: Any, local_type: NodeType, ping_interval: int, network_id: str, inbound_rate_limit_percent: int, outbound_rate_limit_percent: int, root_path: Path, config: Dict, private_ca_crt_key: Tuple[(Path, Path)], chia_ca_crt_key: Tuple[(Path, Path)], name: str=None, introducer_peers: Optional[IntroducerPeers]=None):
        logging.basicConfig(level=(logging.DEBUG))
        self.all_connections = {}
        self.tasks = set()
        self.connection_by_type = {NodeType.FULL_NODE: {}, 
         NodeType.WALLET: {}, 
         NodeType.HARVESTER: {}, 
         NodeType.FARMER: {}, 
         NodeType.TIMELORD: {}, 
         NodeType.INTRODUCER: {}}
        self._port = port
        self._local_type = local_type
        self._ping_interval = ping_interval
        self._network_id = network_id
        self._inbound_rate_limit_percent = inbound_rate_limit_percent
        self._outbound_rate_limit_percent = outbound_rate_limit_percent
        self._tasks = []
        self.log = logging.getLogger(name if name else __name__)
        self.api = api
        self.node = node
        self.root_path = root_path
        self.config = config
        self.on_connect = None
        self.incoming_messages = asyncio.Queue()
        self.shut_down_event = asyncio.Event()
        if self._local_type is NodeType.INTRODUCER:
            self.introducer_peers = IntroducerPeers()
        if self._local_type is not NodeType.INTRODUCER:
            self._private_cert_path, self._private_key_path = private_ssl_paths(root_path, config)
        if self._local_type is not NodeType.HARVESTER:
            self.p2p_crt_path, self.p2p_key_path = public_ssl_paths(root_path, config)
        else:
            self.p2p_crt_path, self.p2p_key_path = (None, None)
        self.ca_private_crt_path, self.ca_private_key_path = private_ca_crt_key
        self.chia_ca_crt_path, self.chia_ca_key_path = chia_ca_crt_key
        self.node_id = self.my_id()
        self.incoming_task = asyncio.create_task(self.incoming_api_task())
        self.gc_task = asyncio.create_task(self.garbage_collect_connections_task())
        self.app = None
        self.runner = None
        self.site = None
        self.connection_close_task = None
        self.site_shutdown_task = None
        self.app_shut_down_task = None
        self.received_message_callback = None
        self.api_tasks = {}
        self.execute_tasks = set()
        self.tasks_from_peer = {}
        self.banned_peers = {}
        self.invalid_protocol_ban_seconds = 10
        self.api_exception_ban_seconds = 10
        self.exempt_peer_networks = [ip_network(net, strict=False) for net in config.get('exempt_peer_networks', [])]

    def my_id(self) -> bytes32:
        """If node has public cert use that one for id, if not use private."""
        if self.p2p_crt_path is not None:
            pem_cert = x509.load_pem_x509_certificate(self.p2p_crt_path.read_bytes(), default_backend())
        else:
            pem_cert = x509.load_pem_x509_certificate(self._private_cert_path.read_bytes(), default_backend())
        der_cert_bytes = pem_cert.public_bytes(encoding=(serialization.Encoding.DER))
        der_cert = x509.load_der_x509_certificate(der_cert_bytes, default_backend())
        return bytes32(der_cert.fingerprint(hashes.SHA256()))

    def set_received_message_callback(self, callback: Callable):
        self.received_message_callback = callback

    async def garbage_collect_connections_task(self) -> None:
        """
        Periodically checks for connections with no activity (have not sent us any data), and removes them,
        to allow room for other peers.
        """
        while 1:
            await asyncio.sleep(600)
            to_remove = []
            for connection in self.all_connections.values():
                if self._local_type == NodeType.FULL_NODE:
                    if connection.connection_type == NodeType.FULL_NODE:
                        if time.time() - connection.last_message_time > 1800:
                            to_remove.append(connection)

            for connection in to_remove:
                self.log.debug(f"Garbage collecting connection {connection.peer_host} due to inactivity")
                await connection.close()

            to_remove_ban = []
            for peer_ip, ban_until_time in self.banned_peers.items():
                if time.time() > ban_until_time:
                    to_remove_ban.append(peer_ip)

            for peer_ip in to_remove_ban:
                del self.banned_peers[peer_ip]

    async def start_server(self, on_connect: Callable=None):
        if self._local_type in [NodeType.WALLET, NodeType.HARVESTER, NodeType.TIMELORD]:
            return
        self.app = web.Application()
        self.on_connect = on_connect
        routes = [
         web.get('/ws', self.incoming_connection)]
        self.app.add_routes(routes)
        self.runner = web.AppRunner((self.app), access_log=None, logger=(self.log))
        await self.runner.setup()
        authenticate = self._local_type not in (NodeType.FULL_NODE, NodeType.INTRODUCER)
        if authenticate:
            ssl_context = ssl_context_for_server(self.ca_private_crt_path, self.ca_private_key_path, self._private_cert_path, self._private_key_path)
        else:
            self.p2p_crt_path, self.p2p_key_path = public_ssl_paths(self.root_path, self.config)
            ssl_context = ssl_context_for_server(self.chia_ca_crt_path, self.chia_ca_key_path, self.p2p_crt_path, self.p2p_key_path)
        self.site = web.TCPSite((self.runner),
          port=(self._port),
          shutdown_timeout=3,
          ssl_context=ssl_context)
        await self.site.start()
        self.log.info(f"Started listening on port: {self._port}")

    async def incoming_connection--- This code section failed: ---

 L. 219         0  LOAD_FAST                'request'
                2  LOAD_ATTR                remote
                4  LOAD_FAST                'self'
                6  LOAD_ATTR                banned_peers
                8  COMPARE_OP               in
               10  POP_JUMP_IF_FALSE    58  'to 58'
               12  LOAD_GLOBAL              time
               14  LOAD_METHOD              time
               16  CALL_METHOD_0         0  '0 positional arguments'
               18  LOAD_FAST                'self'
               20  LOAD_ATTR                banned_peers
               22  LOAD_FAST                'request'
               24  LOAD_ATTR                remote
               26  BINARY_SUBSCR    
               28  COMPARE_OP               <
               30  POP_JUMP_IF_FALSE    58  'to 58'

 L. 220        32  LOAD_FAST                'self'
               34  LOAD_ATTR                log
               36  LOAD_METHOD              warning
               38  LOAD_STR                 'Peer '
               40  LOAD_FAST                'request'
               42  LOAD_ATTR                remote
               44  FORMAT_VALUE          0  ''
               46  LOAD_STR                 ' is banned, refusing connection'
               48  BUILD_STRING_3        3 
               50  CALL_METHOD_1         1  '1 positional argument'
               52  POP_TOP          

 L. 221        54  LOAD_CONST               None
               56  RETURN_VALUE     
             58_0  COME_FROM            30  '30'
             58_1  COME_FROM            10  '10'

 L. 222        58  LOAD_GLOBAL              web
               60  LOAD_ATTR                WebSocketResponse
               62  LOAD_CONST               52428800
               64  LOAD_CONST               ('max_msg_size',)
               66  CALL_FUNCTION_KW_1     1  '1 total positional and keyword args'
               68  STORE_FAST               'ws'

 L. 223        70  LOAD_FAST                'ws'
               72  LOAD_METHOD              prepare
               74  LOAD_FAST                'request'
               76  CALL_METHOD_1         1  '1 positional argument'
               78  GET_AWAITABLE    
               80  LOAD_CONST               None
               82  YIELD_FROM       
               84  POP_TOP          

 L. 224        86  LOAD_GLOBAL              asyncio
               88  LOAD_METHOD              Event
               90  CALL_METHOD_0         0  '0 positional arguments'
               92  STORE_FAST               'close_event'

 L. 225        94  LOAD_FAST                'request'
               96  LOAD_ATTR                transport
               98  LOAD_ATTR                _ssl_protocol
              100  LOAD_ATTR                _extra
              102  LOAD_STR                 'ssl_object'
              104  BINARY_SUBSCR    
              106  LOAD_METHOD              getpeercert
              108  LOAD_CONST               True
              110  CALL_METHOD_1         1  '1 positional argument'
              112  STORE_FAST               'cert_bytes'

 L. 226       114  LOAD_GLOBAL              x509
              116  LOAD_METHOD              load_der_x509_certificate
              118  LOAD_FAST                'cert_bytes'
              120  CALL_METHOD_1         1  '1 positional argument'
              122  STORE_FAST               'der_cert'

 L. 227       124  LOAD_GLOBAL              bytes32
              126  LOAD_FAST                'der_cert'
              128  LOAD_METHOD              fingerprint
              130  LOAD_GLOBAL              hashes
              132  LOAD_METHOD              SHA256
              134  CALL_METHOD_0         0  '0 positional arguments'
              136  CALL_METHOD_1         1  '1 positional argument'
              138  CALL_FUNCTION_1       1  '1 positional argument'
              140  STORE_FAST               'peer_id'

 L. 228       142  LOAD_FAST                'peer_id'
              144  LOAD_FAST                'self'
              146  LOAD_ATTR                node_id
              148  COMPARE_OP               ==
              150  POP_JUMP_IF_FALSE   156  'to 156'

 L. 229       152  LOAD_FAST                'ws'
              154  RETURN_VALUE     
            156_0  COME_FROM           150  '150'

 L. 230       156  LOAD_CONST               None
              158  STORE_FAST               'connection'

 L. 231       160  SETUP_EXCEPT        406  'to 406'

 L. 232       162  LOAD_GLOBAL              WSChiaConnection

 L. 233       164  LOAD_FAST                'self'
              166  LOAD_ATTR                _local_type

 L. 234       168  LOAD_FAST                'ws'

 L. 235       170  LOAD_FAST                'self'
              172  LOAD_ATTR                _port

 L. 236       174  LOAD_FAST                'self'
              176  LOAD_ATTR                log

 L. 237       178  LOAD_CONST               False

 L. 238       180  LOAD_CONST               False

 L. 239       182  LOAD_FAST                'request'
              184  LOAD_ATTR                remote

 L. 240       186  LOAD_FAST                'self'
              188  LOAD_ATTR                incoming_messages

 L. 241       190  LOAD_FAST                'self'
              192  LOAD_ATTR                connection_closed

 L. 242       194  LOAD_FAST                'peer_id'

 L. 243       196  LOAD_FAST                'self'
              198  LOAD_ATTR                _inbound_rate_limit_percent

 L. 244       200  LOAD_FAST                'self'
              202  LOAD_ATTR                _outbound_rate_limit_percent

 L. 245       204  LOAD_FAST                'close_event'
              206  CALL_FUNCTION_13     13  '13 positional arguments'
              208  STORE_FAST               'connection'

 L. 247       210  LOAD_FAST                'connection'
              212  LOAD_METHOD              perform_handshake

 L. 248       214  LOAD_FAST                'self'
              216  LOAD_ATTR                _network_id

 L. 249       218  LOAD_GLOBAL              protocol_version

 L. 250       220  LOAD_FAST                'self'
              222  LOAD_ATTR                _port

 L. 251       224  LOAD_FAST                'self'
              226  LOAD_ATTR                _local_type
              228  CALL_METHOD_4         4  '4 positional arguments'
              230  GET_AWAITABLE    
              232  LOAD_CONST               None
              234  YIELD_FROM       
              236  STORE_FAST               'handshake'

 L. 254       238  LOAD_FAST                'handshake'
              240  LOAD_CONST               True
              242  COMPARE_OP               is
              244  POP_JUMP_IF_TRUE    250  'to 250'
              246  LOAD_ASSERT              AssertionError
              248  RAISE_VARARGS_1       1  'exception instance'
            250_0  COME_FROM           244  '244'

 L. 256       250  LOAD_FAST                'self'
              252  LOAD_METHOD              accept_inbound_connections
              254  LOAD_FAST                'connection'
              256  LOAD_ATTR                connection_type
              258  CALL_METHOD_1         1  '1 positional argument'
          260_262  POP_JUMP_IF_TRUE    328  'to 328'
              264  LOAD_GLOBAL              is_in_network

 L. 257       266  LOAD_FAST                'connection'
              268  LOAD_ATTR                peer_host
              270  LOAD_FAST                'self'
              272  LOAD_ATTR                exempt_peer_networks
              274  CALL_FUNCTION_2       2  '2 positional arguments'
          276_278  POP_JUMP_IF_TRUE    328  'to 328'

 L. 259       280  LOAD_FAST                'self'
              282  LOAD_ATTR                log
              284  LOAD_METHOD              info
              286  LOAD_STR                 'Not accepting inbound connection: '
              288  LOAD_FAST                'connection'
              290  LOAD_METHOD              get_peer_info
              292  CALL_METHOD_0         0  '0 positional arguments'
              294  FORMAT_VALUE          0  ''
              296  LOAD_STR                 '.Inbound limit reached.'
              298  BUILD_STRING_3        3 
              300  CALL_METHOD_1         1  '1 positional argument'
              302  POP_TOP          

 L. 260       304  LOAD_FAST                'connection'
              306  LOAD_METHOD              close
              308  CALL_METHOD_0         0  '0 positional arguments'
              310  GET_AWAITABLE    
              312  LOAD_CONST               None
              314  YIELD_FROM       
              316  POP_TOP          

 L. 261       318  LOAD_FAST                'close_event'
              320  LOAD_METHOD              set
              322  CALL_METHOD_0         0  '0 positional arguments'
              324  POP_TOP          
              326  JUMP_FORWARD        400  'to 400'
            328_0  COME_FROM           276  '276'
            328_1  COME_FROM           260  '260'

 L. 263       328  LOAD_FAST                'self'
              330  LOAD_METHOD              connection_added
              332  LOAD_FAST                'connection'
              334  LOAD_FAST                'self'
              336  LOAD_ATTR                on_connect
              338  CALL_METHOD_2         2  '2 positional arguments'
              340  GET_AWAITABLE    
              342  LOAD_CONST               None
              344  YIELD_FROM       
              346  POP_TOP          

 L. 264       348  LOAD_FAST                'self'
              350  LOAD_ATTR                _local_type
              352  LOAD_GLOBAL              NodeType
              354  LOAD_ATTR                INTRODUCER
              356  COMPARE_OP               is
          358_360  POP_JUMP_IF_FALSE   400  'to 400'
              362  LOAD_FAST                'connection'
              364  LOAD_ATTR                connection_type
              366  LOAD_GLOBAL              NodeType
              368  LOAD_ATTR                FULL_NODE
              370  COMPARE_OP               is
          372_374  POP_JUMP_IF_FALSE   400  'to 400'

 L. 265       376  LOAD_GLOBAL              print
              378  LOAD_STR                 'NodeType.INTRODUCER! add'
              380  CALL_FUNCTION_1       1  '1 positional argument'
              382  POP_TOP          

 L. 266       384  LOAD_FAST                'self'
              386  LOAD_ATTR                introducer_peers
              388  LOAD_METHOD              add
              390  LOAD_FAST                'connection'
              392  LOAD_METHOD              get_peer_info
              394  CALL_METHOD_0         0  '0 positional arguments'
              396  CALL_METHOD_1         1  '1 positional argument'
              398  POP_TOP          
            400_0  COME_FROM           372  '372'
            400_1  COME_FROM           358  '358'
            400_2  COME_FROM           326  '326'
              400  POP_BLOCK        
          402_404  JUMP_FORWARD        818  'to 818'
            406_0  COME_FROM_EXCEPT    160  '160'

 L. 267       406  DUP_TOP          
              408  LOAD_GLOBAL              ProtocolError
              410  COMPARE_OP               exception-match
          412_414  POP_JUMP_IF_FALSE   612  'to 612'
              416  POP_TOP          
              418  STORE_FAST               'e'
              420  POP_TOP          
              422  SETUP_FINALLY       600  'to 600'

 L. 268       424  LOAD_FAST                'connection'
              426  LOAD_CONST               None
              428  COMPARE_OP               is-not
          430_432  POP_JUMP_IF_FALSE   460  'to 460'

 L. 269       434  LOAD_FAST                'connection'
              436  LOAD_METHOD              close
              438  LOAD_FAST                'self'
              440  LOAD_ATTR                invalid_protocol_ban_seconds
              442  LOAD_GLOBAL              WSCloseCode
              444  LOAD_ATTR                PROTOCOL_ERROR
              446  LOAD_FAST                'e'
              448  LOAD_ATTR                code
              450  CALL_METHOD_3         3  '3 positional arguments'
              452  GET_AWAITABLE    
              454  LOAD_CONST               None
              456  YIELD_FROM       
              458  POP_TOP          
            460_0  COME_FROM           430  '430'

 L. 270       460  LOAD_FAST                'e'
              462  LOAD_ATTR                code
              464  LOAD_GLOBAL              Err
              466  LOAD_ATTR                INVALID_HANDSHAKE
              468  COMPARE_OP               ==
          470_472  POP_JUMP_IF_FALSE   496  'to 496'

 L. 271       474  LOAD_FAST                'self'
              476  LOAD_ATTR                log
              478  LOAD_METHOD              warning
              480  LOAD_STR                 'Invalid handshake with peer. Maybe the peer is running old software.'
              482  CALL_METHOD_1         1  '1 positional argument'
              484  POP_TOP          

 L. 272       486  LOAD_FAST                'close_event'
              488  LOAD_METHOD              set
              490  CALL_METHOD_0         0  '0 positional arguments'
              492  POP_TOP          
              494  JUMP_FORWARD        596  'to 596'
            496_0  COME_FROM           470  '470'

 L. 273       496  LOAD_FAST                'e'
              498  LOAD_ATTR                code
              500  LOAD_GLOBAL              Err
              502  LOAD_ATTR                INCOMPATIBLE_NETWORK_ID
              504  COMPARE_OP               ==
          506_508  POP_JUMP_IF_FALSE   532  'to 532'

 L. 274       510  LOAD_FAST                'self'
              512  LOAD_ATTR                log
              514  LOAD_METHOD              warning
              516  LOAD_STR                 'Incompatible network ID. Maybe the peer is on another network'
              518  CALL_METHOD_1         1  '1 positional argument'
              520  POP_TOP          

 L. 275       522  LOAD_FAST                'close_event'
              524  LOAD_METHOD              set
              526  CALL_METHOD_0         0  '0 positional arguments'
              528  POP_TOP          
              530  JUMP_FORWARD        596  'to 596'
            532_0  COME_FROM           506  '506'

 L. 276       532  LOAD_FAST                'e'
              534  LOAD_ATTR                code
              536  LOAD_GLOBAL              Err
              538  LOAD_ATTR                SELF_CONNECTION
              540  COMPARE_OP               ==
          542_544  POP_JUMP_IF_FALSE   556  'to 556'

 L. 277       546  LOAD_FAST                'close_event'
              548  LOAD_METHOD              set
              550  CALL_METHOD_0         0  '0 positional arguments'
              552  POP_TOP          
              554  JUMP_FORWARD        596  'to 596'
            556_0  COME_FROM           542  '542'

 L. 279       556  LOAD_GLOBAL              traceback
              558  LOAD_METHOD              format_exc
              560  CALL_METHOD_0         0  '0 positional arguments'
              562  STORE_FAST               'error_stack'

 L. 280       564  LOAD_FAST                'self'
              566  LOAD_ATTR                log
              568  LOAD_METHOD              error
              570  LOAD_STR                 'Exception '
              572  LOAD_FAST                'e'
              574  FORMAT_VALUE          0  ''
              576  LOAD_STR                 ', exception Stack: '
              578  LOAD_FAST                'error_stack'
              580  FORMAT_VALUE          0  ''
              582  BUILD_STRING_4        4 
              584  CALL_METHOD_1         1  '1 positional argument'
              586  POP_TOP          

 L. 281       588  LOAD_FAST                'close_event'
              590  LOAD_METHOD              set
              592  CALL_METHOD_0         0  '0 positional arguments'
              594  POP_TOP          
            596_0  COME_FROM           554  '554'
            596_1  COME_FROM           530  '530'
            596_2  COME_FROM           494  '494'
              596  POP_BLOCK        
              598  LOAD_CONST               None
            600_0  COME_FROM_FINALLY   422  '422'
              600  LOAD_CONST               None
              602  STORE_FAST               'e'
              604  DELETE_FAST              'e'
              606  END_FINALLY      
              608  POP_EXCEPT       
              610  JUMP_FORWARD        818  'to 818'
            612_0  COME_FROM           412  '412'

 L. 282       612  DUP_TOP          
              614  LOAD_GLOBAL              ValueError
              616  COMPARE_OP               exception-match
          618_620  POP_JUMP_IF_FALSE   708  'to 708'
              622  POP_TOP          
              624  STORE_FAST               'e'
              626  POP_TOP          
              628  SETUP_FINALLY       696  'to 696'

 L. 283       630  LOAD_FAST                'connection'
              632  LOAD_CONST               None
              634  COMPARE_OP               is-not
          636_638  POP_JUMP_IF_FALSE   666  'to 666'

 L. 284       640  LOAD_FAST                'connection'
              642  LOAD_METHOD              close
              644  LOAD_FAST                'self'
              646  LOAD_ATTR                invalid_protocol_ban_seconds
              648  LOAD_GLOBAL              WSCloseCode
              650  LOAD_ATTR                PROTOCOL_ERROR
              652  LOAD_GLOBAL              Err
              654  LOAD_ATTR                UNKNOWN
              656  CALL_METHOD_3         3  '3 positional arguments'
              658  GET_AWAITABLE    
              660  LOAD_CONST               None
              662  YIELD_FROM       
              664  POP_TOP          
            666_0  COME_FROM           636  '636'

 L. 285       666  LOAD_FAST                'self'
              668  LOAD_ATTR                log
              670  LOAD_METHOD              warning
              672  LOAD_FAST                'e'
              674  FORMAT_VALUE          0  ''
              676  LOAD_STR                 ' - closing connection'
              678  BUILD_STRING_2        2 
              680  CALL_METHOD_1         1  '1 positional argument'
              682  POP_TOP          

 L. 286       684  LOAD_FAST                'close_event'
              686  LOAD_METHOD              set
              688  CALL_METHOD_0         0  '0 positional arguments'
              690  POP_TOP          
              692  POP_BLOCK        
              694  LOAD_CONST               None
            696_0  COME_FROM_FINALLY   628  '628'
              696  LOAD_CONST               None
              698  STORE_FAST               'e'
              700  DELETE_FAST              'e'
              702  END_FINALLY      
              704  POP_EXCEPT       
              706  JUMP_FORWARD        818  'to 818'
            708_0  COME_FROM           618  '618'

 L. 287       708  DUP_TOP          
              710  LOAD_GLOBAL              Exception
              712  COMPARE_OP               exception-match
          714_716  POP_JUMP_IF_FALSE   816  'to 816'
              718  POP_TOP          
              720  STORE_FAST               'e'
              722  POP_TOP          
              724  SETUP_FINALLY       804  'to 804'

 L. 288       726  LOAD_FAST                'connection'
              728  LOAD_CONST               None
              730  COMPARE_OP               is-not
          732_734  POP_JUMP_IF_FALSE   760  'to 760'

 L. 289       736  LOAD_FAST                'connection'
              738  LOAD_ATTR                close
              740  LOAD_GLOBAL              WSCloseCode
              742  LOAD_ATTR                PROTOCOL_ERROR
              744  LOAD_GLOBAL              Err
              746  LOAD_ATTR                UNKNOWN
              748  LOAD_CONST               ('ws_close_code', 'error')
              750  CALL_FUNCTION_KW_2     2  '2 total positional and keyword args'
              752  GET_AWAITABLE    
              754  LOAD_CONST               None
              756  YIELD_FROM       
              758  POP_TOP          
            760_0  COME_FROM           732  '732'

 L. 290       760  LOAD_GLOBAL              traceback
              762  LOAD_METHOD              format_exc
              764  CALL_METHOD_0         0  '0 positional arguments'
              766  STORE_FAST               'error_stack'

 L. 291       768  LOAD_FAST                'self'
              770  LOAD_ATTR                log
              772  LOAD_METHOD              error
              774  LOAD_STR                 'Exception '
              776  LOAD_FAST                'e'
              778  FORMAT_VALUE          0  ''
              780  LOAD_STR                 ', exception Stack: '
              782  LOAD_FAST                'error_stack'
              784  FORMAT_VALUE          0  ''
              786  BUILD_STRING_4        4 
              788  CALL_METHOD_1         1  '1 positional argument'
              790  POP_TOP          

 L. 292       792  LOAD_FAST                'close_event'
              794  LOAD_METHOD              set
              796  CALL_METHOD_0         0  '0 positional arguments'
              798  POP_TOP          
              800  POP_BLOCK        
              802  LOAD_CONST               None
            804_0  COME_FROM_FINALLY   724  '724'
              804  LOAD_CONST               None
              806  STORE_FAST               'e'
              808  DELETE_FAST              'e'
              810  END_FINALLY      
              812  POP_EXCEPT       
              814  JUMP_FORWARD        818  'to 818'
            816_0  COME_FROM           714  '714'
              816  END_FINALLY      
            818_0  COME_FROM           814  '814'
            818_1  COME_FROM           706  '706'
            818_2  COME_FROM           610  '610'
            818_3  COME_FROM           402  '402'

 L. 294       818  LOAD_FAST                'close_event'
              820  LOAD_METHOD              wait
              822  CALL_METHOD_0         0  '0 positional arguments'
              824  GET_AWAITABLE    
              826  LOAD_CONST               None
              828  YIELD_FROM       
              830  POP_TOP          

 L. 295       832  LOAD_FAST                'ws'
              834  RETURN_VALUE     
               -1  RETURN_LAST      

Parse error at or near `POP_BLOCK' instruction at offset 400

    async def connection_added(self, connection: WSChiaConnection, on_connect=None):
        if connection.peer_node_id in self.all_connections:
            con = self.all_connections[connection.peer_node_id]
            await con.close()
        self.all_connections[connection.peer_node_id] = connection
        if connection.connection_type is not None:
            self.connection_by_type[connection.connection_type][connection.peer_node_id] = connection
            if on_connect is not None:
                await on_connect(connection)
        else:
            self.log.error(f"Invalid connection type for connection {connection}")

    def is_duplicate_or_self_connection(self, target_node: PeerInfo) -> bool:
        if is_localhost(target_node.host):
            if target_node.port == self._port:
                self.log.debug(f"Not connecting to {target_node}")
                return True
        for connection in self.all_connections.values():
            if connection.host == target_node.host:
                if connection.peer_server_port == target_node.port:
                    self.log.debug(f"Not connecting to {target_node}, duplicate connection")
                    return True

        return False

    async def start_client(self, target_node, on_connect=None, auth=False, is_feeler=False):
        """
        Tries to connect to the target node, adding one connection into the pipeline, if successful.
        An on connect method can also be specified, and this will be saved into the instance variables.
        """
        if self.is_duplicate_or_self_connection(target_node):
            return False
        if target_node.host in self.banned_peers:
            if time.time() < self.banned_peers[target_node.host]:
                self.log.warning(f"Peer {target_node.host} is still banned, not connecting to it")
                return False
        if auth:
            ssl_context = ssl_context_for_client(self.ca_private_crt_path, self.ca_private_key_path, self._private_cert_path, self._private_key_path)
        else:
            ssl_context = ssl_context_for_client(self.chia_ca_crt_path, self.chia_ca_key_path, self.p2p_crt_path, self.p2p_key_path)
        session = None
        connection = None
        try:
            try:
                timeout = ClientTimeout(total=30)
                session = ClientSession(timeout=timeout)
                try:
                    if type(ip_address(target_node.host)) is IPv6Address:
                        target_node = PeerInfo(f"[{target_node.host}]", target_node.port)
                except ValueError:
                    pass

                url = f"wss://{target_node.host}:{target_node.port}/ws"
                self.log.debug(f"Connecting: {url}, Peer info: {target_node}")
                try:
                    ws = await session.ws_connect(url,
                      autoclose=True, autoping=True, heartbeat=60, ssl=ssl_context, max_msg_size=52428800)
                except ServerDisconnectedError:
                    self.log.debug(f"Server disconnected error connecting to {url}. Perhaps we are banned by the peer.")
                    return False
                except asyncio.TimeoutError:
                    self.log.debug(f"Timeout error connecting to {url}")
                    return False
                else:
                    if ws is None:
                        return False
                    if not (ws._response.connection is not None and ws._response.connection.transport is not None):
                        raise AssertionError
                    transport = ws._response.connection.transport
                    cert_bytes = transport._ssl_protocol._extra['ssl_object'].getpeercert(True)
                    der_cert = x509.load_der_x509_certificate(cert_bytes, default_backend())
                    peer_id = bytes32(der_cert.fingerprint(hashes.SHA256()))
                    if peer_id == self.node_id:
                        raise RuntimeError(f"Trying to connect to a peer ({target_node}) with the same peer_id: {peer_id}")
                    connection = WSChiaConnection((self._local_type),
                      ws,
                      (self._port),
                      (self.log),
                      True,
                      False,
                      (target_node.host),
                      (self.incoming_messages),
                      (self.connection_closed),
                      peer_id,
                      (self._inbound_rate_limit_percent),
                      (self._outbound_rate_limit_percent),
                      session=session)
                    handshake = await connection.perform_handshakeself._network_idprotocol_versionself._portself._local_type
                    assert handshake is True
                    await self.connection_added(connection, on_connect)
                    session = None
                    connection_type_str = ''
                    if connection.connection_type is not None:
                        connection_type_str = connection.connection_type.name.lower()
                    self.log.info(f"Connected with {connection_type_str} {target_node}")
                    if is_feeler:
                        asyncio.create_task(connection.close())

                return True
            except client_exceptions.ClientConnectorError as e:
                try:
                    self.log.info(f"{e}")
                finally:
                    e = None
                    del e

            except ProtocolError as e:
                try:
                    if connection is not None:
                        await connection.closeself.invalid_protocol_ban_secondsWSCloseCode.PROTOCOL_ERRORe.code
                    if e.code == Err.INVALID_HANDSHAKE:
                        self.log.warning(f"Invalid handshake with peer {target_node}. Maybe the peer is running old software.")
                    else:
                        if e.code == Err.INCOMPATIBLE_NETWORK_ID:
                            self.log.warning('Incompatible network ID. Maybe the peer is on another network')
                        else:
                            if e.code == Err.SELF_CONNECTION:
                                pass
                            else:
                                error_stack = traceback.format_exc()
                                self.log.error(f"Exception {e}, exception Stack: {error_stack}")
                finally:
                    e = None
                    del e

            except Exception as e:
                try:
                    if connection is not None:
                        await connection.closeself.invalid_protocol_ban_secondsWSCloseCode.PROTOCOL_ERRORErr.UNKNOWN
                    error_stack = traceback.format_exc()
                    self.log.error(f"Exception {e}, exception Stack: {error_stack}")
                finally:
                    e = None
                    del e

        finally:
            if session is not None:
                await session.close()

        return False

    def connection_closed(self, connection: WSChiaConnection, ban_time: int):
        if is_localhost(connection.peer_host):
            if ban_time != 0:
                self.log.warning(f"Trying to ban localhost for {ban_time}, but will not ban")
                ban_time = 0
        self.log.info(f"Connection closed: {connection.peer_host}, node id: {connection.peer_node_id}")
        if ban_time > 0:
            ban_until = time.time() + ban_time
            self.log.warning(f"Banning {connection.peer_host} for {ban_time} seconds")
            if connection.peer_host in self.banned_peers:
                if ban_until > self.banned_peers[connection.peer_host]:
                    self.banned_peers[connection.peer_host] = ban_until
            else:
                self.banned_peers[connection.peer_host] = ban_until
        if connection.peer_node_id in self.all_connections:
            self.all_connections.pop(connection.peer_node_id)
        if connection.connection_type is not None:
            if connection.peer_node_id in self.connection_by_type[connection.connection_type]:
                self.connection_by_type[connection.connection_type].pop(connection.peer_node_id)
        else:
            self.log.debug(f"Invalid connection type for connection {connection.peer_host}, while closing. Handshake never finished.")
        on_disconnect = getattr(self.node, 'on_disconnect', None)
        if on_disconnect is not None:
            on_disconnect(connection)
        self.cancel_tasks_from_peer(connection.peer_node_id)

    def cancel_tasks_from_peer(self, peer_id: bytes32):
        if peer_id not in self.tasks_from_peer:
            return
        task_ids = self.tasks_from_peer[peer_id]
        for task_id in task_ids:
            if task_id in self.execute_tasks:
                continue
            else:
                task = self.api_tasks[task_id]
                task.cancel()

    async def incoming_api_task(self) -> None:
        self.tasks = set()
        while 1:
            payload_inc, connection_inc = await self.incoming_messages.get()
            if not payload_inc is None:
                if connection_inc is None:
                    continue
                else:

                    async def api_call(full_message, connection, task_id):
                        start_time = time.time()
                        try:
                            try:
                                if self.received_message_callback is not None:
                                    await self.received_message_callback(connection)
                                connection.log.debug(f"<- {ProtocolMessageTypes(full_message.type).name} from peer {connection.peer_node_id} {connection.peer_host}")
                                message_type = ProtocolMessageTypes(full_message.type).name
                                f = getattr(self.api, message_type, None)
                                if f is None:
                                    self.log.error(f"Non existing function: {message_type}")
                                    raise ProtocolError(Err.INVALID_PROTOCOL_MESSAGE, [message_type])
                                if not hasattr(f, 'api_function'):
                                    self.log.error(f"Peer trying to call non api function {message_type}")
                                    raise ProtocolError(Err.INVALID_PROTOCOL_MESSAGE, [message_type])
                                if hasattr(self.api, 'api_ready'):
                                    if self.api.api_ready is False:
                                        return
                                timeout = 600
                                if hasattr(f, 'execute_task'):
                                    self.execute_tasks.add(task_id)
                                    timeout = None
                                if hasattr(f, 'peer_required'):
                                    coroutine = f(full_message.data, connection)
                                else:
                                    coroutine = f(full_message.data)

                                async def wrapped_coroutine():
                                    try:
                                        result = await coroutine
                                        return result
                                    except asyncio.CancelledError:
                                        pass
                                    except Exception as e:
                                        try:
                                            tb = traceback.format_exc()
                                            connection.log.error(f"Exception: {e}, {connection.get_peer_info()}. {tb}")
                                            raise e
                                        finally:
                                            e = None
                                            del e

                                response = await asyncio.wait_for((wrapped_coroutine()), timeout=timeout)
                                connection.log.debug(f"Time taken to process {message_type} from {connection.peer_node_id} is {time.time() - start_time} seconds")
                                if response is not None:
                                    response_message = Message(response.type, full_message.id, response.data)
                                    await connection.reply_to_request(response_message)
                            except Exception as e:
                                try:
                                    if self.connection_close_task is None:
                                        tb = traceback.format_exc()
                                        connection.log.error(f"Exception: {e} {type(e)}, closing connection {connection.get_peer_info()}. {tb}")
                                    else:
                                        connection.log.debug(f"Exception: {e} while closing connection")
                                    await connection.closeself.api_exception_ban_secondsWSCloseCode.PROTOCOL_ERRORErr.UNKNOWN
                                finally:
                                    e = None
                                    del e

                        finally:
                            if task_id in self.api_tasks:
                                self.api_tasks.pop(task_id)
                            if task_id in self.tasks_from_peer[connection.peer_node_id]:
                                self.tasks_from_peer[connection.peer_node_id].remove(task_id)
                            if task_id in self.execute_tasks:
                                self.execute_tasks.remove(task_id)

                    task_id = token_bytes()
                    api_task = asyncio.create_task(api_call(payload_inc, connection_inc, task_id))
                    self.api_tasks[task_id] = api_task
                    if connection_inc.peer_node_id not in self.tasks_from_peer:
                        self.tasks_from_peer[connection_inc.peer_node_id] = set()
                    self.tasks_from_peer[connection_inc.peer_node_id].add(task_id)

    async def send_to_others(self, messages: List[Message], node_type: NodeType, origin_peer: WSChiaConnection):
        for node_id, connection in self.all_connections.items():
            if node_id == origin_peer.peer_node_id:
                continue
            if connection.connection_type is node_type:
                for message in messages:
                    await connection.send_message(message)

    async def send_to_all(self, messages: List[Message], node_type: NodeType):
        for _, connection in self.all_connections.items():
            if connection.connection_type is node_type:
                for message in messages:
                    await connection.send_message(message)

    async def send_to_all_except(self, messages: List[Message], node_type: NodeType, exclude: bytes32):
        for _, connection in self.all_connections.items():
            if connection.connection_type is node_type:
                if connection.peer_node_id != exclude:
                    for message in messages:
                        await connection.send_message(message)

    async def send_to_specific(self, messages: List[Message], node_id: bytes32):
        if node_id in self.all_connections:
            connection = self.all_connections[node_id]
            for message in messages:
                await connection.send_message(message)

    def get_outgoing_connections(self) -> List[WSChiaConnection]:
        result = []
        for _, connection in self.all_connections.items():
            if connection.is_outbound:
                result.append(connection)

        return result

    def get_full_node_outgoing_connections(self) -> List[WSChiaConnection]:
        result = []
        connections = self.get_full_node_connections()
        for connection in connections:
            if connection.is_outbound:
                result.append(connection)

        return result

    def get_full_node_connections(self) -> List[WSChiaConnection]:
        return list(self.connection_by_type[NodeType.FULL_NODE].values())

    def get_connections(self, node_type: Optional[NodeType]=None) -> List[WSChiaConnection]:
        result = []
        for _, connection in self.all_connections.items():
            if not node_type is None:
                if connection.connection_type == node_type:
                    pass
            result.append(connection)

        return result

    async def close_all_connections(self) -> None:
        keys = [a for a, b in self.all_connections.items()]
        for node_id in keys:
            try:
                if node_id in self.all_connections:
                    connection = self.all_connections[node_id]
                    await connection.close()
            except Exception as e:
                try:
                    self.log.error(f"Exception while closing connection {e}")
                finally:
                    e = None
                    del e

    def close_all(self) -> None:
        self.connection_close_task = asyncio.create_task(self.close_all_connections())
        if self.runner is not None:
            self.site_shutdown_task = asyncio.create_task(self.runner.cleanup())
        if self.app is not None:
            self.app_shut_down_task = asyncio.create_task(self.app.shutdown())
        for task_id, task in self.api_tasks.items():
            task.cancel()

        self.shut_down_event.set()
        self.incoming_task.cancel()
        self.gc_task.cancel()

    async def await_closed(self) -> None:
        self.log.debug('Await Closed')
        await self.shut_down_event.wait()
        if self.connection_close_task is not None:
            await self.connection_close_task
        if self.app_shut_down_task is not None:
            await self.app_shut_down_task
        if self.site_shutdown_task is not None:
            await self.site_shutdown_task

    async def get_peer_info(self) -> Optional[PeerInfo]:
        ip = None
        port = self._port
        try:
            async with ClientSession() as session:
                async with session.get('https://checkip.amazonaws.com/') as resp:
                    if resp.status == 200:
                        ip = str(await resp.text())
                        ip = ip.rstrip()
        except Exception:
            ip = None

        if ip is None:
            return
        peer = PeerInfo(ip, uint16(port))
        if not peer.is_valid():
            return
        return peer

    def accept_inbound_connections(self, node_type: NodeType) -> bool:
        if not self._local_type == NodeType.FULL_NODE:
            return True
        inbound_count = len([conn for _, conn in self.connection_by_type[node_type].items() if not conn.is_outbound])
        if node_type == NodeType.FULL_NODE:
            return inbound_count < self.config['target_peer_count'] - self.config['target_outbound_peer_count']
        if node_type == NodeType.WALLET:
            return inbound_count < self.config['max_inbound_wallet']
        if node_type == NodeType.FARMER:
            return inbound_count < self.config['max_inbound_farmer']
        if node_type == NodeType.TIMELORD:
            return inbound_count < self.config['max_inbound_timelord']
        return True

    def is_trusted_peer(self, peer: WSChiaConnection, trusted_peers: Dict) -> bool:
        if trusted_peers is None:
            return False
        for trusted_peer in trusted_peers:
            cert = self.root_path / trusted_peers[trusted_peer]
            pem_cert = x509.load_pem_x509_certificate(cert.read_bytes())
            cert_bytes = pem_cert.public_bytes(encoding=(serialization.Encoding.DER))
            der_cert = x509.load_der_x509_certificate(cert_bytes)
            peer_id = bytes32(der_cert.fingerprint(hashes.SHA256()))
            if peer_id == peer.peer_node_id:
                self.log.debug(f"trusted node {peer.peer_node_id} {peer.peer_host}")
                return True

        return False