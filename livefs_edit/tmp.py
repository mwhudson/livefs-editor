import atexit
import os
import shutil
import tempfile

TMP = None


def tmpdir():
    return tempfile.mkdtemp(dir='.tmp')


def setup():
    global TMP
    TMP = tempfile.mkdtemp()
    os.chdir(TMP)
    os.mkdir('.tmp')


@atexit.register
def teardown():
    if TMP is not None:
        shutil.rmtree(TMP)
