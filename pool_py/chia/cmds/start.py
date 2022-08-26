# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\cmds\start.py
import click
from chia.util.service_groups import all_groups

@click.command('start', short_help='Start service groups')
@click.option('-r', '--restart', is_flag=True, type=bool, help='Restart running services')
@click.argument('group', type=(click.Choice(all_groups())), nargs=(-1), required=True)
@click.pass_context
def start_cmd(ctx: click.Context, restart: bool, group: str) -> None:
    import asyncio
    from .start_funcs import async_start
    asyncio.get_event_loop().run_until_complete(async_start(ctx.obj['root_path'], group, restart))