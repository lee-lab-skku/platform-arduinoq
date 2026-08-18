# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

#
# Zephyr LLEXT artifact generation: the multi-pass dynamic relocatable link
# (temporary pass -> gen-rodata-ld -> final pass), debug-symbol stripping,
# sketch packing, the static compatibility link check, and the "size"
# target. This module knows about arm-zephyr-eabi-strip, gen-rodata-ld,
# zephyr-sketch-tool and the resident firmware ELF exported by the framework
# adapter; it has no knowledge of Linux GPIO wiring, OpenOCD, or the
# framework package's internal layout beyond the ARDUINO_ZEPHYR_* values it
# consumes.

from os.path import isfile, join

from SCons.Script import AlwaysBuild, Builder, Import, Return

Import("env platform board build_mode")

env.Replace(STRIP="arm-zephyr-eabi-strip")


def resolve_tool(package, executable, purpose):
    """Absolute path to an executable shipped in a PlatformIO tool package.

    Returns "" in "nobuild" mode: nothing is produced there, so a missing
    tool is not an error, and demanding one would break the upload-only
    sessions that never install it.
    """
    if build_mode.nobuild:
        return ""
    package_dir = platform.get_package_dir(package)
    if not package_dir:
        raise RuntimeError(
            "zephyr-llext: missing '%s' package, required to %s"
            % (package, purpose)
        )
    path = join(package_dir, executable)
    if not isfile(path):
        raise RuntimeError(
            "zephyr-llext: '%s' does not provide %s at %s"
            % (package, executable, path)
        )
    return path


env.Replace(
    ZEPHYRSKETCH=resolve_tool(
        "tool-zephyrsketch", "zephyr-sketch-tool",
        "pack sketch/resident artifacts",
    ),
    GENRODATALD=resolve_tool(
        "tool-genrodatald", "gen-rodata-ld",
        "generate the split rodata linker script for the dynamic build",
    ),
    ZEPHYRCHECKSIZE=resolve_tool(
        "tool-zephyrchecksize", "zephyr-check-size",
        "compute sketch flash and LLEXT heap usage",
    ),
)

# Startup mode. The resident firmware reads this out of the header that
# zephyr-sketch-tool writes, so it is a property of the packed artifact,
# decided at packing time -- not a compile or upload setting. Upstream
# exposes it as the "wait_linux_boot" board menu; here it is
# board_build.boot_mode, with the same default.
#
# "app" is upstream's name for the flag. The loader holds before loading the
# sketch until released; host/board_control.py is the other end of that.
STARTUP_MODE_FLAGS = {
    "wait": [],                  # hold until Linux is up (default)
    "app": ["-wait_for_app"],    # hold until the host releases the sketch
    "immediate": ["-immediate"],
}

# Defaults per build type, and why each one, are in CONTRIBUTING.md:
# the "app" path in particular only works if this module, the test reader and
# the board control agree, so it is documented where all three can find it.
# board_build.boot_mode overrides these -- PlatformIO folds board_* options
# into the board manifest, which is why the manifest itself states none.
build_type = env["BUILD_TYPE"]
if "debug" in build_type:
    default_boot_mode = "immediate"
elif "test" in build_type:
    default_boot_mode = "app"
else:
    default_boot_mode = "wait"

boot_mode = board.get("build.boot_mode", default_boot_mode)
if boot_mode not in STARTUP_MODE_FLAGS:
    raise RuntimeError(
        "zephyr-llext: unknown board_build.boot_mode %r; expected one of %s"
        % (boot_mode, ", ".join(sorted(STARTUP_MODE_FLAGS)))
    )
env.Replace(ZEPHYRSKETCHFLAGS=" ".join(STARTUP_MODE_FLAGS[boot_mode]))

# The Arduino core is always linked as a relocatable LLEXT here; upstream
# calls this "dynamic" and both gen-rodata-ld and zephyr-check-size take it
# as an argument.
LINK_MODE = "dynamic"
env.Replace(ZEPHYR_LINK_MODE=LINK_MODE)

env.Append(
    BUILDERS=dict(
        StripElf=Builder(
            action=env.VerboseAction(" ".join([
                '"$STRIP"',
                "--strip-debug",
                '"$SOURCE"',
                "-o",
                '"$TARGET"',
            ]), "Stripping $TARGET"),
            suffix=".elf"
        ),
        PackZephyrSketch=Builder(
            action=env.VerboseAction(" ".join([
                '"$ZEPHYRSKETCH"',
                "$ZEPHYRSKETCHFLAGS",
                "--output",
                '"$TARGET"',
                '"$SOURCE"',
            ]), "Packing $TARGET"),
            suffix=".bin"
        ),
        GenRodataLd=Builder(
            action=env.VerboseAction(
                '"$GENRODATALD" "$SOURCE" "$TARGET" $ZEPHYR_LINK_MODE',
                "Generating rodata linker script $TARGET"
            )
        )
    )
)


class ArtifactResult:
    """Structured build outputs handed back to builder/main.py."""

    def __init__(self, sketch_elf=None, sketch_artifact=None,
                 build_target=None, checkprogsize_target=None):
        self.sketch_elf = sketch_elf
        self.sketch_artifact = sketch_artifact
        self.build_target = build_target
        self.checkprogsize_target = checkprogsize_target


sketch_elf = None
sketch_artifact = None
checkprogsize_target = None
debug_elf = None
check_elf = None

if build_mode.nobuild:
    # "nobuild" resolves the paths of artifacts produced by a prior normal
    # build; it never triggers compilation or packing itself.
    sketch_elf = join("$BUILD_DIR", "${PROGNAME}.elf")
    sketch_artifact = join("$BUILD_DIR", "${PROGNAME}-zsk.bin")
else:
    # ------------------------------------------------------------------
    # Multi-pass dynamic relocatable link
    #
    # Upstream Arduino Zephyr 0.56.0 links the LLEXT application in three
    # passes: a temporary relocatable link, gen-rodata-ld analyzing that
    # temporary ELF to split .rodata into flash-resident and RAM-resident
    # parts, and a final relocatable link that applies the generated split.
    # This is built as an explicit SCons graph (cloned envs + Program()
    # nodes) instead of a single env.BuildProgram() call, since that helper
    # only ever constructs one link pass.
    #
    # env.BuildProgram()'s "front matter" (resolving PIOBUILDFILES from the
    # framework/project sources, applying build flags, enabling the linker
    # cyclic-reference workaround) still has to run exactly once so both
    # passes see the same, fully-populated build inputs; only its single
    # env.Program() call is replaced.
    # ------------------------------------------------------------------
    env.ProcessProgramDeps()
    env.ProcessProjectDeps()

    # The Arduino core archive and the eagerly built framework libraries
    # reference each other, so ld cannot resolve them in a single
    # left-to-right pass over the archives; they have to be linked as one
    # group. Unconditional here, unlike in a general-purpose build script:
    # this platform pins arm-zephyr-eabi-gcc, always targets hardware, and
    # always links a non-empty LIBS, so there is nothing to test for.
    # Still needed under "-r": relocatable output does not stop ld from
    # selecting archive members, so a cyclic reference can still leave one
    # out.
    env.Prepend(_LIBFLAGS="-Wl,--start-group ")
    env.Append(_LIBFLAGS=" -Wl,--end-group")

    dynamic_ldscript = env.get("LDSCRIPT_PATH")
    if not dynamic_ldscript:
        raise RuntimeError(
            "zephyr-llext: framework adapter did not export a dynamic "
            "LDSCRIPT_PATH"
        )

    build_sources = env.get("PIOBUILDFILES", [])
    rodata_ld = join("$BUILD_DIR", "rodata_split.ld")

    # --- Static compatibility check link --------------------------------
    # Upstream runs this as the first step of every build
    # (recipe.c.combine.1), not as an opt-in target: it re-links the same
    # objects as a normal static executable against memory-check.ld, so
    # that a sketch which cannot fit or resolve is rejected here rather
    # than at load time. "-r" and the dynamic linker script are dropped
    # for this pass, per upstream's note that the check has to emulate a
    # static build.
    check_env = env.Clone()
    check_env.Replace(
        PROGNAME="firmware-check",
        LINKFLAGS=[
            f for f in env.get("LINKFLAGS", [])
            if f != "-r"
        ]
    )
    check_env.Append(
        LINKFLAGS=check_env.get("STATIC_CHECK_LINKFLAGS", [])
    )
    check_elf = check_env.Program(
        check_env.subst("$BUILD_DIR/${PROGNAME}.elf"), build_sources
    )

    # PlatformIO's own env.BuildProgram() only injects "-T $LDSCRIPT_PATH"
    # when LDSCRIPT_PATH is non-empty, so clearing it here on the per-pass
    # clones (rather than on the shared "env") safely omits that automatic
    # injection; the dynamic linker scripts are instead added explicitly
    # below, in the exact order each pass requires. The common LLEXT link
    # flags (machine flags, runtime-suppression flags, specs, --gc-sections,
    # "-r", "-e main", libs) are inherited unchanged from "env" by both
    # clones.

    # --- Pass 1: temporary dynamic relocatable link ----------------------
    temp_env = env.Clone()
    temp_env.Replace(LDSCRIPT_PATH="")
    temp_env.Append(LINKFLAGS=[
        "-T", dynamic_ldscript,
        '-Wl,-Map,"%s"' % join("$BUILD_DIR", "${PROGNAME}_temp.map"),
    ])
    temp_elf = temp_env.Program(
        join("$BUILD_DIR", "${PROGNAME}_temp"), build_sources
    )
    temp_env.Depends(temp_elf, check_elf)

    # --- gen-rodata-ld: derive the flash/RAM .rodata split ----------------
    rodata_ld_node = env.GenRodataLd(rodata_ld, temp_elf)
    env.Depends(rodata_ld_node, "$GENRODATALD")

    # --- Pass 2: final dynamic relocatable link ----------------------------
    # Same sources and common flags as pass 1; adds the generated rodata
    # split ahead of the main dynamic linker script, per upstream order.
    final_env = env.Clone()
    final_env.Replace(LDSCRIPT_PATH="")
    final_env.Append(LINKFLAGS=[
        "-T", rodata_ld,
        "-T", dynamic_ldscript,
        '-Wl,-Map,"%s"' % join("$BUILD_DIR", "${PROGNAME}.map"),
    ])
    debug_elf = final_env.Program(
        join("$BUILD_DIR", "${PROGNAME}_debug"), build_sources
    )
    final_env.Depends(debug_elf, rodata_ld_node)

    env.Replace(PIOMAINPROG=debug_elf)

    # PlatformIO reports "$PROGPATH" as prog_path in its build metadata,
    # and that is the ELF a debug session opens in GDB. Its default,
    # "$BUILD_DIR/$PROGNAME$PROGSUFFIX", is the stripped artifact that gets
    # packed and flashed and carries no debug information, so the
    # unstripped ELF is named instead -- the same distinction upstream
    # makes between the upload artifact and debug.executable. Nothing else
    # in PlatformIO builds from $PROGPATH except env.BuildProgram(), which this
    # module replaces.
    env.Replace(PROGPATH=debug_elf[0])

    sketch_elf = env.StripElf(join("$BUILD_DIR", "${PROGNAME}"), debug_elf)
    sketch_artifact = env.PackZephyrSketch(
        join("$BUILD_DIR", "${PROGNAME}-zsk"), sketch_elf
    )
    # SCons does not treat an executable named inside an action string as an
    # input, so without this an upgraded packer would leave the previous
    # artifact in place. There is deliberately no equivalent for $STRIP: it
    # is a bare command name resolved from PATH, not a package path, and
    # Depends() would turn it into a File node relative to the project.
    env.Depends(sketch_artifact, "$ZEPHYRSKETCH")
    # zephyr-check-size reports flash usage as the on-disk size of the
    # packed upload artifact, so unlike a plain "size" pass this check can
    # only run once packing is done. The dependency direction is therefore
    # the reverse of the usual PlatformIO arrangement, where checkprogsize
    # runs straight after the link.
    checkprogsize_target = AlwaysBuild(
        env.Alias(
            "checkprogsize",
            sketch_elf,
            env.VerboseAction(env.CheckUploadSize, "Checking size $SOURCE"),
        )
    )
    env.Depends(checkprogsize_target, sketch_artifact)

build_target = sketch_artifact

# ---------------------------------------------------------------------------
# "checklink" target
#
# The check link itself is part of every build (see above); this only
# exposes it as a target that can be requested on its own.
# Registered unconditionally, including in "nobuild" mode where check_elf is
# None and the alias has nothing to depend on. That is not a silent no-op
# standing in for a real check: "pio remote run" always builds locally
# first, so if a check ran at all it already ran there. What reaches this
# SCons invocation is only ever an upload-only pass, and "pio remote run"
# reissues every "-t" the caller passed rather than filtering it -- so a
# deployment command such as "-t checklink -t upload" reaches the "nobuild"
# leg with "checklink" still in COMMAND_LINE_TARGETS.
# ---------------------------------------------------------------------------

env.AddPlatformTarget(
    name="checklink",
    dependencies=check_elf,
    actions=None
)

# ---------------------------------------------------------------------------
# Size reporting
#
# Upstream replaced arm-zephyr-eabi-size with its own zephyr-check-size
# (ArduinoCore-zephyr PR #385), because neither number this board cares
# about is a plain section total: flash usage is the size of the packed
# upload artifact, and RAM usage is the LLEXT heap footprint, which in a
# dynamic build is the sum of every SHF_ALLOC section minus the
# non-relocated rodata when CONFIG_LLEXT_RODATA_NO_RELOC is set. The tool
# prints those two figures as ".text" and ".data" lines, matching
# upstream's platform.txt recipe:
#
#     zephyr-check-size <link_mode> <config> <upload_file> <elf_file>
#
# so PlatformIO's size expressions become a direct read of those two
# lines instead of a hand-maintained list of section names.
# ---------------------------------------------------------------------------

size_target = None
if not build_mode.nobuild:
    resident_config = env.get("ARDUINO_ZEPHYR_RESIDENT_CONFIG")
    if not resident_config:
        raise RuntimeError(
            "zephyr-llext: framework adapter did not export "
            "ARDUINO_ZEPHYR_RESIDENT_CONFIG"
        )
    if not isfile(env.subst(resident_config)):
        # Not fatal: zephyr-check-size treats an unreadable config as
        # "CONFIG_LLEXT_RODATA_NO_RELOC unset", which only inflates the
        # reported RAM figure. Worth saying out loud all the same.
        print(
            "Warning! Zephyr configuration not found at %s; reported RAM "
            "usage may be too high" % resident_config
        )

    env.Replace(
        ZEPHYR_SIZE_UPLOAD_ARTIFACT=sketch_artifact[0],
        ZEPHYR_SIZE_ELF=sketch_elf[0],
        SIZECHECKCMD=[
            "$ZEPHYRCHECKSIZE",
            "$ZEPHYR_LINK_MODE",
            "$ARDUINO_ZEPHYR_RESIDENT_CONFIG",
            "$ZEPHYR_SIZE_UPLOAD_ARTIFACT",
            "$ZEPHYR_SIZE_ELF",
        ],
        SIZEPROGREGEXP=r"^\.text\s+(\d+)",
        SIZEDATAREGEXP=r"^\.data\s+(\d+)",
    )

    size_target = env.Alias(
        "size", sketch_artifact,
        env.VerboseAction(
            ' '.join('"%s"' % arg for arg in env.get("SIZECHECKCMD")),
            "Calculating size $SOURCE"
        )
    )
    AlwaysBuild(size_target)

artifacts = ArtifactResult(
    sketch_elf=sketch_elf,
    sketch_artifact=sketch_artifact,
    build_target=build_target,
    checkprogsize_target=checkprogsize_target,
)

Return("artifacts")
