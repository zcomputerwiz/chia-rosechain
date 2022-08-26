# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\api_decorators.py
import functools, logging
from inspect import signature
from chia.util.streamable import Streamable
log = logging.getLogger(__name__)

def api_request(f):

    @functools.wraps(f)
    def f_substitute(*args, **kwargs):
        sig = signature(f)
        binding = (sig.bind)(*args, **kwargs)
        binding.apply_defaults()
        inter = dict(binding.arguments)
        for param_name, param_class in f.__annotations__.items():
            if param_name != 'return':
                if isinstance(inter[param_name], Streamable):
                    if param_class.__name__ == 'bytes':
                        continue
                    if hasattr(f, 'bytes_required'):
                        inter[f"{param_name}_bytes"] = bytes(inter[param_name])
                        continue
            if param_name != 'return':
                if isinstance(inter[param_name], bytes):
                    if param_class.__name__ == 'bytes':
                        continue
                    else:
                        if hasattr(f, 'bytes_required'):
                            inter[f"{param_name}_bytes"] = inter[param_name]
                        inter[param_name] = param_class.from_bytes(inter[param_name])

        return f(**inter)

    setattr(f_substitute, 'api_function', True)
    return f_substitute


def peer_required(func):

    def inner():
        setattr(func, 'peer_required', True)
        return func

    return inner()


def bytes_required(func):

    def inner():
        setattr(func, 'bytes_required', True)
        return func

    return inner()


def execute_task(func):

    def inner():
        setattr(func, 'execute_task', True)
        return func

    return inner()