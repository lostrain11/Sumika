"""Failure-closed boundary for continuity writes used by diagnostics."""
import sqlite3

from extensions.continuity.continuity import ingest


def ingest_observations(root, request):
    """Write host observations or return a safe unknown diagnostic.

    A broken/unavailable continuity store is not an empty success. The caller
    must preserve the unknown result and decide recovery separately; this
    helper never retries and never includes exception text or payloads.
    """
    try:
        result = ingest(root, request)
    except (OSError, sqlite3.Error) as error:
        return {
            'status': 'unknown',
            'source': 'continuity.ingest',
            'provenance': 'observed_write_failure',
            'error_kind': type(error).__name__,
            'error_code': 'continuity-write-failed',
            'retry': False,
        }
    return {'status': 'recorded', 'source': 'continuity.ingest',
            'provenance': 'observed_write', 'result': result}
