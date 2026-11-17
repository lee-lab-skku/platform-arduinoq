# Build and link

This document covers the contracts that keep the sketch build consistent with the framework and with PlatformIO Core.
It covers C++ runtime linking, framework paths outside a build, remote upload-only targets, sketch capacity reporting, and integration metadata for analyzers.

## C++ runtime linking must match the framework recipe

The framework's generated response files and resident configuration define the libc contract.
Keep the framework, SDK, compiler ABI and link recipe aligned when updating packages; do not infer the libc from the SDK version alone.

- **Specs**: Retain the response files' compile-time specs and headers, but do not add the nano/nosys link specs removed from SDK 1.0.
- **Library order**: Keep explicit C++/math/GCC/C libraries inside the existing archive group, after the core archive.
- **Exceptions**: Force `__cxa_allocate_exception` as the upstream recipe does, including in the static compatibility link.
- **Thread-local `errno`**: Compile C++ with `-fno-extern-tls-init` so resident `errno` does not gain an undefined `_ZTH5errno` initialization thunk in the extension.

## Framework paths must be available without a build

PlatformIO runs framework scripts inside `ProcessProgramDeps()`.
`builder/artifacts/zephyr-llext.py` calls it during a build but deliberately skips it in `nobuild` mode, so the framework adapter's `ARDUINO_ZEPHYR_*` exports are unavailable in upload-only execution.

Modules that need framework paths in both modes must use `builder/arduinoq_common/arduino_zephyr_layout.py` without depending on framework initialization.
`builder/upload/openocd.py` needs those paths even when uploading existing artifacts; upload-only remote sessions are the case that breaks if it relies on the adapter's exports.

## Remote targets must remain available without rebuilding

A non-forced `pio remote run` splits the caller's targets between two legs:

| Leg | Targets it runs |
| --- | --- |
| Local | The fixed targets `["checkprogsize", "buildprog"]` |
| Remote | The caller's targets with `nobuild` appended |

For example, `pio remote run -t checklink -t upload` reaches the board with both `checklink` and `nobuild`, even though the local build has already performed the link check.
Keep `checklink` registered unconditionally and accept it as a no-op in `nobuild` mode.
Otherwise, an upload-only remote invocation can fail on an unknown target despite a successful local build.

## Board metadata and sketch capacity

The board manifest holds two kinds of capacity, which serve different readers:

| Fields | Describe | Update when |
| --- | --- | --- |
| `build.mcu`, `build.f_cpu`, `upload.maximum_ram_size`, `upload.maximum_size` | The MCU's nominal hardware specifications, for PlatformIO board listings and hardware summaries | The specifications change |
| `upload.maximum_sketch_size`, `upload.maximum_sketch_ram_size` (bytes) | The resident firmware's sketch allocations | The framework's `user_sketch` partition or LLEXT heap allocation changes |

The nominal fields describe the MCU, not the MPU's Linux memory or storage, and nominal chip capacity does not determine the sketch budget.
The clock metadata does not configure the resident firmware's clock or replace the core's `SystemCoreClock`-based `F_CPU`.

Size checks follow these rules:

- **Shared metadata**: Core's `CheckUploadSize()` reads `upload.maximum_size` and `upload.maximum_ram_size` directly from `BoardConfig()`.
  Both the post-packing check and the `size` target must supply sketch allocations without modifying the shared board metadata, including when a check fails.
  A SCons environment clone alone is insufficient because its normal board lookup still returns the shared platform configuration.
- **Numerator**: Keep `zephyr-check-size` responsible for the numerator: packed sketch image size and LLEXT heap usage.
- **Denominator**: Reuse Core's formatting and flash-error/RAM-warning behavior with the sketch limits as the denominator.
- **Link check**: The static `checklink` pass uses the framework's linker scripts; the shipped `memory-check.ld` uses synthetic memory regions and is not an enforcement of the sketch partition or LLEXT heap capacity.

Keep the user-facing distinction in [Board resources](../README.md#board-resources).

## Integration metadata must describe the build without changing it

The framework response files remain the source of compiler settings.
The platform supplements Core's `DumpIntegrationData` result for analyzers without changing what it builds.

### Integration boundaries

- **Hook**: Supplement Core's `DumpIntegrationData` result through the platform environment's method, installed before project environments are cloned; retain the original method's project receiver.
- **No build changes**: Do not modify installed Core files, globally patch its adapters, or change `CPPPATH`, `CPPDEFINES`, compilation, or linking to accommodate an analyzer.
- **Parsing location**: Keep response parsing in the SCons-independent shared helper.

### Response expansion

- **Position**: Expand response references at their original position, using the compiler working directory for nested relative references.
- **Errors**: Report unreadable files and active recursion cycles with their paths; repeated nonrecursive references are valid.
- **Arguments**: Preserve argument boundaries, language differences, and option order, including later `-std` overrides.
- **Include order**: GCC searches explicit `-I` paths before `-iwithprefixbefore` paths, even when the prefix options occur earlier in the command.
  Concatenate each prefix with its suffix before resolving the path, retain nonexistent configured paths, and preserve Core's library and toolchain include groups.

### Definitions

SCons places `CPPDEFINES` after the language/common flags in this platform's compile commands.

- **Final definitions**: Apply response-file `-D`/`-U` operations first, then Core's definitions, to compute the common final definitions.
- **Replay**: Retain those operations and the trailing Core definitions in each language's flags so replay preserves their precedence.
- **Inexpressible definitions**: Warn about definitions that the common C/C++ field cannot express.
- **Forced headers**: Keep `-imacros` and `-include` as options; copying configuration-header macros into `defines` loses their preprocessing context.

### Validating metadata changes

1. Validate metadata changes in a separate sketch copy that selects the development checkout.
1. Capture `pio run -t compiledb` before and after the change, normalize only relocated paths, and compare every command; also run a clean build, `checklink`, and `size`.
1. Compare GCC `-E -dM`, `-E -v`, and `-M` results for the original and expanded settings to check final macros, include search order, and forced-header dependencies.
1. Count expected framework settings from the installed response files rather than fixing package-specific counts in the implementation.
1. Inspect both analysis adapters' actual input and parsing errors with `pio check -v`; their success labels are not a completeness check.
