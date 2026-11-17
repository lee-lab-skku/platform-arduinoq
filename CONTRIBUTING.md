# Contributing

This document covers development setup, change validation, and the code structure that contributors must preserve.
The cross-file contracts and their design reasoning are kept in the [developer documentation](docs/README.md).
For installation, project configuration, and board operation, see [README.md](README.md).

## Using a development checkout

Clone `platform-arduinoq` and create a separate sketch project using the [Quick start](README.md#quick-start).
Set the platform reference to the absolute path of the checkout you are changing, keeping the other project settings:

```ini
platform = symlink:///home/user/platform-arduinoq
```

Unlike the README's Git URL installation, this uses your working checkout directly, so subsequent invocations see edits without reinstalling the platform.
Framework and tool packages remain separate dependencies.

## Validation

Use the execution environments described in [Where the build runs](README.md#where-the-build-runs).
Validate hardware behavior on the MPU with the development checkout; a workstation build covers only the build side.
For remote changes, check that both participating machines use the intended revision and exercise the affected [remote mode](README.md#remote-builds).

Choose validation scope from the [contracts](docs/README.md) a change touches; the [package resolver](docs/packages-and-libraries.md#resolution-without-a-project-environment) has its own checklist.
For shared helpers, cover their callers across execution environments: OpenOCD changes can affect uploads, test-reader board operations, standalone control targets, and debugger startup.
For artifact changes, cover both the normal build and upload-only paths, plus `size` when changing size reporting.

Hardware scenarios require a suitable sketch or test project; see [Unit testing](README.md#unit-testing) for test-runner setup.
Documentation-only changes need review of the affected claims, examples, and links.

## Code structure

Both `builder/`, running inside SCons, and `host/`, running in PlatformIO's own process, import `arduinoq_common`.
Keep that package free of SCons dependencies so importing a shared helper does not break the host side.

Adding `builder/` to `sys.path` exposes its packages under top-level names throughout the SCons process.
The platform-specific name `arduinoq_common` avoids the collisions a generic `common` package could cause.
`platform.py` handles the related risk by loading helpers by path rather than exposing itself as a top-level `platform` module.
Preserve these import boundaries when moving shared code.

## Design and contracts

Read the [developer documentation](docs/README.md) for the subsystems a change touches before changing it, and update it in the same change when a contract changes.
When writing a contract, follow these rules:

- **Scope**: Keep enough of each cross-file flow to explain where its assumptions hold and where they break.
- **Names**: File and function names belong in a contract when they identify its participants; details local to one implementation belong beside the code.
