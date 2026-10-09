"""Provider-neutral usage estimates and reported token accounting."""
import math
import sqlite3

class UsageStore:
    """Token accounting with P5 audio/vision extensions.

    Migration is additive: existing databases gain nullable audio_seconds and
    vision_calls columns, and older rows keep NULL, which totals report as
    unknown (``None``) instead of folding into zero.
    """

    def __init__(self, database, *, enabled=True):
        self.db=database; self.enabled=enabled
        self.db.execute('CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY, scope TEXT, session TEXT, provider TEXT, model TEXT, status TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER)'); self.db.commit()
        columns={row[1] for row in self.db.execute('PRAGMA table_info(usage)')}
        if 'audio_seconds' not in columns:
            self.db.execute('ALTER TABLE usage ADD COLUMN audio_seconds REAL')
        if 'vision_calls' not in columns:
            self.db.execute('ALTER TABLE usage ADD COLUMN vision_calls INTEGER')
        self.db.commit()
    def record(self, *, scope, session, provider, model, prompt_tokens=None, completion_tokens=None, total_tokens=None, status='unknown', audio_seconds=None, vision_calls=None):
        if not self.enabled:return {'disabled':True}
        if status not in ('estimated','reported','unknown'):raise ValueError('invalid usage status')
        vals=[prompt_tokens,completion_tokens,total_tokens]
        if any(x is not None and (type(x) is not int or x<0) for x in vals):raise ValueError('invalid token count')
        if audio_seconds is not None and (type(audio_seconds) not in (int,float)
                or not math.isfinite(audio_seconds) or audio_seconds < 0):
            raise ValueError('invalid audio seconds')
        if vision_calls is not None and (type(vision_calls) is not int or vision_calls < 0):
            raise ValueError('invalid vision call count')
        self.db.execute('INSERT INTO usage(scope,session,provider,model,status,prompt_tokens,completion_tokens,total_tokens,audio_seconds,vision_calls) VALUES(?,?,?,?,?,?,?,?,?,?)',(scope,session,provider,model,status,*vals,audio_seconds,vision_calls)); self.db.commit(); return {'status':status}
    def totals(self, scope, session=None):
        """Aggregate one scope; per-metric unknowns stay unknown.

        Token columns keep their historical zero fill: a recorded request with
        missing token values stores NULL and rolls into ``unknown_rows``
        instead. Audio seconds and vision calls only exist on rows that
        measured them, so their sums are ``None`` (unknown) unless at least
        one row carries a real value — never silently zero.
        """
        sql=('SELECT COALESCE(SUM(prompt_tokens),0),COALESCE(SUM(completion_tokens),0),'
             'COALESCE(SUM(total_tokens),0),'
             'SUM(audio_seconds),SUM(vision_calls),'
             'SUM(CASE WHEN status=\'unknown\' THEN 1 ELSE 0 END),'
             'COUNT(*) FROM usage WHERE scope=?'); args=[scope]
        if session is not None: sql+=' AND session=?'; args.append(session)
        p,c,t,a,v,u,n=self.db.execute(sql,args).fetchone()
        return {'prompt_tokens':p,'completion_tokens':c,'total_tokens':t,
                'audio_seconds':a,'vision_calls':v,
                'unknown_status_rows':u or 0,'rows':n or 0}
