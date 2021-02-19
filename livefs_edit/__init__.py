#

import subprocess


def run(cmd, check=True, **kw):
    return subprocess.run(cmd, check=check, **kw)


def output(cmd):
    return run(cmd, encoding='utf-8', capture_output=True).stdout


def cat(path):
    with open(path) as f:
        return f.read()
