import gzip
import os
import shutil
import subprocess
from typing import List
import yaml

from . import run


def setup_rootfs(ctxt, target='rootfs'):
    ctxt.rootfs(target)


def shell(ctxt, command=None):
    cmd = ['bash']
    if command is not None:
        cmd.extend(['-c', command])
    run(cmd, cwd=ctxt.p())


def cp(ctxt, source, dest):
    shutil.copy(source, ctxt.p(dest))


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
        shutil.copy(snap, f'{seed_dir}/assertions/{snap_file}.assert')
    else:
        new_snap["unasserted"] = True

    with open(f'{seed_dir}/seed.yaml', "w") as fp:
        yaml.dump({"snaps": new_snaps}, fp)

    run(['/usr/lib/snapd/snap-preseed', '--reset', rootfs])
    run(['/usr/lib/snapd/snap-preseed', rootfs])


def add_cmdline_arg(ctxt, arg, persist: bool = True):
    cfgs = [
        'boot/grub/grub.cfg',
        'isolinux/txt.cfg',
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


def edit_squashfs(ctxt, squash_name, add_sys_mounts=True):
    ctxt.edit_squashfs(squash_name, add_sys_mounts=add_sys_mounts)


def add_autoinstall_cfg(ctxt, autoinstall_config):
    rootfs = ctxt.rootfs()
    shutil.copy(autoinstall_config, os.path.join(rootfs, 'autoinstall.yaml'))
    add_cmdline_arg(ctxt, 'autoinstall', persist=False)


def add_debs_to_pool(ctxt, debs: List[str]):
    from debian import deb822
    pool = ctxt.p('new/iso/pool/main')
    for deb in debs:
        shutil.copy(deb, pool)
    arch = ctxt.get_arch()
    packages = ctxt.p(f'new/iso/dists/stable/main/binary-{arch}/Packages.gz')
    cp = run(
        [
            'apt-ftparchive', '--md5=off', '--sha1=off',
            'packages', 'pool/main',
        ],
        cwd=ctxt.p('new/iso'), stdout=subprocess.PIPE)
    with gzip.open(packages, 'wb') as new_packages:
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
            'release', 'dists/unstable',
        ],
        cwd=ctxt.p('new/iso'), stdout=subprocess.PIPE)
    new = deb822.Deb822(cp.stdout)
    for k in old:
        if k in new:
            old[k] = new[k]
    with open(release, 'wb') as new_release:
        old.dump(new_release)


def add_packages_to_pool(ctxt, packages: List[str]):
    from apt import Cache
    fs = ctxt.mount_squash('filesystem')
    overlay = ctxt.add_overlay(fs)
    ctxt.add_sys_mounts(overlay)
    print('  ** running apt update **')
    run(['chroot', overlay, 'apt', 'update'])
    print('  ** apt update done **')
    cache = Cache(rootdir=overlay)
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


def unpack_initrd(ctxt, target='initrd'):
    target = ctxt.p(target)
    lower = ctxt.p('old/initrd')
    arch = ctxt.get_arch()
    if arch == 's390x':
        initrd_path = 'boot/initrd.ubuntu'
    else:
        initrd_path = 'casper/initrd'
    run(['unmkinitramfs', ctxt.p(f'old/iso/{initrd_path}'), lower])
    upper = ctxt.tmpdir()
    ctxt.add_overlay(lower, target, upper=upper)

    if 'early' in os.listdir(target):
        def _pre_repack_multi():
            if os.listdir(upper) == []:
                # Don't slowly repack initrd if no changes made to it.
                return
            print('repacking initrd...')
            with open(ctxt.p('new/iso/{initrd_path}'), 'wb') as out:
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
