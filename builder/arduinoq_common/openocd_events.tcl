# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

# Observe the framework's decisions without replacing its flash script.
# echo uses OpenOCD's log destination, including the framework's log_output.
rename flash arduinoq_native_flash
proc flash {args} {
	set operation [lindex $args 0]
	set filename_index 1
	if {$operation eq "write_image"} {
		while {[lindex $args $filename_index] eq "erase" || [lindex $args $filename_index] eq "unlock"} {
			incr filename_index
		}
	}
	set part ""
	if {$operation eq "verify_image" || $operation eq "write_image"} {
		set filename [lindex $args $filename_index]
		if {[info exists ::filename0] && $filename eq $::filename0} {
			set part resident
		} elseif {[info exists ::filename1] && $filename eq $::filename1} {
			set part sketch
		}
	}
	if {$part ne ""} {
		if {$operation eq "verify_image"} {
			echo "__ARDUINOQ_OPENOCD__ verify-begin $part"
		} else {
			echo "__ARDUINOQ_OPENOCD__ write $part"
		}
	}

	# Native command groups dispatch using argv[0]: calling the renamed
	# command directly would look for an arduinoq_native_flash command group.
	# Restore its name during dispatch, then reinstall the observer even on
	# errors. uplevel and list construction preserve scope and argument bounds.
	rename flash arduinoq_flash_observer
	rename arduinoq_native_flash flash
	set code [catch {uplevel 1 [linsert $args 0 flash]} result]
	rename flash arduinoq_native_flash
	rename arduinoq_flash_observer flash

	if {$part ne "" && $operation eq "verify_image"} {
		echo "__ARDUINOQ_OPENOCD__ verify-end $part $code"
	}
	# Jim Tcl does not support Tcl's return -options form.
	return -code $code $result
}

# OpenOCD registers the native reset command during init, so an observer
# loaded before the framework script cannot wrap reset immediately.
# Install after a successful init (or now if init has already run), without
# changing the framework's initialization order or replacing target events.
proc arduinoq_observe_reset {} {
	if {[llength [info commands arduinoq_native_reset]] != 0 || [llength [info commands reset]] == 0} {return}
	rename reset arduinoq_native_reset
	proc reset {args} {
		set mode [lindex $args 0]
		if {[llength $args] == 0} {set mode run}
		echo "__ARDUINOQ_OPENOCD__ reset-begin $mode"
		rename reset arduinoq_reset_observer
		rename arduinoq_native_reset reset
		set code [catch {uplevel 1 [linsert $args 0 reset]} result]
		rename reset arduinoq_native_reset
		rename arduinoq_reset_observer reset
		echo "__ARDUINOQ_OPENOCD__ reset-end $mode $code"
		return -code $code $result
	}
}

rename init arduinoq_native_init
proc init {args} {
	rename init arduinoq_init_observer
	rename arduinoq_native_init init
	set code [catch {uplevel 1 [linsert $args 0 init]} result]
	rename init arduinoq_native_init
	rename arduinoq_init_observer init
	if {$code == 0} {arduinoq_observe_reset}
	return -code $code $result
}
arduinoq_observe_reset
