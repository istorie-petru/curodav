"""The Calibre audit: findings between the library folder and Curodav, and the fixes."""

from src import db, media_books, media_calibre_audit as audit


def _library(tmp_path, conn):
    folder = tmp_path / "lib"
    assert media_books.set_library_path(conn, str(folder)) is None
    return media_books.library(conn)


def test_the_audit_finds_and_fixes_each_kind(tmp_path):
    from src import calibre_library as cl

    with db.connect(tmp_path / "c.sqlite") as c:
        lib = _library(tmp_path, c)
        lib.add_book(cl.BookMeta(title="Only Calibre", authors=["Ann Lee"], author_sorts=["Lee, Ann"]))
        db.upsert_citation(c, {"title": "Only Curodav", "type": "book", "authors": [{"family": "Poe", "given": "Edgar"}]})
        kinds = {r["kind"] for r in audit.audit(c)}
        assert {"new", "unlinked"} <= kinds
        assert audit.fix_all(c) >= 2
        assert audit.audit(c) == []


def test_auto_off_stops_the_pull(tmp_path):
    from src import calibre_library as cl

    with db.connect(tmp_path / "c.sqlite") as c:
        lib = _library(tmp_path, c)
        lib.add_book(cl.BookMeta(title="Later", authors=["A B"], author_sorts=["B, A"]))
        audit.set_auto(c, False)
        assert media_books.pull(c) == {"updated": 0, "unlinked": 0, "added": 0}
        assert [r["kind"] for r in audit.audit(c)] == ["new"]
        audit.set_auto(c, True)
        assert media_books.pull(c)["added"] == 1


def test_a_second_import_adds_nothing_and_an_existing_entry_is_linked(tmp_path):
    from src import calibre_library as cl

    with db.connect(tmp_path / "c.sqlite") as c:
        lib = _library(tmp_path, c)
        lib.add_book(cl.BookMeta(title="Dune", authors=["Frank Herbert"], author_sorts=["Herbert, Frank"]))
        lib.add_book(cl.BookMeta(title="Emma", authors=["Jane Austen"], author_sorts=["Austen, Jane"]))
        mine = db.upsert_citation(c, {"title": "Dune", "type": "book", "authors": [{"family": "Herbert", "given": "Frank"}], "status": "current"})
        assert media_books.import_books(c) == 1  # Emma is new, Dune is linked to the entry that already exists
        assert media_books.import_books(c) == 0
        assert len(db.list_citations(c)) == 2
        assert any(e["calibre_uuid"] for e in db.list_editions(c, mine))


def test_copies_of_one_calibre_book_are_removed_but_worked_on_entries_stay(tmp_path):
    from src import calibre_library as cl

    with db.connect(tmp_path / "c.sqlite") as c:
        lib = _library(tmp_path, c)
        u = lib.add_book(cl.BookMeta(title="Dune", authors=["Frank Herbert"], author_sorts=["Herbert, Frank"]))
        made = []
        for status in ("", "", "current"):
            uid = db.upsert_citation(c, {"title": "Dune", "type": "book", "status": status})
            db.set_edition_calibre(c, db.save_edition(c, uid, {}), u, "")
            made.append(uid)
        assert [r["kind"] for r in audit.audit(c) if r["kind"] == "dupe"] == ["dupe"]
        audit.apply(c, [f"dupe:{u}"])
        left = {x["uid"] for x in db.list_citations(c)}
        assert made[2] in left and len(left) == 1
        assert lib.book(u) is not None  # Calibre's book is untouched


def test_maintenance_jobs_report_and_fix(tmp_path):
    from src import calibre_library as cl

    with db.connect(tmp_path / "c.sqlite") as c:
        lib = _library(tmp_path, c)
        u = lib.add_book(cl.BookMeta(title="Dune", authors=["Frank Herbert"], author_sorts=["Herbert, Frank"]))
        for _ in range(3):
            uid = db.upsert_citation(c, {"title": "Dune", "type": "book"})
            db.set_edition_calibre(c, db.save_edition(c, uid, {}), u, "")
        audit.run_job(c, "check")
        assert "1 books have more than one entry (2 extra" in audit.job_state(c)["message"]
        audit.run_job(c, "dedupe")
        assert audit.job_state(c)["state"] == "done" and len(db.list_citations(c)) == 1
        audit.run_job(c, "reimport_metadata")
        assert audit.job_state(c)["state"] == "done"


def test_a_job_records_its_progress(tmp_path):
    from src import calibre_library as cl

    with db.connect(tmp_path / "c.sqlite") as c:
        lib = _library(tmp_path, c)
        for n in range(3):
            lib.add_book(cl.BookMeta(title=f"Book {n}", authors=["A B"], author_sorts=["B, A"]))
        audit.run_job(c, "reimport_list")
        state = audit.job_state(c)
        assert state["state"] == "done" and state["label"] == "Reimport the list" and (state["done"], state["total"]) == (3, 3)
