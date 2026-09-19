"""Opt-in host lifecycle. Core schedules remain in the independent extension."""
import json
import math
import time
from pathlib import Path
from extensions.desktop.schedule_service import ScheduleService
from extensions.desktop.schedule_dsh import DshScheduleBridge


class ExtensionHost:
    def __init__(self,adapter,config_path):
        self.service=None;self.next_tick=0
        config_path=Path(config_path).resolve(strict=True)
        config=json.loads(config_path.read_text(encoding='utf8'))
        if not isinstance(config,dict) or config.get('schema_version')!=1 or type(config.get('enabled')) is not bool:raise ValueError('invalid extension host configuration')
        self.enabled=config['enabled']
        if not self.enabled:return
        settings=config['schedules']
        self.interval=settings.get('interval_seconds',1)
        if type(self.interval) not in (int,float) or not math.isfinite(self.interval) or not .1<=self.interval<=60:raise ValueError('invalid schedule interval')
        directory=Path(settings['directory'])
        if not directory.is_absolute():raise ValueError('schedule directory must be absolute')
        bindings=settings.get('execution_bindings',{})
        if not isinstance(bindings,dict):raise ValueError('execution_bindings must be a mapping')
        for name,b in bindings.items():
            if not isinstance(b,dict) or type(b.get('enabled')) is not bool:raise ValueError('invalid execution binding')
            if not isinstance(b.get('fingerprint'),str) or len(b['fingerprint'])!=64:raise ValueError('full schedule fingerprint required')
            if not isinstance(b.get('action'),str) or not Path(b['workspace']).is_absolute():raise ValueError('explicit action/workspace required')
        directory.mkdir(parents=True,exist_ok=True)
        self.service=ScheduleService(directory/'schedules.json',directory/'history.sqlite3',bridge=DshScheduleBridge(adapter,bindings))

    def tick(self):
        if not self.enabled or time.monotonic()<self.next_tick:return []
        result=self.service.tick()
        self.next_tick=time.monotonic()+self.interval
        return result

    def close(self):
        if self.service:self.service.close();self.service=None
        self.enabled=False
