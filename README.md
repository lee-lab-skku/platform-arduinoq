# Arduino Q: development platform

[![PlatformIO Registry](https://badges.registry.platformio.org/packages/lee-lab-skku/platform/arduinoq.svg)](https://registry.platformio.org/platforms/lee-lab-skku/arduinoq)
![commits since latest](https://img.shields.io/github/commits-since/lee-lab-skku/platform-arduinoq/latest/HEAD?include_prereleases&sort=semver)

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

## Getting started

These sections cover the supported hosts, where each command runs, and installing the platform to build and upload a first sketch.

### Requirements

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

### Where the build runs

Run the platform directly on the MPU over SSH or through an editor session attached to the board.
`pio run`, `pio test`, and `pio debug` execute on the machine where you invoke them.
Uploading and resetting need the MPU's GPIO connection to the MCU, and test output uses the MPU's router service.

A separate supported Linux workstation can run build-only targets: the default target, `checklink`, and `size`.
Use [Remote builds](#remote-builds) to hand off uploading or testing to the board.
Windows and macOS workstations require `--force-remote` because this platform's packages cannot build locally on those systems.

### Installation

This README describes the platform at this revision.
The [Quick start](#quick-start) example pins a registry release, which may differ from the implementation documented here.
When using a released version, refer to the README included with that version.

```console
pio pkg install --global --platform https://github.com/lee-lab-skku/platform-arduinoq.git
```

This command installs the latest commit of the dev-platform by cloning this repository.
To use a versioned release from the PlatformIO registry, follow [Quick start](#quick-start).

Packages are resolved from GitHub release assets for the build host; the MPU selects `linux_aarch64` automatically.
Framework, helper-tool and default library pins are maintained in [platform.json](platform.json); no `platform_packages` overrides are needed for the default package set.
RouterBridge and its dependencies are installed per project environment when resolving project dependencies, rather than during a project-free global platform installation.
These package versions do not change the platform release version or the pins in earlier platform releases.

### Quick start

Each board has its own board ID, which also names the environment in the examples:

| Board | `board` value |
| --- | --- |
| UNO Q | `uno_q` |
| Ventuno Q | `ventuno_q` |

The examples in this README use UNO Q; on Ventuno Q, replace `uno_q` with `ventuno_q`.
On the MPU of UNO Q, create a project with the following `platformio.ini`:

```ini
[env:uno_q]
platform = lee-lab-skku/arduinoq
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

## Uploading and board control

These sections cover the build and board targets, what an upload reports, operating the board without a build, and running targets remotely from a workstation.

### Targets

Select a target with `pio run -t <target>`; without one, the default target runs.

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

### Upload output

Uploads hide normal OpenOCD output unless you pass `-v`, and print short notices instead:

- **Writing notices**: `Writing resident firmware...` and `Writing sketch...` appear only when the framework starts writing that image.
  Images that already match are skipped without a writing notice.
  Writing notices indicate an attempt, not successful completion.
- **Reset completion**: `MCU reset command completed (halt).` or `(run).` appears when the framework's corresponding reset command returns successfully.
  This confirms command completion, not that the sketch has booted or its communication service is ready.
- **Errors**: Received errors remain visible, and failed uploads also show the available diagnostic output.
  A specific bank-verification failure diagnostic is suppressed in either mode when verification completes unsuccessfully without another reported error.
  This diagnostic alone does not distinguish a content mismatch from other verification failures.
- **Unit tests**: Writing notices and received errors also remain visible during a default `pio test`; use `pio test -vvv` for verbose build and upload output.

Some framework flash scripts discard all logs during verification, including actual verification errors; these cannot be displayed even with `-v`.
The platform preserves that behavior and the framework's decision to attempt writing after a failed verification.

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

### Remote builds

Remote commands reach the board through the PlatformIO Remote Agent.
Start it on the MPU with `pio remote agent start`, and log in to the same PlatformIO account with `pio account login` on both machines.

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

## Serial communication and testing

`Serial` output reaches the MPU through the RouterBridge library and its socket rather than a serial port.
These sections cover that dependency, the connection, the device monitor, and unit testing over it.

### RouterBridge dependency

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

### Unit testing

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

A test run starts the sketch in this order, so that the reader does not miss its first output:

1. The reader resets the board through OpenOCD and keeps the MCU halted.
1. It opens the [RouterBridge connection](#routerbridge-connection), or the [`test_port`](#test_port) override.
1. It resumes the MCU and releases a sketch waiting in the loader.
   Test builds default to `app` boot mode, which waits for that release (see [`board_build.boot_mode`](#board_buildboot_mode)).

With `--no-reset`, the reader does not reset the board or release the sketch; a sketch packed for `app` boot mode is then still parked in the loader, so pair that option with an explicit `board_build.boot_mode`.

A run that cannot proceed ends with a message rather than waiting indefinitely:

- **Connection not opened**: The run fails with the connection error and leaves the board running.
- **No output at all**: If nothing arrives within the 120-second silence timeout, the message says that nothing was received; check that `arduino-router.service` is running.
- **Silence mid-suite**: The same timeout applies between lines of output, not to a whole suite.
- **Connection dropped**: The message says that the bridge closed the connection, which points at the Router session rather than the sketch.

If a test binary crashes on entry, Unity's `setjmp`/`longjmp` support does not survive this environment &mdash; build tests with `-DUNITY_EXCLUDE_SETJMP_H`.

## Debugging

A debug session runs GDB on the MPU against the board's OpenOCD.
The platform places the relocatable sketch's symbols at the addresses the resident firmware's loader chose.
These sections cover starting a session, the GDB commands the platform adds, and how debug servers and ports are selected.

### Starting a session

On the MPU, start GDB with `pio debug -e uno_q --interface=gdb`, or start a PlatformIO debug session from an editor attached to the board.
The session builds the sketch in debug mode and flashes it through the platform's normal upload before GDB starts.
Keep the default `debug_load_cmds`: GDB's own `load` would write the relocatable sketch over the resident firmware.

The session then runs to the loader, places the sketch's symbols, and stops with `[arduinoq] stopped in the loader, with the sketch's symbols in place.`
Breakpoints by file and line in the sketch work from there.
Without a `debug_init_break` in the project, the session stays at that stop; a project-defined `debug_init_break` resolves against the sketch, and the session runs to it.
For example, `debug_init_break = tbreak setup` stops at the start of `setup()`.
Restarting the session places the symbols again at the newly loaded addresses.

Frames in the Arduino core resolve to the sources in the installed framework package.
Zephyr's own sources are not on the board, so frames inside Zephyr show no source, including the loader stop itself.

### GDB commands

The platform defines these commands in each session:

- **`arduinoq_sketch`**: After a reset such as `monitor reset halt`, runs to the loader again and places the sketch's symbols at their new addresses.
  It resumes the target, so run it at the prompt rather than in a breakpoint command list.
- **`arduinoq_sketch_regions`**: Prints the memory regions the loader allocated for the sketch, once its symbols have been placed.
- **`arduinoq_loaded_sketch_symbols`** and **`arduinoq_load_sketch_symbols`**: Place the symbols from a manual stop at `llext_bootstrap` or `llext_load`; `help <command>` describes their arguments.

### Debug servers and ports

Without a `debug_server` option, the platform starts the board's OpenOCD from [`board_upload.openocd_dir`](#board_uploadopenocd_dir), and GDB talks to it through a pipe.
A `debug_port` given as a port number or as `host:port` makes GDB connect over TCP, and the server the platform starts listens on that port.

A project-supplied or disabled `debug_server` keeps the platform's upload and symbol placement.
Such a server runs outside the platform's reset and Router coordination.

## Configuration

These options are set per environment in `platformio.ini`.

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

Debug takes precedence over test when both apply, as when a debug session builds a test suite selected with `debug_test`.
An explicit `board_build.boot_mode` overrides these defaults.

**Avoid setting `immediate` globally.**
Early `Serial` output can be lost if the sketch starts before the bridge is ready.

### `board_upload.openocd_dir`

Selects an alternative OpenOCD installation for uploads, board control, test startup, and debugging; the default remains `/opt/openocd` from the board image.
Keep the board-specific executable or launcher, its shared libraries, `openocd_gpiod.cfg`, and target scripts together.
The platform checks for `bin/openocd` and `openocd_gpiod.cfg` and reports a missing file by name; the installation must provide Linux GPIO support.

### Router connection settings

Resets recycle or wait for the Router's connection to the MCU, as each board's transport requires.
The board manifests set these values, and an environment can override them:

| Option | UNO Q | Ventuno Q | Purpose |
| --- | --- | --- | --- |
| `board_upload.router_transport` | `uart` | `usb` | How the Router reaches the MCU; `uart` reopens the Router's serial connection during a reset, while `usb` lets the device reconnect after the MCU resumes |
| `board_upload.router_serial_port` | `/dev/ttyHS1` | `/dev/ttySTM0` | The Router's name for the MCU serial device |

The `ARDUINOQ_ROUTER_SERIAL_PORT` environment variable takes precedence over `board_upload.router_serial_port` when the UART connection is reopened.
`ARDUINO_ROUTER_SOCKET` selects the Router's control socket, `/var/run/arduino-router.sock` by default.

### `test_port`

The platform's test reader uses the default [RouterBridge connection](#routerbridge-connection) unless overridden with `test_port` or `pio test --test-port`.
For the [device monitor](#device-monitor), configure `monitor_port` separately.

## Support boundaries

These sections cover the sketch capacity available on each board and the limits that distinguish this platform's support scope from constraints imposed by its framework, libraries, and tools.

### Board resources

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

The following documents are kept in the repository and are not part of the installed package.

- [CONTRIBUTING.md](https://github.com/lee-lab-skku/platform-arduinoq/blob/main/CONTRIBUTING.md): Development setup, validation guidance, and code structure constraints.
- [Developer documentation](https://github.com/lee-lab-skku/platform-arduinoq/blob/main/docs/README.md): Cross-file contracts and design reasoning that changes must preserve, grouped by subsystem.
- [Changelog](https://github.com/lee-lab-skku/platform-arduinoq/blob/main/CHANGELOG.md): Notable changes in each release and in unreleased work.

## AI disclosure

The code and documentation were written with substantial AI assistance and have had no external review.
This platform flashes and resets physical hardware; review changes and validate them on the intended board before relying on them.

## License

Apache License 2.0 &mdash; see [LICENSE.txt](LICENSE.txt), including its warranty disclaimer.

Packages this platform installs carry their own licenses: `framework-arduino-zephyr` derives from Arduino's ArduinoCore-zephyr, `toolchain-gccarmzephyreabi` from the Zephyr Project's SDK.
