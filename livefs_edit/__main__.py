#!/usr/bin/python3

# Copyright 2021 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3, as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranties of
# MERCHANTABILITY, SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR
# PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see
# <http://www.gnu.org/licenses/>.

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
    if '--help' in argv or len(argv) < 3:
        print(HELP_TXT)
        for action in sorted(ACTIONS.keys()):
            print(f" * --{action.replace('_', '-')}")
        print()
        sys.exit(0)

    debug = False
    arch_emulator = False
    if argv[0] == '--debug':
        debug = True
        argv.pop(0)
    if argv[0] == '--arch_emulator':
        argv.pop(0)
        arch_emulator = argv[0]
        argv.pop(0)

    sourcepath = argv[0]
    destpath = argv[1]

    inplace = False
    if destpath == '/dev/null':
        destpath = None
    elif destpath == sourcepath:
        destpath = destpath + '.new'
        inplace = True

    ctxt = EditContext(sourcepath, debug=debug, arch_emulator=arch_emulator)

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
