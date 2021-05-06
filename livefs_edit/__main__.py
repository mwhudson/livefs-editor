#!/usr/bin/python3

import sys

import yaml

from livefs_edit.context import EditContext
from livefs_edit import actions, cli

isopath = sys.argv[1]
destpath = sys.argv[2]

ctxt = EditContext(isopath)
ctxt.mount_iso()

if sys.argv[3] == '--action-yaml':
    calls = []
    with open(sys.argv[4]) as fp:
        spec = yaml.load(fp)
    print(spec)
    for action in spec:
        func = getattr(actions, action.pop('name').replace('-', '_'))
        calls.append((func, action))
else:
    try:
        calls = cli.parse(actions, sys.argv[3:])
    except cli.ArgException as e:
        print("parsing actions from command line failed:", e)
        sys.exit(1)

try:
    for func, kw in calls:
        print(
            "running", func.__name__.replace('_', '-'),  "with arguments", kw)
        func(ctxt, **kw)

    ctxt.repack_iso(destpath)
finally:
    ctxt.teardown()
