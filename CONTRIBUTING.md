# Contributing

This document covers contracts and reasoning that span files or execution environments and do not have a natural home in a single code comment.
It also records failed approaches whose causes would otherwise need to be rediscovered.
For installation, project configuration, and board operation, see [README.md](README.md).

Keep enough of each cross-file flow to explain where its assumptions hold and where they break.
File and function names belong here when they identify the participants in that contract; details local to one implementation belong beside the code.

## Cross-file contracts

### Board control targets must bypass the build

The `reset`, `halt`, and `release` targets are a platform-owned no-build contract, documented in [Board control](README.md#board-control-without-a-build).
Register them without artifact dependencies and resolve the board controller only when their action executes.
A control-only invocation must return before loading the artifact or upload modules; treating it as upload-only `nobuild` mode would still couple it to artifact paths.
Preserve the existing host-side `BoardControl` semantics and project environment overrides.

Keep target selection rules shared between Core package configuration and the SCons builder.
Core consumes clean requests before the platform builder runs, so builder-only validation cannot reject a mixed control/clean request before cleaning.
Accept one control target with optional `nobuild`, and reject other combinations before actions execute.
Target discovery must not validate OpenOCD or operate hardware.
The guarantee covers sketch build actions, not Core initialization, package installation, or user-provided extra scripts.
Non-forced remote orchestration performs a local build outside this control-only path; document forced remote execution instead.

### Framework paths must be available without a build

PlatformIO runs framework scripts inside `ProcessProgramDeps()`.
`builder/artifacts/zephyr-llext.py` calls it during a build but deliberately skips it in `nobuild` mode, so the framework adapter's `ARDUINO_ZEPHYR_*` exports are unavailable in upload-only execution.

Modules that need framework paths in both modes must use `builder/arduinoq_common/arduino_zephyr_layout.py` without depending on framework initialization.
`builder/upload/openocd.py` needs those paths even when uploading existing artifacts; upload-only remote sessions are the case that breaks if it relies on the adapter's exports.

### Shared helpers must remain independent of SCons

Both `builder/`, running inside SCons, and `host/`, running in PlatformIO's own process, import `arduinoq_common`.
Keep that package free of SCons dependencies so importing a shared helper does not break the host side.

Adding `builder/` to `sys.path` exposes its packages under top-level names throughout the SCons process.
The platform-specific name `arduinoq_common` avoids the collisions a generic `common` package could cause.
`platform.py` handles the related risk by loading helpers by path rather than exposing itself as a top-level `platform` module.
Preserve these import boundaries when moving shared code.

### Sketch startup is an artifact and host coordination contract

`board_build.boot_mode` is written into the packed image by `zephyr-sketch-tool`; it is fixed at packing time, rather than selected during compilation or upload.
The default values and override precedence are documented in [Boot mode](README.md#board_buildboot_mode).
Debug builds use `immediate` because waiting in the loader's `control_gpios` path before `llext_load` would make sketch symbol placement depend on Linux startup timing.
Test builds use `app` to hold the loader before loading the sketch until the reader is connected.
Debug takes precedence for a debug test session because a loader breakpoint already provides the hold.

The `app` path depends on agreement between packing, the test reader, and board control:

1. `builder/artifacts/zephyr-llext.py` packs with `-wait_for_app` so the resident loader waits before loading the sketch.
1. `host/test_reader.py` resets the board, connects to the monitor socket, and only then calls `release()`.
1. `host/board_control.py` releases the loader by writing its control word at the start of backup SRAM through OpenOCD.

Ordinary uploading includes the release write; a plain reset does not.
Keep these operations distinct so tests can attach while the sketch is held.

A previous startup-output failure came from connecting the reader before resetting: SRST interrupted a mid-flight RPC response, and its leftover `0x01` merged with the next boot's banner.
Resetting first and holding the loader in `app` mode until the reader connected resolved it.
Changes to packing, reset, or reader startup must preserve that sequence; changing framing or flushing alone does not address the cause.

### Library ownership and compatibility

The framework package's export policy owns the contents of `libraries/`; do not duplicate that inventory in the platform.
Set `LIBSOURCE_DIRS` to the shared `libraries/` storage directory.
PlatformIO discovers libraries among each storage directory's children, so listing individual library directories breaks discovery.

Keep the framework identifier `arduino` to retain compatibility with libraries declaring `frameworks=arduino` without requiring `lib_compat_mode=off`.
This identifier does not guarantee that a library works with Zephyr.
The user-facing compatibility limits belong in [Limitations](README.md#limitations).

### Remote targets must remain available without rebuilding

For a non-forced `pio remote run`, the local leg runs the fixed targets `["checkprogsize", "buildprog"]`, while the remote leg reissues the caller's targets with `nobuild` appended.
For example, `pio remote run -t checklink -t upload` reaches the board with both `checklink` and `nobuild`, even though the local build has already performed the link check.

Keep `checklink` registered unconditionally and accept it as a no-op in `nobuild` mode.
Otherwise, an upload-only remote invocation can fail on an unknown target despite a successful local build.

## Package resolution

### Version and URL ownership

Keep each package's complete semantic version, including prerelease and build metadata, in `platform.json` as the single source of truth.
`PACKAGE_URL_BASES` in `platform.py` owns the repository and Git tag convention, with a `{release}` placeholder rather than a concrete version.
A routine package version bump should change only `platform.json`.
Change URL bases when a package moves repository or changes its tag convention.

PlatformIO Core 6.1.19 limits package dependency `version` strings to 100 characters during manifest validation.
The complete release asset URLs exceed that limit, so preserve separate version pins and URL expansion while supporting this Core version.

Release assets use `<urlbase><package-name>[-<systype>]-<version>.tar.gz`.
The `packages` property strips prerelease and build metadata when filling the release tag placeholder, but retains the complete version in the asset filename.
For example, a pin such as `0.56.0-leelabskku+unoq` supplies `0.56.0` for `{release}` while keeping the complete pin in the filename.
The framework package is architecture-independent; toolchains and helper tools include `linux_x86_64` or `linux_aarch64` in their asset names.
Explicit `platform_packages` overrides must bypass URL expansion.

### Resolution without a project environment

Resolve package URLs when Core reads `packages`, including during standalone installation, updates, and removal.
In Core 6.1.19, `PlatformPackageManager.install()` calls `configure_project_packages()`, and therefore `configure_default_packages()`, only when a project environment is supplied.
Standalone `pio pkg install -g -p <platform>` and the deprecated `pio platform install <platform>` skip that hook and proceed to `install_required_packages()`.
Expanding URLs only in the project hook therefore leaves standalone installation resolving nominal version pins from the registry instead of fetching release assets.
The `packages` property must also supply resolved URLs for updates and removal without a project environment.

The resolver snapshots the original version pins before accessing `super().packages`, which applies project overrides to the same dictionaries.
Preserve that ordering and the override exclusions: repeated access must never reinterpret an expanded URL or a user override as a version pin.
Core's inherited `configure_default_packages()` remains responsible for framework and target package selection.

When changing resolution, verify:

- Project installation and standalone `pio pkg install -g -p <platform>` on both supported host architectures.
- Explicit `platform_packages` overrides.
- Repeated access to package metadata.
- Package lookup without a project environment, including update and removal paths.

## Board metadata and sketch capacity

The board manifest describes the MCU's nominal hardware specifications for PlatformIO board listings and hardware summaries.
Keep `build.mcu`, `build.f_cpu`, `upload.maximum_ram_size`, and `upload.maximum_size` consistent with those specifications.
These describe the MCU, not the MPU's Linux memory or storage.
The clock metadata does not configure the resident firmware's clock or replace the core's `SystemCoreClock`-based `F_CPU`.

Keep the resident firmware's sketch allocations in `upload.maximum_sketch_size` and `upload.maximum_sketch_ram_size`, in bytes.
Update these only when the framework's `user_sketch` partition or LLEXT heap allocation changes; nominal chip capacity does not determine the sketch budget.

Core's `CheckUploadSize()` reads `upload.maximum_size` and `upload.maximum_ram_size` directly from `BoardConfig()`.
The artifact module routes both its post-packing check and the `size` target through `CheckSketchSize`, which supplies a private board configuration with the sketch limits to Core's checker.
A SCons environment clone alone is insufficient because its normal board lookup still returns the shared platform configuration.
Override that lookup on the checking environment only, so board listings, hardware summaries, and other build actions retain nominal metadata even after a check fails.

Keep `zephyr-check-size` responsible for the numerator: packed sketch image size and LLEXT heap usage.
Reuse Core's formatting and flash-error/RAM-warning behavior with the sketch limits as the denominator.
The static `checklink` pass uses the framework's linker scripts; the shipped `memory-check.ld` uses synthetic memory regions and is not an enforcement of the sketch partition or LLEXT heap capacity.
Keep the user-facing distinction in [Board resources](README.md#board-resources).

## Board integration constraints

The board environment used by this platform boots the MCU through System Memory ROM.
`arduino-router.service` sends the bootloader command that transfers execution to flash, so reset and startup depend on the router being available.
Keep this dependency visible in the user's [Troubleshooting](README.md#troubleshooting) guidance.

Use the board image's OpenOCD installation as the integration baseline.
The shipped executable comes from Arduino's fork, while the MCU configuration files come from ST's fork; validate them together when changing the integration.
Do not rely on `adapter speed` to control the shipped `linuxgpiod` driver's speed.

Do not use `0xC1` as a flush byte in RouterBridge's `bridge.h`.
That attempted fix was reverted because it caused an infinite loop in `Unpacker::feed()`; the startup banner mechanism was not the cause.
The startup-output failure and the reset ordering that resolved it are described under [Sketch startup](#sketch-startup-is-an-artifact-and-host-coordination-contract).
Revisit this only with evidence that the protocol or parser behavior has changed.

## Deferred decisions

- **Zephyr SDK 1.0 migration:** the current framework depends on newlib, which SDK 1.0 removes.
  Coordinate migration with the framework upstream rather than updating the toolchain independently.
- **OpenOCD as a declared package:** retain the board-image installation until executable and configuration provenance can be managed together.
  Core normally derives embedded-platform detection from declared uploader packages; this platform uses an override so it can retain the board-image OpenOCD without declaring an uploader package.
  Preserve that detection behavior if packaging changes.
