"""Explicit tick-driven scheduler; native Harness owns approval and execution.

No background process is installed. A crash after dispatch leaves UNKNOWN, and
never automatically repeats an operation whose result may already have occurred.
Expressions: once=ISO8601 with offset, daily=HH:MM UTC, weekly=0..6 HH:MM UTC.
"""
from datetime import datetime, timedelta, timezone
import sqlite3
from zoneinfo import ZoneInfo


def occurrence(schedule, now):
    if now.tzinfo is None: raise ValueError('timezone-aware clock required')
    now = now.astimezone(timezone.utc)
    if schedule.kind == 'once':
        due = datetime.fromisoformat(schedule.expression)
        if due.tzinfo is None: raise ValueError('once timestamp needs timezone')
        due = due.astimezone(timezone.utc)
    else:
        zone=timezone.utc if schedule.timezone_name=='UTC' else ZoneInfo(schedule.timezone_name)
        local=now.astimezone(zone)
        expression = schedule.expression
        weekday = None
        if schedule.kind == 'weekly':
            day, expression = expression.split()
            weekday = int(day)
            if not 0 <= weekday <= 6: raise ValueError('invalid weekday')
        hour, minute = map(int,expression.split(':'))
        due = local.replace(hour=hour,minute=minute,second=0,microsecond=0,fold=0)
        if weekday is not None: due -= timedelta(days=(due.weekday()-weekday)%7)
        if due.astimezone(timezone.utc) > now: due -= timedelta(days=7 if weekday is not None else 1)
        # Nonexistent spring-forward time is skipped, not shifted silently.
        if due.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)!=due.replace(tzinfo=None):return None
        due=due.astimezone(timezone.utc)
    return due if due <= now else None


class ScheduleRunner:
    def __init__(self,path,*,enabled=True):
        self.enabled=enabled
        self.db=sqlite3.connect(path) if enabled else None
        if self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS occurrences (id TEXT, due TEXT, state TEXT, receipt TEXT, PRIMARY KEY(id,due))')
            self.db.commit()
            self.db.execute('CREATE TABLE IF NOT EXISTS occurrence_errors (id TEXT, due TEXT, error_type TEXT, PRIMARY KEY(id,due))')
            self.db.commit()

    def tick(self,schedules,now,*,remind,dispatch):
        if not self.enabled: return []
        results=[]
        for schedule in schedules:
            if not schedule.enabled: continue
            due=occurrence(schedule,now)
            if due is None: continue
            key=(schedule.id,due.isoformat())
            with self.db:
                claimed=self.db.execute('INSERT OR IGNORE INTO occurrences VALUES (?,?,?,NULL)',(*key,'unknown')).rowcount
            if not claimed: continue
            state='unknown'; receipt=None
            try:
                # Caller uses the native approval flow; a schedule is not authority.
                receipt=(remind if schedule.mode=='reminder' else dispatch)(schedule, '/'.join(key))
                if not isinstance(receipt,str) or not receipt: raise ValueError('native receipt required')
                state='notified' if schedule.mode=='reminder' else 'submitted'
            except Exception as error:
                # Preserve UNKNOWN even when callback raised after performing its action.
                with self.db:self.db.execute('INSERT OR REPLACE INTO occurrence_errors VALUES (?,?,?)',(*key,type(error).__name__))
            with self.db:
                self.db.execute('UPDATE occurrences SET state=?,receipt=? WHERE id=? AND due=?',(state,receipt,*key))
            results.append(dict(id=key[0],due=key[1],state=state,receipt=receipt))
        return results

    def history(self):
        if not self.db: return []
        return [dict(id=i,due=d,state=s,receipt=r) for i,d,s,r in self.db.execute('SELECT * FROM occurrences ORDER BY due,id')]

    def reconcile(self, schedule_id, due, *, outcome, evidence):
        """Record checked external state; never execute or delete an occurrence.

        If an operation is known not to have happened, create a new explicitly
        approved schedule; the original UNKNOWN receipt remains in history.
        """
        if not self.enabled:return {'disabled':True}
        if outcome not in ('confirmed_completed','confirmed_not_executed','cancelled'):
            raise ValueError('unsupported reconciliation outcome')
        if not isinstance(evidence,str) or not evidence.strip():raise ValueError('reconciliation evidence required')
        with self.db:
            changed=self.db.execute('UPDATE occurrences SET state=?,receipt=? WHERE id=? AND due=? AND state=?',(outcome,evidence,schedule_id,due,'unknown')).rowcount
        if changed!=1:raise ValueError('only an existing UNKNOWN occurrence can be reconciled')
        return dict(id=schedule_id,due=due,state=outcome,evidence=evidence)

    def close(self):
        if self.db: self.db.close()
