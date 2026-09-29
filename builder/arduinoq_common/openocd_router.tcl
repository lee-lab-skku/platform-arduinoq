# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

# Keep target reset events and the output observer intact. This procedure is
# called by OpenOCD's reset command, including resets from framework scripts
# and GDB. Loading before init also covers reset processing during init.
rename ocd_process_reset arduinoq_process_reset
proc ocd_process_reset {mode} {
	set held_mode $mode
	if {$mode eq "run"} {set held_mode halt}
	arduinoq_process_reset $held_mode
	# The native reset must succeed before touching the Router. A failed
	# reconnect must propagate without resuming, even for a requested run.
	# exec uses a Tcl list, not a shell; paths retain their argument boundaries.
	eval exec $::arduinoq_router_command
	if {$mode eq "run"} {resume}
}
