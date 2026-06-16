"""Icon pack manifest.json and icons.json validation."""

import json
from dataclasses import dataclass
from pathlib import Path

_REQUIRED_MANIFEST_FIELDS = ("Name", "Version", "Author")


class IconPackValidationError(ValueError):
    """An icon pack's manifest.json or icons.json failed validation."""


@dataclass(frozen=True)
class IconPackManifest:
    """Validated contents of an icon pack's manifest.json."""

    name: str
    version: str
    author: str

    @classmethod
    def load(cls, manifest_path: Path) -> "IconPackManifest":
        """Read and validate manifest.json. Raises IconPackValidationError."""
        data = _load_json_object(manifest_path)
        missing = [field for field in _REQUIRED_MANIFEST_FIELDS if field not in data]
        if missing:
            missing_str = ", ".join(missing)
            raise IconPackValidationError(f"manifest.json missing required field(s): {missing_str}")
        return cls(name=str(data["Name"]), version=str(data["Version"]), author=str(data["Author"]))


def validate_icons_json(icons_path: Path) -> None:
    """Validate that icons.json exists and parses to a JSON object or array. Raises IconPackValidationError."""
    try:
        data = json.loads(icons_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise IconPackValidationError(f"could not read {icons_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise IconPackValidationError(f"malformed JSON in {icons_path}: {exc}") from exc
    if not isinstance(data, (dict, list)):
        raise IconPackValidationError(f"{icons_path} must contain a JSON object or array")


def _load_json_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise IconPackValidationError(f"could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise IconPackValidationError(f"malformed JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise IconPackValidationError(f"{path} must contain a JSON object")
    return data
