# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

#
# Plain Python helpers shared across this platform. Nothing in this package
# may import SCons or touch a build environment: these modules must stay
# usable from any build phase -- including upload-only sessions where no
# compilation happens at all -- and from the PlatformIO process, where the
# modules under host/ run and SCons does not exist.
#
# The package name is deliberately platform-specific. It is reached by
# putting builder/ on sys.path, which publishes it process-wide.
