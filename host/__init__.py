# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

#
# Host-side helpers: code that runs inside the PlatformIO process and drives
# the attached board, as opposed to builder/, which runs inside SCons and
# only produces files.
#
# These modules are loaded by platform.py through an explicit file path, not
# through sys.path. Putting the platform root on sys.path would expose
# platform.py under the module name "platform" and shadow the standard
# library module of that name for the rest of the process.
