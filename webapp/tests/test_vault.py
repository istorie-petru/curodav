"""The Accounts vault: KeePass format, entries, history, recycle bin, one-time codes, health, import and the open session."""

import shutil
import subprocess

import pytest

from src import db, vault_exchange as vx, vault_kdbx as kdbx, vault_service as vs, vault_session as session

TYPES = vs.DEFAULT_TYPES


@pytest.fixture(autouse=True)
def quick_kdf(monkeypatch):
    monkeypatch.setattr(kdbx, "DEFAULT_KDF", {"iterations": 2, "memory": 8 * 1024 * 1024, "parallelism": 1})
    session.lock_all()
    session._failures.clear()
    session._failures_loaded.clear()
    yield
    session.lock_all()


def _vault():
    database = kdbx.new_database("Test")
    uid = vs.save_entry(database, None, {"title": "Mail", "username": "ana", "password": "s3cr3t-ă", "url": "https://mail.example",
                                         "tags": ["work"], "custom": [{"key": "PIN", "value": "1234", "protected": True}]}, TYPES)
    return database, uid


def test_a_vault_round_trips_with_protected_values_and_a_key_file():
    database, uid = _vault()
    key_file = kdbx.make_key_file()
    data = kdbx.dump(database, kdbx.composite_key("pw", key_file))
    assert b"s3cr3t" not in data
    again = kdbx.load(data, kdbx.composite_key("pw", key_file))
    assert vs.secret(again, uid, "Password") == "s3cr3t-ă" and vs.secret(again, uid, "PIN") == "1234"
    for wrong in (kdbx.composite_key("pw"), kdbx.composite_key("nope", key_file)):
        with pytest.raises(kdbx.WrongKey):
            kdbx.load(data, wrong)
    with pytest.raises(kdbx.VaultError):
        kdbx.load(b"not a vault at all", kdbx.composite_key("pw"))


@pytest.mark.skipif(not shutil.which("keepassxc-cli"), reason="KeePassXC is not installed")
def test_keepassxc_opens_a_vault_written_here(tmp_path):
    database, _ = _vault()
    path = tmp_path / "v.kdbx"
    path.write_bytes(kdbx.dump(database, kdbx.composite_key("pw")))
    out = subprocess.run(["keepassxc-cli", "show", "-s", "-q", str(path), "Mail"], input="pw\n", capture_output=True, text=True, timeout=60)
    assert "Password: s3cr3t-ă" in out.stdout and "UserName: ana" in out.stdout


def test_detail_hides_secrets_and_edits_keep_history_and_go_through_the_bin():
    database, uid = _vault()
    detail = vs.entry_detail(database, uid, TYPES)
    assert detail["has_password"] and detail["custom"] == [{"key": "PIN", "value": "", "protected": True, "kind": "secret"}]
    vs.save_entry(database, uid, {"title": "Mail", "username": "ana2", "password": "new", "custom": []}, TYPES)
    assert vs.entry_detail(database, uid, TYPES)["history"] == 1 and vs.edit_values(database, uid)["custom"] == []
    vs.restore_version(database, uid, 0)
    assert vs.secret(database, uid, "Password") == "s3cr3t-ă" and vs.secret(database, uid, "PIN") == "1234"
    assert vs.delete_entry(database, uid) == "binned" and vs.list_entries(database) == []
    assert [e["uuid"] for e in vs.list_entries(database, trash=True)] == [uid]
    vs.restore_entry(database, uid)
    assert [e["title"] for e in vs.list_entries(database, query="mail")] == ["Mail"]
    vs.delete_entry(database, uid)
    assert vs.empty_bin(database) == 1 and vs.find_entry(database, uid) is None


def test_reserved_names_and_bad_codes_are_refused():
    database, _ = _vault()
    for data, field in (({"title": ""}, "title"), ({"title": "X", "otp": "not base32!"}, "otp"),
                        ({"title": "X", "custom": [{"key": "Password", "value": "x"}]}, "custom")):
        with pytest.raises(vs.EntryError) as err:
            vs.save_entry(database, None, data, TYPES)
        assert err.value.field == field


def test_totp_matches_the_rfc_6238_vector():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # "12345678901234567890" in base32
    assert vs.totp(f"otpauth://totp/x?secret={secret}&digits=8", at=59)["code"] == "94287082"
    assert vs.totp("otpauth://totp/x?secret=!!") is None


def test_generator_and_health():
    made = vs.generate(24, symbols=False, min_digits=5)
    pw = made["value"]
    assert len(pw) == 24 and pw.isalnum() and not set(pw) & vs.LOOKALIKES and sum(c.isdigit() for c in pw) >= 5 and made["bits"] > 100
    custom = vs.generate(12, lower=False, upper=False, digits=False, symbols=True, symbol_set="#@", min_symbols=3)["value"]
    assert set(custom) <= {"#", "@"}
    phrase = vs.memorable(6, separator=".", capitalize=True, number=False)
    assert phrase["value"].count(".") == 5 and phrase["value"][0].isupper() and vs.rating(phrase["bits"]) in ("Fair", "Strong", "Very strong")
    database, uid = _vault()
    vs.save_entry(database, None, {"title": "Bank", "password": "s3cr3t-ă"}, TYPES)
    report = vs.health(database)
    assert {r["title"] for r in report["reused"]} == {"Mail", "Bank"} and report["weak"] and report["total"] == 2


def test_imports_from_csv_bitwarden_and_keepass_skip_what_is_already_there():
    database, _ = _vault()
    csv_rows = vx.read_import("chrome.csv", b"name,url,username,password,note\nMail,https://mail.example,ana,x,\nShop,https://shop.example,bo,y,hi\n")
    assert vx.preview(database, csv_rows) == {"count": 2, "duplicates": 1, "new": 1, "groups": []}
    bw = vx.read_import("bw.json", b'{"encrypted": false, "folders": [{"id": "f", "name": "Home"}], "items": [{"name": "Wifi", "folderId": "f", '
                                    b'"login": {"username": "", "password": "w", "uris": []}}]}')
    assert bw[0]["group"] == "Home" and bw[0]["password"] == "w"
    other, _ = _vault()
    kdbx_rows = vx.read_import("old.kdbx", kdbx.dump(other, kdbx.composite_key("other")), "other")
    assert kdbx_rows[0]["password"] == "s3cr3t-ă"
    with pytest.raises(vx.ImportError_):
        vx.read_import("old.kdbx", kdbx.dump(other, kdbx.composite_key("other")), "wrong")
    assert vx.apply(database, csv_rows + bw, TYPES) == 2
    assert {e["title"] for e in vs.list_entries(database)} == {"Mail", "Shop", "Wifi"}
    assert "Password" in vx.export_csv(database).splitlines()[0]


def test_session_creates_unlocks_throttles_and_locks(tmp_path):
    with db.connect(tmp_path / "t.db") as conn:
        token = session.create(conn, "master", None)
        assert session.vault_path(conn).stat().st_mode & 0o777 == 0o600
        state = session.current(conn, token)
        vs.save_entry(state.db, None, {"title": "Kept"}, TYPES)
        session.save(conn, state)
        session.lock(token)
        assert session.current(conn, token) is None
        for _ in range(session.FREE_TRIES):
            with pytest.raises(kdbx.WrongKey):
                session.unlock(conn, "wrong", None)
        with pytest.raises(PermissionError):
            session.unlock(conn, "master", None)
        session._failures.clear()
        again = session.unlock(conn, "master", None)
        assert [e["title"] for e in vs.list_entries(session.current(conn, again).db)] == ["Kept"]
        assert session.vault_path(conn).with_name("accounts.kdbx.bak").exists()
        db.set_app_meta(conn, session.IDLE_KEY, "1")
        session._open[session._key(again)].touched -= 120
        assert session.current(conn, again) is None


def test_groups_are_the_spaces_and_entries_are_filed_by_space():
    database, uid = _vault()
    assert vs.sync_spaces(database, ["Personal", "University"]) is True
    assert vs.sync_spaces(database, ["personal", "University"]) is False
    other = vs.save_entry(database, None, {"title": "Moodle", "space": "University"}, TYPES)
    known = {"personal", "university"}
    assert [e["title"] for e in vs.list_entries(database, space="University", known=known)] == ["Moodle"]
    assert [e["title"] for e in vs.list_entries(database, space="", known=known)] == ["Mail"]
    assert vs.summary(database, vs.find_entry(database, other))["space"] == "University"
    rows = vx.read_import("x.csv", b"title,username,password,group\nShop,bo,y,Old/Stuff\n")
    vx.apply(database, rows, TYPES, space="Personal")
    shop = next(e for e in vs.list_entries(database, space="Personal", known=known))
    assert shop["title"] == "Shop" and shop["tags"] == ["Stuff"]


def test_a_single_field_changes_in_place_and_keeps_the_old_version():
    database, uid = _vault()
    vs.set_field(database, uid, "UserName", "ana2")
    vs.set_field(database, uid, "PIN", "9999")
    vs.set_field(database, uid, "Password", "new-secret")
    assert vs.secret(database, uid, "UserName") == "ana2" and vs.secret(database, uid, "PIN") == "9999"
    assert vs.entry_detail(database, uid, TYPES)["history"] == 3
    assert vs.entry_detail(database, uid, TYPES)["custom"][0]["protected"] is True
    for key, value in (("Nope", "x"), ("otp", "x"), ("Title", " ")):
        with pytest.raises(vs.EntryError):
            vs.set_field(database, uid, key, value)


def test_a_changed_field_can_be_put_back_from_the_history():
    database, uid = _vault()
    assert vs.is_secret(database, uid, "Password") and vs.is_secret(database, uid, "PIN") and not vs.is_secret(database, uid, "UserName")
    assert vs.set_field(database, uid, "Password", "second") is True and vs.set_field(database, uid, "Password", "second") is False
    vs.undo_field(database, uid, "Password")
    assert vs.secret(database, uid, "Password") == "s3cr3t-ă"
    with pytest.raises(vs.EntryError):
        vs.undo_field(vs.save_entry(database, None, {"title": "New"}, TYPES) and database, "missing", "Password")


def _stamp_later(path):
    import os

    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))


def test_protected_values_are_sealed_in_memory_and_open_only_when_read():
    from src import vault_merge  # noqa: F401  (imported here so a broken module fails this test too)

    database, uid = _vault()
    entry = vs.find_entry(database, uid)
    sealed = [v for v in entry.iter("Value") if v.get("Protected") == "True"]
    assert sealed and all(v.get("Sealed") == "1" and "s3cr3t" not in (v.text or "") for v in sealed)
    assert vs.secret(database, uid, "Password") == "s3cr3t-ă"
    reloaded = kdbx.load(kdbx.dump(database, kdbx.composite_key("pw")), kdbx.composite_key("pw"))
    assert vs.secret(reloaded, uid, "Password") == "s3cr3t-ă"


def test_the_vault_file_changed_outside_is_reloaded_and_merged_not_overwritten(tmp_path):
    with db.connect(tmp_path / "t.db") as conn:
        token = session.create(conn, "master-pass", None)
        mine = session.current(conn, token)
        keep = vs.save_entry(mine.db, None, {"title": "Mine"}, TYPES)
        session.save(conn, mine)
        path = session.vault_path(conn)
        key = kdbx.composite_key("master-pass")

        # someone edits the file elsewhere (KeePassXC): adds an entry and renames ours
        elsewhere = kdbx.load(path.read_bytes(), key)
        vs.save_entry(elsewhere, None, {"title": "From outside"}, TYPES)
        vs.save_entry(elsewhere, keep, {"title": "Mine, renamed outside"}, TYPES)
        path.write_bytes(kdbx.dump(elsewhere, key))
        _stamp_later(path)

        # a plain visit shows it
        seen = session.current(conn, token)
        assert {e["title"] for e in vs.list_entries(seen.db)} == {"Mine, renamed outside", "From outside"} and "outside" in seen.notice

        # a save made while the file moved underneath merges instead of overwriting
        path.write_bytes(kdbx.dump(kdbx.load(path.read_bytes(), key), key))  # the file is touched again
        vs.save_entry(seen.db, None, {"title": "Added here"}, TYPES)
        other = kdbx.load(path.read_bytes(), key)
        vs.save_entry(other, None, {"title": "Added elsewhere meanwhile"}, TYPES)
        path.write_bytes(kdbx.dump(other, key))
        _stamp_later(path)
        session.save(conn, seen)
        titles = {e["title"] for e in vs.list_entries(kdbx.load(path.read_bytes(), key))}
        assert {"Added here", "Added elsewhere meanwhile", "From outside"} <= titles and "merged" in seen.notice.lower()


def test_a_deletion_made_outside_wins_unless_the_entry_changed_after():
    from src import vault_merge

    local, uid = _vault()
    remote = kdbx.load(kdbx.dump(local, kdbx.composite_key("k")), kdbx.composite_key("k"))
    vs.delete_entry(remote, uid)
    vs.delete_entry(remote, uid)  # into the bin, then for good
    assert vault_merge.merge(local, remote)["removed"] == 1 and vs.find_entry(local, uid) is None


def test_vault_copies_are_kept_and_the_wrong_tries_survive_a_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "SNAPSHOT_GAP", 0)
    with db.connect(tmp_path / "t.db") as conn:
        token = session.create(conn, "master-pass", None)
        state = session.current(conn, token)
        for i in range(3):
            vs.save_entry(state.db, None, {"title": f"E{i}"}, TYPES)
            session.save(conn, state)
            __import__("time").sleep(1.1)
        copies = session.list_snapshots(conn)
        assert copies and all((session.snapshot_path(conn, c["name"]) or tmp_path).is_file() for c in copies)
        assert session.snapshot_path(conn, "../t.db") is None and session.snapshot_path(conn, "accounts-x/../../y.kdbx") is None
        session.lock(token)
        for _ in range(session.FREE_TRIES):
            with pytest.raises(kdbx.WrongKey):
                session.unlock(conn, "nope", None)
        session._failures.clear()  # the process restarts
        session._failures_loaded.clear()
        assert session.wait_seconds(conn) > 0
        with pytest.raises(PermissionError):
            session.unlock(conn, "master-pass", None)


def test_several_server_processes_are_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    with db.connect(tmp_path / "t.db") as conn:
        with pytest.raises(kdbx.VaultError):
            session.create(conn, "master-pass", None)


def test_damaged_vault_files_never_crash_the_reader():
    import random

    database, _ = _vault()
    key = kdbx.composite_key("pw")
    good = kdbx.dump(database, key)
    rng = random.Random(7)
    for _ in range(150):
        data = bytearray(good)
        for _ in range(rng.randint(1, 6)):
            data[rng.randrange(len(data))] = rng.randrange(256)
        if rng.random() < 0.3:
            data = data[:rng.randrange(1, len(data))]
        try:
            kdbx.load(bytes(data), key)
        except kdbx.VaultError:
            pass  # WrongKey is a VaultError too: every damaged file ends in a clean refusal


def test_several_entries_move_and_change_together_and_delete_or_restore():
    database, first = _vault()
    vs.sync_spaces(database, ["Personal", "University"])
    second = vs.save_entry(database, None, {"title": "Moodle", "tags": ["uni"]}, TYPES)
    known = {"personal", "university"}
    changed = vs.bulk_edit(database, [first, second, "missing"], space="University", add_tags=["shared"], remove_tags=["uni", "work"], type_key="api", types=TYPES)
    assert changed == 2
    rows = {r["title"]: r for r in vs.list_entries(database, space="University", known=known)}
    assert set(rows) == {"Mail", "Moodle"} and rows["Mail"]["tags"] == ["shared"] and rows["Moodle"]["type"] == "api"
    assert vs.entry_detail(database, first, TYPES)["history"] == 1
    assert vs.bulk_edit(database, [first], space="University", types=TYPES) == 0  # nothing to change
    with pytest.raises(vs.EntryError):
        vs.bulk_edit(database, [first], type_key="nope", types=TYPES)
    assert vs.move_entry(database, second, "") is True and vs.list_entries(database, space="", known=known)[0]["title"] == "Moodle"
    assert vs.delete_entries(database, [first, second]) == (2, 0) and vs.list_entries(database) == []
    assert vs.restore_entries(database, [first, second, "x"]) == 2
    vs.delete_entries(database, [first])
    assert vs.delete_entries(database, [first]) == (0, 1)
