# Arduino Q: development platform

[![PlatformIO Registry](https://badges.registry.platformio.org/packages/lee-lab-skku/platform/arduinoq.svg)](https://registry.platformio.org/platforms/lee-lab-skku/arduinoq)
[![commits since latest](https://img.shields.io/github/commits-since/lee-lab-skku/platform-arduinoq/v1.0.0-rc.4/HEAD)](https://github.com/lee-lab-skku/platform-arduinoq/compare/v1.0.0-rc.4...HEAD)

A PlatformIO development platform for Arduino's **Q series** &mdash; boards that pair a Linux application processor (the *MPU*) with a Zephyr-based microcontroller (the *MCU*).
This platform builds a single Arduino sketch for the MCU.
It supports UNO Q and Ventuno Q.

This is an **unofficial, independent platform**, not produced or endorsed by Arduino, the Zephyr Project, or PlatformIO Labs.
"Arduino," "Zephyr," and "PlatformIO" name the projects this interoperates with; no affiliation is implied.

## What this is

The MCU runs **resident firmware** supplied by the framework package.
The platform builds your sketch as a relocatable **LLEXT extension** that this firmware loads at runtime.
Uploading and debugging through this platform use the MPU, as described in [Requirements](#requirements).

Neither the Q series nor its Zephyr-based MCU side has official PlatformIO support upstream.
Everything here &mdash; the platform, the toolchain build, the framework package, and the helper tools &mdash; is packaged independently.

## Requirements

**The build host must be Linux**, `x86_64` or `aarch64`.
The framework and tool packages supplied by this platform are Linux builds.
Library source archives are compiled for the selected MCU.
`pio run` on any other host fails immediately with an explanatory error.

A non-Linux workstation can still be used, through PlatformIO's remote mode with `--force-remote` (`-r`), which runs the whole build on the board.
See [Remote builds](#remote-builds).

**Flashing and debugging happen on the MPU**, over its GPIO lines through OpenOCD's `linuxgpiod` driver.
The platform uses the OpenOCD installation shipped in the board image, at `/opt/openocd` by default.
An alternative installation must have `linuxgpiod` support enabled and include the board's `openocd_gpiod.cfg` interface configuration.
The driver is available in [upstream OpenOCD](https://openocd.org/doc/html/Debug-Adapter-Configuration.html), but its availability in a particular build depends on the build configuration.

## Where the build runs

Run the platform directly on the MPU over SSH or through an editor session attached to the board.
`pio run`, `pio test`, and `pio debug` execute on the machine where you invoke them.
Uploading and resetting need the MPU's GPIO connection to the MCU, and test output uses the MPU's router service.

A separate supported Linux workstation can run build-only targets: the default target, `checklink`, and `size`.
Use [Remote builds](#remote-builds) to hand off uploading or testing to the board.
Windows and macOS workstations require `--force-remote` because this platform's packages cannot build locally on those systems.

## Installation

This README describes the platform at this revision.
The [Quick start](#quick-start) example pins a registry release, which may differ from the implementation documented here.
When using a released version, refer to the README included with that version.

```console
pio pkg install --global --platform https://github.com/lee-lab-skku/platform-arduinoq.git
```

This command installs the latest commit of the dev-platform by cloning this repository.
To use a versioned release from the PlatformIO registry, follow [Quick start](#quick-start).

Packages are resolved from GitHub release assets for the build host; the MPU selects `linux_aarch64` automatically.
This revision uses prebuilt ArduinoCore-zephyr 1.0.0 and Zephyr SDK 1.0.1 packages.
Framework, helper-tool and default library pins are maintained in [platform.json](platform.json); no `platform_packages` overrides are needed for the default package set.
RouterBridge and its dependencies are installed per project environment when resolving project dependencies, rather than during a project-free global platform installation.
These package versions do not change the platform release version or the pins in earlier platform releases.

## Quick start

On the MPU of UNO Q, create a project with the following `platformio.ini`:

```ini
[env:uno_q]
platform = lee-lab-skku/arduinoq@1.0.0-rc.4
board = uno_q
framework = arduino

lib_deps =
    https://github.com/lee-lab-skku/arduino-router-bridge.git
```

Save the sketch as `src/main.cpp`:

```cpp
#include <Arduino.h>

void setup() {
  Serial.begin(115200);
}

void loop() {
  Serial.println("hello");
  delay(1000);
}
```

Build and upload it:

```console
pio run -t upload
```

An upload prints `Writing resident firmware...` and/or `Writing sketch...` only when the framework starts writing that image.
Images that already match are skipped without a writing notice.
Uploads also report `MCU reset command completed (halt).` or `(run).` when the framework's corresponding reset command returns successfully.
This confirms command completion, not that the sketch has booted or its communication service is ready.
Normal OpenOCD output is hidden unless you pass `-v`.
A specific bank-verification failure diagnostic is suppressed in either mode when verification completes unsuccessfully without another reported error.
This diagnostic alone does not distinguish a content mismatch from other verification failures.
Other received errors remain visible.
Failed uploads also show the available diagnostic output.
Writing notices and received errors also remain visible during a default `pio test`; use `pio test -vvv` for verbose build and upload output.

Some framework flash scripts discard all logs during verification, including actual verification errors; these cannot be displayed even with `-v`.
The platform preserves that behavior and the framework's decision to attempt writing after a failed verification.
Writing notices indicate an attempt, not successful completion.

## Serial communication

`Serial` is a logical channel carried over the MCU&harr;MPU link, provided by the **Arduino_RouterBridge** library rather than by the core.
The platform supplies a pinned RouterBridge release automatically for Arduino environments.
PlatformIO follows that library's own pinned RPClite and MsgPack dependencies and installs the chain in the environment's `.pio/libdeps/` storage.
The framework detects RouterBridge's Serial-provider header and defines `ARDUINO_ROUTERBRIDGE_PROVIDES_SERIAL`; no explicit build flag is needed.

An explicit RouterBridge entry in your project's `lib_deps` replaces the platform default.

Named dependencies and RouterBridge repository/release URLs are recognized directly.
Local sources can also be identified by their library manifest.
Use the `Arduino_RouterBridge=<URI>` alias when an arbitrary remote URL does not identify the library by name.
Other dependencies and their version resolution follow PlatformIO's normal library rules.
The platform's qualified combination is its default pin; an override selects a different combination.
This does not rewrite `platformio.ini` or add another platform pin for RPClite or MsgPack.

### RouterBridge connection

On the MPU, the RouterBridge monitor channel is exposed through a TCP socket rather than a USB serial port.
This platform assumes `socket://localhost:7500` as the default endpoint.
The actual endpoint may differ depending on the MPU image and its RouterBridge socket configuration; use the host and port configured on your MPU.
`localhost` refers to the machine running the reader or monitor, so the default address is intended for execution on the MPU.
The socket is not discovered by PlatformIO's serial-port scan.

### Device monitor

Run the monitor in an interactive terminal on the MPU, using the [RouterBridge connection](#routerbridge-connection).
Unlike the platform's test reader, the general monitor requires an explicit endpoint.
Add it to the project's environment in `platformio.ini`, adjusting the address if needed:

```ini
monitor_port = socket://localhost:7500
```

Then run:

```console
pio device monitor -e uno_q
```

Alternatively, supply the endpoint with `--port`.
`test_port` does not supply a default for this command.

Opening the monitor attaches to the current sketch without resetting or releasing it.
For startup output from a sketch packed in `app` mode, run [reset](#board-control-without-a-build), open the monitor, then run `release` from a second MPU terminal.
Changing the boot mode requires rebuilding and uploading the sketch; the ordinary `wait` mode does not hold execution until a monitor connects.
Monitor DTR/RTS settings do not reset the MCU over this socket connection.

## Targets

| Target | What it does |
| --- | --- |
| *(default)* | Build and pack the sketch, then report size |
| `upload` | Build, pack, and flash |
| `checklink` | Check symbol resolution with a temporary static link |
| `size` | Report flash and LLEXT heap usage |
| `nobuild` | Use artifacts from a previous build without rebuilding |
| `reset` | Reset the MCU and let it run, without building |
| `halt` | Reset the MCU and hold it halted, without building |
| `release` | Release a sketch waiting in the `app` startup loader, without building |

`checklink` runs as part of every build and can also be invoked on its own.
It checks symbol resolution using a temporary static link, because the relocatable upload artifact can retain unresolved symbols.
See [Board resources](#board-resources) for the distinction between reported hardware capacity and sketch allocations.

### Board control without a build

On the MPU, select the project's environment and run one operation:

```console
pio run -e uno_q -t reset
pio run -e uno_q -t halt
pio run -e uno_q -t release
```

These targets do not compile, link, pack, check size, or upload.
They require neither sketch source nor previous build artifacts, and do not require `-t nobuild`.
Explicit `-t nobuild` is accepted but has no additional effect.
PlatformIO still initializes the environment and may install required packages.

Each command accepts exactly one board control target.
Combining it with another operation or a build, upload, or clean target is rejected before performing the requested work.
Run separate commands when a sequence is needed.

Board control uses the same OpenOCD output handling as uploads: successful reset commands produce a concise completion notice, received errors remain visible, and failures include available diagnostic context.
Use `pio run -v -e uno_q -t reset` (or `halt` / `release`) to include normal OpenOCD logs.
`release` does not perform a reset and does not print a reset completion notice.

The selected environment supplies the board and `board_upload.openocd_dir`.
The operations use the MPU's GPIO connection and require its OpenOCD installation and running `arduino-router.service`.
`halt` resets before halting; it does not merely pause the current execution.
`reset` does not release a sketch packed for `app` startup: use `release` afterward when you want it to leave the loader.

From a workstation, force remote execution:

```console
pio remote run -r -e uno_q -t reset
```

Use the same form for `halt` and `release`.
Without `-r` / `--force-remote`, PlatformIO Core performs a local build first, so the no-build guarantee does not apply to that remote workflow.

## Configuration

### `board_build.boot_mode`

Controls when the sketch starts relative to Linux booting on the MPU.
The value is stored in the packed image, so changing it requires a rebuild.

| Value | Behaviour |
| --- | --- |
| `wait` | Hold until Linux is up |
| `app` | Hold in the loader, before the sketch is loaded at all, until the MPU releases it |
| `immediate` | Start at once |

In `app` mode, an ordinary upload releases the sketch, while a plain reset leaves it waiting for the MPU.
This allows the test reader to connect before the sketch starts.

The default depends on the build type:

| Build | Default | Why |
| --- | --- | --- |
| Debug | `immediate` | Allows the debugger to reach sketch loading without waiting for Linux |
| Test | `app` | Lets the test reader connect before the sketch starts |
| Otherwise | `wait` | Matches the resident firmware's own default |

Debug takes precedence over test when both apply.
An explicit `board_build.boot_mode` overrides these defaults.

**Avoid setting `immediate` globally.**
Early `Serial` output can be lost if the sketch starts before the bridge is ready.

### `board_upload.openocd_dir`

Selects an alternative OpenOCD installation for uploads, board control, test startup, and debugging; the default remains `/opt/openocd` from the board image.
Keep the board-specific executable or launcher, its shared libraries, `openocd_gpiod.cfg`, and target scripts together.
The platform checks for `bin/openocd` and `openocd_gpiod.cfg` and reports a missing file by name; the installation must provide Linux GPIO support.

### `test_port`

The platform's test reader uses the default [RouterBridge connection](#routerbridge-connection) unless overridden with `test_port` or `pio test --test-port`.
For the [device monitor](#device-monitor), configure `monitor_port` separately.

## Remote builds

```console
pio remote run -t upload          # builds LOCALLY, uploads remotely
pio remote run -r -t upload       # builds and uploads on the board
pio remote test -f test_xxx       # builds a single suite locally, and tests on the board
pio remote test -r                # builds and tests on the board
```

Without `-r`/`--force-remote`, the build runs on the *workstation* and only the result ships to the board &mdash; on a non-Linux workstation, that local build is exactly what fails.
**Use `-r` from Windows or macOS.**

`pio remote run -t checklink -t upload` is supported.
The link check runs during the build; the upload-only remote step does not repeat it.

`pio remote device list` lists serial ports exposed by the MPU; it does not identify an MCU upload target through this platform.
MCU uploads use GPIO/OpenOCD, and test output uses the RouterBridge socket, so an MCU entry in the remote device list is not required for remote uploads or tests.
Exposing the MCU as a remote device would require additional integration with the Remote Agent beyond the development platform itself.

## Unit testing

Test output uses the [RouterBridge connection](#routerbridge-connection); the platform's reader supplies its default endpoint, with [`test_port`](#test_port) available for an override.
Resetting the board for a test run goes through OpenOCD rather than a DTR/RTS line.
The project selects the platform's reader through a custom test runner.
For Unity tests, add this option to the project's environment in `platformio.ini`:

```ini
test_framework = custom
```

Then create `test/test_custom_runner.py`:

```python
# test/test_custom_runner.py
from platformio.public import UnityTestRunner


class CustomTestRunner(UnityTestRunner):
    def stage_testing(self):
        if self.options.without_testing:
            return None

        factory = getattr(self.platform, "get_test_output_reader", None)
        if factory:
            return factory(self).begin()

        return super().stage_testing()
```

`UnityTestRunner` supplies result parsing and suite completion.
Projects with their own `unity_config.h` or `test_transport = custom` retain responsibility for their output hooks.
The skip guard also keeps the reader from running during the local build phase of `pio remote test`.
Projects with an existing custom parser can use the same `stage_testing()` method in their runner while keeping their parsing and completion handling.

A test run resets the board and keeps the MCU paused until the output reader is connected.
Test builds default to `app` boot mode (see [`board_build.boot_mode`](#board_buildboot_mode)).
This ordering addresses reader-attachment races.

With `--no-reset`, the reader does not reset the board or release the sketch; a sketch packed for `app` boot mode is then still parked in the loader, so pair that option with an explicit `board_build.boot_mode`.

If the board falls silent mid-suite, or the bridge drops the connection, the run ends with a message saying which happened rather than waiting indefinitely.
The reader also applies a silence timeout between lines of output.

If a test binary crashes on entry, Unity's `setjmp`/`longjmp` support does not survive this environment &mdash; build tests with `-DUNITY_EXCLUDE_SETJMP_H`.

## Board resources

Board listings show the MCU's total flash and SRAM.
The resident firmware runs Zephyr and loads the sketch into dedicated regions, so only part of that capacity is available to the sketch.
Your sketch must fit within the allocations provided by the pinned framework:

| Board | Sketch flash | Sketch RAM (LLEXT heap) |
| --- | --- | --- |
| UNO Q | 768 KiB | 256 KiB |
| Ventuno Q | 1 MiB | 256 KiB |

The build summary and `pio run -t size` report usage against these sketch limits.
Exceeding the flash limit fails the build; exceeding the RAM limit produces a warning and still requires reducing memory use.
The RAM figure estimates the loaded sketch's footprint from its ELF file; check additional runtime memory use separately, because a successful build does not guarantee that the sketch will fit at runtime.

## Support boundaries

The limits below distinguish this platform's support scope from constraints imposed by its framework, libraries, and tools.

### Platform support

- **Sketch linking:** only dynamic (relocatable LLEXT) linking is supported.
- **Debugger host:** direct debugging from a separate PC is not supported; the debugger must run on the MPU.
- **Resident backtraces:** unwinding through the resident firmware may stop before reaching the full call stack.

### Environment constraints

- **Ventuno firmware:** the pinned framework's Ventuno variant lacks dynamic interrupt registration and an enabled `counter_servo` device.
  Enabling these requires replacement resident firmware and a matching LLEXT EDK; sketch build flags cannot enable them.
- **Arduino library compatibility:** libraries that depend on AVR/SAM internals or conflict with Zephyr symbols may fail even when they declare Arduino compatibility.
  Check whether each library supports the board and its Zephyr-based core.
- **Static analysis:** tools may fail to parse the pinned framework and toolchain headers even when the sketch builds successfully.
  Inspect parsing errors with `pio check -v`; a `PASSED` result alone does not guarantee complete analysis.
  Use `pio check --skip-packages` or `check_skip_packages = yes` to exclude package headers if needed, at the cost of reduced analysis coverage.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development requirements, architectural constraints, and validation guidance.

## AI assistance

The code and documentation were written with substantial AI assistance and have had no external review.
This platform flashes and resets physical hardware; review changes and validate them on the intended board before relying on them.

## License

Apache License 2.0 &mdash; see [LICENSE.txt](LICENSE.txt), including its warranty disclaimer.

Packages this platform installs carry their own licenses: `framework-arduino-zephyr` derives from Arduino's ArduinoCore-zephyr, `toolchain-gccarmzephyreabi` from the Zephyr Project's SDK.
