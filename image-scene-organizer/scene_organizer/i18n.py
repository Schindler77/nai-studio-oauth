"""UI language (Korean / English).

Source strings in the code are English templates; ``tr()`` returns the
Korean text when Korean is active. Templates use ``{name}`` placeholders
filled from keyword arguments. Any template missing from ``KO`` while
Korean is active is recorded in ``MISSES`` (the test-suite checks it).
"""
from __future__ import annotations

LANGUAGES = {"ko": "한국어", "en": "English"}
DEFAULT_LANGUAGE = "ko"

_lang = DEFAULT_LANGUAGE
MISSES: set[str] = set()


def set_language(lang: str) -> None:
    global _lang
    _lang = lang if lang in LANGUAGES else DEFAULT_LANGUAGE


def language() -> str:
    return _lang


def tr(text: str, **kw) -> str:
    if _lang == "ko":
        t = KO.get(text)
        if t is None:
            MISSES.add(text)
            t = text
    else:
        t = text
    return t.format(**kw) if kw else t


KO: dict[str, str] = {
    # ------------------------------------------------------------ menus
    "&File": "파일(&F)",
    "&Edit": "편집(&E)",
    "&Import": "가져오기(&I)",
    "&Region": "영역(&R)",
    "&Arrange": "정렬(&A)",
    "&View": "보기(&V)",
    "Recent Projects": "최근 프로젝트",
    "Color": "색상",
    "Thumbnail Size": "썸네일 크기",
    "Language": "언어",
    "(none)": "(없음)",
    # ----------------------------------------------------------- actions
    "New Project": "새 프로젝트",
    "Open Project…": "프로젝트 열기…",
    "Save Current State": "현재 상태 저장",
    "Save As…": "다른 이름으로 저장…",
    "Save Full Project": "전체 프로젝트 저장",
    "Save Current Region…": "현재 영역 저장…",
    "Load Saved Region…": "저장된 영역 불러오기…",
    "Relink Missing Images…": "누락된 이미지 다시 연결…",
    "Revert Last File Rename/Move…": "마지막 파일 이름 변경/이동 되돌리기…",
    "Preferences…": "환경설정…",
    "Exit": "종료",
    "Undo": "실행 취소",
    "Redo": "다시 실행",
    "Copy": "복사",
    "Cut": "잘라내기",
    "Paste": "붙여넣기",
    "Remove from Region (keeps files)": "영역에서 빼기 (파일은 유지)",
    "Select All (active region, else everything)": "모두 선택 (활성 영역, 없으면 전체)",
    "Lock Selected": "선택 잠금",
    "Unlock Selected": "선택 잠금 해제",
    "Lock Up To Selected (Confirmed Portion)": "선택한 곳까지 잠금 (확정 구간)",
    "Cancel / Clear Selection": "취소 / 선택 해제",
    "Import Image…": "이미지 가져오기…",
    "Import Multiple Images…": "여러 이미지 가져오기…",
    "Import Folder…": "폴더 가져오기…",
    "Import Folder Including Subfolders…": "하위 폴더까지 폴더 가져오기…",
    "New Region": "새 영역",
    "Rename Region…": "영역 이름 바꾸기…",
    "Auto-Arrange": "자동 정렬",
    "Persistent per-region auto-arrange (insertion with automatic shifting)":
        "영역별로 유지되는 자동 정렬 (끼워 넣으면 나머지가 자동으로 밀림)",
    "Duplicate Region": "영역 복제",
    "Clear Region…": "영역 비우기…",
    "Delete Region…": "영역 삭제…",
    "Collapse / Expand Region": "영역 접기 / 펼치기",
    "Lock Entire Region": "영역 전체 잠금",
    "Unlock Entire Region": "영역 전체 잠금 해제",
    "Rename Actual Files by Order…": "순서대로 실제 파일 이름 바꾸기…",
    "Arrange Regions Horizontally": "영역 가로로 정렬",
    "Arrange Regions Vertically": "영역 세로로 정렬",
    "Arrange Regions as Grid": "영역 격자로 정렬",
    "Arrange Selected Regions (Ctrl+click titles)": "선택한 영역만 정렬 (제목줄 Ctrl+클릭)",
    "Arrange Images Inside Region (grid, keep order)": "영역 안 이미지 정렬 (격자, 순서 유지)",
    "Set Order from Visual Position (free mode)": "보이는 위치대로 순서 정하기 (자유 배치)",
    "Fit All": "전체 보기",
    "Fit Selected Region": "선택 영역 맞춰 보기",
    "Canvas Zoom 100%": "캔버스 100%",
    "Larger Thumbnails": "썸네일 크게",
    "Smaller Thumbnails": "썸네일 작게",
    "Default Thumbnail Size": "썸네일 기본 크기",
    "Show Region Names": "영역 이름 표시",
    "Show Image Names": "이미지 이름 표시",
    "Show Sequence Numbers": "순서 번호 표시",
    "Collapse All Regions": "모든 영역 접기",
    "Expand All Regions": "모든 영역 펼치기",
    # ------------------------------------------------------ toolbar/dock
    "Save": "저장",
    "Add Image": "이미지 추가",
    "Add Folder": "폴더 추가",
    "Add Region": "영역 추가",
    "Region Color": "영역 색상",
    "Lock": "잠금",
    "Unlock": "잠금 해제",
    "Regions": "영역 목록",
    "Region List Sidebar": "영역 목록 사이드바",
    "Regions: {r}   Images: {i}   Selected: {s}": "영역: {r}   이미지: {i}   선택: {s}",
    "Thumbnail: {n}px": "썸네일: {n}px",
    "Zoom: {n}%": "배율: {n}%",
    "Untitled": "제목 없음",
    # ------------------------------------------------------------ colours
    "Red": "빨강", "Orange": "주황", "Yellow": "노랑", "Green": "초록", "Teal": "청록",
    "Blue": "파랑", "Purple": "보라", "Pink": "분홍", "Gray": "회색",
    "Custom…": "사용자 지정…",
    # ----------------------------------------------------- status / undo
    "Nothing to undo": "실행 취소할 작업이 없습니다",
    "Nothing to redo": "다시 실행할 작업이 없습니다",
    "Cancelled": "취소했습니다",
    "Cancelled (right-click)": "취소했습니다 (우클릭)",
    # ------------------------------------------------------------ regions
    "Region {n}": "영역 {n}",
    "Imported": "가져온 이미지",
    "Unsorted": "미분류",
    "{name} copy": "{name} 복사본",
    "Created '{name}'. Double-click its title (or F2) to rename.":
        "'{name}' 영역을 만들었습니다. 제목줄을 더블클릭하거나 F2를 눌러 이름을 바꾸세요.",
    "Rename Region": "영역 이름 바꾸기",
    "Region name:": "영역 이름:",
    "Select a region first": "먼저 영역을 선택하세요",
    "Auto-Arrange ON for '{name}'": "'{name}' 자동 정렬 켬",
    "Auto-Arrange OFF for '{name}'": "'{name}' 자동 정렬 끔",
    "Clear Region": "영역 비우기",
    "'{name}' has {n} locked image(s).\n\nYes = remove everything\nNo = remove only unlocked images":
        "'{name}'에 잠긴 이미지가 {n}장 있습니다.\n\n예 = 전부 빼기\n아니요 = 잠기지 않은 이미지만 빼기",
    "Region cleared (source files untouched). Ctrl+Z to undo.":
        "영역을 비웠습니다 (원본 파일은 그대로). Ctrl+Z로 되돌릴 수 있습니다.",
    "Delete Region": "영역 삭제",
    "Delete region '{name}' and its {n} image reference(s)?\nSource files on disk are NOT touched. (Undo: Ctrl+Z)":
        "'{name}' 영역과 이미지 참조 {n}개를 삭제할까요?\n디스크의 원본 파일은 건드리지 않습니다. (되돌리기: Ctrl+Z)",
    "Locked all {n} images in '{name}'": "'{name}'의 이미지 {n}장을 모두 잠갔습니다",
    "Unlocked all {n} images in '{name}'": "'{name}'의 이미지 {n}장을 모두 잠금 해제했습니다",
    "Ctrl+click two or more region titles first": "먼저 영역 제목줄 두 개 이상을 Ctrl+클릭하세요",
    "Auto-Arrange is ON: the region is already arranged": "자동 정렬이 켜져 있어 이미 정렬된 상태입니다",
    "Only meaningful with Auto-Arrange OFF": "자동 정렬이 꺼져 있을 때만 쓸 수 있습니다",
    "Sequence now follows the visual reading order": "보이는 위치(위→아래, 왼쪽→오른쪽) 순서로 바꿨습니다",
    # ------------------------------------------------------------- import
    "Import Images": "이미지 가져오기",
    "Import Image": "이미지 가져오기",
    "Import Folder": "폴더 가져오기",
    "Images": "이미지",
    "No supported images found": "지원하는 이미지 파일이 없습니다",
    "All {n} image(s) are already in '{name}'": "{n}장 모두 이미 '{name}'에 있습니다",
    "Imported {n} image(s) into '{name}' at position {pos}": "이미지 {n}장을 '{name}'의 {pos}번 위치에 가져왔습니다",
    " — {n} already present, skipped": " — 이미 있는 {n}장은 건너뜀",
    " — placed after locked images": " — 잠긴 이미지 뒤에 넣음",
    # ---------------------------------------------------------- clipboard
    "Nothing selected": "선택한 이미지가 없습니다",
    "Copied {n} image(s)": "이미지 {n}장을 복사했습니다",
    "Nothing to cut (locked images can't be cut)": "잘라낼 이미지가 없습니다 (잠긴 이미지는 잘라낼 수 없음)",
    "Cut {n} image(s){extra} — select a region and press Ctrl+V":
        "이미지 {n}장을 잘라냈습니다{extra} — 영역을 선택하고 Ctrl+V를 누르세요",
    " ({n} locked skipped)": " (잠긴 {n}장 제외)",
    "Clipboard is empty": "클립보드가 비어 있습니다",
    "Pasted {n} image(s) into '{name}' at position {pos}": "이미지 {n}장을 '{name}'의 {pos}번 위치에 붙여넣었습니다",
    "Selected images are locked — unlock them to remove": "선택한 이미지가 잠겨 있습니다 — 빼려면 먼저 잠금을 해제하세요",
    "Removed {n} image reference(s) from the project (files untouched){extra}. Ctrl+Z to undo.":
        "프로젝트에서 이미지 참조 {n}개를 뺐습니다 (파일은 그대로){extra}. Ctrl+Z로 되돌릴 수 있습니다.",
    "; {n} locked kept": "; 잠긴 {n}장은 남김",
    "Copied {n} image(s) to '{name}'{extra}": "이미지 {n}장을 '{name}'에 복사했습니다{extra}",
    "Moved {n} image(s) to '{name}'{extra}": "이미지 {n}장을 '{name}' 영역으로 옮겼습니다{extra}",
    " ({n} locked stayed)": " (잠긴 {n}장은 그대로)",
    "Locked images keep their place — inserted after them": "잠긴 이미지는 제자리를 지킵니다 — 그 뒤에 넣었습니다",
    "Dropped outside any region: move cancelled": "영역 밖에 놓아서 이동을 취소했습니다",
    "Locked images can't be moved. Unlock them first.": "잠긴 이미지는 옮길 수 없습니다. 먼저 잠금을 해제하세요.",
    "{n} locked image(s) stay in place": "잠긴 이미지 {n}장은 제자리에 둡니다",
    # -------------------------------------------------------------- locks
    "Select images first (or use the region menu to lock a whole region)":
        "먼저 이미지를 선택하세요 (영역 전체는 영역 우클릭 메뉴에서 잠글 수 있음)",
    "Locked {n} image(s)": "이미지 {n}장을 잠갔습니다",
    "Unlocked {n} image(s)": "이미지 {n}장을 잠금 해제했습니다",
    "Select the last confirmed image of a region first": "먼저 영역에서 마지막으로 확정한 이미지를 선택하세요",
    "Locked images 1–{n} of '{name}'": "'{name}'의 1~{n}번 이미지를 잠갔습니다",
    # --------------------------------------------------------- image menu
    "Open Large View": "크게 보기",
    "Cut ({n})": "잘라내기 ({n})",
    "Copy ({n})": "복사 ({n})",
    "Paste After This Image": "이 이미지 뒤에 붙여넣기",
    "Lock ({n})": "잠금 ({n})",
    "Unlock ({n})": "잠금 해제 ({n})",
    "Lock Up To Here (Confirmed Portion)": "여기까지 잠금 (확정 구간)",
    "Move to Another Region": "다른 영역으로 이동",
    "Copy to Another Region": "다른 영역으로 복사",
    "Change Display Name…": "표시 이름 바꾸기…",
    "Rename Actual Files by Order ({n})…": "순서대로 실제 파일 이름 바꾸기 ({n})…",
    "Rename Actual File…": "실제 파일 이름 바꾸기…",
    "Move Actual File(s) to Folder ({n})…": "실제 파일을 폴더로 이동 ({n})…",
    "Open Source File Location": "원본 파일 위치 열기",
    "Remove from Current Region ({n})": "현재 영역에서 빼기 ({n})",
    "Delete Actual Source File(s) ({n})…": "실제 원본 파일 삭제 ({n})…",
    # -------------------------------------------------------- region menu
    "Import Image(s)…": "이미지 가져오기…",
    "Select All in Region": "영역 안 모두 선택",
    "Expand": "펼치기",
    "Collapse": "접기",
    "Lock Selected Images": "선택한 이미지 잠금",
    "Lock Current Organized Portion (up to last selected)": "정리된 구간 잠금 (마지막으로 선택한 이미지까지)",
    "Unlock All": "모두 잠금 해제",
    "Arrange Images Inside Region (grid)": "영역 안 이미지 정렬 (격자)",
    "Set Order from Visual Position": "보이는 위치대로 순서 정하기",
    "Save Region…": "영역 저장…",
    "Move Actual Files of Region to Folder…": "영역의 실제 파일을 폴더로 이동…",
    # -------------------------------------------------------- canvas menu
    "New Region Here": "여기에 새 영역",
    "Load Saved Region Here…": "여기에 저장된 영역 불러오기…",
    "Paste (into a new region here)": "붙여넣기 (여기에 새 영역으로)",
    "Import Image(s) (new region here)…": "이미지 가져오기 (여기에 새 영역으로)…",
    "Import Folder (new region here)…": "폴더 가져오기 (여기에 새 영역으로)…",
    "Fit All to Screen": "전체를 화면에 맞추기",
    "Right-click → New Region   ·   or drop images / folders here\n"
    "Wheel = zoom   ·   Ctrl+Wheel = thumbnail size   ·   Middle-drag or Space+drag = pan":
        "우클릭 → 새 영역   ·   또는 이미지 / 폴더를 여기에 끌어다 놓기\n"
        "휠 = 확대/축소   ·   Ctrl+휠 = 썸네일 크기   ·   휠 버튼 드래그 또는 Space+드래그 = 화면 이동",
    # ----------------------------------------------------- canvas drawing
    "missing file": "파일 없음",
    "{n} images": "{n}장",
    "Auto-Arrange ON": "자동 정렬 ON",
    "Auto-Arrange OFF": "자동 정렬 OFF",
    # ------------------------------------------------------ appearance
    "Lock / Unlock": "잠금/해제",
    "Lock the selected images, or unlock them if they are all locked (Ctrl+L / Ctrl+Shift+L)":
        "선택한 이미지를 잠그고, 모두 잠겨 있으면 잠금을 풉니다 (Ctrl+L / Ctrl+Shift+L)",
    "Thumbnail Shape": "썸네일 모양",
    "Fill the box (crop edges)": "칸 채우기 (가장자리 잘림)",
    "Show whole image": "이미지 전체 보이기",
    "Theme": "테마",
    "Light": "밝게",
    "Dark": "어둡게",
    "Drop images here, or select this region and use Import": "여기에 이미지를 끌어다 놓거나, 이 영역을 선택하고 가져오기를 쓰세요",
    # ------------------------------------------------------ display names
    "Display Name": "표시 이름",
    "Display name (internal only, the file is not renamed):": "표시 이름 (프로그램 안에서만 쓰이며 파일 이름은 바뀌지 않음):",
    "Display Names": "표시 이름",
    "Prefix for {n} images (numbered in order; files untouched):":
        "이미지 {n}장에 붙일 이름 (순서대로 번호가 붙고, 파일은 그대로):",
    "File not found: {path}": "파일을 찾을 수 없습니다: {path}",
    # -------------------------------------------------- filesystem actions
    "{what}; project saved so it points to the new file paths":
        "{what} — 새 파일 경로를 가리키도록 프로젝트를 저장했습니다",
    "{what}.\n\nThis project has never been saved. Save it now so it points to the new file paths.":
        "{what}.\n\n이 프로젝트는 아직 저장된 적이 없습니다. 새 파일 경로를 기억하도록 지금 저장하세요.",
    "Source file not found": "원본 파일을 찾을 수 없습니다",
    "Rename Actual File": "실제 파일 이름 바꾸기",
    "New file name for\n{path}\n(this renames the file on disk):": "새 파일 이름\n{path}\n(디스크의 실제 파일 이름이 바뀝니다):",
    "Rename failed": "이름 바꾸기 실패",
    "File renamed": "파일 이름을 바꿨습니다",
    "Select a region with images first": "먼저 이미지가 있는 영역을 선택하세요",
    "Nothing was renamed (rolled back).\n\n{err}": "아무 파일도 바뀌지 않았습니다 (원래대로 되돌림).\n\n{err}",
    "Renamed {n} file(s)": "파일 {n}개의 이름을 바꿨습니다",
    "Move {n} file(s) to folder": "파일 {n}개를 옮길 폴더",
    "Nothing to move: {detail}": "옮길 파일이 없습니다: {detail}",
    "{n} with a name conflict": "같은 이름 있음 {n}개",
    "{n} missing": "파일 없음 {n}개",
    "{n} already there": "이미 그 폴더에 있음 {n}개",
    "\n\n{n} file(s) are SKIPPED because a file with the same name already exists there "
    "(nothing is overwritten):\n":
        "\n\n같은 이름의 파일이 이미 있어서 {n}개는 건너뜁니다 (덮어쓰지 않음):\n",
    "\n\n{n} missing file(s) skipped.": "\n\n없는 파일 {n}개는 건너뜁니다.",
    "Move Actual Files": "실제 파일 이동",
    "Move {n} file(s) on disk to\n{dest}\n\n{listing}{notes}\n\nEvery reference in this project follows "
    "the files. File → Revert Last File Rename/Move undoes it.":
        "디스크의 파일 {n}개를 다음 폴더로 옮길까요?\n{dest}\n\n{listing}{notes}\n\n이 프로젝트의 참조는 "
        "모두 새 위치로 바뀝니다. 파일 → 마지막 파일 이름 변경/이동 되돌리기로 취소할 수 있습니다.",
    "Move Files": "파일 이동",
    "Move failed": "이동 실패",
    "Nothing was moved (rolled back).\n\n{err}": "아무 파일도 옮기지 않았습니다 (원래대로 되돌림).\n\n{err}",
    "Moved {n} file(s) to {dest}": "파일 {n}개를 옮겼습니다: {dest}",
    "No rename/move log found": "이름 변경/이동 기록이 없습니다",
    "Revert Last File Rename/Move": "마지막 파일 이름 변경/이동 되돌리기",
    "Put the files from\n{log}\nback to their old names/folders?": "다음 기록의 파일들을\n{log}\n원래 이름/폴더로 되돌릴까요?",
    "Revert failed": "되돌리기 실패",
    "Revert": "되돌리기",
    "Some files were not reverted:\n": "일부 파일은 되돌리지 못했습니다:\n",
    "Reverted {n} file name(s)": "파일 {n}개를 되돌렸습니다",
    "Delete Actual Source Files": "실제 원본 파일 삭제",
    "Move {n} file(s) on disk to the Recycle Bin?\n\n{listing}\n\n"
    "All references to these files in this project are removed{extra}.":
        "디스크의 파일 {n}개를 휴지통으로 보낼까요?\n\n{listing}\n\n"
        "이 프로젝트에서 이 파일들을 가리키는 참조도 모두 빠집니다{extra}.",
    " (including {n} copy/copies in other regions)": " (다른 영역의 복사본 {n}개 포함)",
    "Move to Recycle Bin": "휴지통으로 보내기",
    "Delete": "삭제",
    "Could not move to Recycle Bin (left untouched):\n": "휴지통으로 보내지 못했습니다 (그대로 둠):\n",
    "Moved {n} file(s) to the Recycle Bin": "파일 {n}개를 휴지통으로 보냈습니다",
    "No missing images": "누락된 이미지가 없습니다",
    "Find {n} missing image(s) in folder…": "누락된 이미지 {n}개를 찾을 폴더…",
    "No matching file names found there": "그 폴더에서 같은 이름의 파일을 찾지 못했습니다",
    "Relinked {n} of {total} missing image(s)": "누락된 이미지 {total}개 중 {n}개를 다시 연결했습니다",
    # ------------------------------------------------------------- saving
    "Image Scene Project": "이미지 장면 프로젝트",
    "Image Scene Region": "이미지 장면 영역",
    "All files (*)": "모든 파일 (*)",
    "Save failed": "저장 실패",
    "Could not save:\n{path}\n\n{err}": "저장하지 못했습니다:\n{path}\n\n{err}",
    "Saved {path}": "저장했습니다: {path}",
    "Save Project As": "프로젝트를 다른 이름으로 저장",
    "Save changes to the current project?": "현재 프로젝트의 변경 내용을 저장할까요?",
    "New project": "새 프로젝트를 시작했습니다",
    "Open Project": "프로젝트 열기",
    "Open failed": "열기 실패",
    "Could not open:\n{path}\n\n{err}": "열지 못했습니다:\n{path}\n\n{err}",
    "Opened {name}": "{name} 파일을 열었습니다",
    " — {n} image file(s) missing: File → Relink Missing Images":
        " — 이미지 파일 {n}개가 없습니다: 파일 → 누락된 이미지 다시 연결",
    "Save Region '{name}'": "'{name}' 영역 저장",
    "Saved region '{name}' to {path}": "'{name}' 영역을 저장했습니다: {path}",
    "Load Saved Region": "저장된 영역 불러오기",
    "Load failed": "불러오기 실패",
    "Could not load region:\n{path}\n\n{err}": "영역을 불러오지 못했습니다:\n{path}\n\n{err}",
    "Loaded region '{name}' ({n} images)": "'{name}' 영역을 불러왔습니다 (이미지 {n}장)",
    "Autosaved": "자동 저장했습니다",
    "Autosave failed: {err}": "자동 저장 실패: {err}",
    "Restore Autosave": "자동 저장 복구",
    "{app} did not shut down normally last time.\n\nRestore the autosave from {when}?":
        "{app}이(가) 지난번에 정상적으로 종료되지 않았습니다.\n\n{when}에 자동 저장된 내용을 복구할까요?",
    "Restored from autosave — save to keep it": "자동 저장에서 복구했습니다 — 유지하려면 저장하세요",
    "Restore failed": "복구 실패",
    # ------------------------------------------------------------- viewer
    "Image Viewer": "크게 보기",
    "Fit to Screen": "화면에 맞추기",
    "Close (Esc)": "닫기 (Esc)",
    "cannot open ({err})": "열 수 없음 ({err})",
    # -------------------------------------------------------- bulk rename
    "Rename Actual Files by Order — {name}": "순서대로 실제 파일 이름 바꾸기 — {name}",
    "Name pattern": "이름 형식",
    "Start at": "시작 번호",
    "Digits": "자릿수",
    "Current file": "현재 파일",
    "New file": "새 파일",
    "Status": "상태",
    "rename": "이름 바꿈",
    "already named": "이미 같은 이름",
    "file missing - skipped": "파일 없음 - 건너뜀",
    "same file listed twice - skipped": "같은 파일이 두 번 있음 - 건너뜀",
    "CONFLICT: target exists": "충돌: 같은 이름의 파일이 이미 있음",
    "This renames the REAL files on disk (extensions are kept). The project file is saved afterwards so "
    "it points to the new names. A rename log is written so the operation can be reverted "
    "(File → Revert Last File Rename/Move).":
        "디스크의 실제 파일 이름을 바꿉니다 (확장자는 유지). 끝나면 새 이름을 가리키도록 프로젝트 파일을 "
        "저장합니다. 기록이 남으므로 되돌릴 수 있습니다 (파일 → 마지막 파일 이름 변경/이동 되돌리기).",
    "Apply Rename": "이름 바꾸기 실행",
    "{n} file(s) will be renamed": "파일 {n}개의 이름이 바뀝니다",
    ", {n} conflict(s) — change the pattern or start number": ", 충돌 {n}개 — 이름 형식이나 시작 번호를 바꾸세요",
    ", {n} {what}": ", {what} {n}개",
    # -------------------------------------------------------- preferences
    "Preferences": "환경설정",
    "Enable autosave": "자동 저장 사용",
    "Autosave interval": "자동 저장 간격",
    " min": "분",
    "Autosave writes to a separate recovery file and never overwrites your project file. "
    "After a crash you are offered to restore it on next start.":
        "자동 저장은 별도의 복구 파일에만 쓰며 프로젝트 파일을 덮어쓰지 않습니다. "
        "비정상 종료 후 다음에 실행하면 복구할지 묻습니다.",
    # -------------------------------------------------------------- errors
    "Unexpected error": "예기치 않은 오류",
    "{etype}: {value}\n\nDetails were written to\n{log}\n\nYour project is still open - save it with "
    "File → Save As.":
        "{etype}: {value}\n\n자세한 내용을 다음 파일에 기록했습니다:\n{log}\n\n"
        "프로젝트는 아직 열려 있습니다 — 파일 → 다른 이름으로 저장으로 저장하세요.",
}
