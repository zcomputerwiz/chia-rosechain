# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\peer_info.py
import ipaddress
from dataclasses import dataclass
from typing import Optional, Union
from chia.util.ints import uint16, uint64
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class PeerInfo(Streamable):
    host: str
    port: uint16

    def is_valid(self, allow_private_subnets=False) -> bool:
        ip = None
        try:
            ip = ipaddress.IPv6Address(self.host)
        except ValueError:
            ip = None

        if ip is not None:
            if ip.is_private:
                if not allow_private_subnets:
                    return False
                return True
        try:
            ip = ipaddress.IPv4Address(self.host)
        except ValueError:
            ip = None

        if ip is not None:
            if ip.is_private:
                if not allow_private_subnets:
                    return False
                return True
        return False

    def get_key(self):
        try:
            ip = ipaddress.IPv6Address(self.host)
        except ValueError:
            ip_v4 = ipaddress.IPv4Address(self.host)
            ip = ipaddress.IPv6Address(int(ipaddress.IPv6Address('2002::')) | int(ip_v4) << 80)

        key = ip.packed
        key += bytes([self.port // 256, self.port & 255])
        return key

    def get_group(self):
        ipv4 = 1
        try:
            ip = ipaddress.IPv4Address(self.host)
        except ValueError:
            ip = ipaddress.IPv6Address(self.host)
            ipv4 = 0

        if ipv4:
            group = bytes([1]) + ip.packed[:2]
        else:
            group = bytes([0]) + ip.packed[:4]
        return group


@dataclass(frozen=True)
@streamable
class TimestampedPeerInfo(Streamable):
    host: str
    port: uint16
    timestamp: uint64