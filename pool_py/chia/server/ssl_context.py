# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\server\ssl_context.py
from pathlib import Path
from typing import Dict

def public_ssl_paths(path: Path, config: Dict):
    return (
     path / config['ssl']['public_crt'],
     path / config['ssl']['public_key'])


def private_ssl_paths(path: Path, config: Dict):
    return (
     path / config['ssl']['private_crt'],
     path / config['ssl']['private_key'])


def private_ssl_ca_paths(path: Path, config: Dict):
    return (
     path / config['private_ssl_ca']['crt'],
     path / config['private_ssl_ca']['key'])


def chia_ssl_ca_paths(path: Path, config: Dict):
    return (
     path / config['chia_ssl_ca']['crt'],
     path / config['chia_ssl_ca']['key'])