# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

"""Board operation names and selection rules shared by Core and SCons."""

TARGETS = {
    "reset": "Reset the MCU and let it run (without releasing app startup)",
    "halt": "Reset the MCU and hold it halted",
    "release": "Release a sketch waiting in the app startup loader",
}


def control_target(targets):
    """Return the requested operation, rejecting ambiguous combinations."""
    requested = set(targets)
    operations = requested.intersection(TARGETS)
    if not operations:
        return None
    if len(operations) != 1 or requested - operations - {"nobuild"}:
        raise ValueError(
            "Request exactly one board control target (reset, halt, release), "
            "optionally with nobuild; other targets must run in separate commands."
        )
    return next(iter(operations))
