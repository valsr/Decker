import os
import tomllib


class Setting[T]:
    def __init__(self, key: str, value: T):
        self._key = key
        self._value = value

    @property
    def key(self) -> str:
        return self._key

    @property
    def value(self) -> T:
        return self._value

    def is_type(self, class_or_tuple: __builtins__._ClassInfo) -> bool:
        return isinstance(self._value, class_or_tuple)


class ConfigFileBackend:
    def __init__(self, path: str):
        self._path = path

    def load(self) -> list[Setting]:
        if not os.path.exists(self._path):
            raise FileNotFoundError(f"Config file not found: {self._path}")
        if not os.access(self._path, os.R_OK):
            raise PermissionError(f"Cannot read config file: {self._path}")

        with open(self._path, 'rb', encoding="UTF-8") as file:
            config_data = tomllib.load(file)

        settings = []
        def process_dict(prefix, d):
            for key, value in d.items():
                full_key = f"{prefix}.{key}" if prefix else key
                if isinstance(value, dict):
                    process_dict(full_key, value)
                else:
                    settings.append(Setting(full_key, value))

        process_dict("", config_data)
        return settings

    def save(self, settings: list[Setting]) -> None:
        pass
