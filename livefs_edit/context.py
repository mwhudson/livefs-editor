import glob
import os
import shlex
import shutil
import subprocess
import tempfile
import time

from . import run


class EditContext:

    def __init__(self, iso_path):
        self.iso_path = iso_path
        self.dir = tempfile.mkdtemp()
        os.mkdir(self.p('.tmp'))
        self._rootfs_dir = None
        self._pre_repack_hooks = []
        self._mounts = []

    def tmpdir(self):
        return tempfile.mkdtemp(dir=self.p('.tmp'))

    def p(self, *args):
        return os.path.join(self.dir, *args)

    def add_mount(self, typ, src, mountpoint=None, *, options=None):
        if mountpoint is None:
            mountpoint = self.tmpdir()
        cmd = ['mount', '-t', typ, src]
        if options:
            cmd.extend(['-o', options])
        cmd.append(mountpoint)
        if not os.path.isdir(mountpoint):
            os.makedirs(mountpoint)
        run(cmd)
        self._mounts.append(mountpoint)
        return mountpoint

    def add_sys_mounts(self, mountpoint):
        for typ, relpath in [
                ('devtmpfs',   'dev'),
                ('devpts',     'dev/pts'),
                ('proc',       'proc'),
                ('sysfs',      'sys'),
                ('securityfs', 'sys/kernel/security'),
                ]:
            self.add_mount(typ, typ, f'{mountpoint}/{relpath}')
        resolv_conf = f'{mountpoint}/etc/resolv.conf'
        os.rename(resolv_conf, resolv_conf + '.tmp')
        shutil.copy('/etc/resolv.conf', resolv_conf)

        def _pre_repack():
            os.rename(resolv_conf + '.tmp', resolv_conf)

        self.add_pre_repack_hook(_pre_repack)

    def add_overlay(self, lower, mountpoint=None, *, upper=None):
        if upper is None:
            upper = self.tmpdir()
        elif not os.path.isdir(upper):
            os.makedirs(upper)
        work = self.tmpdir()
        options = f'lowerdir={lower},upperdir={upper},workdir={work}'
        return self.add_mount(
            'overlay', 'overlay', mountpoint, options=options)

    def add_pre_repack_hook(self, hook):
        self._pre_repack_hooks.append(hook)

    def mount_squash(self, name):
        target = self.p('old/' + name)
        squash = self.p(f'old/iso/casper/{name}.squashfs')
        if not os.path.isdir(target):
            self.add_mount('squashfs', squash, target, options='ro')
        return target

    def get_arch(self):
        # Is this really the best way??
        with open(self.p('new/iso/.disk/info')) as fp:
            return fp.read().strip().split()[-2]

    def rootfs(self, target='rootfs'):
        if self._rootfs_dir is not None:
            return self._rootfs_dir
        self._rootfs_dir = self.p(target)
        squashes = sorted(glob.glob(self.p('old/iso/casper/*.squashfs')))
        lowers = []
        for squash in squashes:
            name = os.path.splitext(os.path.basename(squash))[0]
            lowers.append(self.mount_squash(name))
        lower = ':'.join(reversed(lowers))
        upper = self.tmpdir()
        self.add_overlay(lower, self._rootfs_dir, upper=upper)
        self.add_sys_mounts(self._rootfs_dir)

        last_squash = squashes[-1]
        base = os.path.basename(last_squash)
        new_squash = self.p('new/iso/casper/' + chr(ord(base[0])+1) + base[1:])

        def _pre_repack():
            if os.listdir(upper) != []:
                run(['mksquashfs', upper, new_squash])

        self.add_pre_repack_hook(_pre_repack)

        return self._rootfs_dir

    def teardown(self):
        for mount in reversed(self._mounts):
            run(['umount', '-l', mount])
        shutil.rmtree(self.dir)

    def mount_iso(self):
        old = self.p('old/iso')
        self.add_mount('iso9660', self.iso_path, old, options='loop,ro')
        self.add_overlay(old, self.p('new/iso'), upper=self.p('upper/iso'))

    def repack_iso(self, destpath):
        for hook in reversed(self._pre_repack_hooks):
            hook()
        if os.listdir(self.p('upper/iso')) == []:
            print("no changes!")
            return
        cp = run(
            ['xorriso', '-indev', self.iso_path, '-report_el_torito',
             'as_mkisofs'],
            encoding='utf-8', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        opts = shlex.split(cp.stdout)
        run(['xorriso', '-as', 'mkisofs'] + opts +
            ['-o', destpath, '-V', 'Ubuntu custom', self.p('new/iso')])
