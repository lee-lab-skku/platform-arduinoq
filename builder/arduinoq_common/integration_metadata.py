# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

"""Project integration metadata only; never mutate compiler construction variables."""

import os
from pathlib import Path
import warnings


class MetadataError(ValueError):
    """A response file cannot be represented reliably in integration metadata."""


def split_response(text):
    """Split GCC/libiberty response syntax, including escapes inside either quote.

    This is not shell syntax: # is literal and backslash quotes the next
    character even inside single quotes. Returned strings are argv values.
    """
    result, word = [], []
    quote = None
    escaped = started = False
    for char in text:
        if escaped:
            word.append(char)
            escaped = False
        elif char == "\\":
            escaped = started = True
        elif quote:
            if char == quote:
                quote = None
            else:
                word.append(char)
        elif char in "\"'":
            quote = char
            started = True
        elif char in " \t\r\n\v\f":
            if started:
                result.append("".join(word))
                word, started = [], False
        else:
            word.append(char)
            started = True
    if quote or escaped:
        raise MetadataError("unterminated quote or escape")
    if started:
        result.append("".join(word))
    return result


def expand_response_files(flags, cwd, stack=()):
    """Expand @files in place; nested relative names use compiler cwd, not parent.

    Repeated references are legal. Only an active recursion cycle is rejected.
    Missing/unreadable files fail metadata generation with the offending path.
    """
    result = []
    for flag in flags:
        if not flag.startswith("@"):
            result.append(flag)
            continue
        path = Path(cwd, flag[1:]).resolve()
        if path in stack:
            raise MetadataError("response file cycle: " + " -> ".join(map(str, (*stack, path))))
        try:
            arguments = split_response(path.read_text())
        except (OSError, UnicodeError, MetadataError) as exc:
            raise MetadataError(f"response file {path}: {exc}") from exc
        result.extend(expand_response_files(arguments, cwd, (*stack, path)))
    return result


def option_values(flags, options):
    """Yield attached/separate option operands in argv order."""
    index = 0
    while index < len(flags):
        flag = flags[index]
        for option in options:
            if flag == option:
                index += 1
                if index == len(flags):
                    raise MetadataError(f"missing operand for {option}")
                yield option, flags[index]
                break
            if flag.startswith(option):
                yield option, flag[len(option):]
                break
        index += 1


def macro_state(flags, defines):
    """Apply ordered -D/-U, then SCons' trailing CPPDEFINES.

    Keep explicit undefinitions (None) internally: absent and undefined differ
    for compiler built-ins. Function macro redefinitions share the base name.
    """
    state = {}
    operations = list(option_values(flags, ("-D", "-U")))
    operations.extend(("-D", define) for define in defines)
    for option, value in operations:
        name = value.split("=", 1)[0].split("(", 1)[0]
        state[name] = value if option == "-D" else None
    return state


def include_paths(flags, existing, cwd):
    """Resolve prefix includes after all ordinary -I paths, as GCC does.

    Concatenate prefix and suffix literally (a leading slash is not absolute
    here). Keep nonexistent directories; metadata describes configured inputs.
    """
    ordinary, prefixed = [], []
    prefix = None
    for option, value in option_values(flags, ("-iprefix", "-iwithprefixbefore", "-I")):
        if option == "-iprefix":
            prefix = value
        elif option == "-I":
            ordinary.append(value)
        else:
            if prefix is None:
                raise MetadataError("-iwithprefixbefore requires an explicit -iprefix")
            prefixed.append(prefix + value)
    paths = ordinary + list(existing) + prefixed
    return list(dict.fromkeys(os.path.abspath(os.path.join(cwd, path)) for path in paths))


def enrich_metadata(data, cwd, warn=None):
    """Return a copy of Core metadata with expanded language flags and common fields.

    Common defines contain only equal final C/C++ definitions. Language flags
    keep every operation, including -U and the trailing Core definitions, so
    clients that consume flags retain each language's exact macro ordering.
    Header contents deliberately remain in -imacros/-include, never defines.
    """
    if warn is None:
        warn = lambda message: warnings.warn(message, UserWarning, stacklevel=2)
    result = dict(data)
    states, paths = [], []
    defines = data.get("defines", [])
    for key in ("cc_flags", "cxx_flags"):
        flags = expand_response_files(data.get(key, []), cwd)
        states.append(macro_state(flags, defines))
        paths.append(include_paths(flags, data["includes"].get("build", []), cwd))
        result[key] = flags + ["-D" + define for define in defines]
    c, cpp = states
    # -DNAME and -DNAME=1 are equivalent, but preserve the original spelling.
    def normalized(value):
        return value + "=1" if value is not None and "=" not in value else value
    result["defines"] = [value for name, value in c.items()
                         if value is not None and name in cpp
                         and normalized(value) == normalized(cpp[name])]
    differences = [name for name in c.keys() | cpp.keys()
                   if name not in c or name not in cpp
                   or normalized(c[name]) != normalized(cpp[name])]
    if differences:
        warn("Arduino Q metadata: common defines cannot represent C/C++ differences: "
             + ", ".join(sorted(differences)) + "; use the language flags.")
    if paths[0] != paths[1]:
        warn("Arduino Q metadata: common includes cannot represent C/C++ search differences; "
             "use the language flags.")
    result["includes"] = dict(data["includes"])
    result["includes"]["build"] = list(dict.fromkeys(paths[0] + paths[1]))
    return result
