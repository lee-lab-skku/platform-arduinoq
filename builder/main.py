# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

#
# Thin target orchestrator: sets up the shared toolchain/env, normalizes the
# requested build/upload mode once, and wires together the Zephyr LLEXT
# artifact module (builder/artifacts/zephyr-llext.py) and the OpenOCD upload
# backend (builder/upload/openocd.py). It does not know framework package
# layout, GPIO wiring, or OpenOCD target names.
#
# The framework adapter has not run at this point; see CONTRIBUTING.md

import sys
from collections import namedtuple
from os.path import join

from SCons.Script import COMMAND_LINE_TARGETS, AlwaysBuild, Default, DefaultEnvironment

env = DefaultEnvironment()
platform = env.PioPlatform()
board = env.BoardConfig()

# Make builder/arduinoq_common importable by every module loaded below.
# SConscript() does not affect sys.path, and the framework adapter is loaded
# indirectly, so this has to happen before any SConscript call.
BUILDER_DIR = join(platform.get_dir(), "builder")
if BUILDER_DIR not in sys.path:
    sys.path.insert(0, BUILDER_DIR)

# ---------------------------------------------------------------------------
# Common toolchain commands
# ---------------------------------------------------------------------------

env.Replace(
    AR="arm-zephyr-eabi-gcc-ar",
    AS="arm-zephyr-eabi-as",
    CC="arm-zephyr-eabi-gcc",
    CXX="arm-zephyr-eabi-g++",
    GDB="arm-zephyr-eabi-gdb",
    OBJCOPY="arm-zephyr-eabi-objcopy",
    RANLIB="arm-zephyr-eabi-gcc-ranlib",

    ARFLAGS=["rc"],

    PROGSUFFIX=".elf"
)

# "program" is what PlatformIO leaves PROGNAME at when nothing has set it.
UNSET_PROGNAME = "program"

if env.subst("$PROGNAME") in ("", UNSET_PROGNAME):
    env.Replace(PROGNAME="firmware")

# ---------------------------------------------------------------------------
# Normalize requested command-line target modes once
# ---------------------------------------------------------------------------

BuildMode = namedtuple("BuildMode", ("nobuild", "upload"))

build_mode = BuildMode(
    nobuild="nobuild" in COMMAND_LINE_TARGETS,
    upload="upload" in COMMAND_LINE_TARGETS,
)

# ---------------------------------------------------------------------------
# Zephyr LLEXT artifact generation
# ---------------------------------------------------------------------------

artifacts = env.SConscript(
    join("artifacts", "zephyr-llext.py"),
    exports="env platform board build_mode"
)

AlwaysBuild(env.Alias("nobuild", artifacts.build_target))

buildprog_targets = [artifacts.build_target]
if not build_mode.nobuild:
    # The size check used to be pulled in implicitly, because the packed
    # artifact depended on it. zephyr-check-size measures that artifact,
    # so the dependency now runs the other way and "buildprog" has to ask
    # for the check itself. "pio remote run" requests it explicitly, but a
    # plain "pio run" would otherwise skip it.
    buildprog_targets.append(artifacts.checkprogsize_target)

# Sources only, no action: SCons would read a list in Alias' third argument
# as a command line and try to execute the packed .bin.
target_buildprog = env.Alias("buildprog", buildprog_targets)

# "size" is deliberately not a default target. PlatformIO would normally
# swap it for "checkprogsize" itself, but only when SIZETOOL is set, which
# this platform no longer does -- so leaving it in would run the size tool
# twice. "buildprog" pulls in checkprogsize, which reports the same numbers.
Default([target_buildprog])

# ---------------------------------------------------------------------------
# OpenOCD upload backend
# ---------------------------------------------------------------------------

env.SConscript(
    join("upload", "openocd.py"),
    exports="env platform board build_mode artifacts"
)

# Uploading a freshly built sketch has to go through the size check, which
# PlatformIO would normally wire up itself -- again only when SIZETOOL is
# set, and again skipped in "nobuild" mode, where there is nothing to check.
if not build_mode.nobuild:
    env.Depends("upload", artifacts.checkprogsize_target)
