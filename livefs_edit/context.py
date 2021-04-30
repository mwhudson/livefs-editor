import os
import shlex
import shutil
import subprocess
import tempfile

from . import run


class EditContext:

    def __init__(self, iso_path):
        self.iso_path = iso_path
        self.dir = tempfile.mkdtemp()
        os.mkdir(self.p('.tmp'))
        self._pre_repack_hooks = []
        self._mounts = []

    def tmpdir(self):
        return tempfile.mkdtemp(dir=self.p('.tmp'))

    def p(self, *args):
        return os.path.join(self.dir, *args)

    def add_mount(self, typ, src, mountpoint, *, options=None):
        mountpoint = self.p(mountpoint)
        cmd = ['mount', '-t', typ, src]
        if options:
            cmd.extend(['-o', options])
        cmd.append(mountpoint)
        if not os.path.isdir(mountpoint):
            os.makedirs(mountpoint)
        run(cmd)
        self._mounts.append(mountpoint)

    def add_sys_mounts(self, mountpoint):
        for typ, relpath in [
                ('devtmpfs',   'dev'),
                ('devpts',     'dev/pts'),
                ('proc',       'proc'),
                ('sysfs',      'sys'),
                ('securityfs', 'sys/kernel/security'),
                ]:
            self.add_mount(typ, typ, f'{mountpoint}/{relpath}')

    def add_overlay(self, lower, mountpoint, *, upper=None):
        if upper is None:
            upper = self.tmpdir()
        elif not os.path.isdir(upper):
            os.mkdir(upper)
        work = self.tmpdir()
        options = f'lowerdir={lower},upperdir={upper},workdir={work}'
        self.add_mount('overlay', 'overlay', mountpoint, options=options)

    def add_pre_repack_hook(self, hook):
        self._pre_repack_hooks.append(hook)

    def teardown(self):
        for mount in reversed(self._mounts):
            run(['umount', mount])
        shutil.rmtree(self.dir)

    def mount_iso(self):
        old = self.p('old/iso')
        self.add_mount('iso9660', self.iso_path, old, options='loop,ro')
        self.add_overlay(old, 'new/iso')

    def repack_iso(self, destpath):
        for hook in reversed(self._pre_repack_hooks):
            hook()
        cp = run(
            ['xorriso', '-indev', self.iso_path, '-report_el_torito',
             'as_mkisofs'],
            encoding='utf-8', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        opts = shlex.split(cp.stdout)
        run(['xorriso', '-as', 'mkisofs'] + opts +
            ['-o', destpath, '-V', 'Ubuntu custom', self.p('new/iso')])
