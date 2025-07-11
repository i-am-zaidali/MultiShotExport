import contextlib
from importlib import reload
from pathlib import Path

from . import iMaya

reload(iMaya)

from .iMaya import *  # noqa: F403

with contextlib.suppress(Exception):
    import pymel.core as pc


def setConfig(conf):
    iMaya.conf = conf


with open(Path(__file__).parent / "createGeometryCache.mel", "r") as f:  # noqa: SIM117
    with contextlib.suppress(Exception):
        pc.Mel.eval(f.read())
