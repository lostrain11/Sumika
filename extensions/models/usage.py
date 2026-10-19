"""Provider-neutral usage estimates and reported token accounting."""
import math
import sqlite3

# P06 business categories. A row's category decides which metric applies to
# it: token categories are unknown only when their tokens are missing, and an
# audio row without tokens is NOT a token unknown.
CATEGORIES = ('room', 'companion', 'routing', 'behavior', 'audio', 'vision')
CATEGORY_METRICS = {
    'room': ('prompt_tokens', 'completion_tokens', 'total_tokens'),
    'companion': ('prompt_tokens', 'completion_tokens', 'total_tokens'),
    'routing': ('prompt_tokens', 'completion_tokens', 'total_tokens'),
    'behavior': ('prompt_tokens', 'completion_tokens', 'total_tokens'),
    'audio': ('audio_seconds',),
    'vision': ('vision_calls',),
}

class UsageStore:
    """Token accounting with P5 audio/vision and P6 business categories.

    Migration is additive: existing databases gain nullable audio_seconds,
    vision_calls and category columns. Older rows keep NULL everywhere, which
    totals report as unknown instead of folding into zero; a legacy row is
    migrated to a category only when its session identifies one determinably
    (see ``migrate_categories``), otherwise it stays ``unknown``.
    """

    def __init__(self, database, *, enabled=True):
        self.db=database; self.enabled=enabled
        self.db.execute('CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY, scope TEXT, session TEXT, provider TEXT, model TEXT, status TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER)'); self.db.commit()
        columns={row[1] for row in self.db.execute('PRAGMA table_info(usage)')}
        if 'audio_seconds' not in columns:
            self.db.execute('ALTER TABLE usage ADD COLUMN audio_seconds REAL')
        if 'vision_calls' not in columns:
            self.db.execute('ALTER TABLE usage ADD COLUMN vision_calls INTEGER')
        if 'category' not in columns:
            self.db.execute('ALTER TABLE usage ADD COLUMN category TEXT')
        self.db.commit()
    def record(self, *, scope, session, provider, model, prompt_tokens=None, completion_tokens=None, total_tokens=None, status='unknown', audio_seconds=None, vision_calls=None, category=None):
        if not self.enabled:return {'disabled':True}
        if status not in ('estimated','reported','unknown'):raise ValueError('invalid usage status')
        if category is not None and category not in CATEGORIES:
            raise ValueError('invalid usage category')
        vals=[prompt_tokens,completion_tokens,total_tokens]
        if any(x is not None and (type(x) is not int or x<0) for x in vals):raise ValueError('invalid token count')
        if audio_seconds is not None and (type(audio_seconds) not in (int,float)
                or not math.isfinite(audio_seconds) or audio_seconds < 0):
            raise ValueError('invalid audio seconds')
        if vision_calls is not None and (type(vision_calls) is not int or vision_calls < 0):
            raise ValueError('invalid vision call count')
        self.db.execute('INSERT INTO usage(scope,session,provider,model,status,prompt_tokens,completion_tokens,total_tokens,audio_seconds,vision_calls,category) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(scope,session,provider,model,status,*vals,audio_seconds,vision_calls,category)); self.db.commit(); return {'status':status}

    def migrate_categories(self, *, rules):
        """Backfill the category of legacy rows when determinable.

        ``rules`` maps an exact session id (or a ``'room-*'`` prefix pattern)
        to a category; anything unmatched stays NULL and is reported as an
        unknown category — never guessed.
        """
        if not isinstance(rules, dict) or not rules:
            raise ValueError('category migration rules required')
        for session_pattern, category in rules.items():
            if category not in CATEGORIES:
                raise ValueError('invalid usage category')
            if session_pattern.endswith('*'):
                self.db.execute('UPDATE usage SET category=? WHERE category IS NULL AND session LIKE ?',
                                (category, session_pattern[:-1] + '%'))
            else:
                self.db.execute('UPDATE usage SET category=? WHERE category IS NULL AND session=?',
                                (category, session_pattern))
        self.db.commit()
        return {'status': 'migrated'}

    def totals(self, scope, session=None):
        """Aggregate one scope; per-metric unknowns stay unknown.

        Top-level token columns keep their historical zero fill. Category
        sums preserve NULL when no row measured a metric, and unknown_count
        counts each incomplete request once. Audio seconds and vision calls only exist on rows that
        measured them, so their sums are ``None`` (unknown) unless at least
        one row carries a real value — never silently zero.

        The P6 ``categories`` view groups rows by business category with the
        metrics that APPLY to each: ``known_sum`` sums present values,
        ``unknown_count`` counts rows missing an applicable metric (an audio
        row without tokens is not a token unknown), and ``by_status`` keeps
        the estimated/reported/unknown split. Rows recorded before the
        category column report ``unknown`` applicability.
        """
        sql=('SELECT COALESCE(SUM(prompt_tokens),0),COALESCE(SUM(completion_tokens),0),'
             'COALESCE(SUM(total_tokens),0),'
             'SUM(audio_seconds),SUM(vision_calls),'
             'SUM(CASE WHEN status=\'unknown\' THEN 1 ELSE 0 END),'
             'COUNT(*) FROM usage WHERE scope=?'); args=[scope]
        if session is not None: sql+=' AND session=?'; args.append(session)
        p,c,t,a,v,u,n=self.db.execute(sql,args).fetchone()
        group_sql=('SELECT COALESCE(category,\'unknown\'),COUNT(*),'
                   'SUM(prompt_tokens),SUM(completion_tokens),SUM(total_tokens),'
                   'SUM(CASE WHEN prompt_tokens IS NULL OR completion_tokens IS NULL '
                   'OR total_tokens IS NULL THEN 1 ELSE 0 END),'
                   'SUM(audio_seconds),SUM(CASE WHEN audio_seconds IS NULL THEN 1 ELSE 0 END),'
                   'SUM(vision_calls),SUM(CASE WHEN vision_calls IS NULL THEN 1 ELSE 0 END),'
                   'SUM(CASE WHEN status=\'estimated\' THEN 1 ELSE 0 END),'
                   'SUM(CASE WHEN status=\'reported\' THEN 1 ELSE 0 END),'
                   'SUM(CASE WHEN status=\'unknown\' THEN 1 ELSE 0 END) '
                   'FROM usage WHERE scope=?')
        group_args=[scope]
        if session is not None: group_sql+=' AND session=?'; group_args.append(session)
        group_sql+=' GROUP BY COALESCE(category,\'unknown\')'
        categories={}
        for row in self.db.execute(group_sql,group_args).fetchall():
            (name,requests,pt,ct,tt,pt_unknown,au,au_unknown,vi,vi_unknown,
             estimated,reported,status_unknown)=row
            metrics=CATEGORY_METRICS.get(name)
            if metrics is None:
                applicability='unknown'
                unknown_count=requests
                known={}
            else:
                applicability=list(metrics)
                known={}
                unknown_count=0
                if 'prompt_tokens' in metrics:
                    known['prompt_tokens']=pt
                    known['completion_tokens']=ct
                    known['total_tokens']=tt
                    unknown_count+=pt_unknown or 0
                if 'audio_seconds' in metrics:
                    known['audio_seconds']=au
                    unknown_count+=au_unknown or 0
                if 'vision_calls' in metrics:
                    known['vision_calls']=vi
                    unknown_count+=vi_unknown or 0
            categories[name]={'requests':requests or 0,
                              'metric_applicability':applicability,
                              'known_sum':known,
                              'unknown_count':unknown_count,
                              'by_status':{'estimated':estimated or 0,
                                           'reported':reported or 0,
                                           'unknown':status_unknown or 0}}
        return {'prompt_tokens':p,'completion_tokens':c,'total_tokens':t,
                'audio_seconds':a,'vision_calls':v,
                'unknown_status_rows':u or 0,'rows':n or 0,
                'categories':categories}
