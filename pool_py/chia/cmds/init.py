# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\cmds\init.py
import click

@click.command('init', short_help='Create or migrate the configuration')
@click.option('--create-certs',
  '-c',
  default=None,
  help='Create new SSL certificates based on CA in [directory]',
  type=(click.Path()))
@click.pass_context
def init_cmd(ctx: click.Context, create_certs: str):
    """
    Create a new configuration or migrate from previous versions to current

    \x08
    Follow these steps to create new certificates for a remote harvester:
    - Make a copy of your Farming Machine CA directory: ~/.chiarose/[version]/config/ssl/ca
    - Shut down all chia daemon processes with `chia stop all -d`
    - Run `chia init -c [directory]` on your remote harvester,
      where [directory] is the the copy of your Farming Machine CA directory
    - Get more details on remote harvester on Chia wiki:
      https://github.com/Chia-Network/chia-blockchain/wiki/Farming-on-many-machines
    """
    from pathlib import Path
    from .init_funcs import init
    init(Path(create_certs) if create_certs is not None else None, ctx.obj['root_path'])


if __name__ == '__main__':
    from .init_funcs import chia_init
    from chia.util.default_root import DEFAULT_ROOT_PATH
    chia_init(DEFAULT_ROOT_PATH)