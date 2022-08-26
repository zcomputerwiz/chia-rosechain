# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\cmds\start_funcs.py
import asyncio, os, subprocess, sys
from pathlib import Path
from typing import Optional
from chia.daemon.client import DaemonProxy, connect_to_daemon_and_validate
from chia.util.service_groups import services_for_groups

def launch_start_daemon(root_path: Path) -> subprocess.Popen:
    os.environ['CHIA_ROOT'] = str(root_path)
    chia = sys.argv[0]
    process = subprocess.Popen((f"{chia} run_daemon".split()), stdout=(subprocess.PIPE))
    return process


async def create_start_daemon_connection(root_path: Path) -> Optional[DaemonProxy]:
    connection = await connect_to_daemon_and_validate(root_path)
    if connection is None:
        print('Starting daemon')
        process = launch_start_daemon(root_path)
        if process.stdout:
            process.stdout.readline()
        await asyncio.sleep(1)
        connection = await connect_to_daemon_and_validate(root_path)
    if connection:
        return connection


async def async_start(root_path, group, restart):
    daemon = await create_start_daemon_connection(root_path)
    if daemon is None:
        print('Failed to create the chia daemon')
        return
    for service in services_for_groups(group):
        if await daemon.is_running(service_name=service):
            print(f"{service}: ", end='', flush=True)
            if restart:
                if not await daemon.is_running(service_name=service):
                    print('not running')
                else:
                    if await daemon.stop_service(service_name=service):
                        print('stopped')
                    else:
                        print('stop failed')
            else:
                print('Already running, use `-r` to restart')
                continue
        print(f"{service}: ", end='', flush=True)
        msg = await daemon.start_service(service_name=service)
        success = msg and msg['data']['success']
        if success is True:
            print('started')
        else:
            error = 'no response'
        if msg:
            error = msg['data']['error']
        else:
            print(f"{service} failed to start. Error: {error}")

    await daemon.close()