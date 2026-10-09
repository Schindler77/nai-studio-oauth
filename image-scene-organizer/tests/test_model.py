import os

import pytest

from scene_organizer import fileops
from scene_organizer.model import (ImageRef, Project, Region, adjust_insert_index, load_json,
                                   region_file_dict, region_from_file_dict, save_json_atomic)


def names(reg):
    return [os.path.basename(r.path) for r in reg.images]


def make(n=5, locked=()):
    reg = Region("R")
    reg.images = [ImageRef(f"{i:02d}") for i in range(1, n + 1)]
    for i in locked:
        reg.images[i].locked = True
    return reg


# --- §34 A: persistent auto-arrange insertion -------------------------------

def test_move_03_to_front():
    reg = make()
    reg.move([reg.images[2].id], 0)
    assert names(reg) == ["03", "01", "02", "04", "05"]


def test_move_05_between_03_and_04():
    reg = make()
    reg.move([reg.images[4].id], 3)  # index in the sequence without 05
    assert names(reg) == ["01", "02", "03", "05", "04"]


def test_move_block_keeps_relative_order():
    reg = make(6)
    reg.move([reg.images[5].id, reg.images[1].id], 0)
    assert names(reg) == ["02", "06", "01", "03", "04", "05"]


# --- §34 B: locking ----------------------------------------------------------

def test_locked_prefix_is_not_disturbed_by_insert_at_front():
    reg = make(5, locked=(0, 1, 2))
    at = reg.insert([ImageRef("new")], 0)
    assert at == 3
    assert names(reg)[:3] == ["01", "02", "03"]


def test_import_appends_after_locked():
    reg = make(5, locked=range(5))
    reg.insert([ImageRef(f"n{i}") for i in range(30)])
    assert names(reg)[:5] == ["01", "02", "03", "04", "05"]
    assert len(reg.images) == 35


def test_locked_run_never_split():
    reg = make(6, locked=(2, 3, 4))
    assert adjust_insert_index(reg.images, 3) == 5
    assert adjust_insert_index(reg.images, 4) == 5
    assert adjust_insert_index(reg.images, 2) == 2  # before a middle run is allowed


def test_move_into_locked_run_redirects_after_it():
    reg = make(5, locked=(0, 1))
    reg.move([reg.images[4].id], 1)
    assert names(reg) == ["01", "02", "05", "03", "04"]


def test_lock_up_to():
    reg = make()
    assert reg.lock_up_to(reg.images[2].id) == 3
    assert [r.locked for r in reg.images] == [True, True, True, False, False]


# --- §34 C/D: save / restore / reusable region -------------------------------

def test_project_roundtrip(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    reg = make(3, locked=(0,))
    reg.images.append(ImageRef(str(img)))
    reg.name, reg.color, reg.auto_arrange, reg.collapsed = "First Meeting", "#e05252", False, True
    p = Project([reg, Region("Other")], thumb_size=180)
    path = str(tmp_path / "p.isproj")
    save_json_atomic(path, p.to_dict(str(tmp_path)))
    save_json_atomic(path, p.to_dict(str(tmp_path)))  # second save keeps a .bak
    assert os.path.exists(path + ".bak")
    q = Project.from_dict(load_json(path), str(tmp_path))
    r = q.regions[0]
    assert (r.name, r.color, r.auto_arrange, r.collapsed) == ("First Meeting", "#e05252", False, True)
    assert [x.path for x in r.images] == [x.path for x in reg.images]
    assert [x.locked for x in r.images] == [True, False, False, False]
    assert q.thumb_size == 180 and len(q.regions) == 2


def test_relative_path_fallback(tmp_path):
    (tmp_path / "imgs").mkdir()
    f = tmp_path / "imgs" / "a.png"
    f.write_bytes(b"x")
    reg = Region("R", images=[ImageRef(str(f))])
    d = region_file_dict(reg, str(tmp_path))
    d["region"]["images"][0]["path"] = "/nonexistent/old/location/a.png"  # project folder moved
    r2 = region_from_file_dict(d, str(tmp_path))
    assert r2.images[0].path == os.path.normpath(str(f))
    assert r2.id != reg.id and r2.images[0].id != reg.images[0].id  # fresh ids on load


def test_remap_paths_updates_display_name():
    p = Project([Region("R", images=[ImageRef("/x/IMG_1.png"), ImageRef("/x/b.png", "custom")])])
    p.remap_paths({os.path.normcase(os.path.abspath("/x/IMG_1.png")): "/x/[R] 001.png",
                   os.path.normcase(os.path.abspath("/x/b.png")): "/x/[R] 002.png"})
    assert [r.display_name for r in p.regions[0].images] == ["[R] 001", "custom"]


# --- §14: bulk rename ----------------------------------------------------------

def _files(tmp_path, names_):
    out = []
    for n in names_:
        f = tmp_path / n
        f.write_bytes(n.encode())
        out.append(str(f))
    return out


def test_bulk_rename_by_order(tmp_path):
    a, b, c, d = _files(tmp_path, ["A.png", "B.png", "C.jpg", "D.png"])
    plan = fileops.plan_rename([a, d, c, b], fileops.DEFAULT_TEMPLATE, "First Meeting")
    assert [os.path.basename(e.new) for e in plan] == [
        "[First Meeting] 001.png", "[First Meeting] 002.png", "[First Meeting] 003.jpg",
        "[First Meeting] 004.png"]
    pairs = fileops.apply_rename(plan)
    assert len(pairs) == 4
    assert (tmp_path / "[First Meeting] 002.png").read_bytes() == b"D.png"


def test_bulk_rename_swap_within_set(tmp_path):
    x, y = _files(tmp_path, ["s 001.png", "s 002.png"])
    plan = fileops.plan_rename([y, x], "s {num}", "")
    assert all(e.status == "ok" for e in plan)
    fileops.apply_rename(plan)
    assert (tmp_path / "s 001.png").read_bytes() == b"s 002.png"


def test_bulk_rename_conflict_with_outside_file(tmp_path):
    a, _ = _files(tmp_path, ["a.png", "[R] 001.png"])
    plan = fileops.plan_rename([a], fileops.DEFAULT_TEMPLATE, "R")
    assert plan[0].status == "conflict"
    with pytest.raises(RuntimeError):
        fileops.apply_rename(plan)


def test_rename_log_revert(tmp_path):
    a, b = _files(tmp_path, ["a.png", "b.png"])
    pairs = fileops.apply_rename(fileops.plan_rename([b, a], "{region} {num}", "x"))
    log = fileops.write_rename_log(str(tmp_path / "logs"), pairs)
    reverted, problems = fileops.revert_rename_log(log)
    assert not problems and len(reverted) == 2
    assert (tmp_path / "a.png").read_bytes() == b"a.png"


def test_sanitize_region_name():
    assert fileops.sanitize_filename('a<b>:c"d/e\\f|g?h*') == "a_b__c_d_e_f_g_h_"
    assert fileops.sanitize_filename("CON") == "_CON"


def test_expand_paths_natural_sort(tmp_path):
    _files(tmp_path, ["img10.png", "img2.png", "img1.png", "notes.txt"])
    got = [os.path.basename(p) for p in fileops.expand_paths([str(tmp_path)])]
    assert got == ["img1.png", "img2.png", "img10.png"]


def test_move_plan_and_apply(tmp_path):
    a, b, c = _files(tmp_path, ["a.png", "b.png", "c.png"])
    dest = tmp_path / "scene1"
    dest.mkdir()
    (dest / "c.png").write_bytes(b"other")
    plan = fileops.plan_move([a, b, c, a, str(tmp_path / "gone.png")], str(dest))
    assert [e.status for e in plan] == ["ok", "ok", "conflict", "duplicate", "missing"]
    pairs = fileops.apply_move(plan)
    assert len(pairs) == 2 and (dest / "a.png").read_bytes() == b"a.png"
    assert (dest / "c.png").read_bytes() == b"other" and os.path.exists(c)  # nothing overwritten
    log = fileops.write_rename_log(str(tmp_path / "logs"), pairs)
    reverted, problems = fileops.revert_rename_log(log)
    assert not problems and os.path.exists(a) and os.path.exists(b)


def test_move_rolls_back_on_failure(tmp_path, monkeypatch):
    a, b = _files(tmp_path, ["a.png", "b.png"])
    dest = tmp_path / "d"
    dest.mkdir()
    plan = fileops.plan_move([a, b], str(dest))
    real = fileops.shutil.move
    calls = []

    def flaky(src, dst):
        calls.append(src)
        if len(calls) == 2:
            raise PermissionError("locked by another program")
        return real(src, dst)
    monkeypatch.setattr(fileops.shutil, "move", flaky)
    with pytest.raises(PermissionError):
        fileops.apply_move(plan)
    assert os.path.exists(a) and os.path.exists(b)  # first move was undone


def test_thumbnail_shapes_and_legacy_projects():
    from scene_organizer.model import ASPECT_DEFAULT, cell_size, closest_aspect
    assert closest_aspect(832 / 1216) == "2:3" and closest_aspect(1920 / 1080) == "16:9"
    assert closest_aspect(1.0) == "1:1"
    assert cell_size(160, "16:9", label=False) == (160, 90)
    assert cell_size(150, "2:3", label=False) == (100, 150)
    new = Project()
    assert new.thumb_aspect == ASPECT_DEFAULT and new.aspect_auto
    legacy = Project.from_dict({"regions": [], "thumb_size": 150})  # saved before shapes existed
    assert (legacy.thumb_aspect, legacy.thumb_fill, legacy.aspect_auto) == ("1:1", "fit", False)
    again = Project.from_dict(Project(thumb_aspect="3:4", thumb_fill="cover").to_dict())
    assert (again.thumb_aspect, again.thumb_fill) == ("3:4", "cover")
