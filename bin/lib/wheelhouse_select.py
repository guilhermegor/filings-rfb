"""Select, pack and assemble the offline wheelhouse (blueprintx#299, pieces 2-3).

Invoked by ``bin/build_wheelhouse.sh``, which owns the network I/O (``poetry export``,
``pip download``); everything here is pure file/data manipulation, which is why it lives in
a file its own tooling can lint and test rather than a shell heredoc (see ``bin/CLAUDE.md``,
"The lib's Python companions").

Three subcommands, one per piece:

``select``
    Evaluate each exported requirement's PEP 508 marker against a TARGET environment
    (python/platform/implementation), not the build machine's. ``pip download --platform``
    does not do this — it evaluates markers against the CURRENT interpreter and silently
    takes the wrong platform-specific pin (blueprintx#299's ``pywin32`` example). Also drops
    any package named by ``--drop`` (the DB_BACKEND driver-pruning step).

``pack``
    Zip a wheels directory, split it into fixed-size parts, and write a manifest recording
    each part's sha256 plus the whole archive's sha256 — the data an ``assemble`` on another
    machine needs to refuse a truncated transfer instead of writing a corrupt zip whose only
    symptom is "End-of-central-directory signature not found".

``assemble``
    The install-side counterpart. Accepts loose wheels, a single unmanifested zip, or a
    manifest + split parts — REFUSES on a part-count or sha256 mismatch rather than writing
    a truncated wheelhouse.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile


_RE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
_RE_NORMALIZE = re.compile(r"[-_.]+")
_INT_CHUNK_BYTES = 1024 * 1024
_MANIFEST_SCHEMA_VERSION = 1
_INT_FULL_VERSION_PARTS = 3
_OS_BY_SYS_PLATFORM = {
    "win32": {"os_name": "nt", "platform_system": "Windows"},
    "linux": {"os_name": "posix", "platform_system": "Linux"},
    "darwin": {"os_name": "posix", "platform_system": "Darwin"},
}


def normalize(str_name: str) -> str:
    """Return the PEP 503 normalized form of a distribution name.

    Parameters
    ----------
    str_name : str
        A distribution name, any casing/separator style.

    Returns
    -------
    str
        Lowercased, with runs of ``-``/``_``/``.`` collapsed to a single ``-``.
    """
    return _RE_NORMALIZE.sub("-", str_name).lower()


def sha256_of(path_file: Path) -> str:
    """Return the hex sha256 digest of a file, read in fixed-size chunks.

    Parameters
    ----------
    path_file : Path
        File to digest.

    Returns
    -------
    str
        Hex-encoded sha256 digest.
    """
    obj_hash = hashlib.sha256()
    with path_file.open("rb") as file_in:
        for bytes_chunk in iter(lambda: file_in.read(_INT_CHUNK_BYTES), b""):
            obj_hash.update(bytes_chunk)
    return obj_hash.hexdigest()


_IMPLEMENTATION_NAMES = {
    "cpython": "CPython",
    "pypy": "PyPy",
    "jython": "Jython",
    "ironpython": "IronPython",
}


def _canonical_implementation(str_implementation: str) -> str:
    """Map a lowercase implementation key to the spelling PEP 508 markers compare against.

    ``str.capitalize()`` yields ``Cpython``, and ``platform_python_implementation ==
    "CPython"`` is then False — so every CPython-only requirement silently leaves the
    wheelhouse. An unknown key is returned unchanged rather than guessed at: a wrong
    canonical spelling is the same silent-drop failure this function exists to prevent.

    Parameters
    ----------
    str_implementation : str
        Implementation key, e.g. ``cpython``.

    Returns
    -------
    str
        The canonical spelling, or the input unchanged when it is not known.
    """
    return _IMPLEMENTATION_NAMES.get(str_implementation.lower(), str_implementation)


def target_environment(
    str_python_version: str,
    str_sys_platform: str,
    str_platform_machine: str,
    str_implementation: str,
) -> dict[str, str]:
    """Build a PEP 508 marker environment for a TARGET machine, not this one.

    Parameters
    ----------
    str_python_version : str
        Target Python version, e.g. ``"3.11"`` or ``"3.11.4"``.
    str_sys_platform : str
        Target ``sys.platform`` value, e.g. ``"win32"``, ``"linux"``, ``"darwin"``.
    str_platform_machine : str
        Target ``platform.machine()`` value, e.g. ``"x86_64"``, ``"AMD64"``.
    str_implementation : str
        Target Python implementation, e.g. ``"cpython"``.

    Returns
    -------
    dict of str to str
        An environment mapping suitable for ``packaging.markers.Marker.evaluate``.
    """
    dict_default = {"os_name": "posix", "platform_system": "Linux"}
    dict_os = _OS_BY_SYS_PLATFORM.get(str_sys_platform, dict_default)
    list_parts_version = str_python_version.split(".")
    str_full = str_python_version
    if len(list_parts_version) < _INT_FULL_VERSION_PARTS:
        str_full = f"{str_python_version}.0"
    str_short = ".".join(list_parts_version[:2])
    return {
        "python_version": str_short,
        "python_full_version": str_full,
        "sys_platform": str_sys_platform,
        "platform_machine": str_platform_machine,
        "platform_python_implementation": _canonical_implementation(str_implementation),
        "implementation_name": str_implementation.lower(),
        "implementation_version": str_full,
        "platform_release": "",
        "platform_version": "",
        "os_name": dict_os["os_name"],
        "platform_system": dict_os["platform_system"],
    }


def requirement_matches_target(str_line: str, dict_env: dict[str, str]) -> bool:
    """Return whether a requirement line's marker applies to the TARGET environment.

    Parameters
    ----------
    str_line : str
        One exported requirement line, possibly carrying a ``; marker`` suffix.
    dict_env : dict of str to str
        The target environment, from :func:`target_environment`.

    Returns
    -------
    bool
        ``True`` when there is no marker, or the marker evaluates true for ``dict_env``.
    """
    str_marker = str_line.split(";", 1)[1].strip() if ";" in str_line else ""
    if not str_marker:
        return True
    from packaging.markers import Marker

    return bool(Marker(str_marker).evaluate(environment=dict_env))


def select_requirements(args: argparse.Namespace) -> int:
    """Filter an exported requirements file down to what the TARGET actually needs.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed ``select`` arguments (``requirements``, ``out``, target fields, ``drop``).

    Returns
    -------
    int
        0 on success. Always succeeds; an empty target set is a valid answer.
    """
    dict_env = target_environment(
        args.target_python_version,
        args.target_sys_platform,
        args.target_platform_machine,
        args.target_implementation,
    )
    set_drop = {normalize(str_name) for str_name in args.drop}
    list_kept: list[str] = []
    for str_line in Path(args.requirements).read_text(encoding="utf-8").splitlines():
        str_stripped = str_line.strip()
        if not str_stripped or str_stripped.startswith("#"):
            continue
        cls_match = _RE_NAME.match(str_stripped)
        if cls_match and normalize(cls_match.group(0)) in set_drop:
            continue
        if requirement_matches_target(str_stripped, dict_env):
            list_kept.append(str_stripped.split(";", 1)[0].strip())

    str_suffix = "\n" if list_kept else ""
    Path(args.out).write_text("\n".join(list_kept) + str_suffix, encoding="utf-8")
    str_target = f"{dict_env['sys_platform']}/{dict_env['python_version']}"
    print(f"selected {len(list_kept)} requirement(s) for {str_target}")
    return 0


def build_zip(dir_wheels: Path, path_zip: Path) -> None:
    """Zip every wheel in a directory into one archive, in a deterministic order.

    Parameters
    ----------
    dir_wheels : Path
        Directory holding the downloaded ``*.whl`` files.
    path_zip : Path
        Archive to create.

    Raises
    ------
    SystemExit
        When ``dir_wheels`` holds no wheels — an empty payload is never a valid build.
    """
    list_wheels = sorted(dir_wheels.glob("*.whl"))
    if not list_wheels:
        raise SystemExit(f"wheelhouse pack: no *.whl files found in {dir_wheels}")
    list_other = sorted(p.name for p in dir_wheels.iterdir() if p.is_file() and p.suffix != ".whl")
    if list_other:
        raise SystemExit(
            f"wheelhouse pack: {len(list_other)} download(s) are not wheels "
            f"({', '.join(list_other)}) — no matching wheel exists for the target; set "
            "WHEELHOUSE_PIP_PLATFORM/ABI or pin a version that ships one"
        )
    with zipfile.ZipFile(path_zip, "w", zipfile.ZIP_DEFLATED) as zip_out:
        for path_wheel in list_wheels:
            zip_out.write(path_wheel, arcname=path_wheel.name)


def split_into_parts(path_file: Path, int_part_mb: int) -> list[Path]:
    """Split a file into fixed-size ``<name>.NNN`` parts, in order.

    Parameters
    ----------
    path_file : Path
        File to split; left untouched.
    int_part_mb : int
        Part size, in megabytes.

    Returns
    -------
    list of Path
        The created part files, in the order they must be concatenated back.
    """
    if int_part_mb < 1:
        raise SystemExit(f"part size must be a positive number of MB, got {int_part_mb}")
    int_part_bytes = int_part_mb * 1024 * 1024
    list_parts: list[Path] = []
    with path_file.open("rb") as file_in:
        int_index = 0
        while bytes_chunk := file_in.read(int_part_bytes):
            path_part = path_file.with_name(f"{path_file.name}.{int_index:03d}")
            path_part.write_bytes(bytes_chunk)
            list_parts.append(path_part)
            int_index += 1
    return list_parts


def pack_wheelhouse(args: argparse.Namespace) -> int:
    """Zip, split and manifest a wheels directory into a transferable payload.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed ``pack`` arguments (``wheels_dir``, ``zip_path``, ``manifest``, ``part_size_mb``).

    Returns
    -------
    int
        0 on success.
    """
    dir_wheels = Path(args.wheels_dir)
    path_zip = Path(args.zip_path)
    path_zip.parent.mkdir(parents=True, exist_ok=True)
    build_zip(dir_wheels, path_zip)
    for path_stale in path_zip.parent.glob(f"{path_zip.name}.[0-9][0-9][0-9]"):
        path_stale.unlink()

    list_wheel_names = sorted(path_wheel.name for path_wheel in dir_wheels.glob("*.whl"))
    int_wheel_count = len(list_wheel_names)
    str_zip_sha256 = sha256_of(path_zip)
    int_zip_size = path_zip.stat().st_size
    list_parts = split_into_parts(path_zip, args.part_size_mb)
    path_zip.unlink()

    dict_manifest = {
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "wheel_count": int_wheel_count,
        "wheel_names": list_wheel_names,
        "zip_name": path_zip.name,
        "zip_sha256": str_zip_sha256,
        "zip_size": int_zip_size,
        "part_size_mb": args.part_size_mb,
        "part_count": len(list_parts),
        "parts": [
            {
                "name": path_part.name,
                "sha256": sha256_of(path_part),
                "size": path_part.stat().st_size,
            }
            for path_part in list_parts
        ],
    }
    Path(args.manifest).write_text(json.dumps(dict_manifest, indent=2) + "\n", encoding="utf-8")
    int_part_count = len(list_parts)
    str_summary = f"{int_wheel_count} wheel(s) into {int_part_count} part(s), {int_zip_size} bytes"
    print(f"packed {str_summary}")
    return 0


def _contained_path(dir_base: Path, str_name: str) -> Path:
    """Resolve ``str_name`` under ``dir_base``, refusing anything that escapes it.

    The manifest is transferred alongside the parts it describes, so it is untrusted
    input: ``Path(base) / "/etc/passwd"`` discards the base entirely, and
    ``"../../x"`` walks out of it. The sha256 fields authenticate CONTENT, never the
    path, so a crafted manifest could otherwise make the assembler read, overwrite or
    unlink a file outside the transfer directory.

    Parameters
    ----------
    dir_base : Path
        Directory every manifest-named file must stay inside.
    str_name : str
        Untrusted file name taken from the manifest.

    Returns
    -------
    Path
        The resolved path, guaranteed to be under ``dir_base``.

    Raises
    ------
    SystemExit
        When the name is absolute or resolves outside ``dir_base``.
    """
    path_resolved = (dir_base / str_name).resolve()
    dir_resolved = dir_base.resolve()
    if not path_resolved.is_relative_to(dir_resolved):
        raise SystemExit(
            f"wheelhouse assemble: manifest entry {str_name!r} escapes {dir_resolved} "
            f"— REFUSING, a manifest may only name files inside the transfer directory"
        )
    return path_resolved


def verify_parts(dir_source: Path, dict_manifest: dict) -> list[Path]:
    """Verify every manifest-listed part is present with a matching sha256.

    Parameters
    ----------
    dir_source : Path
        Directory expected to hold the transferred part files.
    dict_manifest : dict
        Manifest written by :func:`pack_wheelhouse`.

    Returns
    -------
    list of Path
        The verified part paths, in manifest order.

    Raises
    ------
    SystemExit
        On a missing part, a part-count mismatch, or a sha256 mismatch — REFUSES rather
        than reassembling a truncated or corrupt transfer.
    """
    list_expected = dict_manifest["parts"]
    int_declared = dict_manifest.get("part_count")
    if int_declared is not None and int_declared != len(list_expected):
        raise SystemExit(
            f"wheelhouse assemble: manifest declares {int_declared} part(s) but lists "
            f"{len(list_expected)} — REFUSING, the manifest disagrees with itself"
        )
    list_paths = [_contained_path(dir_source, dict_part["name"]) for dict_part in list_expected]
    list_missing = [str(path_part) for path_part in list_paths if not path_part.is_file()]
    if list_missing:
        str_names = ", ".join(list_missing)
        int_missing = len(list_missing)
        int_expected = len(list_expected)
        raise SystemExit(
            f"wheelhouse assemble: missing {int_missing}/{int_expected} part(s): {str_names}"
        )
    for path_part, dict_part in zip(list_paths, list_expected, strict=True):
        str_actual = sha256_of(path_part)
        if str_actual != dict_part["sha256"]:
            raise SystemExit(
                f"wheelhouse assemble: sha256 mismatch for {path_part.name} "
                f"(expected {dict_part['sha256']}, got {str_actual}) — refusing a corrupt transfer"
            )
    return list_paths


def reassemble_zip(list_parts: list[Path], dict_manifest: dict, path_zip_out: Path) -> None:
    """Concatenate verified parts and refuse if the whole file's sha256 disagrees.

    Parameters
    ----------
    list_parts : list of Path
        Verified parts, in manifest order (see :func:`verify_parts`).
    dict_manifest : dict
        Manifest written by :func:`pack_wheelhouse`.
    path_zip_out : Path
        Where to write the reassembled archive.

    Raises
    ------
    SystemExit
        When the reassembled file's sha256 does not match ``dict_manifest["zip_sha256"]``.
    """
    with path_zip_out.open("wb") as file_out:
        for path_part in list_parts:
            file_out.write(path_part.read_bytes())
    str_actual = sha256_of(path_zip_out)
    if str_actual != dict_manifest["zip_sha256"]:
        raise SystemExit(
            f"wheelhouse assemble: reassembled zip sha256 mismatch "
            f"(expected {dict_manifest['zip_sha256']}, got {str_actual})"
        )


def unzip_wheels(path_zip: Path, dir_out: Path) -> int:
    """Extract every ``*.whl`` member of a zip into a directory.

    Parameters
    ----------
    path_zip : Path
        Archive to extract.
    dir_out : Path
        Destination directory, created if missing.

    Returns
    -------
    int
        How many wheels were extracted.
    """
    dir_out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path_zip) as zip_in:
        list_names = [str_name for str_name in zip_in.namelist() if str_name.endswith(".whl")]
        for str_name in list_names:
            (dir_out / Path(str_name).name).write_bytes(zip_in.read(str_name))
    return len(list_names)


def _remove_loose_wheels(dir_out: Path) -> None:
    """Delete every ``*.whl`` in a directory, so none can sit beside a fresh extraction.

    Parameters
    ----------
    dir_out : Path
        Output directory; a missing one is a no-op.
    """
    for path_wheel in dir_out.glob("*.whl"):
        path_wheel.unlink()


def _loose_wheels_match_manifest(path_manifest: Path, list_loose: list[str]) -> bool:
    """Return whether loose wheels in the output dir may stand in for the verified payload.

    Parameters
    ----------
    path_manifest : Path
        The payload manifest; absent means there is nothing to compare against.
    list_loose : list of str
        File names of the ``*.whl`` files already sitting in the output directory.

    Returns
    -------
    bool
        False when the manifest names different wheels: a leftover or half-extracted
        ``wheels/`` — including N wheels from another lock — must not shadow the fresh
        payload. A manifest written before ``wheel_names`` existed falls back to comparing
        ``wheel_count`` alone.
    """
    if not path_manifest.is_file():
        return True
    dict_manifest = json.loads(path_manifest.read_text(encoding="utf-8"))
    list_names = dict_manifest.get("wheel_names")
    if list_names is not None:
        return sorted(list_names) == sorted(list_loose)
    int_expected = dict_manifest.get("wheel_count")
    return int_expected is None or int_expected == len(list_loose)


def assemble_wheelhouse(args: argparse.Namespace) -> int:
    """Assemble an installable wheels dir from loose wheels, a zip, or split parts.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed ``assemble`` arguments (``source``, ``wheels_out``, ``manifest``).

    Returns
    -------
    int
        0 on success.

    Raises
    ------
    SystemExit
        When none of the three accepted input shapes is found in ``args.source``.

    Notes
    -----
    Three input shapes, tried in order: loose ``*.whl`` files already in the output
    directory (nothing to do); a manifest + split parts (verified, REFUSES on mismatch —
    see :func:`verify_parts`); a bare ``wheelhouse.zip`` with no manifest, extracted
    as-is since there is nothing to verify it against.
    """
    dir_source = Path(args.source)
    dir_out = Path(args.wheels_out)

    path_manifest = Path(args.manifest)
    list_loose = [path_wheel.name for path_wheel in dir_out.glob("*.whl")]
    int_count = len(list_loose)
    if int_count and _loose_wheels_match_manifest(path_manifest, list_loose):
        print(f"{int_count} wheel(s) already loose in {dir_out} — nothing to assemble")
        return 0

    if path_manifest.is_file():
        dict_manifest = json.loads(path_manifest.read_text(encoding="utf-8"))
        list_parts = verify_parts(dir_source, dict_manifest)
        str_zip_name = dict_manifest.get("zip_name") or "wheelhouse.zip"
        path_zip_tmp = _contained_path(dir_source, str_zip_name)
        if path_zip_tmp.resolve() in {path_manifest.resolve(), *list_parts}:
            raise SystemExit(
                f"wheelhouse assemble: zip_name {str_zip_name!r} collides with an input file"
            )
        try:
            reassemble_zip(list_parts, dict_manifest, path_zip_tmp)
            _remove_loose_wheels(dir_out)
            int_count = unzip_wheels(path_zip_tmp, dir_out)
        finally:
            path_zip_tmp.unlink(missing_ok=True)
        print(f"assembled {int_count} wheel(s) into {dir_out} (manifest-verified)")
        return 0

    path_zip = dir_source / "wheelhouse.zip"
    if path_zip.is_file():
        int_count = unzip_wheels(path_zip, dir_out)
        print(f"assembled {int_count} wheel(s) into {dir_out} (no manifest — unverified)")
        return 0

    raise SystemExit(
        f"wheelhouse assemble: nothing found in {dir_source} (no manifest, zip, or wheel)"
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the ``select`` / ``pack`` / ``assemble`` subcommand parser.

    Returns
    -------
    argparse.ArgumentParser
        The configured top-level parser.
    """
    obj_parser = argparse.ArgumentParser(description="Select, pack and assemble the wheelhouse.")
    obj_sub = obj_parser.add_subparsers(dest="command", required=True)

    obj_select = obj_sub.add_parser("select", help="filter requirements for a target environment")
    obj_select.add_argument("--requirements", required=True)
    obj_select.add_argument("--out", required=True)
    obj_select.add_argument("--target-python-version", required=True)
    obj_select.add_argument("--target-sys-platform", required=True)
    obj_select.add_argument("--target-platform-machine", required=True)
    obj_select.add_argument("--target-implementation", required=True)
    obj_select.add_argument("--drop", action="append", default=[])
    obj_select.set_defaults(func=select_requirements)

    obj_pack = obj_sub.add_parser("pack", help="zip and split the wheels dir into a manifest")
    obj_pack.add_argument("--wheels-dir", required=True)
    obj_pack.add_argument("--zip-path", required=True)
    obj_pack.add_argument("--manifest", required=True)
    obj_pack.add_argument("--part-size-mb", type=int, required=True)
    obj_pack.set_defaults(func=pack_wheelhouse)

    obj_assemble = obj_sub.add_parser("assemble", help="reassemble wheels, refusing a mismatch")
    obj_assemble.add_argument("--source", required=True)
    obj_assemble.add_argument("--wheels-out", required=True)
    obj_assemble.add_argument("--manifest", required=True)
    obj_assemble.set_defaults(func=assemble_wheelhouse)

    return obj_parser


def main() -> int:
    """Parse argv and dispatch to the selected subcommand.

    Returns
    -------
    int
        The subcommand's own exit code.
    """
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
