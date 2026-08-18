# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

#
# This is the PlatformIO integration adapter for the "arduino" framework
# entry declared in platform.json. Together with
# builder/arduinoq_common/arduino_zephyr_layout.py it owns all knowledge of the
# internal directory layout of the "framework-arduino-zephyr" package. Every
# other builder module (artifact generation, upload backend) must consume the
# ARDUINO_ZEPHYR_* values exported below, or -- when this adapter did not run
# at all, as in an upload-only session -- the shared resolver, instead of
# re-deriving framework paths of its own.

import sys
from os.path import join

from SCons.Script import DefaultEnvironment

env = DefaultEnvironment()
platform = env.PioPlatform()
board = env.BoardConfig()

# builder/main.py normally puts builder/ on sys.path before anything else
# runs, but this adapter is invoked indirectly through
# ProcessProgramDeps() -> BuildFrameworks(), so the guard is repeated here
# rather than assumed.
BUILDER_DIR = join(platform.get_dir(), "builder")
if BUILDER_DIR not in sys.path:
    sys.path.insert(0, BUILDER_DIR)

from arduinoq_common.arduino_zephyr_layout import (  # noqa: E402
    resolve as resolve_layout,
    validate_build_inputs,
    validate_flash_config,
)

# ---------------------------------------------------------------------------
# Resolve and validate the upstream framework package and board variant
# ---------------------------------------------------------------------------

layout = resolve_layout(platform, board)
validate_flash_config(layout)
validate_build_inputs(layout)

FRAMEWORK_DIR = layout.framework_dir
variant = layout.variant
variant_dir = layout.variant_dir
resident_dir = layout.resident_dir
resident_elf = layout.resident_elf
resident_config = layout.resident_config
flash_sketch_config = layout.flash_sketch_config
upstream_flag_files = layout.upstream_flag_files
dynamic_ldscript = layout.dynamic_ldscript
static_check_ldscripts = layout.static_check_ldscripts

# ---------------------------------------------------------------------------
# Setting fragments, grouped by category. Compiler/linker flag ORDER is
# significant to gcc/ld (later flags can override earlier ones, e.g. a
# "-std=" inside an upstream response file), so fragments from different
# categories are concatenated below in the exact order the toolchain expects
# rather than being appended to the environment category-by-category.
# ---------------------------------------------------------------------------

board_id = board.get("build.arduino.board")
machine_flags = board.get("build.machine_flags", [])

# --- upstream-derived compiler and include settings -------------------------
# Consumed as-is from the upstream Zephyr/Arduino build: response files and
# generated LLEXT EDK headers.
UPSTREAM_CFLAGS = [
    "@%s" % upstream_flag_files["cflags.txt"],
]
UPSTREAM_CXXFLAGS = [
    "@%s" % upstream_flag_files["cxxflags.txt"],
]
UPSTREAM_CCFLAGS = [
    "-imacros%s" % join(
        variant_dir, "llext-edk", "include", "zephyr", "include",
        "generated", "zephyr", "autoconf.h"
    ),
    "-imacros%s" % join(
        variant_dir, "llext-edk", "include", "zephyr", "include",
        "zephyr", "toolchain", "zephyr_stdint.h"
    ),
    "-iprefix%s" % variant_dir,
    "@%s" % upstream_flag_files["includes.txt"],
]

# --- PlatformIO adaptation settings ------------------------------------------
# Fit the upstream sources into PlatformIO's build model: board-specific
# machine flags, Arduino-facing defines, core/library include paths, and
# library discovery.
# Optimisation is left to PlatformIO in a debug build. Its
# ConfigureDebugTarget() strips "-Os" from ASFLAGS, CCFLAGS and LINKFLAGS
# before merging debug_build_flags, but not from CFLAGS or CXXFLAGS, which
# is where upstream's ordering requires ours to sit. Keeping it there would
# mean the level only changes because "-Og" happens to be appended later --
# and a debug_build_flags without any "-O" would silently leave "-Os" in
# force. Dropping it makes debug_build_flags the only source of a level.
OPTIMIZATION_FLAGS = [] if "debug" in env["BUILD_TYPE"] else ["-Os"]
ADAPTATION_CFLAGS = ["-g"] + OPTIMIZATION_FLAGS + ["-std=gnu17"]
ADAPTATION_CXXFLAGS = ["-g"] + OPTIMIZATION_FLAGS + ["-std=gnu++17"]
# Section splitting belongs to CCFLAGS, which SCons places after the
# language-specific flags ("$CFLAGS $CCFLAGS", "$CXXFLAGS $CCFLAGS") and
# therefore after the upstream response files -- the same position
# upstream's recipes use, and the opposite of the optimisation level, which
# has to stay ahead of them so the response file can still override it.
ADAPTATION_CCFLAGS = machine_flags + [
    "-w",
    "-fdata-sections",
    "-ffunction-sections",
    "-MMD",
]

# --- LLEXT-specific compile and link settings --------------------------------
# The Arduino core is linked as a relocatable Zephyr LLEXT, not as a normal
# standalone ELF executable: runtime-suppression flags, no-stdlib relocatable
# linking, and the static compatibility-check link configuration consumed
# later by builder/artifacts/zephyr-llext.py.
LLEXT_RUNTIME_FLAGS = [
    "-fno-threadsafe-statics",
    "-fno-rtti",
    "-fno-exceptions",
    "-fno-use-cxa-atexit",
    "-fno-unwind-tables",
]
LLEXT_CXXFLAGS = LLEXT_RUNTIME_FLAGS + [
    "-lstdc++",
    "-lsupc++",
    "-lnosys",
    "-nostdlib",
    "-lm",
]
LLEXT_LINKFLAGS = [
    "--specs=nano.specs",
    "--specs=nosys.specs",
    "-Wl,--gc-sections",
] + LLEXT_RUNTIME_FLAGS + [
    "-lstdc++",
    "-lsupc++",
    "-lnosys",
    "-nostdlib",
    "-r",
    "-e",
    "main",
]
STATIC_CHECK_LINKFLAGS = [
    "-T",
    "%s" % static_check_ldscripts[0],
    "-T",
    "%s" % static_check_ldscripts[1],
    "-T",
    "%s" % static_check_ldscripts[2],
]

env.Append(
    ASFLAGS=machine_flags,
    ASPPFLAGS=[
        "-x",
        "assembler-with-cpp",
    ] + machine_flags,
    CFLAGS=ADAPTATION_CFLAGS + UPSTREAM_CFLAGS,
    CXXFLAGS=ADAPTATION_CXXFLAGS + UPSTREAM_CXXFLAGS + LLEXT_CXXFLAGS,
    CCFLAGS=ADAPTATION_CCFLAGS + UPSTREAM_CCFLAGS,
    CPPDEFINES=[
        ("ARDUINO", 10607),
        "ARDUINO_ARCH_ZEPHYR",
        "ARDUINO_%s" % board_id,
        ("_PICOLIBC_CTYPE_SMALL", 1),
        ("ARDUINO_LIBRARY_DISCOVERY_PHASE", 0),
    ],
    CPPPATH=[
        join(FRAMEWORK_DIR, "cores", "arduino"),
        join(FRAMEWORK_DIR, "cores", "arduino", "api"),
        join(FRAMEWORK_DIR, "cores", "arduino", "api", "deprecated"),
        join(FRAMEWORK_DIR, "cores", "arduino", "api", "deprecated-avr-comp"),
        variant_dir,
    ],
    # Upstream links with "-L{build.variant.path}"; linker scripts reach
    # for it through INPUT()/GROUP() even when every "-T" is absolute.
    # The matching "-L{build.path}" is already covered: PlatformIO
    # initialises LIBPATH to ["$BUILD_DIR"].
    LIBPATH=[variant_dir],
    # One storage directory, not one entry per library: PlatformIO treats
    # each element as a directory whose children are libraries. Appended
    # rather than prepended, so that the project's own lib_deps outrank the
    # bundled copies -- which is what lets libraries/stubs carry a diagnostic
    # header without shadowing the real library once it is installed.
    LIBSOURCE_DIRS=[join(FRAMEWORK_DIR, "libraries")],
    LIBS=[
        "stdc++",
        "supc++",
        "m",
    ],
    LINKFLAGS=machine_flags + LLEXT_LINKFLAGS,
    STATIC_CHECK_LINKFLAGS=STATIC_CHECK_LINKFLAGS,
)

# LDSCRIPT_PATH points at the dynamic-build LLEXT linker script
# (build-dynamic.ld). builder/artifacts/zephyr-llext.py performs the actual
# multi-pass dynamic link itself (temporary pass, gen-rodata-ld, final pass),
# so it reads this value directly and injects "-T" / map-file arguments
# per pass rather than relying on a single flag baked in here.
env.Replace(LDSCRIPT_PATH=dynamic_ldscript)

# ---------------------------------------------------------------------------
# Build the Arduino core and bundled framework libraries
# ---------------------------------------------------------------------------

env.BuildSources(join("$BUILD_DIR", "FrameworkArduinoVariant"), variant_dir)
env.Prepend(LIBS=[
    env.BuildLibrary(
        join("$BUILD_DIR", "FrameworkArduino"),
        join(FRAMEWORK_DIR, "cores", "arduino")
    )
])

# ---------------------------------------------------------------------------
# Framework-to-platform contract
#
# Downstream modules (builder/artifacts/zephyr-llext.py,
# builder/upload/openocd.py) must consume these resolved values instead of
# rediscovering the framework package layout.
# ---------------------------------------------------------------------------

env.Replace(
    ARDUINO_ZEPHYR_FRAMEWORK_DIR=FRAMEWORK_DIR,
    ARDUINO_ZEPHYR_VARIANT_DIR=variant_dir,
    ARDUINO_ZEPHYR_RESIDENT_DIR=resident_dir,
    ARDUINO_ZEPHYR_FLASH_SKETCH_CONFIG=flash_sketch_config,
    ARDUINO_ZEPHYR_RESIDENT_ELF=resident_elf,
    ARDUINO_ZEPHYR_RESIDENT_CONFIG=resident_config,
)
