"""Thin adapter to an owned DSH instance. No HTTP endpoint trust or model routing.

The caller supplies a managed instance and explicitly enabled schedule bindings.
Native DSH policies continue to approve tools. Persisted schedules cannot enable
their own execution or choose a profile, workspace, credentials or model.
"""
import hashlib
from pathlib import Path


class DshScheduleBridge:
    def __init__(self,adapter,bindings):
        self.adapter=adapter
        self.instance_id=adapter.instance.instance_id
        self.bindings={key:dict(value) for key,value in bindings.items()}

    @staticmethod
    def session_id(key):return 'sumika-schedule-'+hashlib.sha256(key.encode()).hexdigest()[:32]

    def _binding(self,schedule):
        from sumika_next.contracts import Trust
        if self.adapter.instance.trust != Trust.MANAGED:raise PermissionError('managed Harness required')
        if self.adapter.instance.instance_id!=self.instance_id:raise PermissionError('Harness instance changed')
        value=self.bindings.get(schedule.id)
        if not value or value.get('enabled') is not True:raise PermissionError('schedule execution binding disabled')
        # Exact immutable action snapshot prevents edited schedules inheriting approval.
        if value.get('action')!=schedule.action:raise PermissionError('schedule changed; rebind explicitly')
        if value.get('fingerprint') is not None and value['fingerprint']!=schedule.fingerprint():raise PermissionError('schedule revision changed; rebind explicitly')
        root=Path(value['workspace']).resolve(strict=True)
        if not root.is_dir():raise ValueError('workspace missing')
        return root

    def dispatch(self,schedule,key):
        root=self._binding(schedule)
        session=self.session_id(key)
        self.adapter._rpc('session/create',{'sessionId':session,'cwd':str(root)})
        result=self.adapter._rpc('session/prompt',{'sessionId':session,'requestId':session,'mode':'queue','content':[{'type':'text','text':schedule.action}]})
        if result!={'accepted':True}:raise RuntimeError('DSH did not acknowledge scheduled prompt')
        return session

    def cancel(self,schedule,key):
        self._binding(schedule)
        session=self.session_id(key)
        result=self.adapter._rpc('session/cancel',{'sessionId':session})
        if result!={'accepted':True}:raise RuntimeError('DSH did not acknowledge cancellation')
        return {'session':session,'status':'cancel_requested','boundary':'inspect native history to confirm completion; no automatic retry'}
