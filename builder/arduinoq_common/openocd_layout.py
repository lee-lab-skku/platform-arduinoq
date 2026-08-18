# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

#
# Single source of truth for the OpenOCD installation this board is flashed
# and debugged through.
#
# Two callers need it, and they do not run in the same process:
# builder/upload/openocd.py inside SCons, and host/board_control.py inside
# PlatformIO's own. Before this module they were two copies of the same four
# constants, two copies of the same existence check and two differently
# worded errors -- which is to say nothing actually kept them in step.

from collections import namedtuple
from os.path import isfile, join

# OpenOCD build shipped in the Arduino UNO Q MPU image. Override per project
# with "board_upload.openocd_dir" in platformio.ini.
DEFAULT_OPENOCD_DIR = "/opt/openocd"

# Relative to the OpenOCD root. The executable and the Linux GPIO interface
# configuration are both required, so that an installation without gpiod
# support is rejected by name here rather than failing later inside OpenOCD:
# a stock OpenOCD build does not carry the latter.
OPENOCD_BINARY = join("bin", "openocd")
OPENOCD_INTERFACE_CONFIG = "openocd_gpiod.cfg"
OPENOCD_SCRIPTS_DIR = join("share", "openocd", "scripts")

REQUIRED_FILES = (OPENOCD_BINARY, OPENOCD_INTERFACE_CONFIG)

OpenOcdLayout = namedtuple(
    "OpenOcdLayout", ("root", "binary", "interface_config", "scripts_dir")
)


def resolve(openocd_dir=None):
    """Layout of an OpenOCD installation, defaulting to the MPU's own."""
    root = openocd_dir or DEFAULT_OPENOCD_DIR
    return OpenOcdLayout(
        root=root,
        binary=join(root, OPENOCD_BINARY),
        interface_config=join(root, OPENOCD_INTERFACE_CONFIG),
        scripts_dir=join(root, OPENOCD_SCRIPTS_DIR),
    )


def resolve_from_board(board_config):
    """Layout for a board, honouring "board_upload.openocd_dir"."""
    return resolve(board_config.get("upload.openocd_dir", "") or None)


def missing_files(layout):
    """Required files that are absent, in declaration order."""
    return [name for name in REQUIRED_FILES if not isfile(join(layout.root, name))]


def describe_missing(layout, missing):
    """The one explanation both callers give for an unusable installation."""
    return (
        "%s is not a usable OpenOCD installation for this board (missing %s). "
        "It has to be an OpenOCD build with Linux GPIO (gpiod) support, which "
        "also means it only works on the MPU itself -- from a workstation, use "
        "'pio remote'. To point at a different build, set "
        "'board_upload.openocd_dir' in platformio.ini."
        % (layout.root, ", ".join(missing))
    )


def base_arguments(layout, commands=(), quiet=True):
    """OpenOCD arguments for this installation, without the executable.

    Returned separately from the binary because PlatformIO's debug server
    configuration wants the two apart.
    """
    argv = ["-d0"] if quiet else []
    argv += [
        "-s",
        layout.root,
        "-s",
        layout.scripts_dir,
        "-f",
        layout.interface_config,
    ]
    for command in commands:
        argv += ["-c", command]
    return argv
