# Debugging

This document covers the contracts that let GDB debug a relocatable sketch loaded at run time by the resident firmware.
They cover the session-local resident symbols, placing the sketch's symbols during GDB initialization, and the PlatformIO session defaults the platform replaces.

## Debug symbols must use loader allocations

GDB reads a session-local copy of the resident firmware and places the sketch at the regions the loader allocated.

- **Resident copy**: Prepare a session-local resident ELF with `text` renamed to `.text` before GDB reads it to avoid the GDB 16.2 breakpoint crash observed with the packaged resident ELF.
  Preserve loadable addresses/bytes and DWARF, leave the package resident immutable, and keep the temporary ELF alive across Core's pre-debug rebuild/upload.
- **Uploads and cleanup**: The upload path must continue using the original resident, and session cleanup must remove the temporary copy.
- **Section addresses**: Read section addresses from the resident firmware's `struct llext` and enum names before replacing its symbol table.
- **Initialized data**: Keep `.data` distinct from `.text`: LLEXT allocates initialized data separately, and GDB leaves omitted sections at their original ELF addresses.

Validate an initialized global's value and address as well as a local variable and a file/line breakpoint; reading a zero-initialized `.bss` global alone does not check `.data` placement.
Cover both automatic build/upload and loading existing artifacts, including symbol relocation after reset.

## Symbol placement must finish in the init script

`configure_debug_session()` in `platform.py` appends the placement sequence to the effective `debug_init_cmds` after resolving project and tool overrides, so placement completes before the project's and tool's extra commands.
The sequence takes these steps:

1. Load the session-local resident ELF.
1. Source `host/gdb/llext.gdb`.
1. Stop at `llext_bootstrap`, recording the breakpoint's number in `$_aq_llext_bp`.
1. Call `arduinoq_loaded_sketch_symbols` with the sketch's debug ELF.
   The helper deletes the recorded breakpoint before discarding the resident symbol table it belongs to, and then re-enables breakpoints that the symbol table change disabled.

`arduinoq_sketch` repeats the sequence after a reset by loading the resident symbols again first.
Debug builds start the sketch in `immediate` boot mode so that reaching this stop does not depend on Linux startup timing, as [Sketch startup](board-operations.md#sketch-startup-is-an-artifact-and-host-coordination-contract) explains.

The design rests on these reasons:

- **Inside the init script**: GDB resolves a breakpoint location once and inserts it at that address on the next resume; an address the loader has not chosen yet cannot be written, and the resume aborts.
  An IDE sets its breakpoints after the init script, so they resolve against the placed symbols.
- **At `llext_bootstrap`**: The loader reaches it with the extension already loaded and named by its `ext` argument.
- **Not at `llext_load`**: A stop there sees `ext` as an unwritten out-parameter, so `arduinoq_load_sketch_symbols` must finish the call first.
  That resumes the target, and GDB stops reading a breakpoint command list at the first resuming command, so this entry point serves only manual use.
- **Not by scanning SRAM**: Scanning for the extension's name assumes a struct layout that `CONFIG_USERSPACE` changes and an enum order that `CONFIG_LLEXT_VENEERS` changes.
  It can also read a stale value from the previous boot.

## Session commands must replace PlatformIO defaults that do not fit

The platform supplies these session settings in place of PlatformIO's defaults:

- **Initialization**: The default init commands omit PlatformIO's `monitor init`, because the debug server has already run `init` and a second one halts the target again.
  A project-supplied server must also run `init` before GDB connects.
- **Initial breakpoint**: `$INIT_BREAK` moves after symbol placement, where a project's `debug_init_break` resolves against the sketch rather than the resident firmware.
  Without a project value it is cleared: PlatformIO resumes whenever an initial breakpoint is set, which would run the sketch past the loader stop.
- **Loading**: `debug_load_cmds` defaults to `preload`, so Core runs the platform's upload before the session and GDB issues no `load`.
  GDB's `load` would write the relocatable object's zero-based sections over the resident firmware.
- **Restart**: The platform defines `pio_restart_target` as a halted reset followed by `arduinoq_sketch`.
  PlatformIO's default restart only resets and steps, which leaves the symbols at the previous run's addresses.
- **Server**: Without a project `debug_server`, the server is the board's OpenOCD resolved as uploads and resets resolve it.
  State a GDB port only when the project configured one.
  Without one, Core runs the server as a GDB pipe command, and a named port would break that connection.

Arguments pass through several layers, and each needs its own quoting.
The server's output also stays unobserved, as [OpenOCD output](board-operations.md#reset-notices) requires.

| Argument | Reader | Rule |
| --- | --- | --- |
| Debug server arguments | Core, which may flatten the invocation into one pipe command that wraps each argument in double quotes | Contain no double quotes |
| Router command paths in OpenOCD arguments | The same flattened command, then Jim Tcl | `router_control.py` encodes them as Jim Tcl `format` character codes |
| Sketch path for the GDB helper | The helper's `eval`, which uses a double-quoted format string | Pass it in single quotes |

Validate startup changes with and without a project `debug_init_break`, after a session restart and after `arduinoq_sketch`, and with a project-supplied `debug_server`.
