# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\cmds\chia.py
import click
from chia import __version__
from chia.cmds.configure import configure_cmd
from chia.cmds.farm import farm_cmd
from chia.cmds.init import init_cmd
from chia.cmds.keys import keys_cmd
from chia.cmds.netspace import netspace_cmd
from chia.cmds.plots import plots_cmd
from chia.cmds.show import show_cmd
from chia.cmds.start import start_cmd
from chia.cmds.stop import stop_cmd
from chia.cmds.wallet import wallet_cmd
from chia.cmds.plotnft import plotnft_cmd
from chia.util.default_root import DEFAULT_ROOT_PATH
CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

def monkey_patch_click() -> None:
    import click.core
    click.core._verify_python3_env = lambda *args, **kwargs: 0


@click.group(help=f"\n  Manage chia blockchain infrastructure ({__version__})\n",
  epilog="Try 'chia start node', 'chia netspace -d 192', or 'chia show -s'",
  context_settings=CONTEXT_SETTINGS)
@click.option('--root-path', default=DEFAULT_ROOT_PATH, help='Config file root', type=(click.Path()), show_default=True)
@click.pass_context
def cli(ctx: click.Context, root_path: str) -> None:
    from pathlib import Path
    ctx.ensure_object(dict)
    ctx.obj['root_path'] = Path(root_path)


@cli.command('version', short_help='Show chia version')
def version_cmd() -> None:
    print(__version__)


@cli.command('run_daemon', short_help='Runs chia daemon')
@click.pass_context
def run_daemon_cmd(ctx: click.Context) -> None:
    from chia.daemon.server import async_run_daemon
    import asyncio
    asyncio.get_event_loop().run_until_complete(async_run_daemon(ctx.obj['root_path']))


cli.add_command(keys_cmd)
cli.add_command(plots_cmd)
cli.add_command(wallet_cmd)
cli.add_command(plotnft_cmd)
cli.add_command(configure_cmd)
cli.add_command(init_cmd)
cli.add_command(show_cmd)
cli.add_command(start_cmd)
cli.add_command(stop_cmd)
cli.add_command(netspace_cmd)
cli.add_command(farm_cmd)

def main() -> None:
    monkey_patch_click()
    cli()


if __name__ == '__main__':
    main()