"""Manage local schedules/reminders. Client lifecycle owns execution bridge."""
import argparse
import json
from pathlib import Path
import threading
from extensions.desktop.scheduler import Schedule
from extensions.desktop.schedule_service import ScheduleService


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path,required=True)
    p.add_argument('operation',choices=('status','list','upsert','disable','remove','tick','watch','history','reminders','acknowledge','reconcile'))
    p.add_argument('--input',type=Path);p.add_argument('--id');p.add_argument('--due');p.add_argument('--outcome');p.add_argument('--evidence')
    a=p.parse_args();a.directory.mkdir(parents=True,exist_ok=True)
    s=ScheduleService(a.directory/'schedules.json',a.directory/'history.sqlite3')
    try:
        if a.operation=='upsert':
            if not a.input:p.error('--input required')
            job=Schedule(**json.loads(a.input.read_text(encoding='utf8')));s.store.upsert(job);result=job.to_dict()
        elif a.operation=='status':result=s.status()
        elif a.operation=='list':result=[x.to_dict() for x in s.store.load()]
        elif a.operation=='disable':s.disable(a.id);result={'disabled':a.id}
        elif a.operation=='remove':s.store.remove(a.id);result={'removed':a.id}
        elif a.operation=='tick':result=s.tick()
        elif a.operation=='history':result=s.runner.history()
        elif a.operation=='reminders':result=s.reminders()
        elif a.operation=='acknowledge':s.acknowledge(a.id);result={'acknowledged':a.id}
        elif a.operation=='reconcile':result=s.runner.reconcile(a.id,a.due,outcome=a.outcome,evidence=a.evidence)
        else:
            try:s.run(threading.Event())
            except KeyboardInterrupt:pass
            result={'stopped':True}
        print(json.dumps(result,ensure_ascii=False));return 0
    except (ValueError,OSError,KeyError,TypeError) as error:p.exit(2,str(error)+'\n')
    finally:s.close()


if __name__=='__main__':raise SystemExit(main())
