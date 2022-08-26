# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\__init__.py
from pkg_resources import DistributionNotFound, get_distribution, resource_filename
try:
    __version__ = get_distribution('chia-rosechain').version
except DistributionNotFound:
    __version__ = 'unknown'

PYINSTALLER_SPEC_PATH = resource_filename('chia', 'pyinstaller.spec')