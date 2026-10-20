# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

"""Resolve platform library pins and preserve explicit project selections."""

from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
from urllib.parse import unquote
import zipfile

from platformio.package.meta import PackageSpec


def resolve(libraries, url_bases):
    """Expand versions without mutating platform.json or caching resolved URLs."""
    result = deepcopy(libraries)
    for name, options in result.items():
        version = options.get("version")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("Platform library %s requires a version" % name)
        if name not in url_bases:
            raise ValueError("No release URL rule for platform library %s" % name)
        options["version"] = "%s%s-%s.tar.gz" % (
            url_bases[name].format(version=version), name, version,
        )
    return result


def _identity(name):
    # Git repository names commonly use '-' where library.json uses '_'.
    return re.sub(r"[-_]", "", name or "").casefold()


def _manifest_name(filename, contents):
    if filename == "library.json":
        return json.loads(contents).get("name")
    for line in contents.splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "name":
            return value.strip()
    return None


def _local_name(path):
    """Read local manifests without extracting archives or fetching a URL."""
    try:
        if path.is_dir():
            for filename in ("library.json", "library.properties"):
                manifest = path / filename
                if manifest.is_file():
                    return _manifest_name(filename, manifest.read_text(encoding="utf-8"))
        elif path.is_file():
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as archive:
                    for name in sorted(archive.namelist(), key=lambda item: len(PurePosixPath(item).parts)):
                        filename = PurePosixPath(name).name
                        if filename in ("library.json", "library.properties"):
                            return _manifest_name(filename, archive.read(name).decode("utf-8"))
            else:
                with tarfile.open(path, "r:*") as archive:
                    for member in sorted(archive.getmembers(), key=lambda item: len(PurePosixPath(item.name).parts)):
                        filename = PurePosixPath(member.name).name
                        if member.isfile() and filename in ("library.json", "library.properties"):
                            return _manifest_name(filename, archive.extractfile(member).read().decode("utf-8"))
    except (OSError, ValueError, UnicodeError, tarfile.TarError, zipfile.BadZipFile):
        # Identification must not replace Core's normal installation diagnostic.
        pass
    return None


def merge(dependencies, libraries, project_dir):
    """Append defaults only for libraries not explicitly selected by the project.

    Arbitrary remote sources whose names do not identify the library require
    Core's name=URI syntax. Existing direct selections remain byte-for-byte
    unchanged; transitive dependency resolution stays with Library Manager.
    """
    result = list(dependencies)
    selected = set()
    for dependency in dependencies:
        spec = PackageSpec(dependency)
        name = spec.name
        if not spec.has_custom_name() and spec.uri:
            for prefix in ("file://", "symlink://"):
                if spec.uri.startswith(prefix):
                    path = Path(unquote(spec.uri[len(prefix):])).expanduser()
                    if not path.is_absolute():
                        path = Path(project_dir) / path
                    name = _local_name(path) or name
                    break
        selected.add(_identity(name))
    for name, options in libraries.items():
        if _identity(name) not in selected:
            result.append("%s=%s" % (name, options["version"]))
            selected.add(_identity(name))
    return result
