import logging

from autoresearch.observability import get_logger


def test_context_logger_adds_run_context(caplog) -> None:  # type: ignore[no-untyped-def]
    logger = get_logger(
        "validator",
        run_id="run_1",
        project_id="project_1",
        task_id="task_1",
    )

    with caplog.at_level(logging.INFO, logger="autoresearch.validator"):
        logger.info("validated")

    record = caplog.records[0]
    assert record.run_id == "run_1"
    assert record.component == "validator"
    assert record.project_id == "project_1"
    assert record.task_id == "task_1"


def test_context_logger_uses_placeholder_defaults(caplog) -> None:  # type: ignore[no-untyped-def]
    logger = get_logger("scheduler")

    with caplog.at_level(logging.INFO, logger="autoresearch.scheduler"):
        logger.info("queued")

    record = caplog.records[0]
    assert record.run_id == "-"
    assert record.component == "scheduler"
    assert record.project_id == "-"
    assert record.task_id == "-"
