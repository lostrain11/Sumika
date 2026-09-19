"""Provider-neutral usage estimates and reported token accounting."""
import sqlite3

class UsageStore:
    def __init__(self, database, *, enabled=True):
        self.db=database; self.enabled=enabled
        self.db.execute('CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY, scope TEXT, session TEXT, provider TEXT, model TEXT, status TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER)'); self.db.commit()
    def record(self, *, scope, session, provider, model, prompt_tokens=None, completion_tokens=None, total_tokens=None, status='unknown'):
        if not self.enabled:return {'disabled':True}
        if status not in ('estimated','reported','unknown'):raise ValueError('invalid usage status')
        vals=[prompt_tokens,completion_tokens,total_tokens]
        if any(x is not None and (type(x) is not int or x<0) for x in vals):raise ValueError('invalid token count')
        self.db.execute('INSERT INTO usage(scope,session,provider,model,status,prompt_tokens,completion_tokens,total_tokens) VALUES(?,?,?,?,?,?,?,?)',(scope,session,provider,model,status,*vals)); self.db.commit(); return {'status':status}
    def totals(self, scope, session=None):
        sql='SELECT COALESCE(SUM(prompt_tokens),0),COALESCE(SUM(completion_tokens),0),COALESCE(SUM(total_tokens),0) FROM usage WHERE scope=?'; args=[scope]
        if session is not None: sql+=' AND session=?'; args.append(session)
        p,c,t=self.db.execute(sql,args).fetchone(); return {'prompt_tokens':p,'completion_tokens':c,'total_tokens':t}
