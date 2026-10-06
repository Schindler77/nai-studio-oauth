"""Project data model.

This module has no Qt dependency. It is the single source of truth for the
project state; the canvas only mirrors it. Everything that decides *order*
lives here so it can be unit-tested and revised in one place.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field

FORMAT_VERSION = 1
PROJECT_EXT = ".isproj"
REGION_EXT = ".isregion"

# Canvas layout constants (scene units). Shared by the model (free-mode
# placement of new images) and the canvas (drawing / hit testing).
TITLE_H = 44
PAD = 12
GAP = 10
LABEL_H = 20

THUMB_MIN = 48
THUMB_MAX = 320
THUMB_DEFAULT = 150

# Thumbnail cell shape. thumb_size is the longer edge of the image box.
ASPECTS = {"16:9": 16 / 9, "4:3": 4 / 3, "1:1": 1.0, "3:4": 3 / 4, "2:3": 2 / 3}
ASPECT_DEFAULT = "16:9"
FILLS = ("cover", "fit")  # cover = crop to fill the box, fit = whole image (letterbox)

PRESET_COLORS = [
    ("Red", "#e05252"),
    ("Orange", "#e8913a"),
    ("Yellow", "#d6be3a"),
    ("Green", "#4caf6a"),
    ("Teal", "#36a99e"),
    ("Blue", "#4a86e8"),
    ("Purple", "#9a6ce0"),
    ("Pink", "#e06aa8"),
    ("Gray", "#8a8f98"),
]


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------- layout math

def image_box(thumb: int, aspect: str) -> tuple[int, int]:
    a = ASPECTS.get(aspect, ASPECTS[ASPECT_DEFAULT])
    return (thumb, round(thumb / a)) if a >= 1 else (round(thumb * a), thumb)


def cell_size(thumb: int, aspect: str = ASPECT_DEFAULT, label: bool = True) -> tuple[int, int]:
    w, h = image_box(thumb, aspect)
    return w, h + (LABEL_H if label else 0)


def closest_aspect(ratio: float) -> str:
    """Preset whose width/height ratio is closest (in log space) to ``ratio``."""
    return min(ASPECTS, key=lambda k: abs(math.log(ASPECTS[k]) - math.log(max(ratio, 1e-3))))


def grid_cols(region_w: float, cw: float) -> int:
    return max(1, int((region_w - 2 * PAD + GAP) // (cw + GAP)))


def grid_pos(i: int, cols: int, cw: float, ch: float) -> tuple[float, float]:
    return PAD + (i % cols) * (cw + GAP), TITLE_H + PAD + (i // cols) * (ch + GAP)


def grid_content_height(n: int, cols: int, ch: float) -> float:
    rows = max(1, math.ceil(n / cols))
    return TITLE_H + PAD + rows * (ch + GAP) - GAP + PAD


def slot_at(x: float, y: float, cols: int, cw: float, ch: float, n: int) -> int:
    """Grid slot under a region-local point: the image lands in that cell."""
    col = math.floor((x - PAD + GAP / 2) / (cw + GAP))
    row = math.floor((y - TITLE_H - PAD + GAP / 2) / (ch + GAP))
    col = min(max(col, 0), cols)
    row = max(row, 0)
    return min(max(row * cols + col, 0), n)


def default_region_size(cw: float, ch: float) -> tuple[float, float]:
    cols = 6 if cw < 130 else 5
    return 2 * PAD + cols * cw + (cols - 1) * GAP, TITLE_H + 2 * PAD + 1.4 * ch


# --------------------------------------------------------------- lock policy

def adjust_insert_index(seq: list["ImageRef"], k: int) -> int:
    """Where an insertion at index ``k`` of ``seq`` is actually allowed.

    Lock policy (prototype; revise here):
      * a locked run is never split - an insertion inside it goes after it;
      * a locked run that starts the region stays at the start - an
        insertion at index 0 goes after it.
    Inserting directly before a locked run that follows an unlocked image is
    allowed: the run moves back as a block but keeps its internal order.
    """
    k = min(max(k, 0), len(seq))
    while k < len(seq) and seq[k].locked and (k == 0 or seq[k - 1].locked):
        k += 1
    return k


# ---------------------------------------------------------------- data types

@dataclass
class ImageRef:
    """One placement of a source image inside a region.

    The same file may be referenced by several ImageRefs (copies).
    ``display_name`` is internal only; the file name on disk is ``path``.
    """
    path: str
    display_name: str = ""
    locked: bool = False
    x: float = 0.0  # region-local position, used in free (auto-arrange OFF) mode
    y: float = 0.0
    id: str = field(default_factory=new_id)

    def __post_init__(self):
        if not self.display_name:
            self.display_name = os.path.splitext(os.path.basename(self.path))[0]

    def clone(self) -> "ImageRef":
        return ImageRef(self.path, self.display_name, False, self.x, self.y)

    def to_dict(self, base_dir: str | None = None) -> dict:
        d = {"id": self.id, "path": self.path, "display_name": self.display_name,
             "locked": self.locked, "x": round(self.x, 2), "y": round(self.y, 2)}
        rel = _relpath(self.path, base_dir)
        if rel:
            d["rel"] = rel
        return d

    @classmethod
    def from_dict(cls, d: dict, base_dir: str | None = None, new_ids=False) -> "ImageRef":
        path = d["path"]
        if not os.path.exists(path) and d.get("rel") and base_dir:
            cand = os.path.normpath(os.path.join(base_dir, d["rel"]))
            if os.path.exists(cand):
                path = cand
        ref = cls(path, d.get("display_name", ""), bool(d.get("locked", False)),
                  float(d.get("x", 0)), float(d.get("y", 0)))
        if not new_ids and d.get("id"):
            ref.id = d["id"]
        return ref


@dataclass
class Region:
    name: str
    color: str = PRESET_COLORS[5][1]
    x: float = 0.0
    y: float = 0.0
    w: float = 800.0
    h: float = 240.0
    auto_arrange: bool = True
    collapsed: bool = False
    images: list[ImageRef] = field(default_factory=list)
    id: str = field(default_factory=new_id)

    # -- queries
    def index_of(self, ref_id: str) -> int:
        for i, r in enumerate(self.images):
            if r.id == ref_id:
                return i
        return -1

    def get(self, ref_id: str) -> ImageRef | None:
        i = self.index_of(ref_id)
        return self.images[i] if i >= 0 else None

    def has_path(self, path: str) -> bool:
        key = norm_path(path)
        return any(norm_path(r.path) == key for r in self.images)

    # -- ordering operations
    def insert(self, refs: list[ImageRef], index: int | None = None) -> int:
        """Insert refs as a block. Returns the index actually used."""
        k = adjust_insert_index(self.images, len(self.images) if index is None else index)
        self.images[k:k] = refs
        return k

    def remove(self, ids: set[str]) -> list[ImageRef]:
        removed = [r for r in self.images if r.id in ids]
        self.images = [r for r in self.images if r.id not in ids]
        return removed

    def move(self, ids: list[str], index: int) -> int:
        """Reorder: take ``ids`` out and insert them as a block at ``index``.

        ``index`` is expressed in the sequence *without* the moved images,
        which is what the canvas computes while dragging.
        """
        idset = set(ids)
        moving = [r for r in self.images if r.id in idset]
        self.images = [r for r in self.images if r.id not in idset]
        return self.insert(moving, index)

    def lock_up_to(self, ref_id: str) -> int:
        i = self.index_of(ref_id)
        for r in self.images[: i + 1]:
            r.locked = True
        return i + 1

    def free_spot_positions(self, count: int, cw: float, ch: float) -> list[tuple[float, float]]:
        """Grid positions below existing images, for free-mode additions."""
        bottom = TITLE_H + PAD
        for r in self.images:
            bottom = max(bottom, r.y + ch + GAP)
        cols = grid_cols(self.w, cw)
        out = []
        for i in range(count):
            x, y = grid_pos(i, cols, cw, ch)
            out.append((x, y - TITLE_H - PAD + bottom))
        return out

    # -- serialization
    def to_dict(self, base_dir: str | None = None) -> dict:
        return {"id": self.id, "name": self.name, "color": self.color,
                "x": round(self.x, 2), "y": round(self.y, 2),
                "w": round(self.w, 2), "h": round(self.h, 2),
                "auto_arrange": self.auto_arrange, "collapsed": self.collapsed,
                "images": [r.to_dict(base_dir) for r in self.images]}

    @classmethod
    def from_dict(cls, d: dict, base_dir: str | None = None, new_ids=False) -> "Region":
        reg = cls(d.get("name", "Region"), d.get("color", PRESET_COLORS[5][1]),
                  float(d.get("x", 0)), float(d.get("y", 0)),
                  float(d.get("w", 800)), float(d.get("h", 240)),
                  bool(d.get("auto_arrange", True)), bool(d.get("collapsed", False)),
                  [ImageRef.from_dict(i, base_dir, new_ids) for i in d.get("images", [])])
        if not new_ids and d.get("id"):
            reg.id = d["id"]
        return reg


@dataclass
class Project:
    regions: list[Region] = field(default_factory=list)
    thumb_size: int = THUMB_DEFAULT
    show_labels: bool = False   # file / display name under the thumbnail
    show_numbers: bool = True   # sequence number under the thumbnail
    show_region_names: bool = True
    view: dict = field(default_factory=dict)  # {"cx","cy","zoom"}
    thumb_aspect: str = ASPECT_DEFAULT
    thumb_fill: str = "cover"
    aspect_auto: bool = True  # pick the aspect from the first imported images

    def label_shown(self) -> bool:
        return self.show_numbers or self.show_labels

    def cell(self) -> tuple[int, int]:
        return cell_size(self.thumb_size, self.thumb_aspect, self.label_shown())

    def image_box(self) -> tuple[int, int]:
        return image_box(self.thumb_size, self.thumb_aspect)

    def region(self, region_id: str | None) -> Region | None:
        for r in self.regions:
            if r.id == region_id:
                return r
        return None

    def find(self, ref_id: str) -> tuple[Region, ImageRef] | tuple[None, None]:
        for reg in self.regions:
            ref = reg.get(ref_id)
            if ref:
                return reg, ref
        return None, None

    def all_refs(self):
        for reg in self.regions:
            for ref in reg.images:
                yield reg, ref

    def image_count(self) -> int:
        return sum(len(r.images) for r in self.regions)

    def remap_paths(self, mapping: dict[str, str]) -> int:
        """After a real filesystem rename: point every reference to the new path."""
        n = 0
        for _, ref in self.all_refs():
            new = mapping.get(norm_path(ref.path))
            if new:
                old_stem = os.path.splitext(os.path.basename(ref.path))[0]
                if ref.display_name == old_stem:
                    ref.display_name = os.path.splitext(os.path.basename(new))[0]
                ref.path = new
                n += 1
        return n

    def unique_region_name(self, base: str) -> str:
        names = {r.name for r in self.regions}
        if base not in names:
            return base
        i = 2
        while f"{base} ({i})" in names:
            i += 1
        return f"{base} ({i})"

    def to_dict(self, base_dir: str | None = None) -> dict:
        return {"format": "image-scene-organizer-project", "version": FORMAT_VERSION,
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "thumb_size": self.thumb_size, "show_labels": self.show_labels,
                "show_numbers": self.show_numbers,
                "show_region_names": self.show_region_names, "view": dict(self.view),
                "thumb_aspect": self.thumb_aspect, "thumb_fill": self.thumb_fill,
                "aspect_auto": self.aspect_auto,
                "regions": [r.to_dict(base_dir) for r in self.regions]}

    @classmethod
    def from_dict(cls, d: dict, base_dir: str | None = None) -> "Project":
        if d.get("format") not in (None, "image-scene-organizer-project"):
            raise ValueError("Not an Image Scene Organizer project file")
        # Files from before thumbnail shapes existed keep their look: square, whole image.
        aspect = d.get("thumb_aspect", "1:1")
        fill = d.get("thumb_fill", "fit")
        return cls([Region.from_dict(r, base_dir) for r in d.get("regions", [])],
                   int(d.get("thumb_size", THUMB_DEFAULT)), bool(d.get("show_labels", True)),
                   bool(d.get("show_numbers", True)), bool(d.get("show_region_names", True)),
                   dict(d.get("view", {})), aspect if aspect in ASPECTS else ASPECT_DEFAULT,
                   fill if fill in FILLS else "cover", bool(d.get("aspect_auto", False)))


# ------------------------------------------------------- reusable region file

def region_file_dict(region: Region, base_dir: str | None) -> dict:
    return {"format": "image-scene-organizer-region", "version": FORMAT_VERSION,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "region": region.to_dict(base_dir)}


def region_from_file_dict(d: dict, base_dir: str | None) -> Region:
    if d.get("format") != "image-scene-organizer-region":
        raise ValueError("Not an Image Scene Organizer region file")
    # Fresh ids so the same region can be loaded several times.
    return Region.from_dict(d["region"], base_dir, new_ids=True)


# ----------------------------------------------------------------- file I/O

def norm_path(p: str) -> str:
    return os.path.normcase(os.path.abspath(p))


def _relpath(path: str, base_dir: str | None) -> str | None:
    if not base_dir:
        return None
    try:
        return os.path.relpath(path, base_dir)
    except ValueError:  # different drive on Windows
        return None


def save_json_atomic(path: str, data: dict, keep_backup=True) -> None:
    """Write to a temp file, keep the previous version as .bak, then replace."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    if keep_backup and os.path.exists(path):
        try:
            shutil.copy2(path, path + ".bak")
        except OSError:
            pass
    os.replace(tmp, path)


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
