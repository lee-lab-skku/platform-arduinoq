# Arduino Q: development platform

A PlatformIO development platform for Arduino's **Q series** &mdash; boards that pair a Linux application processor (the *MPU*) with a Zephyr-based microcontroller (the *MCU*).
This platform builds a single Arduino sketch for the MCU.
Only **UNO Q** support is currently implemented in this repository.

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
Every package this platform installs is a Linux build.
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

```console
pio pkg install --global --platform https://github.com/lee-lab-skku/platform-arduinoq.git
```

This command installs the development version by cloning this repository.
To use a versioned release from the PlatformIO registry, follow [Quick start](#quick-start).

Packages are resolved from GitHub release assets.
The `linux_aarch64` build is selected automatically on the MPU.

## Quick start

On the MPU, create a project with the following `platformio.ini`:

```ini
[env:uno_q]
platform = lee-lab-skku/arduinoq@1.0.0-rc.3
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

### `Serial` requires Arduino_RouterBridge

`Serial` is a logical channel carried over the MCU&harr;MPU link, provided by the **Arduino_RouterBridge** library rather than by the core.
Add RouterBridge to `lib_deps` when using `Serial`, as shown above.
PlatformIO resolves its RPCLite and MsgPack dependencies automatically.

`Serial1` provides hardware UART access on `D0`/`D1`.

## Targets

| Target | What it does |
| --- | --- |
| *(default)* | Build and pack the sketch, then report size |
| `upload` | Build, pack, and flash |
| `checklink` | Check symbol resolution with a temporary static link |
| `size` | Report flash and LLEXT heap usage |
| `nobuild` | Use artifacts from a previous build without rebuilding |

`checklink` runs as part of every build and can also be invoked on its own.
It checks symbol resolution using a temporary static link, because the relocatable upload artifact can retain unresolved symbols.
See [Board resources](#board-resources) for the distinction between reported hardware capacity and sketch allocations.

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

Selects an alternative OpenOCD installation.
It must have Linux GPIO support and `openocd_gpiod.cfg` at its root; both are checked, and a missing one is reported by name.

### `test_port`

Defaults to `socket://localhost:7500`, which exposes the RouterBridge monitor channel.
This workflow uses that socket instead of USB serial port discovery.

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

## Unit testing

Test output arrives over a socket rather than a serial port, and resetting the board for a test run goes through OpenOCD rather than a DTR/RTS line.
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
The skip guard also keeps the reader from running during the local build phase of `pio remote test`.
Projects with an existing custom parser can use the same `stage_testing()` method in their runner while keeping their parsing and completion handling.

A test run resets the board first, connects to the monitor socket, and only then releases the sketch &mdash; which is why test builds default to `app` boot mode (see [`board_build.boot_mode`](#board_buildboot_mode)).
This sequence avoids losing startup output because the reader attached too late or mixing it with output interrupted by reset.

With `--no-reset`, the reader does not reset the board or release the sketch; a sketch packed for `app` boot mode is then still parked in the loader, so pair that option with an explicit `board_build.boot_mode`.

If the board falls silent mid-suite, or the bridge drops the connection, the run ends with a message saying which happened rather than waiting indefinitely.
The reader also applies a silence timeout between lines of output.

If a test binary crashes on entry, Unity's `setjmp`/`longjmp` support does not survive this environment &mdash; build tests with `-DUNITY_EXCLUDE_SETJMP_H`.

## Troubleshooting

**`arduino-router.service` must be running on the MPU.**
The service participates in reset and flashing as well as relaying `Serial`.
Check its status when uploads, resets, or serial communication fail unexpectedly.

## Board resources

The UNO Q's STM32U585 MCU has a Cortex-M33 core with a single-precision FPU and a nominal clock of 160 MHz.
The board metadata shows the chip's nominal capacities, while the resident firmware allocates smaller regions to sketches:

| Resource | Nominal MCU capacity | Sketch allocation |
| --- | --- | --- |
| Flash | 2 MiB (2,097,152 bytes) | 768 KiB `user_sketch` partition |
| SRAM | 786 KiB (804,864 bytes) | 256 KiB LLEXT heap |

The [STM32U585 specifications](https://www.st.com/en/microcontrollers-microprocessors/stm32u585ai.html) include 2 KiB of backup SRAM in the nominal SRAM total, with ECC disabled.
These figures describe MCU memory, not the MPU's Linux RAM or eMMC storage.

A sketch is loaded into resident firmware, so the full chip capacity is not available to it.
The size tool reports the packed sketch's flash usage and its LLEXT heap footprint.
Both the build summary and `pio run -t size` compare these figures with the sketch allocations above, while board listings show nominal MCU capacities.
Exceeding the sketch flash allocation fails the size check; exceeding the LLEXT RAM allocation produces a warning.
The RAM figure is an ELF-based estimate of LLEXT usage, not a measurement of peak runtime memory use.
`checklink` checks symbol resolution separately and does not enforce these allocations.

## Known issues

The following behaviors originate in PlatformIO Core's remote orchestration, not in this platform.
They are listed here because they are easy to mistake for platform bugs.

### Only the last test suite runs under `pio remote test`

When a project defines multiple test suites, a non-forced remote test run executes only the last one.
This is a long-standing upstream issue; the upstream guidance is to use `--force-remote`.

### "Building & uploading" is printed on upload-only runs

In a non-forced remote run the local leg has already built the project, and the remote leg receives `nobuild`.
The "Building & uploading" label can still appear during this upload-only step; it does not indicate that the board is rebuilding the project.

### The local leg reports 0 tests

A non-forced remote test splits into a local build leg and a remote execution leg.
The local leg only builds, so it has no results to report and prints a zero count.
The real result comes from the remote leg.

### Recommendation

If a remote test produces output or a result count that does not match expectations, re-run with `-r` (`--force-remote`) before investigating further.
Running the test directly on the MPU is also a useful reference point.

## Limitations

- **Only the dynamic (relocatable LLEXT) link mode is supported.**
- **Arduino library compatibility is best-effort.**
  The `arduino` framework identifier allows discovery of Arduino libraries, but libraries that depend on AVR/SAM internals or conflict with Zephyr symbols may fail.
  Check whether each library supports the board and its Zephyr-based core.
- **Only the UNO Q is implemented** at present.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development requirements, architectural constraints, and validation guidance.

## AI assistance

The code and documentation were written with substantial AI assistance.
This platform flashes and resets physical hardware; review changes and validate them on the intended board before relying on them.

## License

Apache License 2.0 &mdash; see [LICENSE.txt](LICENSE.txt), including its warranty disclaimer.

Packages this platform installs carry their own licenses: `framework-arduino-zephyr` derives from Arduino's ArduinoCore-zephyr, `toolchain-gccarmzephyreabi` from the Zephyr Project's SDK.
