<!-- markdownlint-disable MD024 -->

# Changelog of Arduino Q Platform

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0-rc.5] &mdash; 2026-10-27

### Added

- Support for Ventuno Q (`board = ventuno_q`), including sketch builds, uploads, board control, unit testing, and debugging through the MPU.
- Automatic installation of `Arduino_RouterBridge 0.4.5-leelabskku` for Arduino environments.

### Changed

- Manual `ARDUINO_ROUTERBRIDGE_PROVIDES_SERIAL` build flag is no longer required.
- **Breaking:** Raised the minimum PlatformIO Core requirement to `6.2.0`.
- Default packages now use prebuilt `ArduinoCore-zephyr 1.0.0`, `Zephyr SDK 1.0.1`, and matching helper tools.
  Updated C++ runtime linking and resident/sketch debug symbol handling for compatibility with the new packages.
- Updated user and contributor guidance for remote operation, sketch memory limits, platform support boundaries, and transport-specific reset coordination.
- Refined the platform metadata.

### Fixed

- PlatformIO integration metadata now expands framework compiler response files, preserving ordered C/C++ flags and exposing Zephyr include paths and shared final definitions without changing compilation or linking.
- **Breaking:** Platform-controlled resets on UNO Q renew the Router UART connection while the MCU is halted and leave it halted if reconnection fails.
  Custom connection settings use `ARDUINO_ROUTER_SOCKET` and `ARDUINOQ_ROUTER_SERIAL_PORT` on the MPU.

  - Resets now require access to the Router control socket and support for its serial close/open commands.

- Test startup keeps the MCU halted until the output reader is connected.

## [1.0.0-rc.4] &mdash; 2026-09-18

### Added

- No-build `reset`, `halt`, and `release` targets for UNO Q board control through the selected project environment.
- Resident and sketch write-attempt notices for OpenOCD uploads in both `pio run` and `pio test`.
- Successful reset command completion notices, including the reset mode, for uploads and host board control.
- Verbose OpenOCD logs for board control CLI targets with `-v`.

### Changed

- **Breaking:** Build size checks use separate sketch limits of 256 KiB LLEXT RAM and 768 KiB flash while preserving nominal board metadata.
  The `size` target now uses the same usage report and checks, with an error for flash overflow and a warning for RAM overflow.
- Uploads and host board control share OpenOCD diagnostics, with normal tool logs requiring verbose output and expected verification mismatch diagnostics suppressed.
  Framework scripts retain control of verification and writing; logs discarded by the framework cannot be recovered.
- Clarified the README's platform scope and OpenOCD requirements, and reorganized user and contributor guidance.
  Contributor guidance now includes development checkout setup and validation scope across build and board execution paths.

### Fixed

- Corrected UNO Q board metadata to identify the STM32U585AI at 160 MHz and report nominal MCU capacities of 786 KiB SRAM and 2 MiB flash.
- OpenOCD uploads preserve received errors and failure diagnostics, including during silent uploads in `pio test`.
  Host board control also retains received errors and failure context instead of discarding the tool output.

## [1.0.0-rc.3] &mdash; 2026-09-05

### Changed

- The README's unit-testing example now uses `UnityTestRunner`, declares `test_framework = custom`, and skips testing when requested.

### Fixed

- Host-side board control and debug sessions now honor `board_upload.openocd_dir` from the active project environment.
- Sketch debug symbols are loaded before project and tool extra commands run, while preserving custom initialization commands.
- Standalone platform installation now resolves dependencies from GitHub release assets without requiring a project environment.

## [1.0.0-rc.2] &mdash; 2026-08-19

### Changed

- Package declarations now store only semantic versions in `platform.json`; the platform derives the release asset URLs.

## [1.0.0-rc.1] &mdash; 2026-08-18

### Added

- PlatformIO development platform for Arduino's Q series, with board support for the Arduino UNO Q (`board = uno_q`) under `framework = arduino`.
- Sketch builds as a relocatable LLEXT extension, packed into the upload image the resident Zephyr firmware loads at runtime.
- `checklink` target: a static link against fixed memory regions that verifies the sketch's symbols resolve and that it fits the `user_sketch` partition, neither of which the shipped relocatable link can answer.
  Runs as part of every build; the target exposes it on its own.
- Flash and LLEXT heap usage reporting against the board's real limits (768 KiB and 256 KiB), rather than the chip totals.
- `upload` target flashing the MCU from the MPU over its GPIO lines, through an OpenOCD build with Linux GPIO (gpiod) support.
- Remote build, upload, and test through `pio remote`, including upload-only runs where the build happened on the workstation.
- Debug sessions (`pio debug`) that place the sketch's symbols at the addresses the loader chose, so breakpoints and backtraces resolve despite the shipped ELF being relocatable.
  `arduinoq_sketch` and `arduinoq_sketch_regions` remain available for use by hand.
- Unit testing over the RouterBridge monitor socket, with the board reset through OpenOCD rather than a DTR/RTS line.
  A project's `test_custom_runner.py` obtains the reader from the platform.
- `board_build.boot_mode` (`wait`, `app`, `immediate`) to control when the loaded sketch starts relative to Linux coming up on the MPU.
- `board_upload.openocd_dir` to flash through an OpenOCD installation other than the board image's.
- `test_port`, defaulting to the RouterBridge monitor socket, since the board exposes no serial device for port discovery to find.
- Independently packaged toolchain, framework, and helper tools (`toolchain-gccarmzephyreabi`, `framework-arduino-zephyr`, `tool-zephyrsketch`, `tool-genrodatald`, `tool-zephyrchecksize`), resolved for `linux_x86_64` and `linux_aarch64` hosts from a single set of pinned versions.

[Unreleased]: https://github.com/lee-lab-skku/platform-arduinoq/compare/v1.0.0-rc.5...HEAD
[1.0.0-rc.5]: https://github.com/lee-lab-skku/platform-arduinoq/compare/v1.0.0-rc.4...v1.0.0-rc.5
[1.0.0-rc.4]: https://github.com/lee-lab-skku/platform-arduinoq/compare/v1.0.0-rc.3...v1.0.0-rc.4
[1.0.0-rc.3]: https://github.com/lee-lab-skku/platform-arduinoq/compare/v1.0.0-rc.2...v1.0.0-rc.3
[1.0.0-rc.2]: https://github.com/lee-lab-skku/platform-arduinoq/compare/v1.0.0-rc.1...v1.0.0-rc.2
[1.0.0-rc.1]: https://github.com/lee-lab-skku/platform-arduinoq/tree/v1.0.0-rc.1
