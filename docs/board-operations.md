# Board operations

This document covers the contracts behind operating the board from the MPU: board control targets, sketch startup, reset and Router coordination, board integration constraints, and OpenOCD output.
They span the artifact builder, the upload backend, and the host-side board control and test reader.

## Board control targets must bypass the build

The `reset`, `halt`, and `release` targets are a platform-owned no-build contract, documented in [Board control](../README.md#board-control-without-a-build).
The guarantee covers sketch build actions, not Core initialization, package installation, or user-provided extra scripts.

- **Registration**: Register the targets without artifact dependencies and resolve the board controller only when their action executes.
  Target discovery must not validate OpenOCD or operate hardware.
- **Early return**: A control-only invocation must return before loading the artifact or upload modules.
  Treating it as upload-only `nobuild` mode would still couple it to artifact paths.
- **Target selection**: Keep target selection rules shared between Core package configuration and the SCons builder.
  Core consumes clean requests before the platform builder runs, so builder-only validation cannot reject a mixed control/clean request before cleaning.
- **Accepted combinations**: Accept one control target with optional `nobuild`, and reject other combinations before actions execute.
- **Existing behavior**: Preserve the existing host-side `BoardControl` semantics and project environment overrides.
- **Remote execution**: Non-forced remote orchestration performs a local build outside this control-only path; document forced remote execution instead.

## Sketch startup is an artifact and host coordination contract

`board_build.boot_mode` is written into the packed image by `zephyr-sketch-tool`; it is fixed at packing time, rather than selected during compilation or upload.
The default values and override precedence are documented in [Boot mode](../README.md#board_buildboot_mode), and each default has this reason:

| Build | Mode | Reason |
| --- | --- | --- |
| Debug | `immediate` | Waiting in the loader's `control_gpios` path before `llext_load` would make sketch symbol placement depend on Linux startup timing |
| Test | `app` | Holds the loader before loading the sketch until the reader is connected |
| Debug test | `immediate` | Debug takes precedence because a loader breakpoint already provides the hold |

Keep boot-mode packing and host startup control consistent:

- **Release**: An `app` image waits for a separate SRAM release; ordinary uploading supplies that release, while a plain reset does not.
  CPU resume and app release must remain distinct operations.
- **Test reader**: The reader must complete reset before attaching its monitor, and keep the MCU halted until attachment succeeds.
  Ordinary uploads and resets do not attach a monitor.
- **Transports**: Transport handling is described under [Reset and Router coordination](#reset-and-router-coordination).
  Verify initial output separately for each transport and boot mode.

## Reset and Router coordination

Use shared reset coordination for platform-owned host operations, framework uploads, and debugger resets, including resets during OpenOCD initialization.
External resets and custom debug servers are outside this coordination.

- **Configuration**: Select the transport from the board configuration, respecting project overrides in every caller.
- **Separation**: Keep coordination separate from output observation, and preserve the framework's flash policy and target reset event handlers.
- **Order**: Reset the MCU before handling its Router connection.
  A requested running reset must first halt the MCU, then resume only after the required transport handling succeeds.
- **Failures**: Requested halt outcomes must stay halted; reset or Router failures must propagate without resuming or reporting success.
- **Startup**: Test monitor attachment and `app` release follow the [sketch startup contract](#sketch-startup-is-an-artifact-and-host-coordination-contract).

Each transport handles the Router connection differently:

- **UART (UNO Q)**: Close the old Router serial connection, wait for it to terminate, then reopen it through the separate host control channel.
  This discards incomplete Router decoder state that flushing the UART alone cannot clear.
  Preserve monitor connections and the Router service's GPIO readiness signal rather than restarting the service.
  The open acknowledgement does not guarantee receive readiness: retain the provisional fixed delay after open and before MCU resume until a reliable readiness check can replace it.
- **USB CDC (Ventuno Q)**: Let reset disconnect the device, ending the old Router decoder and RPC registrations; Router reconnects when MCU execution restores USB.
  Do not issue serial close/open while the device is absent: Router 0.11.0 can wait for USB while ignoring the close signal, deadlocking with a halted MCU.
  Verify readiness through actual RPC/Serial responses after resume.

Validate changes on the MPU with its actual OpenOCD build across upload, direct board control, test startup, and debugger resets, covering early output in each boot mode and failures that must leave execution halted.
Host-only checks cannot establish transport readiness or hardware reset behavior.

## Board integration constraints

These constraints come from the board image rather than from the platform:

- **Router readiness signal**: The board-specific configuration of `arduino-router.service` asserts a GPIO readiness signal.
  The resident loader's `wait` and `app` modes check the level of its `control_gpios` input before loading the sketch.
  While that signal remains asserted, an MCU reset can pass the same readiness check without a new command from the Router.
- **App release**: The `app` mode additionally waits for the backup SRAM release described under [Sketch startup](#sketch-startup-is-an-artifact-and-host-coordination-contract).
- **OpenOCD baseline**: Use the board image's OpenOCD installation as the integration baseline.

Keep the readiness dependency visible in the user-facing [README.md](../README.md).
Preserve the [startup ordering](#sketch-startup-is-an-artifact-and-host-coordination-contract) that protects reader attachment rather than substituting framing changes for reset coordination.

## OpenOCD output must follow the commands actually executed

The framework's flash script stays authoritative for verification, writing, reset requests, and the SRAM release.
The shared [reset coordination](#reset-and-router-coordination) controls the pause inside each reset request.
The platform only observes those commands and filters their output.
Its rules cover upload observation, reset notices, error handling, output routing, and validation.

### Upload observation

- **Wrapping**: The upload observer wraps `flash` calls before that script runs and identifies images using `filename0` and `filename1`.
  Do not branch on framework versions or infer writing from the number of verification errors.
- **Writing notice**: The notice must precede the actual `write_image` call and must not appear for an image the script skips.
- **Transparency**: Preserve argument boundaries, caller scope, and the original command's return code and result.
- **Tcl dialect**: Use syntax supported by OpenOCD's Jim Tcl interpreter, rather than assuming full Tcl compatibility.
  The forwarding and wrapper installation constraints are documented beside the implementation in `builder/arduinoq_common/openocd_events.tcl`.
- **Location**: Keep output filtering and Tcl observation in the SCons-independent `arduinoq_common` package so uploads and host board operations share their diagnostics without importing the upload builder.

### Reset notices

- **Observation only**: Observe reset commands without changing target initialization order or outcome, and do not replace target reset events.
- **Completion**: Report reset completion only for a matching begin/end pair with return code zero, after reset coordination has completed, preserving the requested `run`, `halt`, and `init` outcomes.
  This is command completion evidence, not sketch readiness; an interrupted or failed command must not produce a completion notice.
- **No inference**: Do not infer a reset from GDB startup or OpenOCD shutdown messages, and do not synthesize one for the release write.
- **Debugger server**: Keep debugger server arguments unobserved and verbose because PlatformIO uses their output to detect readiness.

### Error handling

- **Internal protocol**: Treat the observer's log records as an internal protocol, including at OpenOCD debug level 3 where commands themselves are traced.
- **Return codes**: Accept signed verification return codes: some OpenOCD builds propagate negative native errors through Jim Tcl's `catch`, while others return Tcl's error code `1`.
  Preserve those codes in the observer and interpret them in the output filter without checking the OpenOCD or framework version.
- **Suppressed diagnostic**: Only suppress the known bank-verification failure diagnostic inside a completed, failed verification with no other reported error.
  That diagnostic is not a unique error code for content mismatch; retain it when accompanied by another error, outside verification, or when verification ends unexpectedly.
- **Failures**: Preserve the subprocess exit status and include available diagnostic context on failure.
- **Framework log policy**: Respect the framework's `log_output` policy, and do not change its catch-and-write behavior as part of output filtering.
  Some scripts discard verification logs and restore output before writing; this also discards real verification errors, even in verbose mode.
  The user-facing limitation is documented in [Upload output](../README.md#upload-output).

### Output routing

- **Verbosity**: Keep normal log visibility controlled by `PIOVERBOSE`, gating normal logs before forwarding them to stderr.
- **Flags**: Preserve the ordering of user `upload_flags` after platform flags.
- **Stream**: Send shared filtered output to stderr: PlatformIO invokes uploads silently during a default `pio test`, which discards stdout even when it contains explicit writing notices or errors.

### Validating output changes

OpenOCD output handling is shared, so a change can affect every caller.
Validate it on the MPU with the board's OpenOCD build:

1. Run an upload, each board control target, a test run, and a debug session start.
1. Compare the default output with `-v`, and check a default `pio test`, where PlatformIO discards stdout.
1. Upload once with an image that already matches and once with one that changes, and check that only the written image gets a writing notice.
1. Make a command fail, and check that its exit status and diagnostic context reach the user without repeated error lines.
