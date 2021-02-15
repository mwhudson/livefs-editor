import atexit
import os
import subprocess
from . import tmp


def run(cmd):
    return subprocess.run(cmd, check=False)


def add_mount(typ, src, mountpoint, *, options=None, existing=False):
    cmd = ['mount', '-t', typ, src]
    if options:
        cmd.extend(['-o', options])
    cmd.append(mountpoint)
    if not existing:
        os.mkdir(mountpoint)
    run(cmd)
    atexit.register(run, ['umount', mountpoint])


def add_overlay(lower, mountpoint, *, upper=None):
    if upper is None:
        upper = tmp.tmpdir()
    else:
        os.mkdir(upper)
    work = tmp.tmpdir()
    options = f'lowerdir={lower},upperdir={upper},workdir={work}'
    add_mount('overlay', 'overlay', mountpoint, options=options)


def add_sys_mount(typ, mountpoint):
    add_mount(typ, typ, mountpoint, existing=True)
