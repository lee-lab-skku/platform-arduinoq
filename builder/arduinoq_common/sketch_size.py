# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

"""Apply sketch allocations to Core's size report without changing board metadata."""

from copy import deepcopy


def check_sketch_size(_, target, source, env):
    board = deepcopy(env.BoardConfig())
    for resource in ("size", "ram_size"):
        key = "upload.maximum_sketch_" + resource
        limit = int(board.get(key))
        if limit <= 0:
            raise ValueError("%s must be positive" % key)
        board.update("upload.maximum_" + resource, limit)

    # Clone() alone does not isolate BoardConfig(): Core obtains it through
    # the shared platform object. Override that lookup only on this clone.
    check_env = env.Clone()
    check_env.AddMethod(lambda _: board, "BoardConfig")
    return check_env.CheckUploadSize(target, source, check_env)
