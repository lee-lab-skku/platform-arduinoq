<!-- markdownlint-disable MD024 -->

# Changelog of Arduino Q Platform

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0-rc.1] &mdash; 2026-08-18

### Added

- PlatformIO development platform for Arduino's Q series, with board support for
  the Arduino UNO Q (`board = uno_q`) under `framework = arduino`.
- Sketch builds as a relocatable LLEXT extension, packed into the upload image
  the resident Zephyr firmware loads at runtime.
- `checklink` target: a static link against fixed memory regions that verifies
  the sketch's symbols resolve and that it fits the `user_sketch` partition,
  neither of which the shipped relocatable link can answer. Runs as part of
  every build; the target exposes it on its own.
- Flash and LLEXT heap usage reporting against the board's real limits (768 KiB
  and 256 KiB), rather than the chip totals.
- `upload` target flashing the MCU from the MPU over its GPIO lines, through an
  OpenOCD build with Linux GPIO (gpiod) support.
- Remote build, upload, and test through `pio remote`, including upload-only
  runs where the build happened on the workstation.
- Debug sessions (`pio debug`) that place the sketch's symbols at the addresses
  the loader chose, so breakpoints and backtraces resolve despite the shipped
  ELF being relocatable. `arduinoq_sketch` and `arduinoq_sketch_regions` remain
  available for use by hand.
- Unit testing over the RouterBridge monitor socket, with the board reset
  through OpenOCD rather than a DTR/RTS line. A project's
  `test_custom_runner.py` obtains the reader from the platform.
- `board_build.boot_mode` (`wait`, `app`, `immediate`) to control when the
  loaded sketch starts relative to Linux coming up on the MPU.
- `board_upload.openocd_dir` to flash through an OpenOCD installation other
  than the board image's.
- `test_port`, defaulting to the RouterBridge monitor socket, since the board
  exposes no serial device for port discovery to find.
- Independently packaged toolchain, framework, and helper tools
  (`toolchain-gccarmzephyreabi`, `framework-arduino-zephyr`, `tool-zephyrsketch`,
  `tool-genrodatald`, `tool-zephyrchecksize`), resolved for `linux_x86_64` and
  `linux_aarch64` hosts from a single set of pinned versions.

[Unreleased]: https://github.com/lee-lab-skku/platform-arduinoq
[1.0.0-rc.1]: https://github.com/lee-lab-skku/platform-arduinoq/tree/v1.0.0-rc.1
