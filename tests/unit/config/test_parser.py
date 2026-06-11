from pathlib import Path

import pytest

from autoresearch.config import ConfigFormat, ConfigParser, SystemConfig


@pytest.mark.parametrize(
    "config_format",
    [ConfigFormat.JSON, ConfigFormat.YAML, ConfigFormat.TOML],
)
def test_config_parser_round_trips_supported_formats(config_format: ConfigFormat) -> None:
    parser = ConfigParser()
    config = SystemConfig(
        project_root=Path("workspace"),
        max_cost_per_run_usd=2.5,
    )

    text = parser.format(config, config_format)
    parsed = parser.parse_text(text, config_format=config_format)

    assert parsed == config


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("config.json", ConfigFormat.JSON),
        ("config.yaml", ConfigFormat.YAML),
        ("config.yml", ConfigFormat.YAML),
        ("config.toml", ConfigFormat.TOML),
    ],
)
def test_config_format_detects_supported_extensions(path: str, expected: ConfigFormat) -> None:
    assert ConfigFormat.from_path(Path(path)) == expected


def test_config_format_rejects_unknown_extension() -> None:
    with pytest.raises(ValueError, match="Unsupported configuration file extension"):
        ConfigFormat.from_path(Path("config.ini"))


@pytest.mark.parametrize(
    ("config_format", "text", "message"),
    [
        (ConfigFormat.JSON, "{", "Invalid JSON configuration"),
        (ConfigFormat.YAML, "key: [", "Invalid YAML configuration"),
        (ConfigFormat.TOML, "key = ", "Invalid TOML configuration"),
    ],
)
def test_config_parser_reports_syntax_errors(
    config_format: ConfigFormat,
    text: str,
    message: str,
) -> None:
    parser = ConfigParser()

    with pytest.raises(ValueError, match=message):
        parser.parse_text(text, config_format=config_format)


def test_config_parser_reports_schema_errors() -> None:
    parser = ConfigParser()

    with pytest.raises(ValueError, match="Invalid SystemConfig configuration schema"):
        parser.parse_text(
            "compute:\n  max_memory_mb: 64\n",
            config_format=ConfigFormat.YAML,
        )


def test_config_parser_reads_and_writes_files(tmp_path: Path) -> None:
    parser = ConfigParser()
    path = tmp_path / "config.yaml"
    config = SystemConfig(log_level="DEBUG")

    parser.write_file(config, path)

    assert parser.parse_file(path) == config
