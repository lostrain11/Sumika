"""Reference advice using the configured auxiliary model and existing usage store."""
import json
import sqlite3
from pathlib import Path
from contextlib import closing

from extensions.models.settings import load
from extensions.models.auxiliary import analyze_reference
from extensions.models.usage import UsageStore
from extensions.roles.chat import usage_counts


class ConfiguredReferenceAnalyzer:
    def __init__(self, settings_path):
        self.settings_path = settings_path
        self._settings()

    def _settings(self):
        settings = load(self.settings_path)
        if not settings['auxiliary']['enabled']:
            raise ValueError('configured auxiliary model is disabled')
        return settings

    def __call__(self, evidence):
        settings = self._settings()
        result = analyze_reference(settings, evidence)
        if settings['usage']['enabled']:
            database = Path(settings['role']['database'])
            database.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(database)) as connection:
                counts = usage_counts(result)
                UsageStore(connection).record(scope=settings['role']['project_id'],
                    session='reference-research', provider=settings['auxiliary']['provider'],
                    model=settings['auxiliary']['model'],
                    status='reported' if counts else 'unknown', **counts)
        if result['status'] != 'reported' or result.get('finish_reason') == 'length':
            raise ValueError('reference analysis result unavailable')
        return json.loads(result['text'])
