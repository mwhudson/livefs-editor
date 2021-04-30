import glob
import os
import shutil
import yaml

from . import run


def setup_tree(ctxt, target):
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


def inject_snap(ctxt, snap, target, channel="stable"):
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
