# Packages and libraries

This document covers how the platform resolves its packages and default libraries and which component owns each choice.
It also records the deferred decision on managing MPU host packages.

## Version and URL ownership

Each part of a package's download location has one owner:

| Owner | Holds | Changes when |
| --- | --- | --- |
| `platform.json` | Each package's complete semantic version, including prerelease and build metadata; the single source of truth | A routine package version bump, which should change only this file |
| `PACKAGE_URL_BASES` in `platform.py` | The repository and Git tag convention, with a `{release}` placeholder rather than a concrete version | A package moves repository or changes its tag convention |

Release assets use `<urlbase><package-name>[-<systype>]-<version>.tar.gz`:

- **Release tag**: The `packages` property strips prerelease and build metadata when filling the release tag placeholder, but retains the complete version in the asset filename.
  For example, a pin such as `0.56.0-leelabskku+unoq` supplies `0.56.0` for `{release}` while keeping the complete pin in the filename.
- **Host suffix**: The framework package is architecture-independent; toolchains and helper tools include `linux_x86_64` or `linux_aarch64` in their asset names.
- **Overrides**: Explicit `platform_packages` overrides must bypass URL expansion.

A framework or toolchain update also has to keep [C++ runtime linking](build.md#c-runtime-linking-must-match-the-framework-recipe) aligned with the new recipe.
When it changes the sketch partition or LLEXT heap, update the sketch allocations described in [Board metadata and sketch capacity](build.md#board-metadata-and-sketch-capacity).

## Platform-managed libraries

The top-level `libraries` field in `platform.json` owns exact default library versions.
It is interpreted by this platform, separately from Core's framework/tool `packages` field.

Library versions follow these rules:

- **URLs**: `LIBRARY_URL_BASES` owns library repository and tag rules; retain the complete library version in both the release tag and asset name.
- **Resolver output**: The library resolver returns copies and must not replace the manifest's nominal versions with URLs.

`configure_project_packages()` first retains Core's package configuration and target validation, then adds library defaults to the shared in-memory configuration of Arduino environments.
Core installs these through Library Manager before a build; SCons recreates the same defaults when it loads the platform.

- **Side effects**: Do not save the project configuration, install libraries inside the hook, or add hardware/SCons dependencies to the resolver.
- **Repetition**: Repeated calls must not duplicate defaults or leak selections between environments.
- **Global installation**: Project-free global platform installation does not create a library environment.

An explicit RouterBridge entry in a project follows these rules:

- **Precedence**: An explicit project RouterBridge selection suppresses the platform default; preserve its specification and let Core handle transitive dependencies.
- **Identity**: Use `PackageSpec` identity, including repository-name spelling, and inspect existing local manifests without extracting them.
  Unidentifiable remote sources use Core's explicit `Arduino_RouterBridge=<URI>` alias.
- **No second solver**: Do not add a second dependency-conflict solver or repin RPClite and MsgPack in the platform.

The pinned framework variant detects `routerbridge_provides_serial.h` and defines `ARDUINO_ROUTERBRIDGE_PROVIDES_SERIAL` before RouterBridge declares and defines its `Serial` alias.
Keep this framework/library capability check authoritative instead of forcing a platform-wide macro.
The framework's devicetree selection also owns `ARDUINO_ROUTER_SERIAL`.
Validate the default without a manual macro in multiple translation units and check that `Serial` and `Monitor` share one instance.

## Resolution without a project environment

Resolve package URLs when Core reads `packages`, including during standalone installation, updates, and removal.
In Core 6.2.0, `PlatformPackageManager.install()` calls `configure_project_packages()`, and therefore `configure_default_packages()`, only when a project environment is supplied.
Standalone `pio pkg install -g -p <platform>` and the deprecated `pio platform install <platform>` skip that hook and proceed to `install_required_packages()`.
Expanding URLs only in the project hook would therefore leave standalone installation resolving nominal version pins from the registry instead of fetching release assets.

- **Every access**: The `packages` property must also supply resolved URLs for updates and removal without a project environment.
- **Snapshot order**: The resolver snapshots the original version pins before accessing `super().packages`, which applies project overrides to the same dictionaries.
  Preserve that ordering and the override exclusions: repeated access must never reinterpret an expanded URL or a user override as a version pin.
- **Package selection**: Core's inherited `configure_default_packages()` remains responsible for framework and target package selection.

When changing resolution, verify:

- Project installation and standalone `pio pkg install -g -p <platform>` on both supported host architectures.
- Explicit `platform_packages` overrides.
- Repeated access to package metadata.
- Package lookup without a project environment, including update and removal paths.

## Library ownership and compatibility

The framework package and PlatformIO's discovery rules decide which libraries a project sees:

- **Inventory**: The framework package's export policy owns the contents of `libraries/`; do not duplicate that inventory in the platform.
- **Discovery**: Set `LIBSOURCE_DIRS` to the shared `libraries/` storage directory.
  PlatformIO discovers libraries among each storage directory's children, so listing individual library directories breaks discovery.
- **Framework identifier**: Keep the framework identifier `arduino` to retain compatibility with libraries declaring `frameworks=arduino` without requiring `lib_compat_mode=off`.
  This identifier does not guarantee that a library works with Zephyr.

The user-facing compatibility limits belong in [Environment constraints](../README.md#environment-constraints).

## MPU host package management is deferred

Consider OpenOCD packaging and version control for other host dependencies, including Arduino Router, together as a reproducibility concern.
These remain deferred options, not implemented dependencies or version requirements; Router 0.10.0 is not an established fix for test runs that intermittently receive no output at startup.

- **OpenOCD**: Consider providing a declared platform package containing a compatible executable and configuration set; retain the board-image installation until their provenance can be managed together.
- **Embedded detection**: Core normally derives embedded-platform detection from declared uploader packages; this platform uses an override so it can retain the board-image OpenOCD without declaring an uploader package.
  Preserve that detection behavior if packaging changes.
- **Arduino Router and other host packages**: First consider pinning tested versions rather than introducing platform packages for them.
