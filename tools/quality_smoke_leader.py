"""Use a freshly evaluated leader for isolated workflow acceptance only."""
from __future__ import annotations

import hashlib
import json
from quality_routing import QualityEvidence

from sumika_core.quality.selection import FixedEvaluationSample
from tools.activate_model_roles import validate_report


def use_evaluated_leader(service, report_path, stack):
    if report_path is None:
        return None
    report = json.loads(report_path.read_text(encoding='utf-8'))
    profile = service.app.storage.get_provider_profile(report['profile_id'])
    candidate_id = validate_report(report, profile)
    if report['purpose'] != 'leader':
        raise ValueError('leader evaluation required')
    settings = service.settings('sumika')
    if candidate_id not in settings['candidate_pool']:
        raise ValueError('evaluated leader must already belong to the authorized pool')
    digest = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
    for sample in report['samples']:
        service.record_fixed_sample('sumika', FixedEvaluationSample(
            digest[:32] + ':' + sample['id'], candidate_id, report['model_version'], 'leader',
            'role-activation-leader', 'v1', '1', True, sample['observed_at'], sample['observed_at'] + 7 * 86400))
    qualified = service.selection_qualification('sumika', candidate_id, model_version=report['model_version'])
    if not qualified['qualified']:
        raise ValueError('test leader does not meet the current cohort')
    storage = service.app.storage
    for key in ('quality-routing/settings/v1', 'quality-routing/last-auto-leader:sumika'):
        original = storage.get_meta(key)
        stack.callback(storage.set_meta, key, original or '')
    service.update_settings({'assistant_id': 'sumika', 'leader_candidate_id': candidate_id,
                             'selection_mode': {**settings['selection_mode'], 'leader': 'fixed'}})
    return candidate_id


def use_evaluated_executor(service, report_path):
    if report_path is None:
        return None
    report = json.loads(report_path.read_text(encoding='utf-8'))
    profile = service.app.storage.get_provider_profile(report['profile_id'])
    candidate_id = validate_report(report, profile, bounded=True)
    if candidate_id not in service.settings('sumika')['candidate_pool']:
        raise ValueError('executor must belong to the authorized pool')
    expires = min(sample['observed_at'] for sample in report['samples']) + 86400
    service.register_quality_evidence(candidate_id, (QualityEvidence('bounded-text', 'bounded-text-v1', expires,
                                       'fixed-bounded-text-v1'),))
    return candidate_id
