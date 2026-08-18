# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

#
# Placing a sketch's symbols at the addresses the LLEXT loader chose.
#
# The sketch is linked relocatable: its sections sit at offsets from zero and
# the loader allocates one region per section group at run time, so the ELF
# alone tells GDB nothing about where anything ended up. The regions are read
# out of the resident firmware's own "struct llext" once it exists.
#
# This intercepts llext_bootstrap rather than scanning SRAM for the extension's
# name. Scanning has to assume both a struct layout (which CONFIG_USERSPACE
# changes) and an enum ordering (which CONFIG_LLEXT_VENEERS changes), and it
# reads whatever the previous boot left behind. Reading the "ext" argument at
# a breakpoint the loader itself reaches after loading assumes neither, and
# cannot see a stale value. A breakpoint on llext_load works the same way but
# one step earlier, while "ext" is still an out-parameter the call has not
# written yet; see arduinoq_load_sketch_symbols below for why that entry point
# exists separately.
#
# The resident firmware's symbols must be loaded when this runs; the platform
# arranges that, along with the breakpoint on llext_bootstrap.

# Number of that breakpoint, so it can be dropped before its symbol table
# goes away. The platform overwrites this right after setting it; the default
# keeps the helper usable when this file is sourced on its own.
set $_aq_llext_bp = 0

define arduinoq_sketch_regions
  if $argc != 0
    echo usage: arduinoq_sketch_regions\n
  else
    printf "  .text                  0x%08x  %8u bytes\n", \
        $_aq_ext->mem[LLEXT_MEM_TEXT], $_aq_ext->mem_size[LLEXT_MEM_TEXT]
    printf "  .rodata                0x%08x  %8u bytes\n", \
        $_aq_ext->mem[LLEXT_MEM_RODATA], $_aq_ext->mem_size[LLEXT_MEM_RODATA]
    printf "  .bss                   0x%08x  %8u bytes\n", \
        $_aq_ext->mem[LLEXT_MEM_BSS], $_aq_ext->mem_size[LLEXT_MEM_BSS]
    printf "  .llext.rodata.noreloc  0x%08x  %8u bytes\n", \
        $_aq_ext->mem[LLEXT_MEM_RODATA_NO_RELOC], \
        $_aq_ext->mem_size[LLEXT_MEM_RODATA_NO_RELOC]
  end
end

document arduinoq_sketch_regions
Print the memory regions the LLEXT loader allocated for the sketch.
Only meaningful after arduinoq_loaded_sketch_symbols has captured them.
end

# Placement itself, given $_aq_ext already points at the loaded extension.
# Kept separate from how that pointer was obtained: the two entry points
# below differ only in that, and one of them must not resume execution.
# No argument check here, deliberately: both entry points validate before
# calling, and wrapping this whole body in an "else" to make a check do
# anything would buy nothing.
define arduinoq_place_sketch_symbols
  # Capture as plain integers before dropping the symbol table: the values
  # would otherwise keep a type that is about to disappear.
  set $_aq_text = (unsigned long)$_aq_ext->mem[LLEXT_MEM_TEXT]
  set $_aq_rodata = (unsigned long)$_aq_ext->mem[LLEXT_MEM_RODATA]
  set $_aq_bss = (unsigned long)$_aq_ext->mem[LLEXT_MEM_BSS]
  set $_aq_noreloc = (unsigned long)$_aq_ext->mem[LLEXT_MEM_RODATA_NO_RELOC]

  echo \n[arduinoq] extension loaded, regions:\n
  arduinoq_sketch_regions

  set confirm off
  # The breakpoint cannot survive its symbol table, and it has already done
  # its job.
  if $_aq_llext_bp != 0
    delete $_aq_llext_bp
    set $_aq_llext_bp = 0
  end

  # Drop the resident firmware's symbols along with the copy of the sketch
  # that PlatformIO passed on the command line, which sits at address zero.
  # Keeping either one would shadow what is added next.
  symbol-file

  # The path goes into the format string rather than through %s: GDB
  # substitutes $arg0 textually before parsing the line, so it arrives as a
  # bare word, and eval's arguments have to be expressions.
  #
  # The positional address is the .text region; every other section is offset
  # by the same amount, which is what .data needs since the loader keeps it
  # inside the text allocation. The regions that get their own allocation are
  # named explicitly.
  eval "add-symbol-file $arg0 0x%lx -s .rodata 0x%lx -s .bss 0x%lx -s .llext.rodata.noreloc 0x%lx", \
      $_aq_text, $_aq_rodata, $_aq_bss, $_aq_noreloc

  # Dropping the symbol table disabled every breakpoint that could not be
  # re-set at the time, and re-adding it fixes the address but not the
  # enabled flag. Without this they sit at the right place and never fire.
  enable
  set confirm on

  echo \n[arduinoq] sketch symbols placed. Breakpoints by file and line work from here.\n
end

document arduinoq_place_sketch_symbols
Place the sketch's symbols at their run-time addresses.
Usage: arduinoq_place_sketch_symbols <path to firmware_debug.elf>
Expects $_aq_ext to point at the loaded extension; use one of the entry
points below instead of calling this directly.
end

# Entry point for a breakpoint on llext_load, which is reached before the
# extension exists: the call has to be finished first.
#
# Resuming execution rules this out of a breakpoint command list -- GDB stops
# reading such a list at the first command that resumes -- so it is meant to
# be typed at the prompt, or in an IDE's debug console.
define arduinoq_load_sketch_symbols
  if $argc != 1
    echo usage: arduinoq_load_sketch_symbols <path to firmware_debug.elf>\n
  else
    # "ext" is llext_load's out-parameter, still unwritten at this point.
    # Taken by name rather than from $r2: the DWARF is intact, so this
    # survives a change of calling convention or of optimisation level,
    # whereas the register only holds the argument until it is spilled.
    set $_aq_ext_out = ext
    finish
    set $_aq_ext = *$_aq_ext_out
    arduinoq_place_sketch_symbols $arg0
  end
end

document arduinoq_load_sketch_symbols
Finish llext_load, then place the sketch's symbols at their run-time
addresses. Usage: arduinoq_load_sketch_symbols <path to firmware_debug.elf>
Run while stopped at the llext_load breakpoint.
end

# Entry point for a breakpoint on a function that receives the extension
# after it has been loaded, such as llext_bringup or llext_bootstrap. Nothing
# here resumes execution, so this one can go in a breakpoint command list and
# run without anyone typing it.
define arduinoq_loaded_sketch_symbols
  if $argc != 1
    echo usage: arduinoq_loaded_sketch_symbols <path to firmware_debug.elf>\n
  else
    set $_aq_ext = ext
    arduinoq_place_sketch_symbols $arg0
  end
end

document arduinoq_loaded_sketch_symbols
Place the sketch's symbols at their run-time addresses, from a stop where
the extension is already loaded and named by an "ext" argument.
Usage: arduinoq_loaded_sketch_symbols <path to firmware_debug.elf>
end
