# Maintainer notes

This document is for people and agents working *on* this repository,
covering the part that is hard to recover by reading the code; what the platform
does and how to use it is in `README.md`.

Everything here is either an invariant no single file owns, or a record of
something already tried and disproved. Anything explaining why one particular
line is the shape may belong next to that line, not here.

## Cross-file contracts

These are the things that break quietly, because no single file is responsible
for them and a change to one side leaves the other still compiling.

### Framework adapter does not run before the artifact module

PlatformIO runs framework scripts from inside `ProcessProgramDeps()`, which
`builder/artifacts/zephyr-llext.py` calls — and deliberately skips in
`nobuild` mode.

**Therefore:** any module needing framework package paths *regardless of build
mode* must go through `builder/arduinoq_common/arduino_zephyr_layout.py`, not
through the adapter's `ARDUINO_ZEPHYR_*` exports. `builder/upload/openocd.py`
is the module this exists for; upload-only remote sessions are the case that
breaks without it.

### `arduinoq_common` is SCons-free, deliberately

Both `builder/` (inside SCons) and `host/` (inside PlatformIO's own process)
import it. Importing SCons there would break the `host/` side.

The package is named for this platform rather than `common` because putting
`builder/` on `sys.path` publishes its packages under top-level names for the
whole SCons process. `platform.py` avoids the same hazard differently &mdash; it
loads helpers by path so as not to publish itself as `platform`.

### Boot mode is a three-file protocol

`board_build.boot_mode` decides when a loaded sketch starts. The value is
written into the packed image by `zephyr-sketch-tool`, so it is a property of
the artifact, fixed at packing time, not at compile or upload time.

| Build type | Default | Why |
| --- | --- | --- |
| `debug` | `immediate` | The loader must not park in its `control_gpios` wait before reaching `llext_load`, or symbol placement depends on what Linux is doing |
| `test` | `app` | The loader holds before loading the sketch until the host releases it, so the reader attaches before the first line of output exists |
| `release` | `wait` | Upstream's default |

Debug wins over test. An explicit `board_build.boot_mode` overrides all of it.

The `app` path spans three files and only works if all three agree:

1. `builder/artifacts/zephyr-llext.py` packs with `-wait_for_app`
1. `host/test_reader.py` resets, connects, *then* calls `release()`
1. `host/board_control.py` writes the magic word over OpenOCD

### The framework manifest owns which libraries exist

The framework package's export policy decides what ships in `libraries/`. The
platform does not restate that list.

`LIBSOURCE_DIRS` must be the single `libraries/` storage directory &mdash;
PlatformIO enumerates each element's *children* as libraries. Listing
`libraries/<name>[/src]` per library makes discovery return nothing at all.

### The framework identifier stays `arduino`

Splitting it (`arduino-zephyr`) would lose compatibility with libraries declaring
`frameworks=arduino`, unless `lib_compat_mode=off` . The accepted cost is that libraries advertise
compatibility they cannot deliver &mdash; this is Zephyr underneath. Best-effort,
documented as such in `README.md`.

## Environmental facts

Things that look like bugs in this platform and are not.

- **The MCU boots from System Memory ROM.**
  `arduino-router.service` sends the bootloader command that jumps to flash.
  A stopped router therefore breaks keeps the firmware from running.
- **`pio remote run` re-issues the caller's targets** on the remote leg
  with `nobuild` appended, while the local leg always runs a fixed
  `["checkprogsize", "buildprog"]`. `checklink` must therefore stay registered
  unconditionally.
- **`linuxgpiod` ignores `adapter speed`** entirely.
- The shipped OpenOCD is sourced from *Arduino* fork, while the MCU configuration files come from *ST* fork.

---

Do not re-derive these. Each was tried and disproved.

- **RouterBridge `bridge.h` flush byte.** `0xC1` is wrong and
  the change was reverted; the banner mechanism was not the cause. `0xC1`
  causes an infinite loop in `Unpacker::feed()`.
- **Stray bytes among the first lines of test output.** Not a framing or flush
  problem. The reader connected before resetting, so SRST cut a mid-flight RPC
  response frame; its leftover `0x01` merged with the next boot's banner. Fixed
  by resetting first and holding the loader in `app` mode until the reader is
  attached.

## Deferred

Decided against, with reasons. Reopening needs a new reason, not a rediscovery.

- **Zephyr SDK 1.0 migration** &mdash; watching framework upstream. It drops `newlib`,
  which the current framework relies on.
- **OpenOCD as a declared package** &mdash; PlatformIO only treats a platform as
  embedded if an uploader package is declared, but overriding adresses it. Because the
  sources of truth are scattered in repositories, just using the shipped OpenOCD version now.
- **Manifest fields such as `build.core` or `build.f_cpu`** &mdash; `F_CPU` comes from
  `SystemCoreClock` in the core.
