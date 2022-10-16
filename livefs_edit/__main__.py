#!/usr/bin/python3

import os
import subprocess
import sys
import traceback

import yaml

from livefs_edit import cli
from livefs_edit.context import EditContext
from livefs_edit.actions import ACTIONS


HELP_TXT = """\
# livefs-edit source.{iso,img} dest.{iso,img} [actions]

livefs-edit makes modifications to Ubuntu live ISOs and images.

Actions include:
"""


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if '--help' in argv:
        print(HELP_TXT)
        for action in sorted(ACTIONS.keys()):
            print(f" * --{action.replace('_', '-')}")
        print()
        sys.exit(0)

    sourcepath = argv[0]
    destpath = argv[1]

    inplace = False
    if destpath == '/dev/null':
        destpath = None
    elif destpath == sourcepath:
        destpath = destpath + '.new'
        inplace = True

    ctxt = EditContext(sourcepath)

    if argv[2] == '--action-yaml':
        calls = []
        with open(argv[3]) as fp:
            spec = yaml.safe_load(fp)
        print(spec)
        for action in spec:
            func = ACTIONS[action.pop('name')]
            calls.append((func, action))
    else:
        try:
            calls = cli.parse(ACTIONS, argv[2:])
        except cli.ArgException as e:
            print("parsing actions from command line failed:", e)
            sys.exit(1)

    try:
        ctxt.mount_source()

        for func, kw in calls:
            func(ctxt, **kw)

        if destpath is not None:
            changed = ctxt.repack(destpath)
            if changed and inplace:
                os.rename(destpath, sourcepath)
    except subprocess.CalledProcessError as cp:
        traceback.print_exc()
        if cp.stdout:
            print("\nStdout:\n\n"+cp.stdout)
        if cp.stderr:
            print("\nStderr:\n\n"+cp.stderr)
        sys.exit(1)
    finally:
        ctxt.teardown()


if __name__ == '__main__':
    main(sys.argv[1:])
