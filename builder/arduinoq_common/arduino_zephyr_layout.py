# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

#
# Single source of truth for the internal directory layout of the
# "framework-arduino-zephyr" package.
#
# Both the framework adapter (builder/frameworks/arduino-zephyr.py) and the
# OpenOCD upload backend (builder/upload/openocd.py) need framework-relative
# paths, but they do not always run in the same session: PlatformIO only
# executes framework scripts from within ProcessProgramDeps(), which the
# artifact module skips in "nobuild" mode. An upload-only session -- the MPU
# side of a default "pio remote run -t upload" -- therefore never sees the
# adapter's exports and has to resolve the same paths on its own.
#
# resolve() deliberately depends on nothing but the platform and board
# objects: no build environment, no compiled artifacts, no values left
# behind by the adapter. Anything that violates that defeats the purpose.

from collections import namedtuple
from os.path import isdir, isfile, join

FRAMEWORK_PACKAGE = "framework-arduino-zephyr"

# Upstream response files consumed verbatim from the Zephyr/Arduino build.
# "machine_flags.txt" is intentionally absent: the board manifest's
# build.machine_flags is authoritative for this platform.
UPSTREAM_FLAG_FILE_NAMES = ("cflags.txt", "cxxflags.txt", "includes.txt")

ArduinoZephyrLayout = namedtuple(
    "ArduinoZephyrLayout",
    (
        "board_id",
        "framework_dir",
        "variant",
        "variant_dir",
        "resident_dir",
        "resident_elf",
        "resident_config",
        "flash_sketch_config",
        "upstream_flag_files",
        "dynamic_ldscript",
        "static_check_ldscripts",
    ),
)


def resolve(platform, board):
    """Compute the framework package layout for the given board.

    Only the package root and the board variant directory are verified here,
    since those two failures cannot produce a useful error message later.
    Per-file validation is left to validate_flash_config() and
    validate_build_inputs() so that an upload-only session is not forced to
    check inputs it will never read.
    """
    framework_dir = platform.get_package_dir(FRAMEWORK_PACKAGE)
    if not framework_dir:
        raise RuntimeError(
            "arduino-zephyr layout: the '%s' package is not installed; "
            "framework paths cannot be resolved" % FRAMEWORK_PACKAGE
        )

    board_id = board.id
    variant = board.get("build.variant", "")
    if not variant:
        raise RuntimeError(
            "arduino-zephyr layout: board '%s' does not declare "
            "build.variant" % board_id
        )

    variant_dir = join(framework_dir, "variants", variant)
    if not isdir(variant_dir):
        raise RuntimeError(
            "arduino-zephyr layout: missing variant directory for board "
            "'%s' at %s" % (board_id, variant_dir)
        )

    ldscripts_dir = join(framework_dir, "variants", "_ldscripts")
    resident_dir = join(framework_dir, "firmwares")

    return ArduinoZephyrLayout(
        board_id=board_id,
        framework_dir=framework_dir,
        variant=variant,
        variant_dir=variant_dir,
        resident_dir=resident_dir,
        resident_elf=join(resident_dir, "zephyr-%s.elf" % variant),
        resident_config=join(resident_dir, "zephyr-%s.config" % variant),
        flash_sketch_config=join(variant_dir, "flash_sketch.cfg"),
        upstream_flag_files={
            name: join(variant_dir, name) for name in UPSTREAM_FLAG_FILE_NAMES
        },
        dynamic_ldscript=join(ldscripts_dir, "build-dynamic.ld"),
        static_check_ldscripts=(
            join(variant_dir, "syms-dynamic.ld"),
            join(ldscripts_dir, "memory-check.ld"),
            join(ldscripts_dir, "build-static.ld"),
        ),
    )


def validate_flash_config(layout):
    """Check the OpenOCD flash configuration required by an upload.

    Only the sketch configuration is consumed. Upstream's flash_sketch.cfg
    already expects the resident firmware and decides for itself
    whether that part has to be rewritten, so the separate bootloader
    configuration is not used by this platform.
    """
    if not isfile(layout.flash_sketch_config):
        raise RuntimeError(
            "arduino-zephyr layout: missing flash configuration file "
            "for board '%s' at %s"
            % (layout.board_id, layout.flash_sketch_config)
        )


def validate_resident_elf(layout):
    """Check the resident firmware ELF that is flashed alongside the sketch."""
    if not isfile(layout.resident_elf):
        raise RuntimeError(
            "arduino-zephyr layout: resident firmware ELF not found at %s "
            "(required for upload)" % layout.resident_elf
        )


def validate_build_inputs(layout):
    """Check the response files and linker scripts needed to compile and
    link. Only meaningful in a session that actually builds."""
    for name, path in sorted(layout.upstream_flag_files.items()):
        if not isfile(path):
            raise RuntimeError(
                "arduino-zephyr layout: missing upstream flag response file "
                "'%s' for board '%s' at %s" % (name, layout.board_id, path)
            )

    for ldscript in (layout.dynamic_ldscript,) + layout.static_check_ldscripts:
        if not isfile(ldscript):
            raise RuntimeError(
                "arduino-zephyr layout: missing linker script for board "
                "'%s' at %s" % (layout.board_id, ldscript)
            )
