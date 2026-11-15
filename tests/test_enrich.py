import json
import os
import shutil
import struct
import subprocess
from datetime import datetime
from pathlib import Path

import click
import pytest
from PIL import Image

from enrich_gallery3_photo_exif import db, interactive, metadata, planning


def box(name: bytes, body: bytes = b"") -> bytes:
    return struct.pack(">I4s", 8 + len(body), name) + body


def make_mp4(path: Path) -> None:
    """Write a minimal MP4 with one track and zeroed creation times."""
    mvhd = box(b"mvhd", bytes(4) + bytes(8) + struct.pack(">II", 1000, 0) + bytes(80))
    tkhd = box(b"tkhd", bytes(4) + bytes(8) + bytes(72))
    mdhd = box(b"mdhd", bytes(4) + bytes(8) + struct.pack(">II", 1000, 0) + bytes(4))
    hdlr = box(b"hdlr", bytes(8) + b"vide" + bytes(13))
    trak = box(b"trak", tkhd + box(b"mdia", mdhd + hdlr))
    path.write_bytes(
        box(b"ftyp", b"isom" + bytes(4) + b"isom")
        + box(b"moov", mvhd + trak)
        + box(b"mdat", b"video")
    )


def make_jpeg(path: Path) -> None:
    Image.new("RGB", (4, 4)).save(path, "JPEG")


needs_exiftool = pytest.mark.skipif(
    not shutil.which("exiftool"), reason="exiftool is not installed"
)
TAGS = {
    "tags_list": ["1993/valley-view", "Valley View Middle School"],
    "hierarchical": ["1993|valley-view"],
    "keywords": ["1993", "valley-view", "Valley View Middle School"],
}


JPEG_TAGS = {**TAGS, "iptc_keywords": TAGS["keywords"]}


def exiftool_json(path: Path, *args: str) -> dict:
    out = subprocess.run(
        ["exiftool", "-j", *args, str(path)],
        check=False,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out)[0]


def test_detect_format(tmp_path: Path) -> None:
    make_jpeg(tmp_path / "a.jpg")
    make_mp4(tmp_path / "a.mp4")
    Image.new("RGB", (4, 4)).save(tmp_path / "a.png")
    (tmp_path / "a.txt").write_text("hello")
    assert metadata.detect_format(tmp_path / "a.jpg") == "jpeg"
    assert metadata.detect_format(tmp_path / "a.mp4") == "mp4"
    # Even when misnamed, PNG must not be treated as JPEG
    assert metadata.detect_format(tmp_path / "a.png") is None
    assert metadata.detect_format(tmp_path / "a.txt") is None


@needs_exiftool
@pytest.mark.parametrize("fmt", ["jpeg", "mp4"])
def test_update_file_roundtrip(tmp_path: Path, fmt: str) -> None:
    path = tmp_path / "a.bin"
    (make_jpeg if fmt == "jpeg" else make_mp4)(path)
    os.utime(path, (1_000_000_000, 1_000_000_000))
    assert metadata.read_metadata_bulk([path])[path.resolve()] == (
        None,
        None,
        {"tags_list": [], "hierarchical": [], "keywords": [], "iptc_keywords": []},
        "",
    )
    before = path.stat()  # after the read above, which may touch atime

    tags = planning.wanted_tags(
        {"tags": TAGS}, {"format": fmt, "gallery_tags": ["Café ☕"]}
    )
    for _ in range(2):  # repeating must not duplicate tags
        metadata.update_file(
            path,
            fmt,
            "Café ☕",
            datetime(2020, 1, 2, 3, 4, 5),
            tags,
            "[2008-01-23 Kathy] AZ Mom\nGreat ☕",
        )

    after = path.stat()
    assert after.st_mtime_ns == before.st_mtime_ns
    assert after.st_atime_ns == before.st_atime_ns
    assert metadata.read_metadata_bulk([path])[path.resolve()] == (
        "Café ☕",
        "2020:01:02 03:04:05",
        {
            "tags_list": tags["tags_list"],
            "hierarchical": tags["hierarchical"],
            "keywords": tags["keywords"],
            "iptc_keywords": tags.get("iptc_keywords", []),
        },
        "[2008-01-23 Kathy] AZ Mom\nGreat ☕",
    )
    found = exiftool_json(path, "-TagsList", "-HierarchicalSubject", "-Subject")
    assert found["TagsList"] == tags["tags_list"]
    assert found["HierarchicalSubject"] == tags["hierarchical"]
    assert [str(tag) for tag in found["Subject"]] == tags["keywords"]
    if fmt == "jpeg":
        iptc = exiftool_json(path, "-IPTC:Keywords", "-IPTC:CodedCharacterSet")
        assert [str(tag) for tag in iptc["Keywords"]] == tags["keywords"]
    assert [p.name for p in tmp_path.iterdir()] == ["a.bin"]


@needs_exiftool
def test_update_mp4_sets_all_header_times(tmp_path: Path) -> None:
    path = tmp_path / "a.mp4"
    make_mp4(path)
    metadata.update_file(path, "mp4", "", datetime(2020, 1, 2, 3, 4, 5), TAGS)
    found = exiftool_json(
        path, "-G0", "-a", "-TrackCreateDate", "-MediaCreateDate", "-Description"
    )
    assert found["QuickTime:TrackCreateDate"] == "2020:01:02 03:04:05"
    assert found["QuickTime:MediaCreateDate"] == "2020:01:02 03:04:05"
    assert "ItemList:Description" not in found


@needs_exiftool
def test_update_file_failure_keeps_original(tmp_path: Path) -> None:
    path = tmp_path / "a.jpg"
    path.write_bytes(b"not a jpeg")
    with pytest.raises(RuntimeError):
        metadata.update_file(path, "jpeg", "x", datetime(2020, 1, 1), TAGS)
    assert path.read_bytes() == b"not a jpeg"
    assert [p.name for p in tmp_path.iterdir()] == ["a.jpg"]


class FakeCursor:
    def __init__(self, row: tuple) -> None:
        self.row = row

    def execute(self, *args: object) -> None:
        pass

    def fetchone(self) -> tuple:
        return self.row


class FakeConn:
    def __init__(self, row: tuple) -> None:
        self.row = row

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.row)


def test_get_album_info() -> None:
    info = db.get_album_info(FakeConn(("1993/valley-view", "Valley View/MS")), 132)
    assert info["tags"] == {
        "tags_list": ["1993/valley-view", "Valley View-MS"],
        "hierarchical": ["1993|valley-view"],
        "keywords": ["1993", "valley-view", "Valley View-MS"],
    }
    assert info["year_hint"] == datetime(1993, 1, 1)


def test_get_album_info_without_year() -> None:
    info = db.get_album_info(FakeConn(("trips/beach", "")), 1)
    assert info["tags"]["tags_list"] == ["trips/beach"]
    assert info["year_hint"] is None


def test_prompt_datetime_defaults_to_captured_then_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(click, "prompt", lambda *a, default, **k: default)
    captured = datetime(2001, 2, 3, 4, 5, 6)
    year = datetime(1993, 1, 1)
    photo = {"datetime_original": None, "captured": captured}
    assert interactive.prompt_datetime(photo, datetime(2000, 1, 1), year) == captured
    photo = {"datetime_original": None}
    assert interactive.prompt_datetime(photo, None, year) == year


def test_prompt_datetime_reprompts_on_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["nonsense", "2020:01:02 03:04:05"])
    monkeypatch.setattr(click, "prompt", lambda *a, **k: next(answers))
    photo = {"datetime_original": None}
    assert interactive.prompt_datetime(photo, None) == datetime(2020, 1, 2, 3, 4, 5)


def test_prompt_datetime_last_plus_five(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(click, "prompt", lambda *a, **k: "2")
    photo = {"datetime_original": None}
    last = datetime(2020, 1, 1, 0, 0, 0)
    assert interactive.prompt_datetime(photo, last) == datetime(2020, 1, 1, 0, 5, 0)


def test_prompt_description_skips_empty_option(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["1", "2"])
    monkeypatch.setattr(click, "prompt", lambda *a, **k: next(answers))
    photo = {
        "filename": "a.jpg",
        "exif_description": None,
        "description": "desc",
        "title": None,
    }
    assert interactive.prompt_description(photo) == "desc"


def photo_with_tags(**tags: list[str]) -> dict:
    return {"filename": "a.jpg", "tags": tags}


def test_resolve_tags_no_prompt_when_nothing_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*a: object, **k: object) -> str:
        raise AssertionError("should not prompt")

    monkeypatch.setattr(click, "prompt", fail)
    photo = photo_with_tags(tags_list=["1993/valley-view"], keywords=["1993"])
    assert interactive.resolve_tags(photo, TAGS) == TAGS
    assert interactive.resolve_tags({"filename": "a.jpg", "tags": {}}, TAGS) == TAGS


@pytest.mark.parametrize(
    ("choice", "expected_keywords"),
    [
        ("o", ["1993", "valley-view", "Valley View Middle School"]),
        ("m", ["mine", "1993", "valley-view", "Valley View Middle School"]),
        ("k", []),
    ],
)
def test_resolve_tags_prompts_before_dropping(
    monkeypatch: pytest.MonkeyPatch, choice: str, expected_keywords: list[str]
) -> None:
    monkeypatch.setattr(click, "prompt", lambda *a, **k: choice)
    photo = photo_with_tags(keywords=["mine", "1993"])
    assert interactive.resolve_tags(photo, TAGS)["keywords"] == expected_keywords


class ScriptedCursor:
    """Answer each query with the rows whose key appears in its SQL."""

    def __init__(self, results: dict[str, list[tuple]]) -> None:
        self.results = results
        self.rows: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.rows = next(rows for key, rows in self.results.items() if key in sql)

    def fetchall(self) -> list[tuple]:
        return self.rows


class ScriptedConn:
    def __init__(self, results: dict[str, list[tuple]]) -> None:
        self.results = results

    def cursor(self) -> ScriptedCursor:
        return ScriptedCursor(self.results)


def day(epoch: int) -> str:
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d")


def test_get_db_content_attaches_tags_and_comments() -> None:
    conn = ScriptedConn(
        {
            "FROM comments": [
                (
                    16216,
                    1201114185,
                    "Anonymous coward",
                    " AZ Mom\nKathy ",
                    "guest",
                    "Guest User",
                    1,
                ),
                (16216, 1355815963, "", "Nice", "jdoe", "John Doe", 0),
            ],
            "FROM items_tags": [(16216, "Lego"), (16216, "Sun/Moon")],
            "FROM items": [
                (16216, "a.jpg", "desc and more", "desc", None),
                (16217, "b.jpg", None, "Title", 1355750153),
            ],
        }
    )
    first, second = db.get_db_content(conn, 132)
    assert first["gallery_tags"] == ["Lego", "Sun-Moon"]
    assert first["comments"] == [
        f"[{day(1201114185)} Anonymous coward] AZ Mom\nKathy",
        f"[{day(1355815963)} John Doe (jdoe)] Nice",
    ]
    assert first["title"] is None  # redundant with the description
    assert first["captured"] is None
    assert second["gallery_tags"] == second["comments"] == []
    assert second["captured"] == datetime.fromtimestamp(1355750153)


def test_wanted_tags_adds_gallery_tags() -> None:
    album = {"tags": TAGS}
    wanted = planning.wanted_tags(album, {"gallery_tags": ["Lego", "1993"]})
    assert wanted["tags_list"] == [*TAGS["tags_list"], "Lego", "1993"]
    assert wanted["hierarchical"] == ["1993|valley-view", "Lego", "1993"]
    assert wanted["keywords"] == [
        "1993",
        "valley-view",
        "Valley View Middle School",
        "Lego",
    ]


def test_approve_comments_asks_per_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter([True, False, True])
    monkeypatch.setattr(click, "confirm", lambda *a, **k: next(answers))
    photo = {
        "filename": "a.jpg",
        "exif_comment": "[old] kept",
        "comments": ["[old] kept", "[1] good", "[2] spam", "[3] also good"],
    }
    assert (
        interactive.approve_comments(photo) == "[old] kept\n\n[1] good\n\n[3] also good"
    )


def test_approve_comments_none_approved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(click, "confirm", lambda *a, **k: False)
    assert (
        interactive.approve_comments({"filename": "a", "comments": ["[1] spam"]})
        is None
    )
    assert interactive.approve_comments({"filename": "a", "comments": []}) is None


def make_photo(**overrides: object) -> dict:
    photo = {
        "filename": "a.jpg",
        "format": "jpeg",
        "description": None,
        "title": None,
        "captured": None,
        "exif_description": None,
        "datetime_original": None,
        "tags": {"tags_list": [], "hierarchical": [], "keywords": []},
        "exif_comment": "",
        "gallery_tags": [],
        "comments": [],
    }
    return photo | overrides


def test_plan_photo_and_noop() -> None:
    album = {"tags": TAGS, "year_hint": datetime(1993, 1, 1)}
    photo = make_photo()
    plan = planning.plan_photo(photo, None, album["year_hint"])
    assert plan["date"] == datetime(1993, 1, 1)
    assert plan["date_source"] == "album year"
    assert not planning.plan_is_noop(photo, plan, planning.wanted_tags(album, photo))

    done = make_photo(
        datetime_original="1993:01:01 00:00:00",
        tags={**JPEG_TAGS, "tags_list": [*TAGS["tags_list"], "extra"]},
    )
    plan = planning.plan_photo(done, None, None)
    assert plan["date_source"] == "existing"
    assert planning.plan_is_noop(done, plan, planning.wanted_tags(album, done))

    with_comment = {**done, "comments": ["[1] new"]}
    assert not planning.plan_is_noop(
        with_comment, plan, planning.wanted_tags(album, done)
    )
    assert planning.plan_photo(make_photo(), None, None) is None


def test_bulk_phase_applies_only_what_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    album = {"tags": TAGS, "year_hint": datetime(1993, 1, 1)}
    saved = []
    monkeypatch.setattr(
        interactive,
        "save_photo",
        lambda photo, description, date, last, album: (
            saved.append((photo["filename"], date)) or date
        ),
    )
    monkeypatch.setattr(click, "prompt", lambda *a, **k: "y")
    photos = [
        make_photo(filename="a.jpg"),
        make_photo(filename="b.jpg"),
        make_photo(
            filename="c.jpg",
            datetime_original="2000:01:01 00:00:00",
            exif_description=None,
            tags=JPEG_TAGS,
        ),
    ]
    interactive.bulk_phase(photos, album)
    # a gets the album year, b follows it by 5 minutes, c is already complete
    assert saved == [
        ("a.jpg", datetime(1993, 1, 1, 0, 0)),
        ("b.jpg", datetime(1993, 1, 1, 0, 5)),
    ]


def test_bulk_phase_declined(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(click, "prompt", lambda *a, **k: "n")
    monkeypatch.setattr(
        interactive, "save_photo", lambda *a: pytest.fail("should not save")
    )
    album = {"tags": TAGS, "year_hint": datetime(1993, 1, 1)}
    assert interactive.bulk_phase([make_photo()], album) is None


def test_wanted_tags_iptc_only_for_jpeg_and_truncated() -> None:
    long_tag = "é" * 40  # 80 bytes
    album = {"tags": TAGS}
    jpeg = planning.wanted_tags(album, {"format": "jpeg", "gallery_tags": [long_tag]})
    assert jpeg["iptc_keywords"] == [*TAGS["keywords"], "é" * 32]
    assert jpeg["keywords"][-1] == long_tag  # XMP has no limit
    assert "iptc_keywords" not in planning.wanted_tags(album, {"format": "mp4"})


def fields_by_name(photo: dict, album: dict, last: datetime | None = None) -> dict:
    plan = planning.plan_photo(photo, last, album["year_hint"])
    wanted = planning.wanted_tags(album, photo)
    return {
        name: (state, text)
        for name, state, text in planning.diff_fields(photo, plan, wanted)
    }


def test_diff_fields_marks_added_changed_and_same() -> None:
    album = {"tags": TAGS, "year_hint": datetime(1993, 1, 1)}

    fresh = fields_by_name(
        make_photo(gallery_tags=["Lego"], comments=["[1] hi"]), album
    )
    assert fresh["date"] == ("add", "1993:01:01 00:00:00 (album year)")
    assert fresh["description"] == ("same", "(none)")
    assert fresh["tags"][0] == "add"
    assert "+Lego" in fresh["tags"][1]
    assert fresh["comments"] == ("add", "1 to review (you approve each)")

    changed = fields_by_name(
        make_photo(
            datetime_original="2000:01:01 00:00:00",
            exif_description="old",
            description="new",
            title="new title",
            captured=datetime(2001, 2, 3, 4, 5, 6),
        ),
        album,
    )
    # An existing date and description are kept, so they're unchanged
    assert changed["date"] == ("same", "2000:01:01 00:00:00")
    assert changed["description"] == ("same", "'old'")

    done = fields_by_name(
        make_photo(datetime_original="1993:01:01 00:00:00", tags=JPEG_TAGS), album
    )
    assert {state for state, _ in done.values()} == {"same"}


def test_diff_fields_flags_tags_that_will_be_asked_about() -> None:
    album = {"tags": TAGS, "year_hint": datetime(1993, 1, 1)}
    photo = make_photo(
        datetime_original="1993:01:01 00:00:00",
        tags={**JPEG_TAGS, "keywords": ["mine", *TAGS["keywords"]]},
    )
    # Nothing to add, so the file isn't written and nothing is at risk
    assert fields_by_name(photo, album)["tags"][0] == "same"

    photo["gallery_tags"] = ["Lego"]
    state, text = fields_by_name(photo, album)["tags"]
    assert state == "change"
    assert "will ask about existing: mine" in text


def test_diff_fields_overwritten_date_is_yellow_change() -> None:
    album = {"tags": TAGS, "year_hint": None}
    photo = make_photo(
        datetime_original="2000:01:01 00:00:00", captured=datetime(2001, 1, 1)
    )
    plan = planning.plan_photo(photo, None, None)
    plan["date"] = datetime(2005, 6, 7, 8, 9, 10)
    plan["date_source"] = "custom"
    fields = {
        n: (s, t)
        for n, s, t in planning.diff_fields(
            photo, plan, planning.wanted_tags(album, photo)
        )
    }
    assert fields["date"] == (
        "change",
        "2000:01:01 00:00:00 → 2005:06:07 08:09:10 (custom)",
    )


def test_show_overview_prints_changed_and_unchanged(
    capsys: pytest.CaptureFixture,
) -> None:
    album = {"tags": TAGS, "year_hint": datetime(1993, 1, 1)}
    photos = [
        make_photo(filename="a.jpg"),
        make_photo(
            filename="b.jpg", datetime_original="1993:01:01 00:00:00", tags=JPEG_TAGS
        ),
        make_photo(filename="c.jpg"),
    ]
    plans = [
        planning.plan_photo(photos[0], None, album["year_hint"]),
        planning.plan_photo(photos[1], None, None),
        None,
    ]
    interactive.show_overview(photos, plans, album)
    out = capsys.readouterr().out
    assert "a.jpg" in out and "1993:01:01 00:00:00 (album year)" in out
    assert "unchanged: description, comments" in out
    assert "b.jpg  no change" in out
    assert "c.jpg  needs your input" in out
