# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\streamable.py
from __future__ import annotations
import dataclasses, io, pprint, sys
from enum import Enum
from typing import Any, BinaryIO, Dict, List, Tuple, Type, Callable, Optional, Iterator
from blspy import G1Element, G2Element, PrivateKey
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.hash import std_hash
from chia.util.ints import int64, int512, uint32, uint64, uint128
from chia.util.type_checking import is_type_List, is_type_SpecificOptional, is_type_Tuple, strictdataclass
if sys.version_info < (3, 8):

    def get_args(t: 'Type[Any]') -> 'Tuple[Any, ...]':
        return getattr(t, '__args__', ())


else:
    from typing import get_args
pp = pprint.PrettyPrinter(indent=1, width=120, compact=True)
size_hints = {'PrivateKey':PrivateKey.PRIVATE_KEY_SIZE, 
 'G1Element':G1Element.SIZE, 
 'G2Element':G2Element.SIZE, 
 'ConditionOpcode':1}
unhashable_types = [
 PrivateKey,
 G1Element,
 G2Element,
 Program,
 SerializedProgram]
big_ints = [
 uint64, int64, uint128, int512]

def dataclass_from_dict(klass, d):
    """
    Converts a dictionary based on a dataclass, into an instance of that dataclass.
    Recursively goes through lists, optionals, and dictionaries.
    """
    if is_type_SpecificOptional(klass):
        if not d:
            return
        return dataclass_from_dict(get_args(klass)[0], d)
    if is_type_Tuple(klass):
        i = 0
        klass_properties = []
        for item in d:
            klass_properties.append(dataclass_from_dict(klass.__args__[i], item))
            i = i + 1

        return tuple(klass_properties)
    if dataclasses.is_dataclass(klass):
        fieldtypes = {f.name: f.type for f in dataclasses.fields(klass)}
        return klass(**)
    if is_type_List(klass):
        return [dataclass_from_dict(get_args(klass)[0], item) for item in d]
    if issubclass(klass, bytes):
        return klass(hexstr_to_bytes(d))
    if klass in unhashable_types:
        return klass.from_bytes(hexstr_to_bytes(d))
    return klass(d)


def recurse_jsonify(d):
    """
    Makes bytes objects and unhashable types into strings with 0x, and makes large ints into
    strings.
    """
    if isinstance(d, list) or isinstance(d, tuple):
        new_list = []
        for item in d:
            if type(item) in unhashable_types or issubclass(type(item), bytes):
                item = f"0x{bytes(item).hex()}"
            else:
                if isinstance(item, dict):
                    item = recurse_jsonify(item)
                if isinstance(item, list):
                    item = recurse_jsonify(item)
                if isinstance(item, tuple):
                    item = recurse_jsonify(item)
                if isinstance(item, Enum):
                    item = item.name
                if isinstance(item, int):
                    if type(item) in big_ints:
                        item = int(item)
                new_list.append(item)

        d = new_list
    else:
        for key, value in d.items():
            if type(value) in unhashable_types or issubclass(type(value), bytes):
                d[key] = f"0x{bytes(value).hex()}"
            else:
                if isinstance(value, dict):
                    d[key] = recurse_jsonify(value)
                if isinstance(value, list):
                    d[key] = recurse_jsonify(value)
                if isinstance(value, tuple):
                    d[key] = recurse_jsonify(value)
                if isinstance(value, Enum):
                    d[key] = value.name
            if isinstance(value, int):
                if type(value) in big_ints:
                    d[key] = int(value)

    return d


PARSE_FUNCTIONS_FOR_STREAMABLE_CLASS = {}

def streamable(cls: 'Any'):
    """
    This is a decorator for class definitions. It applies the strictdataclass decorator,
    which checks all types at construction. It also defines a simple serialization format,
    and adds parse, from bytes, stream, and __bytes__ methods.

    Serialization format:
    - Each field is serialized in order, by calling from_bytes/__bytes__.
    - For Lists, there is a 4 byte prefix for the list length.
    - For Optionals, there is a one byte prefix, 1 iff object is present, 0 iff not.

    All of the constituents must have parse/from_bytes, and stream/__bytes__ and therefore
    be of fixed size. For example, int cannot be a constituent since it is not a fixed size,
    whereas uint32 can be.

    Furthermore, a get_hash() member is added, which performs a serialization and a sha256.

    This class is used for deterministic serialization and hashing, for consensus critical
    objects such as the block header.

    Make sure to use the Streamable class as a parent class when using the streamable decorator,
    as it will allow linters to recognize the methods that are added by the decorator. Also,
    use the @dataclass(frozen=True) decorator as well, for linters to recognize constructor
    arguments.
    """
    cls1 = strictdataclass(cls)
    t = type(cls.__name__, (cls1, Streamable), {})
    parse_functions = []
    try:
        fields = cls1.__annotations__
    except Exception:
        fields = {}

    for _, f_type in fields.items():
        parse_functions.append(cls.function_to_parse_one_item(f_type))

    PARSE_FUNCTIONS_FOR_STREAMABLE_CLASS[t] = parse_functions
    return t


def parse_bool(f: 'BinaryIO') -> 'bool':
    bool_byte = f.read(1)
    if not (bool_byte is not None and len(bool_byte) == 1):
        raise AssertionError
    if bool_byte == bytes([0]):
        return False
    if bool_byte == bytes([1]):
        return True
    raise ValueError('Bool byte must be 0 or 1')


def parse_optional(f: 'BinaryIO', parse_inner_type_f: 'Callable[[BinaryIO], Any]') -> 'Optional[Any]':
    is_present_bytes = f.read(1)
    if not (is_present_bytes is not None and len(is_present_bytes) == 1):
        raise AssertionError
    if is_present_bytes == bytes([0]):
        return
    if is_present_bytes == bytes([1]):
        return parse_inner_type_f(f)
    raise ValueError('Optional must be 0 or 1')


def parse_bytes(f: 'BinaryIO') -> 'bytes':
    list_size_bytes = f.read(4)
    if not (list_size_bytes is not None and len(list_size_bytes) == 4):
        raise AssertionError
    list_size = uint32(int.from_bytes(list_size_bytes, 'big'))
    bytes_read = f.read(list_size)
    if not (bytes_read is not None and len(bytes_read) == list_size):
        raise AssertionError
    return bytes_read


def parse_list(f: 'BinaryIO', parse_inner_type_f: 'Callable[[BinaryIO], Any]') -> 'List[Any]':
    full_list = []
    list_size_bytes = f.read(4)
    if not (list_size_bytes is not None and len(list_size_bytes) == 4):
        raise AssertionError
    list_size = uint32(int.from_bytes(list_size_bytes, 'big'))
    for list_index in range(list_size):
        full_list.append(parse_inner_type_f(f))

    return full_list


def parse_tuple(f: 'BinaryIO', list_parse_inner_type_f: 'List[Callable[[BinaryIO], Any]]') -> 'Tuple[Any, ...]':
    full_list = []
    for parse_f in list_parse_inner_type_f:
        full_list.append(parse_f(f))

    return tuple(full_list)


def parse_size_hints(f, f_type, bytes_to_read):
    bytes_read = f.read(bytes_to_read)
    if not (bytes_read is not None and len(bytes_read) == bytes_to_read):
        raise AssertionError
    return f_type.from_bytes(bytes_read)


def parse_str(f: 'BinaryIO') -> 'str':
    str_size_bytes = f.read(4)
    if not (str_size_bytes is not None and len(str_size_bytes) == 4):
        raise AssertionError
    str_size = uint32(int.from_bytes(str_size_bytes, 'big'))
    str_read_bytes = f.read(str_size)
    if not (str_read_bytes is not None and len(str_read_bytes) == str_size):
        raise AssertionError
    return bytes.decode(str_read_bytes, 'utf-8')


class Streamable:

    @classmethod
    def function_to_parse_one_item(cls: 'Type[cls.__name__]', f_type: 'Type'):
        """
        This function returns a function taking one argument `f: BinaryIO` that parses
        and returns a value of the given type.
        """
        if f_type is bool:
            return parse_bool
        if is_type_SpecificOptional(f_type):
            inner_type = get_args(f_type)[0]
            parse_inner_type_f = cls.function_to_parse_one_item(inner_type)
            return lambda f: parse_optional(f, parse_inner_type_f)
        if hasattr(f_type, 'parse'):
            return f_type.parse
        if f_type == bytes:
            return parse_bytes
        if is_type_List(f_type):
            inner_type = get_args(f_type)[0]
            parse_inner_type_f = cls.function_to_parse_one_item(inner_type)
            return lambda f: parse_list(f, parse_inner_type_f)
        if is_type_Tuple(f_type):
            inner_types = get_args(f_type)
            list_parse_inner_type_f = [cls.function_to_parse_one_item(_) for _ in inner_types]
            return lambda f: parse_tuple(f, list_parse_inner_type_f)
        if hasattr(f_type, 'from_bytes'):
            if f_type.__name__ in size_hints:
                bytes_to_read = size_hints[f_type.__name__]
                return lambda f: parse_size_hints(f, f_type, bytes_to_read)
        if f_type is str:
            return parse_str
        raise NotImplementedError(f"Type {f_type} does not have parse")

    @classmethod
    def parse(cls: 'Type[cls.__name__]', f: 'BinaryIO') -> 'cls.__name__':
        obj = object.__new__(cls)
        fields = iter(getattr(cls, '__annotations__', {}))
        values = (parse_f(f) for parse_f in PARSE_FUNCTIONS_FOR_STREAMABLE_CLASS[cls])
        for field, value in zip(fields, values):
            object.__setattr__(obj, field, value)

        if next(fields, -1) != -1:
            raise ValueError('Failed to parse incomplete Streamable object')
        if next(values, -1) != -1:
            raise ValueError('Failed to parse unknown data in Streamable object')
        return obj

    def stream_one_item(self, f_type: 'Type', item, f: 'BinaryIO') -> 'None':
        if is_type_SpecificOptional(f_type):
            inner_type = get_args(f_type)[0]
            if item is None:
                f.write(bytes([0]))
            else:
                f.write(bytes([1]))
                self.stream_one_item(inner_type, item, f)
        else:
            if f_type == bytes:
                f.write(uint32(len(item)).to_bytes(4, 'big'))
                f.write(item)
            else:
                if hasattr(f_type, 'stream'):
                    item.stream(f)
                else:
                    if hasattr(f_type, '__bytes__'):
                        f.write(bytes(item))
                    else:
                        if is_type_List(f_type):
                            assert is_type_List(type(item))
                            f.write(uint32(len(item)).to_bytes(4, 'big'))
                            inner_type = get_args(f_type)[0]
                            for element in item:
                                self.stream_one_item(inner_type, element, f)

                        else:
                            if is_type_Tuple(f_type):
                                inner_types = get_args(f_type)
                                assert len(item) == len(inner_types)
                                for i in range(len(item)):
                                    self.stream_one_item(inner_types[i], item[i], f)

                            else:
                                if f_type is str:
                                    str_bytes = item.encode('utf-8')
                                    f.write(uint32(len(str_bytes)).to_bytes(4, 'big'))
                                    f.write(str_bytes)
                                else:
                                    if f_type is bool:
                                        f.write(int(item).to_bytes(1, 'big'))
                                    else:
                                        raise NotImplementedError(f"can't stream {item}, {f_type}")

    def stream(self, f: 'BinaryIO') -> 'None':
        try:
            fields = self.__annotations__
        except Exception:
            fields = {}

        for f_name, f_type in fields.items():
            self.stream_one_item(f_type, getattr(self, f_name), f)

    def get_hash(self) -> 'bytes32':
        return bytes32(std_hash(bytes(self)))

    @classmethod
    def from_bytes(cls: 'Any', blob: 'bytes') -> 'Any':
        f = io.BytesIO(blob)
        parsed = cls.parse(f)
        assert f.read() == b''
        return parsed

    def __bytes__(self: 'Any') -> 'bytes':
        f = io.BytesIO()
        self.stream(f)
        return bytes(f.getvalue())

    def __str__(self: 'Any') -> 'str':
        return pp.pformat(recurse_jsonify(dataclasses.asdict(self)))

    def __repr__(self: 'Any') -> 'str':
        return pp.pformat(recurse_jsonify(dataclasses.asdict(self)))

    def to_json_dict(self) -> 'Dict':
        return recurse_jsonify(dataclasses.asdict(self))

    @classmethod
    def from_json_dict(cls: 'Any', json_dict: 'Dict') -> 'Any':
        return dataclass_from_dict(cls, json_dict)