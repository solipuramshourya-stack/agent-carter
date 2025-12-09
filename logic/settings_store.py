import json
import os

SETTINGS_FILE = "settings.json"


class SettingsStore:
    def __init__(self):
        self._data = {}
        self._load()

    def _load(self):
        """Load settings from local JSON file if it exists."""
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r") as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {}
        else:
            self._data = {}

    def _save(self):
        """Persist settings to local JSON file."""
        with open(SETTINGS_FILE, "w") as f:
            json.dump(self._data, f, indent=4)

    def get(self, key, default=None):
        """Get a setting, return default if missing."""
        return self._data.get(key, default)

    def set(self, key, value):
        """Update a setting and save it."""
        self._data[key] = value
        self._save()


# Singleton instance used by the app
settings_store = SettingsStore()
