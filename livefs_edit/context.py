import contextlib
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
        self._cache = {}
        self._indent = ''
        self._pre_repack_hooks = []
        self._mounts = []

    def log(self, msg):
        print(self._indent + msg)

    @contextlib.contextmanager
    def logged(self, msg, done_msg=None):
        self.log(msg)
        self._indent += '  '
        try:
            yield
        finally:
            self._indent = self._indent[:-2]
        if done_msg is not None:
            self.log(done_msg)

    def tmpdir(self):
        d = tempfile.mkdtemp(dir=self.p('.tmp'))
        os.chmod(d, 0o755)
        return d

    def tmpfile(self):
        return tempfile.mktemp(dir=self.p('.tmp'))

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

    def umount(self, mountpoint):
        self._mounts.remove(mountpoint)
        run(['umount', mountpoint])

    def add_sys_mounts(self, mountpoint):
        mnts = []
        for typ, relpath in [
                ('devtmpfs',   'dev'),
                ('devpts',     'dev/pts'),
                ('proc',       'proc'),
                ('sysfs',      'sys'),
                ('securityfs', 'sys/kernel/security'),
                ]:
            mnts.append(self.add_mount(typ, typ, f'{mountpoint}/{relpath}'))
        resolv_conf = f'{mountpoint}/etc/resolv.conf'
        os.rename(resolv_conf, resolv_conf + '.tmp')
        shutil.copy('/etc/resolv.conf', resolv_conf)

        def _pre_repack():
            for mnt in reversed(mnts):
                self.umount(mnt)
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

    def edit_squashfs(self, name, *, add_sys_mounts=True):
        lower = self.mount_squash(name)
        upper = self.tmpdir()
        target = self.p(f'new/{name}')
        if os.path.exists(target):
            return target
        self.add_overlay(lower, target, upper=upper)
        self.log(f"squashfs {name!r} now mounted at {target!r}")
        new_squash = self.p(f'new/iso/casper/{name}.squashfs')

        def _pre_repack():
            try:
                os.unlink(f'{upper}/etc/resolv.conf')
                os.rmdir(f'{upper}/etc')
            except OSError:
                pass
            if os.listdir(upper) == []:
                self.log(f"no changes found in squashfs {name!r}")
                return
            with self.logged(f"repacking squashfs {name!r}"):
                os.unlink(new_squash)
            run(['mksquashfs', target, new_squash])

        self.add_pre_repack_hook(_pre_repack)

        if add_sys_mounts:
            self.add_sys_mounts(target)

        return target

    def teardown(self):
        for mount in reversed(self._mounts):
            run(['mount', '--make-rprivate', mount])
            run(['umount', '-R', mount])
        shutil.rmtree(self.dir)

    def mount_iso(self):
        old = self.p('old/iso')
        self.add_mount('iso9660', self.iso_path, old, options='loop,ro')
        self.add_overlay(old, self.p('new/iso'), upper=self.p('upper/iso'))

    def repack_iso(self, destpath):
        for hook in reversed(self._pre_repack_hooks):
            hook()
        if os.listdir(self.p('upper/iso')) == []:
            self.log("no changes!")
            return
        cp = run(
            ['xorriso', '-indev', self.iso_path, '-report_el_torito',
             'as_mkisofs'],
            encoding='utf-8', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        opts = shlex.split(cp.stdout)
        run(['xorriso', '-as', 'mkisofs'] + opts +
            ['-o', destpath, '-V', 'Ubuntu custom', self.p('new/iso')])
