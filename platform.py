# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0


import importlib.util
import os
import re

from platformio.exception import UserSideException
from platformio.public import PlatformBase, get_systype

# Helper modules are loaded by path rather than by import. Adding the platform
# directory to sys.path would publish this file as the module "platform" and
# shadow the standard library module of the same name.
HOST_MODULE_DIR = "host"
LAYOUT_MODULE = ("builder", "arduinoq_common", "arduino_zephyr_layout.py")
LLEXT_GDB_SCRIPT = ("host", "gdb", "llext.gdb")

# The manifest carries only nominal package versions so it stays within
# PlatformIO's 100-character limit for the version field. Release locations
# and asset naming conventions belong to the platform hook; {version} always
# comes from platform.json, while {systype} is selected for the current host.
PACKAGE_URL_TEMPLATES = {
    "toolchain-gccarmzephyreabi": (
        "https://github.com/lee-lab-skku/sdk-ng/releases/download/v{version}/"
        "toolchain-gccarmzephyreabi-{systype}-{version}-leelabskku.tar.gz"
    ),
    "framework-arduino-zephyr": (
        "https://github.com/lee-lab-skku/ArduinoCore-zephyr/releases/download/"
        "{version}/framework-arduino-zephyr-{version}-leelabskku+unoq.tar.gz"
    ),
    "tool-zephyrsketch": (
        "https://github.com/lee-lab-skku/ArduinoCore-zephyr/releases/download/"
        "tools%2Fzephyr-sketch-tool%2F{version}/tool-zephyrsketch-{systype}-"
        "{version}-leelabskku.tar.gz"
    ),
    "tool-genrodatald": (
        "https://github.com/lee-lab-skku/ArduinoCore-zephyr/releases/download/"
        "tools%2Fgen-rodata-ld%2F{version}/tool-genrodatald-{systype}-{version}-"
        "leelabskku.tar.gz"
    ),
    "tool-zephyrchecksize": (
        "https://github.com/lee-lab-skku/ArduinoCore-zephyr/releases/download/"
        "tools%2Fzephyr-check-size%2F{version}/tool-zephyrchecksize-{systype}-"
        "{version}-leelabskku.tar.gz"
    ),
}

# Helper modules already loaded, keyed by absolute path. Module level rather
# than per instance: the modules hold no state, loading one twice is pure
# waste, and PlatformBase offers no __init__ hook to hang a cache on.
_LOADED_MODULES = {}

# PlatformIO's stock GDB start-up script, less two lines.
#
# "monitor init" is gone. The server this platform starts has already run
# init, and running it again halts the target a second time -- which is where
# the two consecutive "halted due to debug-request" came from.
#
# "$INIT_BREAK" is gone because it is evaluated here, while only the resident
# firmware's symbols are loaded -- so its default of "tbreak main" resolves
# against the resident firmware and stops the run to llext_bootstrap short.
# Dropping it also means a project no longer has to blank debug_init_break; a
# session stops in a defined place regardless, and another initial breakpoint
# belongs in debug_extra_cmds, which is evaluated once the sketch's symbols
# are in place.
DEBUG_INIT_CMDS = (
    "define pio_reset_halt_target",
    "monitor reset halt",
    "end",
    "define pio_reset_run_target",
    "monitor reset",
    "end",
    "target extended-remote $DEBUG_PORT",
    "$LOAD_CMDS",
    "pio_reset_halt_target",
)

class ArduinoqPlatform(PlatformBase):
    def is_embedded(self):
        # PlatformBase derives this from the presence of a package declared
        # with type "uploader", which PlatformIO then force-installs for any
        # target whose name contains "upload" -- ignoring "optional".
        #
        # PlatformIO reads this for the linker "cyclic reference" workaround
        # (--start-group/--end-group), IDE target listing, and unit-test and
        # debug session behaviour.
        return True

    def configure_default_packages(self, variables, targets):
        """Resolve the pinned package versions to host-specific release assets.

        platform.json remains the source of truth for versions but contains
        only their nominal strings, keeping the manifest valid under
        PlatformIO's version-field length limit. URL and asset conventions are
        expanded here after the manifest has been loaded.
        """
        SUPPORTED_SYSTYPES = ("linux_x86_64", "linux_aarch64")

        systype = get_systype()
        if systype not in SUPPORTED_SYSTYPES:
            raise UserSideException(
                "The '%s' platform does not support the '%s' host. Every "
                "package it installs is a Linux build; supported hosts are "
                "%s. Note that the board is flashed from the Linux MPU "
                "either way, so a non-Linux workstation can still drive this "
                "platform through remote command with '-r' option, which builds on MPU."
                % (
                    self.name,
                    systype,
                    ", ".join(sorted(SUPPORTED_SYSTYPES)),
                )
            )

        # Keep an immutable copy because PlatformBase exposes the manifest's
        # package dictionaries directly and this hook replaces their version
        # values in place. The copy also makes repeated configuration calls
        # safe.
        if not hasattr(self, "_manifest_package_versions"):
            self._manifest_package_versions = {
                name: self.manifest["packages"][name]["version"]
                for name in PACKAGE_URL_TEMPLATES
            }

        # PlatformIO applies platform_packages overrides through the same
        # dictionaries. Those are explicit user choices and must not be
        # interpreted as nominal versions from this platform's manifest.
        custom_package_names = set()
        for item in self._custom_packages or []:
            name = item.split("@", 1)[0]
            custom_package_names.add(self.pm.ensure_spec(name).name)

        packages = self.packages
        for name, template in PACKAGE_URL_TEMPLATES.items():
            if name in custom_package_names:
                continue
            packages[name]["version"] = template.format(
                version=self._manifest_package_versions[name], systype=systype
            )

        return super().configure_default_packages(variables, targets)

    # -----------------------------------------------------------------------
    # Host-side services
    #
    # Anything a project may need to do to the board outside a build is
    # reached through these, so that the board's wiring stays described in
    # one place. Both are plain methods on the platform instance, which
    # PlatformIO hands to a custom test runner as ".platform".
    # -----------------------------------------------------------------------

    def _resolve_path(self, *relative_parts):
        return os.path.join(self.get_dir(), *relative_parts)

    def _load_module(self, *relative_parts):
        path = self._resolve_path(*relative_parts)
        if path not in _LOADED_MODULES:
            stem, _ = os.path.splitext("_".join(relative_parts))
            spec = importlib.util.spec_from_file_location(
                "%s_%s" % (self.name, stem), path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _LOADED_MODULES[path] = module
        return _LOADED_MODULES[path]

    def _load_host_module(self, name):
        return self._load_module(HOST_MODULE_DIR, "%s.py" % name)

    def get_board_control(self, board_id):
        """Board operations driven through OpenOCD (reset, halt, ...).

        Usable from a project as
        ``env.PioPlatform().get_board_control(board_id).reset()``, or from a
        custom test runner through ``self.platform``.
        """
        board_control = self._load_host_module("board_control")
        return board_control.BoardControl.from_board_config(
            self.board_config(board_id)
        )

    def configure_debug_session(self, debug_config):
        """Point PlatformIO's debug session at the board's own OpenOCD.

        PlatformBase raises NotImplementedError here, which DebugConfigBase
        swallows, so without this the session would start with no server at
        all. The server is described here rather than in the board manifest
        so that it resolves the OpenOCD installation exactly as uploads and
        resets do, instead of repeating the path a third time.
        """
        env_options = debug_config.env_options
        # The project supplied its own server, or turned it off entirely.
        if "debug_server" in env_options or debug_config.server is None:
            return

        control = self.get_board_control(debug_config.board_config.id)
        debug_config.server.update(
            cwd=control.openocd_dir,
            executable=control.openocd_binary,
            arguments=control.server_arguments(
                gdb_port=self._gdb_port(debug_config)
            ),
        )

        self._add_debug_commands(debug_config)

        if not env_options.get("debug_load_cmds"):
            # "preload" is PlatformIO's way of saying "the platform loads the
            # firmware, not GDB": it runs the "upload" target before the
            # session and then clears the load commands, so GDB never issues
            # one. That is the only workable arrangement here, because what
            # gets flashed is the packed image while the ELF GDB opens is a
            # relocatable object the LLEXT loader places at run time.
            debug_config.load_cmds = ["preload"]

    @staticmethod
    def _gdb_port(debug_config):
        """The TCP port to tell OpenOCD about, when there is one at all.

        With an OpenOCD server, a GDB client and no port configured,
        PlatformIO does not open a socket: it runs the server as a pipe
        command for GDB and passes "gdb_port pipe" itself. Naming a port in
        that case would override the pipe and break the connection outright.

        A configured debug_port is exactly what turns that off, so the port is
        only worth stating when the project asked for one. It is still checked
        for being a bare number, since it may instead address a server this
        platform does not start.
        """
        configured = debug_config.env_options.get(
            "debug_port"
        ) or debug_config.tool_settings.get("port")
        if not configured:
            return None
        match = re.match(r"^:?(\d+)$", str(configured))
        return int(match.group(1)) if match else None

    def _add_debug_commands(self, debug_config):
        """Prepare the session for placing the sketch's symbols.

        The ELF PlatformIO hands to GDB is a relocatable object, so nothing in
        it sits where it will actually run. What is needed to fix that lives
        in the resident firmware: the "struct llext" type and the llext_load
        call whose out-parameter names the regions the loader allocated. Both
        are loaded here, together with the helper that reads them.

        Appended to the tool's own extra commands rather than replacing them,
        and PlatformIO concatenates the project's debug_extra_cmds after these
        in any case.
        """
        layout = self._load_module(*LAYOUT_MODULE).resolve(
            self, debug_config.board_config
        )

        if not debug_config.tool_settings.get("init_cmds"):
            debug_config.tool_settings["init_cmds"] = list(DEBUG_INIT_CMDS)

        commands = [
            # A safety net only, now that the sketch's symbols stay loaded
            # throughout. It does not help an IDE: MI's -break-insert ignores
            # this setting and fails outright unless it is given -f.
            "set breakpoint pending on",
            # The resident firmware is built with its paths rewritten relative
            # to the tree it came from. Only the part of that tree the
            # framework package ships can be pointed at; Zephyr's own sources
            # are not on the board at all, so those frames stay source-less.
            "set substitute-path ./ArduinoCore-zephyr %s" % layout.framework_dir,
            "source %s" % self._resolve_path(*LLEXT_GDB_SCRIPT),
            # Only the resident firmware for now: it is what runs until the
            # extension is started, and the sketch's own symbols would be at
            # addresses nothing occupies yet.
            #
            # Absolute: this is fed to GDB verbatim, with no shell to expand
            # a "~" along the way.
            "symbol-file %s" % layout.resident_elf,
            # Run to the extension and place its symbols here, while the init
            # script still has control. Everything an IDE does happens after
            # this file finishes, so by then the sketch's symbols are already
            # where they will stay -- which is the only arrangement that works
            # for it. Resolving breakpoints later is not enough: GDB resolves
            # a location once and then tries to insert it at that address on
            # the next resume, and an address the loader has not chosen yet
            # cannot be written, which aborts the resume outright.
            #
            # llext_bootstrap rather than llext_load: the loader reaches it
            # with the extension already loaded and named by its first
            # argument, so nothing has to be finished to see the result.
            "break llext_bootstrap",
            # Remembered so the helper can drop it before discarding the
            # symbol table it belongs to.
            "set $_aq_llext_bp = $bpnum",
            "continue",
            # $PROG_PATH is substituted by PlatformIO before GDB sees it.
            "arduinoq_loaded_sketch_symbols $PROG_PATH",
            # Left defined so the placement can be repeated by hand from any
            # stop where the extension is in scope.
            "define arduinoq_sketch",
            "arduinoq_loaded_sketch_symbols $PROG_PATH",
            "end",
            "echo \\n[arduinoq] stopped in the loader, with the sketch's "
            "symbols in place.\\n",
        ]
        debug_config.tool_settings["extra_cmds"] = (
            list(debug_config.tool_settings.get("extra_cmds") or []) + commands
        )

    def get_test_output_reader(self, test_runner):
        """Reader that collects unit-test output from this board.

        A project's test_custom_runner.py is expected to ask the platform for
        this instead of instantiating a reader itself; platforms that do not
        provide the method fall back to PlatformIO's serial reader.
        """
        board_id = test_runner.project_config.get(
            "env:%s" % test_runner.test_suite.env_name, "board"
        )
        test_reader = self._load_host_module("test_reader")
        return test_reader.ArduinoqTestOutputReader(
            test_runner,
            board_control=self.get_board_control(board_id),
            board_config=self.board_config(board_id),
        )
