# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

"""Prepare session-local resident symbols without changing upload inputs."""

from pathlib import Path
import subprocess
import tempfile


class ResidentSymbols:
    """Own a debugger-only ELF for as long as the debug configuration lives.

    GDB 16.2 crashes when setting breakpoints in the resident's section named
    ``text``. Renaming that section to ``.text`` in a separate ELF avoids the
    failure while retaining its addresses, contents and DWARF. Uploads must
    continue to use the original framework resident.
    """

    def __init__(self, resident_elf, objcopy):
        self.directory = tempfile.TemporaryDirectory(prefix="arduinoq-debug-")
        self.path = str(Path(self.directory.name) / "resident.elf")
        try:
            result = subprocess.run(
                [objcopy, "--rename-section", "text=.text", resident_elf, self.path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(
                    "Cannot prepare resident debug symbols: %s" % result.stdout.strip()
                )
        except Exception:
            self.directory.cleanup()
            raise
