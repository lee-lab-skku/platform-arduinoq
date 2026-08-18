# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

#
# Board operations driven from the host through OpenOCD.
#
# This is the counterpart of builder/upload/openocd.py for things that are
# not part of a build: resetting the board before a test run, halting it, or
# issuing any other OpenOCD command. Neither module describes the
# installation itself; both take it from
# builder/arduinoq_common/openocd_layout.py, which is what actually keeps
# them in step.
#
# Everything here talks to the board over the MPU's GPIO lines, which means
# it only works when it runs on the MPU itself. On a workstation it fails
# with the same explanation the upload backend gives.

import subprocess
import sys
from os.path import abspath, dirname, join

# Reach the shared helpers. Unlike platform.py, which loads the modules in
# this package by path so as not to publish itself as "platform", putting
# builder/ on sys.path is safe: the package under it is named for this
# platform.
BUILDER_DIR = join(dirname(dirname(abspath(__file__))), "builder")
if BUILDER_DIR not in sys.path:
    sys.path.insert(0, BUILDER_DIR)

from arduinoq_common import openocd_layout  # noqa: E402

# Commands for a long-running GDB server, matching the invocation the MPU's
# own debug helper uses. "reset_config" has to precede "init", which is why
# it is spelled out rather than left to OpenOCD's implicit start-up init.
# The board's stm32x5x_common.cfg, unlike upstream's, sets no global
# reset_config at all, so SRST is never asserted unless it is requested
# here.
DEBUG_SERVER_COMMANDS = (
    "reset_config srst_only srst_push_pull",
    "init",
)

# The shipped configuration calls these on every GDB attach and detach but
# never defines them, which raises a Tcl error each time. They have to be in
# place before "init" -- a "monitor" command would come too late, the first
# attach having already happened. Guarded, so a configuration that does
# define them keeps its own.
#
# No double quotes anywhere in these, deliberately. PlatformIO may hand the
# whole server invocation to GDB as a pipe command, flattening the arguments
# into one string and wrapping each of them in double quotes of its own; a
# quote here would close that wrapper early and truncate the command.
#
# The attach hook halts rather than doing nothing. GDB inspects the target as
# soon as it connects, and if that happens while the core is running it reads
# a program counter that is not a real one -- hence OpenOCD's "GDB connection
# not halted" warning and the failed read at address 0 that follows it.
# Halting on attach is what most board configurations do for the same reason.
# It polls first: the event fires before OpenOCD has established what the
# target is doing, and halting from an unknown state warns about exactly that.
GDB_HOOK_STUBS = (
    "if {[llength [info procs gdb_attach_hook]] == 0} "
    "{proc gdb_attach_hook {} {poll; halt}}",
    "if {[llength [info procs gdb_detach_hook]] == 0} "
    "{proc gdb_detach_hook {} {}}",
)


# A sketch packed for "app" startup leaves the loader polling a word in backup
# SRAM, before it loads the sketch at all, until something non-zero is written
# there. All three values are taken from upstream's flash configuration, which
# performs the same write after its own reset -- including the settle time,
# which is there because the word is written from outside the loader's control
# and a write that lands too early does not stick.
WAIT_FOR_APP_ADDRESS = 0x40036400
WAIT_FOR_APP_MAGIC = 0xCAFFEEEE
WAIT_FOR_APP_SETTLE_MS = 100


class BoardControlError(Exception):
    pass


class BoardControl:
    """OpenOCD-backed board operations available to projects and tooling.

    Obtained from the platform rather than constructed directly:

        control = platform.get_board_control(board_id)
        control.reset()

    New operations belong here as named methods, so that a project never has
    to know the OpenOCD invocation or where the installation lives.
    """

    def __init__(self, openocd_dir=None):
        self.layout = openocd_layout.resolve(openocd_dir)

    @classmethod
    def from_board_config(cls, board_config):
        return cls(board_config.get("upload.openocd_dir", "") or None)

    @property
    def openocd_dir(self):
        return self.layout.root

    @property
    def openocd_binary(self):
        return self.layout.binary

    @property
    def interface_config(self):
        return self.layout.interface_config

    def is_available(self):
        return not openocd_layout.missing_files(self.layout)

    def ensure_available(self):
        missing = openocd_layout.missing_files(self.layout)
        if missing:
            raise BoardControlError(
                openocd_layout.describe_missing(self.layout, missing)
            )

    def arguments(self, *commands, **kwargs):
        """OpenOCD arguments for this board, without the executable."""
        return openocd_layout.base_arguments(
            self.layout, commands, quiet=kwargs.get("quiet", True)
        )

    def server_arguments(self, gdb_port=None, commands=DEBUG_SERVER_COMMANDS):
        """Arguments for an OpenOCD instance that stays up as a GDB server.

        Left verbose on purpose: PlatformIO decides the server is ready by
        watching its output.
        """
        self.ensure_available()
        setup = list(GDB_HOOK_STUBS)
        if gdb_port:
            setup.append("gdb_port %d" % gdb_port)
        return self.arguments(*(setup + list(commands)), quiet=False)

    def openocd(self, *commands, **kwargs):
        """Run OpenOCD against this board with the given -c commands."""
        self.ensure_available()
        argv = [self.openocd_binary] + self.arguments(*commands)

        quiet = kwargs.get("quiet", True)
        try:
            subprocess.check_call(
                argv,
                stdout=subprocess.DEVNULL if quiet else None,
                stderr=subprocess.STDOUT,
            )
        except OSError as exc:
            raise BoardControlError(
                "could not run %s: %s" % (self.openocd_binary, exc)
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise BoardControlError(
                "OpenOCD failed with exit code %d while running: %s"
                % (exc.returncode, " ".join(commands))
            ) from exc

    def reset(self):
        """Reset the target and let it run."""
        self.openocd("init", "reset run", "shutdown")

    def release(self):
        """Let a sketch packed for "app" startup leave the loader.

        Harmless for a sketch packed any other way: nothing reads the word.
        """
        self.openocd(
            "init",
            "sleep %d" % WAIT_FOR_APP_SETTLE_MS,
            "mww 0x%08X 0x%08X" % (WAIT_FOR_APP_ADDRESS, WAIT_FOR_APP_MAGIC),
            "shutdown",
        )

    def halt(self):
        """Reset the target and hold it halted."""
        self.openocd("init", "reset halt", "shutdown")
