import os
import shlex
import subprocess

from . import output, run, cat

from .mount import add_mount, add_overlay, add_sys_mount


def setup_iso(isopath):
    add_mount('iso9660', isopath, 'old_iso', options='loop,ro')
    add_mount(
        'squashfs', 'old_iso/casper/filesystem.squashfs', 'old_filesystem')
    add_mount(
        'squashfs', 'old_iso/casper/installer.squashfs', 'old_installer')
    add_overlay('old_filesystem', 'new_filesystem', upper='filesystem_upper')
    add_overlay('old_installer', 'new_installer', upper='installer_upper')
    add_overlay(
        'old_installer:old_filesystem', 'tree', upper='jnstaller_upper')
    add_overlay('old_iso', 'new_iso', upper='iso_upper')
    add_sys_mount('devtmpfs', 'tree/dev')
    add_sys_mount('devpts', 'tree/dev/pts')
    add_sys_mount('proc', 'tree/proc')
    add_sys_mount('sysfs', 'tree/sys')
    add_sys_mount('securityfs', 'tree/sys/kernel/security')


def repack_iso(destpath):
    loop = os.path.basename(
        output(['findmnt', '-no', 'source', 'old_iso']).strip())
    backing = cat(f'/sys/class/block/{loop}/loop/backing_file').strip()
    for s in 'filesystem', 'installer', 'jnstaller':
        if os.listdir(f'{s}_upper') == []:
            continue
        dest = f'new_iso/casper/{s}.squashfs'
        if os.path.exists(dest):
            os.unlink(dest)
        if s == 'jnstaller':
            src = 'jnstaller_upper'
        else:
            src = f'new_{s}'
        run(['mksquashfs', src, dest])
    filepaths = set()
    for dirpath, dirnames, filenames in os.walk('iso_upper'):
        for filename in filenames:
            filepaths.add(os.path.join(dirpath, filename))
    cp = run(
        ['xorriso', '-indev', backing, '-report_el_torito', 'as_mkisofs'],
        encoding='utf-8', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    opts = shlex.split(cp.stdout)
    run(['xorriso', '-as', 'mkisofs'] + opts +
        ['-o', destpath, '-V', 'Ubuntu custom', 'new_iso'])
