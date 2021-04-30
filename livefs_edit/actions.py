import glob
import os
import shutil

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
