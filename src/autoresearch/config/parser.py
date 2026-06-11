"""Configuration parser and formatter for JSON, YAML, and TOML files."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from .models import SystemConfig

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    tomllib = None  # type: ignore[assignment]

try:
    import toml as legacy_toml
except ModuleNotFoundError:  # pragma: no cover - covered by current Python with tomllib
    legacy_toml = None  # type: ignore[assignment]

ConfigModel = TypeVar("ConfigModel", bound=BaseModel)


class ConfigFormat(str, Enum):
    """Supported configuration file formats."""

    JSON = "json"
    YAML = "yaml"
    TOML = "toml"

    @classmethod
    def from_path(cls, path: Path) -> "ConfigFormat":
        suffix = path.suffix.lower()
        if suffix == ".json":
            return cls.JSON
        if suffix in {".yaml", ".yml"}:
            return cls.YAML
        if suffix == ".toml":
            return cls.TOML
        raise ValueError(
            f"Unsupported configuration file extension '{path.suffix}' for {path}. "
            "Expected .json, .yaml, .yml, or .toml."
        )


class ConfigParser:
    """Parse and format AutoResearch configuration models."""

    def parse_file(
        self,
        path: str | Path,
        model_type: type[ConfigModel] = SystemConfig,
        config_format: ConfigFormat | None = None,
    ) -> ConfigModel:
        config_path = Path(path)
        detected_format = config_format or ConfigFormat.from_path(config_path)
        try:
            text = config_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"Could not read configuration file {config_path}: {exc}") from exc
        return self.parse_text(text, model_type=model_type, config_format=detected_format)

    def parse_text(
        self,
        text: str,
        model_type: type[ConfigModel] = SystemConfig,
        config_format: ConfigFormat = ConfigFormat.YAML,
    ) -> ConfigModel:
        data = self._load_mapping(text, config_format)
        try:
            return model_type.model_validate(data)
        except ValidationError as exc:
            raise ValueError(
                f"Invalid {model_type.__name__} configuration schema: {exc}"
            ) from exc

    def format(
        self,
        config: BaseModel,
        config_format: ConfigFormat = ConfigFormat.YAML,
    ) -> str:
        data = config.model_dump(mode="json")
        if config_format == ConfigFormat.JSON:
            return json.dumps(data, indent=2, sort_keys=True) + "\n"
        if config_format == ConfigFormat.YAML:
            return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        if config_format == ConfigFormat.TOML:
            return self._dump_toml(data)
        raise ValueError(f"Unsupported configuration format: {config_format}")

    def write_file(
        self,
        config: BaseModel,
        path: str | Path,
        config_format: ConfigFormat | None = None,
    ) -> None:
        config_path = Path(path)
        detected_format = config_format or ConfigFormat.from_path(config_path)
        config_path.write_text(self.format(config, detected_format), encoding="utf-8")

    def _load_mapping(self, text: str, config_format: ConfigFormat) -> dict[str, Any]:
        if config_format == ConfigFormat.JSON:
            data = self._load_json(text)
        elif config_format == ConfigFormat.YAML:
            data = self._load_yaml(text)
        elif config_format == ConfigFormat.TOML:
            data = self._load_toml(text)
        else:
            raise ValueError(f"Unsupported configuration format: {config_format}")

        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError(
                f"Invalid {config_format.value.upper()} configuration: top-level value "
                "must be a mapping/object."
            )
        return data

    def _load_json(self, text: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON configuration at line {exc.lineno}, column {exc.colno}: "
                f"{exc.msg}"
            ) from exc

    def _load_yaml(self, text: str) -> Any:
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML configuration: {exc}") from exc

    def _load_toml(self, text: str) -> Any:
        try:
            if tomllib is not None:
                return tomllib.loads(text)
            if legacy_toml is not None:
                return legacy_toml.loads(text)
            raise ValueError("No TOML parser is available. Install toml on Python 3.10.")
        except Exception as exc:
            raise ValueError(f"Invalid TOML configuration: {exc}") from exc

    def _dump_toml(self, data: dict[str, Any]) -> str:
        lines: list[str] = []
        table_lines: list[str] = []

        for key, value in data.items():
            if isinstance(value, dict):
                table_lines.extend(self._dump_toml_table(key, value))
            else:
                lines.append(f"{key} = {self._format_toml_value(value)}")

        if lines and table_lines:
            return "\n".join(lines) + "\n\n" + "\n".join(table_lines) + "\n"
        if table_lines:
            return "\n".join(table_lines) + "\n"
        return "\n".join(lines) + "\n"

    def _dump_toml_table(self, table_name: str, values: dict[str, Any]) -> list[str]:
        lines = [f"[{table_name}]"]
        nested_tables: list[str] = []

        for key, value in values.items():
            if isinstance(value, dict):
                nested_tables.extend(self._dump_toml_table(f"{table_name}.{key}", value))
            else:
                lines.append(f"{key} = {self._format_toml_value(value)}")

        if nested_tables:
            lines.append("")
            lines.extend(nested_tables)
        return lines

    def _format_toml_value(self, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int | float):
            return str(value)
        if isinstance(value, list):
            return "[" + ", ".join(self._format_toml_value(item) for item in value) + "]"
        if value is None:
            raise ValueError("TOML does not support null values in configuration output.")
        return json.dumps(str(value))
