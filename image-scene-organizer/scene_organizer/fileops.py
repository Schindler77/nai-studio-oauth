"""Real filesystem operations.

Everything that touches files on disk lives here, so internal organization
code (model / canvas) can never modify the filesystem by accident.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass

from .model import norm_path

SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".jfif", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in SUPPORTED_EXTS


def list_images(folder: str, recursive: bool = False) -> list[str]:
    out: list[str] = []
    if recursive:
        for root, dirs, files in os.walk(folder):
            dirs.sort(key=natural_key)
            out.extend(os.path.join(root, f) for f in sorted(files, key=natural_key) if is_image(f))
    else:
        try:
            names = sorted(os.listdir(folder), key=natural_key)
        except OSError:
            return []
        out = [os.path.join(folder, n) for n in names
               if is_image(n) and os.path.isfile(os.path.join(folder, n))]
    return out


def expand_paths(paths: list[str], recursive: bool = False) -> list[str]:
    """Files stay in the given order, folders expand to their images (natural sort)."""
    seen, out = set(), []
    for p in paths:
        items = list_images(p, recursive) if os.path.isdir(p) else ([p] if is_image(p) else [])
        for f in items:
            key = norm_path(f)
            if key not in seen:
                seen.add(key)
                out.append(os.path.abspath(f))
    return out


# ------------------------------------------------------------------ renaming

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


def sanitize_filename(name: str) -> str:
    name = _INVALID.sub("_", name).strip().rstrip(". ")
    if not name:
        name = "_"
    if name.split(".")[0].upper() in _RESERVED:
        name = "_" + name
    return name


DEFAULT_TEMPLATE = "[{region}] {num}"


@dataclass
class RenameEntry:
    old: str
    new: str
    status: str  # "ok" | "unchanged" | "missing" | "duplicate" | "conflict"

    @property
    def will_rename(self) -> bool:
        return self.status == "ok"


def build_name(template: str, region: str, n: int, pad: int, ext: str) -> str:
    base = template.replace("{region}", region).replace("{num}", str(n).zfill(pad))
    return sanitize_filename(base) + ext


def plan_rename(paths: list[str], template: str, region_name: str,
                start: int = 1, pad: int = 3) -> list[RenameEntry]:
    """Preview of renaming ``paths`` (in this order) inside their own folders."""
    entries: list[RenameEntry] = []
    sources = {norm_path(p) for p in paths if os.path.exists(p)}
    seen_src: set[str] = set()
    targets: dict[str, int] = {}
    n = start
    for p in paths:
        ext = os.path.splitext(p)[1]
        new = os.path.join(os.path.dirname(p), build_name(template, region_name, n, pad, ext))
        n += 1
        key = norm_path(p)
        if key in seen_src:
            entries.append(RenameEntry(p, new, "duplicate"))
            continue
        seen_src.add(key)
        if not os.path.exists(p):
            entries.append(RenameEntry(p, new, "missing"))
            continue
        if os.path.normpath(p) == os.path.normpath(new):
            entries.append(RenameEntry(p, new, "unchanged"))
            continue
        tkey = norm_path(new).lower()  # case-insensitive: safe on Windows
        status = "ok"
        if tkey in targets:
            status = "conflict"
        elif os.path.exists(new) and norm_path(new) not in sources and tkey != key.lower():
            status = "conflict"  # would overwrite a file outside this rename set
        targets[tkey] = len(entries)
        entries.append(RenameEntry(p, new, status))
    return entries


def apply_rename(entries: list[RenameEntry]) -> list[tuple[str, str]]:
    """Two-phase rename (via temp names) so names inside the set can swap.

    On failure, everything already renamed is rolled back and the error is
    re-raised. Returns the list of (old, new) pairs actually applied.
    """
    todo = [e for e in entries if e.will_rename]
    if any(e.status == "conflict" for e in entries):
        raise RuntimeError("Resolve conflicts before renaming.")
    tag = uuid.uuid4().hex[:8]
    staged: list[tuple[str, str, str]] = []  # (old, tmp, new)
    done: list[tuple[str, str]] = []
    try:
        for i, e in enumerate(todo):
            tmp = os.path.join(os.path.dirname(e.old), f".iso_tmp_{tag}_{i}{os.path.splitext(e.old)[1]}")
            os.rename(e.old, tmp)
            staged.append((e.old, tmp, e.new))
        for old, tmp, new in staged:
            if os.path.exists(new):
                raise FileExistsError(new)
            os.rename(tmp, new)
            done.append((old, new))
    except Exception:
        for old, new in reversed(done):
            try:
                os.rename(new, old)
            except OSError:
                pass
        finished = {o for o, _ in done}
        for old, tmp, _ in staged:
            if old not in finished and os.path.exists(tmp):
                try:
                    os.rename(tmp, old)
                except OSError:
                    pass
        raise
    return done


def rename_single(old: str, new_filename: str) -> str:
    new_filename = sanitize_filename(new_filename)
    if not os.path.splitext(new_filename)[1]:
        new_filename += os.path.splitext(old)[1]
    new = os.path.join(os.path.dirname(old), new_filename)
    if os.path.exists(new) and norm_path(new) != norm_path(old):
        raise FileExistsError(new)
    os.rename(old, new)
    return new


def write_rename_log(log_dir: str, pairs: list[tuple[str, str]]) -> str:
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, time.strftime("rename_%Y%m%d_%H%M%S.json"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"renamed": [{"old": o, "new": n} for o, n in pairs]}, f, ensure_ascii=False, indent=1)
    return path


def latest_rename_log(log_dir: str) -> str | None:
    if not os.path.isdir(log_dir):
        return None
    logs = sorted(f for f in os.listdir(log_dir) if f.startswith("rename_") and f.endswith(".json"))
    return os.path.join(log_dir, logs[-1]) if logs else None


def revert_rename_log(path: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Undo a logged bulk rename. Returns (reverted pairs new->old, problems)."""
    with open(path, encoding="utf-8") as f:
        pairs = [(d["old"], d["new"]) for d in json.load(f)["renamed"]]
    reverted, problems = [], []
    for old, new in reversed(pairs):
        if not os.path.exists(new):
            problems.append(f"missing: {new}")
        elif os.path.exists(old) and norm_path(old) != norm_path(new):
            problems.append(f"already exists: {old}")
        else:
            shutil.move(new, old)  # works for renames and cross-drive moves
            reverted.append((new, old))
    os.replace(path, path + ".reverted")
    return reverted, problems


# -------------------------------------------------------------------- moving

def plan_move(paths: list[str], dest_dir: str) -> list[RenameEntry]:
    """Preview of moving files into ``dest_dir`` (names kept, never overwrites)."""
    entries: list[RenameEntry] = []
    seen_src: set[str] = set()
    targets: set[str] = set()
    for p in paths:
        new = os.path.join(dest_dir, os.path.basename(p))
        key = norm_path(p)
        if key in seen_src:
            entries.append(RenameEntry(p, new, "duplicate"))
            continue
        seen_src.add(key)
        tkey = norm_path(new).lower()
        if not os.path.exists(p):
            status = "missing"
        elif norm_path(os.path.dirname(p)) == norm_path(dest_dir):
            status = "unchanged"
        elif os.path.exists(new) or tkey in targets:
            status = "conflict"
        else:
            status = "ok"
        targets.add(tkey)
        entries.append(RenameEntry(p, new, status))
    return entries


def apply_move(entries: list[RenameEntry]) -> list[tuple[str, str]]:
    """Move the 'ok' entries; conflicts are skipped (caller shows them).

    On failure, files already moved are moved back and the error re-raised.
    """
    done: list[tuple[str, str]] = []
    try:
        for e in entries:
            if not e.will_rename:
                continue
            if os.path.exists(e.new):
                raise FileExistsError(e.new)
            shutil.move(e.old, e.new)
            done.append((e.old, e.new))
    except Exception:
        for old, new in reversed(done):
            try:
                shutil.move(new, old)
            except OSError:
                pass
        raise
    return done


# --------------------------------------------------------------- shell / bin

def move_to_trash(path: str) -> bool:
    from PySide6.QtCore import QFile
    res = QFile.moveToTrash(path)
    return bool(res[0] if isinstance(res, tuple) else res)


def reveal_in_explorer(path: str) -> None:
    if sys.platform.startswith("win"):
        subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path) or "."])


def find_by_basename(folder: str, names: set[str]) -> dict[str, str]:
    """For relinking: lower-cased basename -> first matching file under folder."""
    found: dict[str, str] = {}
    for root, _, files in os.walk(folder):
        for f in files:
            k = f.lower()
            if k in names and k not in found:
                found[k] = os.path.join(root, f)
    return found
