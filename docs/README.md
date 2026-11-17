# Developer documentation

These documents record the contracts that contributors must preserve across files or execution environments, grouped by subsystem.
They also record design reasoning and failed approaches whose causes would otherwise need to be rediscovered.
[CONTRIBUTING.md](../CONTRIBUTING.md) covers development setup and validation; [README.md](../README.md) covers user-facing behavior.

- [Board operations](board-operations.md): Board control targets, sketch startup, reset and Router coordination, board integration constraints, and OpenOCD output.
- [Build and link](build.md): C++ runtime linking and sketch capacity, which package updates must keep aligned; framework paths outside a build, remote targets, and integration metadata.
- [Debugging](debugging.md): Session-local resident symbols, placing the relocatable sketch's symbols during GDB initialization, and the PlatformIO session defaults the platform replaces.
- [Packages and libraries](packages-and-libraries.md): Package and library version ownership, resolution without a project environment, framework library discovery, and deferred MPU host package management.
