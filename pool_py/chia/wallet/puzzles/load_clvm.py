# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\puzzles\load_clvm.py
import pathlib, pkg_resources
from clvm_tools.clvmc import compile_clvm
from chia.types.blockchain_format.program import Program, SerializedProgram

def load_serialized_clvm(clvm_filename, package_or_requirement=__name__) -> SerializedProgram:
    """
    This function takes a .clvm file in the given package and compiles it to a
    .clvm.hex file if the .hex file is missing or older than the .clvm file, then
    returns the contents of the .hex file as a `Program`.

    clvm_filename: file name
    package_or_requirement: usually `__name__` if the clvm file is in the same package
    """
    hex_filename = f"{clvm_filename}.hex"
    try:
        if pkg_resources.resource_exists(package_or_requirement, clvm_filename):
            full_path = pathlib.Path(pkg_resources.resource_filename(package_or_requirement, clvm_filename))
            output = full_path.parent / hex_filename
            compile_clvm(full_path, output, search_paths=[full_path.parent])
    except NotImplementedError:
        pass

    clvm_hex = pkg_resources.resource_string(package_or_requirement, hex_filename).decode('utf8')
    clvm_blob = bytes.fromhex(clvm_hex)
    return SerializedProgram.from_bytes(clvm_blob)


def load_clvm(clvm_filename, package_or_requirement=__name__) -> Program:
    return Program.from_bytes(bytes(load_serialized_clvm(clvm_filename, package_or_requirement=package_or_requirement)))