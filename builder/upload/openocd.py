# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

#
# OpenOCD upload backend. This module owns everything needed to flash the
# board over OpenOCD: locating the OpenOCD installation, the board's OpenOCD
# interface/target metadata, and the "upload" target definition.
#
# There is deliberately no OpenOCD PlatformIO package. Flashing needs a build
# with Linux GPIO (gpiod) support, which the board image already provides;
# declaring a package would collide with the
# official platformio/tool-openocd, which has no gpiod interface.
# See ArduinoqPlatform.is_embedded() in platform.py.
#
# The flash configuration path comes from the framework adapter's export
# (ARDUINO_ZEPHYR_FLASH_SKETCH_CONFIG) when it ran, and otherwise from the
# shared layout resolver. That fallback is not optional: PlatformIO only
# executes framework scripts from within ProcessProgramDeps(), which
# builder/artifacts/zephyr-llext.py skips in "nobuild" mode, so an upload-only
# session -- the MPU side of a default "pio remote run -t upload" -- never
# sees that export. This module still never walks the framework package's
# "variants" directory itself; it asks the resolver.

from os.path import isfile

from SCons.Script import AlwaysBuild, Import

from arduinoq_common import openocd_layout
from arduinoq_common.arduino_zephyr_layout import resolve as resolve_layout
from arduinoq_common.arduino_zephyr_layout import (
    validate_flash_config,
    validate_resident_elf,
)

Import("env platform board build_mode artifacts")

_layout = None


def _get_layout():
    """Resolve the framework package layout lazily, and only once."""
    global _layout
    if _layout is None:
        _layout = resolve_layout(platform, board)
        validate_flash_config(_layout)
    return _layout


def _flash_config_path():
    return (
        env.get("ARDUINO_ZEPHYR_FLASH_SKETCH_CONFIG")
        or _get_layout().flash_sketch_config
    )


def _resident_elf():
    """The resident firmware, taken unpacked from the framework package.

    Upstream passes firmwares/zephyr-<variant>.elf straight to OpenOCD as
    filename0, in both its openocd and remoteocd upload patterns, so it is
    used here as-is rather than being run through zephyr-sketch-tool. It is
    an input to the upload, never a build product, which also means a remote
    upload-only session reads it from the MPU's own framework package
    instead of expecting it in the transferred build directory.
    """
    resident_elf = env.get("ARDUINO_ZEPHYR_RESIDENT_ELF")
    if resident_elf:
        return resident_elf
    layout = _get_layout()
    validate_resident_elf(layout)
    return layout.resident_elf


def _openocd():
    layout = openocd_layout.resolve_from_board(board)
    missing = openocd_layout.missing_files(layout)
    if missing:
        raise RuntimeError(
            "openocd upload: %s" % openocd_layout.describe_missing(layout, missing)
        )
    return layout


def _configure_upload_command():
    openocd = _openocd()

    flash_config_path = _flash_config_path()
    if not isfile(flash_config_path):
        raise RuntimeError(
            "openocd upload: missing flash configuration at %s"
            % flash_config_path
        )

    resident_elf = env.subst(_resident_elf())
    if not isfile(resident_elf):
        raise RuntimeError(
            "openocd upload: resident firmware not found at %s"
            % resident_elf
        )

    # filename0 (resident firmware) and filename1 (sketch) are both
    # required by flash_sketch.cfg: it checks the resident firmware and decides
    # on its own whether that part needs to be rewritten.
    # UPLOAD_FLAGS is prepended, not appended: PlatformIO exposes the same
    # variable to the project as the "upload_flags" option (and the
    # PLATFORMIO_UPLOAD_FLAGS environment variable), and fills it in before
    # this script runs. Putting ours first leaves the user's flags last,
    # which is where "extra flags" belong and what OpenOCD needs for a
    # repeated option such as -d to take effect.
    env.Append(UPLOADCMD='"%s" $UPLOAD_FLAGS' % openocd.binary)
    env.Prepend(
        UPLOAD_FLAGS=openocd_layout.base_arguments(
            openocd,
            (
                "set filename0 {%s}" % resident_elf,
                "set filename1 {%s}" % "${SOURCES[0]}",
            ),
        ) + ["-f", flash_config_path]
    )

# Every path that can fail is behind this guard, so that merely loading the
# module is free. builder/main.py loads it unconditionally, and a plain build
# -- including the local "buildprog" phase of a remote run, which uploads
# nothing -- must not be able to raise from here.
if build_mode.upload:
    _configure_upload_command()

# The packed sketch is the only build product an upload consumes. The resident
# runtime is an input taken from the framework package and is substituted into
# UPLOAD_FLAGS above; keeping it out of SOURCES is also what lets this alias be
# declared without resolving anything.
AlwaysBuild(env.Alias(
    "upload", artifacts.sketch_artifact,
    [env.VerboseAction("$UPLOADCMD", "Uploading $SOURCE")]
))
