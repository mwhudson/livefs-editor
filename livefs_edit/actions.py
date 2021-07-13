import gzip
import os
import shutil
import subprocess
from typing import List
import yaml

from . import run


ACTIONS = {}


def register_action(func):
    ACTIONS[func.__name__.replace('_', '-')] = func
    return func


@register_action
def setup_rootfs(ctxt, target='rootfs'):
    ctxt.rootfs(target)


@register_action
def shell(ctxt, command=None):
    cmd = ['bash']
    if command is not None:
        cmd.extend(['-c', command])
    run(cmd, cwd=ctxt.p())


@register_action
def cp(ctxt, source, dest):
    shutil.copy(source, ctxt.p(dest))


@register_action
def inject_snap(ctxt, snap, channel="stable"):
    rootfs = ctxt.rootfs()
    seed_dir = f'{rootfs}/var/lib/snapd/seed'
    snap_mount = ctxt.tmpdir()
    ctxt.add_mount('squashfs', snap, snap_mount)
    with open(f'{snap_mount}/meta/snap.yaml') as fp:
        snap_meta = yaml.safe_load(fp)

    snap_name = snap_meta['name']

    snap_file = f'{snap_name}_injected'

    new_snap = {
        "name": snap_name,
        "file": snap_file + '.snap',
        "channel": channel,
        }

    if snap_meta.get('confinement') == 'classic':
        new_snap['classic'] = True

    new_snaps = []

    with open(f'{seed_dir}/seed.yaml') as fp:
        old_seed = yaml.safe_load(fp)
    for old_snap in old_seed["snaps"]:
        if old_snap["name"] == snap_name:
            old_base = os.path.splitext(old_snap['file'])[0]
            old_snap_file = f'{seed_dir}/snaps/{old_base}.snap'
            old_assertion = f'{seed_dir}/assertions/{old_base}.assert'
            for p in old_snap_file, old_assertion:
                if os.path.exists(p):
                    os.unlink(p)
        else:
            new_snaps.append(old_snap)

    new_snaps.append(new_snap)
    shutil.copy(snap, f'{seed_dir}/snaps/{snap_file}.snap')
    assert_file = os.path.splitext(snap)[0] + '.assert'
    if os.path.exists(assert_file):
        shutil.copy(assert_file, f'{seed_dir}/assertions/{snap_file}.assert')
    else:
        new_snap["unasserted"] = True

    with open(f'{seed_dir}/seed.yaml', "w") as fp:
        yaml.dump({"snaps": new_snaps}, fp)

    run(['/usr/lib/snapd/snap-preseed', '--reset', rootfs])
    run(['/usr/lib/snapd/snap-preseed', rootfs])


@register_action
def add_snap_from_store(ctxt, snap_name, channel="stable"):
    dldir = ctxt.tmpdir()
    run([
        'snap', 'download',
        '--channel=' + channel,
        '--target-directory=' + dldir,
        '--basename=dl',
        snap_name,
        ])
    inject_snap(ctxt, os.path.join(dldir, 'dl.snap'), channel)


@register_action
def add_cmdline_arg(ctxt, arg, persist: bool = True):
    cfgs = [
        'boot/grub/grub.cfg',    # grub, most arches
        'isolinux/txt.cfg',      # isolinux, BIOS amd64/i386 <= focal
        'boot/parmfile.ubuntu',  # s390x
        ]
    for path in cfgs:
        p = ctxt.p('new/iso/' + path)
        if not os.path.exists(p):
            continue
        print('rewriting', path)
        with open(p) as fp:
            inputlines = list(fp)
        with open(p, 'w') as outfp:
            for line in inputlines:
                if '---' in line:
                    if persist:
                        line = line.rstrip() + ' ' + arg + '\n'
                    else:
                        before, after = line.split('---', 1)
                        line = before.rstrip() + ' ' + arg + ' ---' + after
                outfp.write(line)


@register_action
def edit_squashfs(ctxt, squash_name, add_sys_mounts=True):
    ctxt.edit_squashfs(squash_name, add_sys_mounts=add_sys_mounts)


@register_action
def add_autoinstall_config(ctxt, autoinstall_config):
    seed_dir = 'var/lib/cloud/seed/nocloud'
    CC_PREFIX = '#cloud-config\n'

    rootfs = ctxt.rootfs()
    is_cc = False
    with open(autoinstall_config) as fp:
        first_line = fp.readline()
        if first_line == CC_PREFIX:
            is_cc = True
            first_line = ''
        config = yaml.safe_load(first_line + fp.read())
    if not is_cc:
        config = {'autoinstall': config}
    with open(os.path.join(rootfs, seed_dir, 'user-data'), 'w') as fp:
        fp.write(CC_PREFIX)
        yaml.dump(config, fp)
    add_cmdline_arg(ctxt, 'autoinstall', persist=False)


@register_action
def add_debs_to_pool(ctxt, debs: List[str]):
    gpgconf = ctxt.tmpfile()
    gpghome = ctxt.tmpdir()
    with open(gpgconf, 'x') as c:
        c.write("""\
%no-protection
Key-Type: eddsa
Key-Curve: Ed25519
Key-Usage: sign
Name-Real: Ubuntu Custom ISO One-Time Signing Key
Name-Email: noone@nowhere.invalid
Expire-Date: 0
""")
    gpgconfp = open(gpgconf)
    gpg_proc = subprocess.Popen(
        ['gpg', '--home', gpghome, '--gen-key', '--batch'],
        stdin=gpgconfp)

    from debian import deb822
    pool = ctxt.p('new/iso/pool/main')
    for deb in debs:
        shutil.copy(deb, pool)
    arch = ctxt.get_arch()
    packages = ctxt.p(f'new/iso/dists/stable/main/binary-{arch}/Packages')
    cp = run(
        [
            'apt-ftparchive', '--md5=off', '--sha1=off',
            'packages', 'pool/main',
        ],
        cwd=ctxt.p('new/iso'), stdout=subprocess.PIPE)
    with open(packages, 'wb') as new_packages:
        new_packages.write(cp.stdout)
    with gzip.open(packages + '.gz', 'wb') as new_packages:
        new_packages.write(cp.stdout)
    release = ctxt.p(f'new/iso/dists/stable/Release')
    with open(release) as o:
        old = deb822.Deb822(o)
    for p in release, release + '.gpg':
        if os.path.exists(p):
            os.unlink(p)
    cp = run(
        [
            'apt-ftparchive', '--md5=off', '--sha1=off', '--sha512=off',
            'release', 'dists/stable',
        ],
        cwd=ctxt.p('new/iso'), stdout=subprocess.PIPE)
    # The uncompressed Packages file has to be around when
    # apt-ftparchive release is run, but it can be deleted now.
    os.unlink(packages)
    new = deb822.Deb822(cp.stdout)
    for k in old:
        if k in new:
            old[k] = new[k]
    with open(release, 'wb') as new_release:
        old.dump(new_release)

    gpg_proc.wait()

    run(['gpg', '--home', gpghome, '--detach-sign', '--armor', release])
    os.rename(release + '.asc', release + '.gpg')

    new_fs = ctxt.edit_squashfs('filesystem')
    key_path = f'{new_fs}/etc/apt/trusted.gpg.d/custom-iso-key.gpg'
    with open(key_path, 'w') as new_key:
        run(['gpg', '--home', gpghome, '--export'], stdout=new_key)


@register_action
def add_packages_to_pool(ctxt, packages: List[str]):
    import apt_pkg
    from apt import Cache
    from apt.progress.text import AcquireProgress
    fs = ctxt.mount_squash('filesystem')
    overlay = ctxt.add_overlay(fs)
    for key in apt_pkg.config.list():
        apt_pkg.config.clear(key)
    apt_pkg.config["Dir"] = overlay
    apt_pkg.init_config()
    apt_pkg.config["APT::Architecture"] = ctxt.get_arch()
    apt_pkg.config["APT::Architectures"] = ctxt.get_arch()
    apt_pkg.init_system()
    cache = Cache()
    print('  ** updating apt lists... **')
    cache.update(AcquireProgress())
    print('  ** updating apt lists done **')
    cache.open()
    for p in packages:
        print('marking', p, 'for installation')
        cache[p].mark_install()
    tdir = ctxt.tmpdir()
    pool_debs = set()
    for dirpath, dirnames, filenames in os.walk(ctxt.p('new/iso/pool')):
        for fname in filenames:
            if fname.endswith('.deb'):
                pool_debs.add(fname)
    debs = []
    for p in cache.get_changes():
        fname = os.path.basename(p.candidate.filename)
        if fname not in pool_debs:
            debs.append(p.candidate.fetch_binary(tdir))
    add_debs_to_pool(ctxt, debs)


def add_to_pipeline(prev_proc, cmds, env=None, **kw):
    if env is not None:
        base_env = os.environ.copy()
        base_env.update(env)
        env = base_env
    if prev_proc is not None:
        stdin = prev_proc.stdout
    else:
        stdin = None
    proc = subprocess.Popen(
        cmds, stdout=kw.pop('stdout', subprocess.PIPE),
        stdin=stdin, env=env, **kw)
    if stdin is not None:
        stdin.close()
    return proc


def pack_for_initrd(dir, compress, outfile):
    find = add_to_pipeline(None, ['find', '.'], cwd=dir)
    sort = add_to_pipeline(find, ['sort'], env={'LC_ALL': 'C'})
    cpio = add_to_pipeline(
        sort, ['cpio', '-R', '0:0', '-o', '-H', 'newc'], cwd=dir)
    if dir == 'main':
        compress = add_to_pipeline(cpio, ['gzip'], stdout=outfile)
    else:
        compress = add_to_pipeline(cpio, ['cat'], stdout=outfile)
    compress.communicate()


@register_action
def unpack_initrd(ctxt, target='new/initrd'):
    target = ctxt.p(target)
    lower = ctxt.p('old/initrd')
    arch = ctxt.get_arch()
    if arch == 's390x':
        initrd_path = 'boot/initrd.ubuntu'
    else:
        initrd_path = 'casper/initrd'
    run(['unmkinitramfs', ctxt.p(f'new/iso/{initrd_path}'), lower])
    upper = ctxt.tmpdir()
    ctxt.add_overlay(lower, target, upper=upper)

    if 'early' in os.listdir(target):
        def _pre_repack_multi():
            if os.listdir(upper) == []:
                # Don't slowly repack initrd if no changes made to it.
                return
            print('repacking initrd to', initrd_path, '...')
            with open(ctxt.p(f'new/iso/{initrd_path}'), 'wb') as out:
                for dir in sorted(os.listdir(target)):
                    print("  packing", dir)
                    pack_for_initrd(f'{target}/{dir}', dir == "main", out)

            print("  ... done")

        ctxt.add_pre_repack_hook(_pre_repack_multi)
    else:
        def _pre_repack_single():
            if os.listdir(upper) == []:
                # Don't slowly repack initrd if no changes made to it.
                return
            print('repacking initrd...')
            with open(ctxt.p('new/iso/{initrd_path}'), 'wb') as out:
                pack_for_initrd(target, True, out)
            print("  ... done")

        ctxt.add_pre_repack_hook(_pre_repack_single)
