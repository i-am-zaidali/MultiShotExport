import re
import subprocess
from importlib import reload

from . import src

reload(src)

from .src import _submit as subm

reload(module=subm)

try:
    import pymel
    import PySide2
    import typing_extensions

except ImportError:
    print("This script cannot be run outside of Bees And Butterfly.")
    exit(1)


def verify_lan():
    try:
        # Run ipconfig and filter using findstr
        result = subprocess.check_output(
            'ipconfig /all | findstr /C:"Connection-specific DNS Suffix"',
            shell=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )

        # Extract all suffixes found
        suffixes = []
        for line in result.strip().split("\n"):
            # Match the text after the colon
            match = re.search(r"DNS Suffix\s*.*?:\s*(.*)", line)
            if match:
                suffix = match.group(1).strip()
                if suffix:
                    suffixes.append(suffix.encode("utf-16"))

        if (
            b"\xff\xfeB\x00e\x00e\x00s\x00n\x00b\x00u\x00t\x00t\x00e\x00r\x00f\x00l\x00y\x00.\x00l\x00a\x00n\x00"
            in suffixes
        ):
            return True

    except subprocess.CalledProcessError:
        return False


def run():
    if not verify_lan():
        print("This script cannot be run outside of Bees And Butterfly.")
        return
    submitter = subm.SubmitterWindow()
    submitter.show()
