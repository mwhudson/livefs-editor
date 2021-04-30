#

import subprocess


def run(cmd, check=True, **kw):
    return subprocess.run(cmd, check=check, **kw)
