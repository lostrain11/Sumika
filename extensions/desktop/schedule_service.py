"""Foreground schedule host with durable local reminders and explicit stop.

Use run(stop_event) from a client lifecycle, or tick() from a native timer.
No autostart entry or paid model is configured by this module.
"""
import json
from datetime import datetime,timezone
from pathlib import Path
from extensions.desktop.scheduler import ScheduleStore
from extensions.desktop.schedule_runner import ScheduleRunner


class ScheduleService:
    def __init__(self,schedules,history,*,bridge=None,enabled=True):
        self.enabled=enabled;self.bridge=bridge
        self.store=ScheduleStore(schedules) if enabled else None
        self.runner=ScheduleRunner(history,enabled=enabled)
        if enabled:
            self.runner.db.execute('CREATE TABLE IF NOT EXISTS reminders (key TEXT PRIMARY KEY, text TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0)')
            self.runner.db.commit()

    def _remind(self,schedule,key):
        with self.runner.db:self.runner.db.execute('INSERT OR IGNORE INTO reminders(key,text) VALUES (?,?)',(key,schedule.action))
        return key

    def tick(self,now=None):
        if not self.enabled:return []
        # Serialize definition edits with snapshot admission to avoid dispatching
        # a stale enabled snapshot after another process has disabled it.
        with self.store.editing():
            schedules=self.store.load()
            eligible=[s for s in schedules if s.mode=='reminder' or self.bridge is not None]
            result=self.runner.tick(eligible,now or datetime.now(timezone.utc),remind=self._remind,dispatch=self.bridge.dispatch if self.bridge else None)
        return result

    def status(self):
        if not self.enabled:return {'enabled':False,'blocked':[]}
        return {'enabled':True,'blocked':[{'id':s.id,'reason':'execution backend not connected'} for s in self.store.load() if s.enabled and s.mode=='execute' and self.bridge is None]}

    def reminders(self,*,unread=True):
        if not self.enabled:return []
        return [dict(key=k,text=t,seen=bool(s)) for k,t,s in self.runner.db.execute('SELECT key,text,seen FROM reminders'+(' WHERE seen=0' if unread else '')+' ORDER BY rowid')]

    def acknowledge(self,key):
        if not self.enabled:return {'disabled':True}
        with self.runner.db:self.runner.db.execute('UPDATE reminders SET seen=1 WHERE key=?',(key,))

    def disable(self,schedule_id):
        if not self.enabled:return {'disabled':True}
        self.store.disable(schedule_id)

    def cancel(self,schedule_id,due):
        if not self.enabled:return {'disabled':True}
        schedule=next((s for s in self.store.load() if s.id==schedule_id),None)
        if schedule is None:raise ValueError('schedule missing')
        self.store.disable(schedule_id)
        if not self.bridge:raise ValueError('native cancellation backend unavailable')
        record=next((r for r in self.runner.history() if r['id']==schedule_id and r['due']==due),None)
        if not record or record['state'] not in ('submitted','unknown'):raise ValueError('no cancellable occurrence')
        return self.bridge.cancel(schedule,schedule_id+'/'+due)

    def reconcile(self, schedule_id, due, outcome, evidence):
        if not self.enabled: return {'disabled': True}
        return self.runner.reconcile(schedule_id, due, outcome=outcome, evidence=evidence)

    def run(self,stop_event,*,interval=1):
        if not self.enabled:return
        if not isinstance(interval,(int,float)) or not 0.1<=interval<=60:raise ValueError('invalid polling interval')
        while not stop_event.is_set():
            self.tick()
            stop_event.wait(interval)

    def close(self):self.runner.close()
