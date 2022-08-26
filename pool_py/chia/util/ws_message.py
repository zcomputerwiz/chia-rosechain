# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\ws_message.py
from secrets import token_bytes
from typing import Any, Dict
from chia.util.json_util import dict_to_json_str
try:
    from typings import TypedDict
except ImportError:
    from typing_extensions import TypedDict

class WsRpcMessage(TypedDict):
    command: str
    ack: bool
    data: Dict[(str, Any)]
    request_id: str
    destination: str
    origin: str


def format_response(incoming_msg: WsRpcMessage, response_data: Dict[(str, Any)]) -> str:
    """
    Formats the response into standard format.
    """
    response = {'command':incoming_msg['command'], 
     'ack':True, 
     'data':response_data, 
     'request_id':incoming_msg['request_id'], 
     'destination':incoming_msg['origin'], 
     'origin':incoming_msg['destination']}
    json_str = dict_to_json_str(response)
    return json_str


def create_payload(command: str, data: Dict[(str, Any)], origin: str, destination: str) -> str:
    response = create_payload_dict(command, data, origin, destination)
    return dict_to_json_str(response)


def create_payload_dict(command: str, data: Dict[(str, Any)], origin: str, destination: str) -> WsRpcMessage:
    return WsRpcMessage(command=command,
      ack=False,
      data=data,
      request_id=(token_bytes().hex()),
      destination=destination,
      origin=origin)


def pong() -> Dict[(str, Any)]:
    response = {'success': True}
    return response