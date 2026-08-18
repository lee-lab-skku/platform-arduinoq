# platform-arduinoq

A PlatformIO development platform for Arduino's **Q series** — boards that pair
a Linux application processor (the *MPU*) with a Zephyr-based microcontroller
(the *MCU*), programmed as a single Arduino sketch. It currently ships support
for the **UNO Q**; nothing else in the family has been built yet, but the
packaging (variants, per-board firmware, board manifests) is laid out to add
one without restructuring.

This is an **unofficial, independent platform**, not produced or endorsed by
Arduino, the Zephyr Project, or PlatformIO Labs. "Arduino," "Zephyr," and
"PlatformIO" name the projects this interoperates with; no affiliation is
implied.

**No warranty.** This repository — code and documentation alike — was written
with substantial AI assistance and has had no external review. It flashes and
resets real hardware; treat it accordingly, and see [LICENSE.txt](LICENSE.txt)
for the disclaimer this is offered under.

## What this is

A sketch is not built as standalone firmware. The MCU permanently runs a
**resident firmware** that ships inside the framework package, and a sketch is
built as a relocatable **LLEXT extension** that the resident firmware loads at
runtime. This shows up throughout the workflow — most visibly in why uploading
and debugging both have to happen through the MPU rather than a USB debug
probe — and the rest of this document explains the specific consequences as
they come up.

Neither the Q series nor its Zephyr-based MCU side has official PlatformIO
support upstream. Everything here — the platform, the toolchain build, the
framework package, and the helper tools — is packaged independently.

## Requirements

**The build host must be Linux**, `x86_64` or `aarch64`. Every package this
platform installs is a Linux build. `pio run` on any other host fails
immediately with an explanatory error.

A non-Linux workstation can still be used, through PlatformIO's remote mode
with `--force-remote` (`-r`), which runs the whole build on the board. See
[Remote builds](#remote-builds).

**Flashing and debugging happen on the MPU**, over its GPIO lines through
OpenOCD's `linuxgpiod` driver — there is no USB debug probe. This requires the
OpenOCD build that ships in the board image, at `/opt/openocd` by default. A
stock OpenOCD will not do: it typically lacks both gpiod support and the gpiod
interface configuration this needs.

## Where the build runs

**The default mode assumes you are working on the board.** `pio run`,
`pio test`, and `pio debug` all run where you invoke them, and everything past
building needs the MPU: uploading and resetting go through the OpenOCD
installation in the board image, driving the MCU over the MPU's own GPIO
lines, and test output arrives on a socket the MPU's router service exposes.
None of that exists on a workstation. So the ordinary way to use this platform
is over SSH to the board, or in an editor session attached to it.

A separate Linux `x86_64` workstation can still run the targets that only
build — the default target, `checklink`, `size` — since the toolchain is
packaged for both architectures. `upload`, `test`, and `debug` are not
available there, and there is no cross-machine handoff for them outside of
PlatformIO's remote mode.

From Windows or macOS nothing builds locally at all. See
[Remote builds](#remote-builds).

## Installation

```ini
[env:uno_q]
platform = https://github.com/lee-lab-skku/platform-arduinoq.git
board = uno_q
framework = arduino
```

Packages are resolved from GitHub release assets; the `linux_aarch64` build is
selected automatically on the MPU, nothing has to be configured for it.

## Quick start

```ini
[env:uno_q]
platform = https://github.com/lee-lab-skku/platform-arduinoq.git
board = uno_q
framework = arduino

lib_deps =
    https://github.com/lee-lab-skku/arduino-router-bridge.git
```

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

```console
pio run -t upload
```

### `Serial` requires Arduino_RouterBridge

**This is the single most common way for a first build to fail.** `Serial` is
not a UART on these boards — it is a logical channel carried over the MCU↔MPU
link, provided by the **Arduino_RouterBridge** library rather than by the core.
Without it in `lib_deps`, any sketch touching `Serial` fails to compile with
`'Serial' was not declared in this scope`. PlatformIO has no mechanism for a
platform to declare a library dependency on a sketch's behalf, so this is
unavoidably something every project has to add for itself.

RouterBridge depends on RPCLite and MsgPack in turn. Neither has a tagged
upstream release, so its own manifest pins both to forks built off their
`main` branches; adding RouterBridge alone is enough, PlatformIO's dependency
resolution pulls the rest in automatically.

`Serial1` *is* a real UART, on `D0`/`D1`.

## Targets

| Target | What it does |
| --- | --- |
| *(default)* | Build and pack the sketch, then report size |
| `upload` | Build, pack, and flash |
| `checklink` | Verify the sketch links and fits, as a static build |
| `size` | Report flash and LLEXT heap usage |
| `nobuild` | Use artifacts from a previous build without rebuilding |

`checklink` runs as part of every build regardless; the target just exposes it
on its own. It exists because the shipped artifact is relocatable, and a
relocatable link leaves undefined symbols unresolved and places nothing — so
neither "does it link" nor "does it fit" is answered by the build that
actually ships. `checklink` performs a throwaway static link, against fixed
memory regions, purely to answer those two questions.

## Configuration

### `board_build.boot_mode`

Controls when the sketch starts, relative to Linux booting on the MPU. Written
into the packed image at packing time, so changing it needs a rebuild.

| Value | Behaviour |
| --- | --- |
| `wait` | Hold until Linux is up |
| `app` | Hold in the loader, before the sketch is loaded at all, until the MPU releases it |
| `immediate` | Start at once |

"app" is the resident firmware's name for the flag, and it means the sketch —
not a Linux-side application. The loader parks ahead of loading it, polling a
word at the start of backup SRAM, and proceeds once the MPU writes something
non-zero there. Flashing does that write as part of its own sequence, so an
ordinary `upload` is unaffected; a plain reset does not, which is what makes
the mode useful for testing.

Rather than one default, the mode follows what is being built:

| Build | Default | Why |
| --- | --- | --- |
| Debug | `immediate` | The loader would otherwise be parked in its startup wait when you attach, and whether a session can place the sketch's symbols would depend on what Linux happens to be doing |
| Test | `app` | Holds the board until the test reader has attached to the monitor socket, so no output can be produced before there is anything reading it |
| Otherwise | `wait` | Matches the resident firmware's own default |

Debug wins over test, since a debug test session is both: a breakpoint in the
loader already holds the board, so the reader does not need to.

Setting `board_build.boot_mode` explicitly overrides all of it.

**Do not set `immediate` globally as a convenience.** Anything the sketch
writes before the bridge is up is lost rather than buffered, so early
`Serial` output drops intermittently, depending on which side of that race
wins — a genuinely unpleasant thing to chase down.

### `board_upload.openocd_dir`

Points at a different OpenOCD installation. It must have Linux GPIO support
and `openocd_gpiod.cfg` at its root; both are checked, and a missing one is
reported by name.

### `test_port`

Defaults to `socket://localhost:7500`, the socket the RouterBridge monitor
channel surfaces on — there is no USB serial device for PlatformIO's usual
port discovery to find.

## Remote builds

```console
pio remote run -t upload          # builds LOCALLY, uploads remotely
pio remote run -r -t upload       # builds and uploads on the board
pio remote test -f test_xxx       # builds a single suite locally, and tests on the board
pio remote test -r                # builds and tests on the board
```

Without `-r`/`--force-remote`, the build runs on the *workstation* and only
the result ships to the board — on a non-Linux workstation, that local build
is exactly what fails. **Use `-r` from Windows or macOS.**

`pio remote run` also re-issues whatever `-t` targets were passed on the
remote leg, with `nobuild` appended. `pio remote run -t checklink -t upload`
therefore reaches the board with `checklink` and `nobuild` together; this is
accepted as a no-op rather than failing, since the real check already ran
during the local build.

## Unit testing

Test output arrives over a socket rather than a serial port, and resetting the
board for a test run goes through OpenOCD rather than a DTR/RTS line.
PlatformIO gives a development platform no way to register a test runner on
its own — only `test_custom_runner.py` from the project is ever loaded — so
the project has to delegate to it:

```python
# test/test_custom_runner.py
from platformio.test.runners.base import TestRunnerBase
from platformio.test.runners.readers.serial import SerialTestOutputReader


class CustomTestRunner(TestRunnerBase):
    def stage_testing(self):
        factory = getattr(self.platform, "get_test_output_reader", None)
        reader = factory(self) if factory else SerialTestOutputReader(self)
        return reader.begin()
```

A test run resets the board first, connects to the monitor socket, and only
then releases the sketch — which is why test builds default to `app` boot mode
(see [`board_build.boot_mode`](#board_buildboot_mode)). Nothing the sketch
prints can be missed or arrive interleaved with the reset, so a test suite does
not need to wait on `Serial` or delay in `suiteSetup` to compensate.

With `--no-reset` the board is left alone and neither step happens; a sketch
packed for `app` boot mode is then still parked in the loader, so pair that
option with an explicit `board_build.boot_mode`.

If the board falls silent mid-suite, or the bridge drops the connection, the
run ends with a message saying which happened rather than waiting indefinitely.
The silence timeout is sized for the gap between lines of output, so a
long-running individual test case will not trip it.

If a test binary crashes on entry, Unity's `setjmp`/`longjmp` support does not
survive this environment — build tests with `-DUNITY_EXCLUDE_SETJMP_H`.

## Troubleshooting

**`arduino-router.service` has to be running on the MPU.** It isn't only
relaying `Serial` — it's also part of the reset and flashing sequence. If it's
stopped, uploads, resets, and serial communication can all start failing in
ways that don't obviously point back to it. If something inexplicable is
happening, check its status before anything else.

## Board resources

Currently `uno_q` only — STM32U585, Cortex-M33 with a hardware
single-precision FPU:

| Resource | Size |
| --- | --- |
| Sketch flash (`user_sketch` partition) | 768 KiB |
| LLEXT heap | 256 KiB |

These are the limits `checklink` and the size check report against — not the
chip's total flash or RAM, most of which belongs to the resident firmware.

## Known issues

The following behaviors originate in PlatformIO Core's remote orchestration,
not in this platform. They are listed here because they are easy to mistake
for platform bugs.

### Only the last test suite runs under `pio remote test`

When a project defines multiple test suites, a non-forced remote test run
executes only the last one. This is a long-standing upstream issue; the
upstream guidance is to use `--force-remote`.

### "Building & uploading" is printed on upload-only runs

In a non-forced remote run the local leg has already built the project, and
the remote leg receives `nobuild`. The "Building & uploading" label is emitted
by PlatformIO's `TestRunnerBase` whenever the platform is detected as embedded,
independently of the path actually taken. The message does not indicate that a
rebuild is happening on the board.

### The local leg reports 0 tests

A non-forced remote test splits into a local build leg and a remote execution
leg. The local leg only builds, so it has no results to report and prints a
zero count. The real result comes from the remote leg.

### Recommendation

If a remote test produces output or a result count that does not match
expectations, re-run with `-r` (`--force-remote`) before investigating further.
Running the test directly on the MPU is also a useful reference point.

## Limitations

- **Only the dynamic (relocatable LLEXT) link mode is supported.**
- **The framework identifier is `arduino`, deliberately** — splitting it out
  (e.g. `arduino-zephyr`) would lose compatibility with every library
  declaring `frameworks=arduino`. The tradeoff is that libraries advertise
  compatibility they cannot really promise: this is Zephyr underneath, and
  anything assuming AVR/SAM internals, or colliding with a Zephyr global
  symbol, will fail. Compatibility is best-effort; it's on you to judge
  whether a given library applies.
- **Only the UNO Q is implemented** at present.

## Repository layout

```text
platform.py                          Platform class: packages, debug, test hooks
builder/
  main.py                            Target orchestration
  frameworks/arduino-zephyr.py       Framework integration, flags, libraries
  artifacts/zephyr-llext.py          Multi-pass link, strip, pack, size, checklink
  upload/openocd.py                  Upload backend
  arduinoq_common/                   SCons-free helpers, also used from host/
    arduino_zephyr_layout.py         Where the framework package keeps things
    openocd_layout.py                Where the OpenOCD installation keeps things
host/
  board_control.py                   Reset/halt through OpenOCD
  test_reader.py                     Socket-based test output reader
  gdb/llext.gdb                      Symbol placement helpers
boards/uno_q.json                    Board manifest
```

## License

Apache License 2.0 — see [LICENSE.txt](LICENSE.txt).

Packages this platform installs carry their own licenses:
`framework-arduino-zephyr` derives from Arduino's ArduinoCore-zephyr,
`toolchain-gccarmzephyreabi` from the Zephyr Project's SDK.
