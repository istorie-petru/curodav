"""The log helper keeps lines at four levels for the live view and never shows a secret."""

from src import log


def test_the_log_view_filters_by_level():
    logger = log.get_logger("tests.levels")
    start = log.entries("all")[-1]["id"] if log.entries("all") else 0
    logger.debug("quiet detail")
    logger.info("something happened")
    logger.warning("careful")
    logger.error("it broke")
    messages = lambda level: [e["message"] for e in log.entries(level, after=start)]
    assert messages("all") == ["quiet detail", "something happened", "careful", "it broke"]
    assert messages("important") == ["something happened"]
    assert messages("warnings") == ["careful"]
    assert messages("errors") == ["it broke"]


def test_a_secret_in_a_log_line_is_hidden():
    logger = log.get_logger("tests.secrets")
    start = log.entries("all")[-1]["id"]
    logger.info("login with password=hunter2 and token: abc123")
    shown = log.entries("all", after=start)[0]["message"]
    assert "hunter2" not in shown and "abc123" not in shown


def test_entries_report_only_what_is_new():
    logger = log.get_logger("tests.after")
    logger.info("first")
    seen = log.entries("all")[-1]["id"]
    logger.info("second")
    assert [e["message"] for e in log.entries("all", after=seen)] == ["second"]
