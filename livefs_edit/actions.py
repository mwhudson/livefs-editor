import glob
import gzip
import os
import shutil
import subprocess
import yaml

from . import run


def setup_tree(ctxt, target='tree'):
    target = ctxt.p(target)
    squashes = sorted(glob.glob(ctxt.p('old/iso/casper/*.squashfs')))
    lowers = []
    for squash in squashes:
        lower = ctxt.p('old/' + os.path.splitext(os.path.basename(squash))[0])
        if not os.path.isdir(lower):
            ctxt.add_mount('squashfs', squash, lower)
        lowers.append(lower)
    lower = ':'.join(reversed(lowers))
    upper = ctxt.tmpdir()
    ctxt.add_overlay(lower, target, upper=upper)
    ctxt.add_sys_mounts(target)

    last_squash = squashes[-1]
    base = os.path.basename(last_squash)
    new_squash = ctxt.p('new/iso/casper/' + chr(ord(base[0])+1) + base[1:])

    def _pre_repack():
        if os.listdir(upper) != []:
            run(['mksquashfs', upper, new_squash])

    ctxt.add_pre_repack_hook(_pre_repack)


def shell(ctxt, command=None):
    cmd = ['bash']
    if command is not None:
        cmd.extend(['-c', command])
    run(cmd, cwd=ctxt.p())


def replace_file(ctxt, source, dest):
    shutil.copy(source, ctxt.p(dest))


def inject_snap(ctxt, snap, target='tree', channel="stable"):
    target = ctxt.p(target)
    seed_dir = f'{target}/var/lib/snapd/seed'
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

    run(['/usr/lib/snapd/snap-preseed', '--reset', target])
    run(['/usr/lib/snapd/snap-preseed', target])


def add_cmdline_arg(ctxt, arg, persist=True):
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


def add_autoinstall_cfg(ctxt, autoinstall_config, target='tree'):
    shutil.copy(autoinstall_config, ctxt.p(target, 'autoinstall.yaml'))
    add_cmdline_arg(ctxt, 'autoinstall', persist=False)


def add_debs_to_pool(ctxt, debs):
    from debian import deb822
    pool = ctxt.p('new/iso/pool/main')
    with open(ctxt.p('new/iso/.disk/info')) as fp:
        arch = fp.read().strip().split()[-2]
    for deb in debs:
        shutil.copy(deb, pool)
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


def add_packages_to_pool(ctxt, packages, target='tree'):
    from apt import Cache
    cache = Cache(rootdir=ctxt.p(target))
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
