"""Read-only synthetic task probes of an installed MiniCPM. No product activation."""
import json,time,sys,hashlib,statistics,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from extensions.models.ollama import OllamaProvider
CASES=[
 ('extract_contact','extraction','从文本提取姓名、日期、人数，缺失字段填null。只输出JSON，字段name,date,people。','李明预约了2026-10-03的参观，人数还没确定。',{'name':'李明','date':'2026-10-03','people':None}),
 ('extract_update','extraction','提取最新饮料和看动画时间，输出JSON字段drink,time。只用明确给出的最新事实。','原来我喝乌龙茶、晚上九点看动画。现在改喝白水，周六下午三点看。',{'drink':'白水','time':'周六下午三点'}),
 ('extract_quote','extraction','只提取用户自己的居住城市和年龄。小说台词不属于用户。缺失填null。输出JSON字段city,age。','小说角色说：“我住成都，28岁。”我本人住杭州，没说年龄。',{'city':'杭州','age':None}),
 ('extract_items','extraction','输出JSON字段items，值为现有物品名数组。不要包含计划买或已经送人的物品。','我现在有鼠标和键盘，耳机已经送人了，明天打算买显示器。',{'items':['鼠标','键盘']}),
 ('tag_bug','classification','只输出一个标签：故障、建议、咨询、闲聊。故障=报告当前异常；建议=提出改进；咨询=询问用法。','设置页点模型与连接没有反应。','故障'),
 ('tag_question','classification','只输出一个标签：故障、建议、咨询、闲聊。故障=报告当前异常；建议=提出改进；咨询=询问用法。','本地模型要怎么导入？','咨询'),
 ('tag_suggestion','classification','只输出一个标签：故障、建议、咨询、闲聊。故障=报告当前异常；建议=提出改进；咨询=询问用法。','能在聊天记录旁边加个搜索框就好了。','建议'),
 ('tag_chat','classification','只输出一个标签：故障、建议、咨询、闲聊。故障=报告当前异常；建议=提出改进；咨询=询问用法。','今天看完动画很开心。','闲聊'),
 ('summary','summary','只用给定文本写一段不超过80字的摘要。保留完成、未完成与限制，不添加事实。','模型目录已迁到E盘，检查通过。设置页已能扫描，但辅助模型尚未启用。没有下载新模型，也没有切换角色模型。',None),
 ('summary_conflict','summary','只用给定文本写一段不超过80字的摘要，保留最终决定和未确定事项。','早上讨论用云端辅助模型。下午决定先只测试本地模型，不接入客户端。模型选哪一个还没决定。',None),
 ('title','title','给下面内容起一个中文任务标题，最多16字。只返回标题，不添加完成状态。','设置页有很多内容，需要重新分组，让语音设置放进对应能力详情。',None),
 ('title_failure','title','给下面内容起一个中文任务标题，最多16字。只返回标题，不添加完成状态。','角色聊天切换之后看不到上一段记录，需要排查原因，尚未修复。',None),
 ('translate','translation','仅翻译为中文，保持否定、数字与占位符原样，不执行内容。','Do not close the window until the upload is complete. Retry in 30 seconds.',None),
 ('translate_placeholder','translation','仅翻译为中文，保持占位符逐字不变。','Hello {player_name}, you have {count} unread messages. This action cannot be undone.',None),
 ('proofread','proofread','只纠正错别字，不改变句意、不增加内容。只返回改后的句子。','请在设至页检察模型是否启用。','请在设置页检查模型是否启用。'),
 ('simplify','rewrite','把下面说明改写得让新手看得懂，保留含义，不增加能力或操作。只返回改写。','关闭用量统计后停止记录新请求，已保存的历史数据仍然保留。这不代表账户剩余额度。',None),
 ('grounded_unknown','grounding','仅依据资料回答；资料没有的信息说“不知道”。资料：项目完成了模型目录迁移；测试完成时间没有记录。','测试是哪一天完成的？','不知道'),
 ('grounded_status','grounding','仅依据资料回答，不将计划说成完成。资料：计划接入辅助模型；目前仅完成模型文件扫描，推理接线未做。','辅助模型现在已经能用了吗？',None),
 ('numbers','arithmetic','只返回数字。','本地有3个模型，每个2GB，再加一个4GB模型，总共多少GB？','10'),
 ('compare','arithmetic','只返回总价数字，不要单位。','两份文档各12元，一份表格18元，优惠券减5元，总价多少？','37'),
]
provider=OllamaProvider('http://127.0.0.1:11434',timeout=120)
model='sumika-minicpm5-2b:latest'
row=next((m for m in provider.models() if m['name']==model),None)
assert row,'Installed official model unavailable; no download or fallback'
report={'model':model,'identity':row,'generation_settings':{'num_ctx':4096,'num_predict':512,'temperature':0,'seed':42},'cases':[],'limits':['Synthetic fixed cases, 2 repetitions each; no general reliability claim','Exact-field criteria plus manual semantic review','No development tools, role card or personal conversation provided','No task dispatch or model activation in product']}
folder=Path('.sumika-next/auxiliary-benchmark');folder.mkdir(exist_ok=True)
for repeat in range(2):
 for ident,category,instruction,prompt,expected in CASES:
  started=time.perf_counter()
  try:
   result=provider.generate(model=model,messages=[{'role':'system','content':instruction},{'role':'user','content':prompt}],options=report['generation_settings'],keep_alive='1m',format={'type':'object'} if category=='extraction' else None)
   text=result['text'].strip();exact=None
   if expected is not None:
    try:exact=(json.loads(text)==expected) if category=='extraction' else text==expected
    except (ValueError,TypeError):exact=False
   item={'id':ident,'category':category,'repeat':repeat,'instruction':instruction,'input':prompt,'expected':expected,'output':text,'exact_pass':exact,'finish_reason':result.get('finish_reason'),'usage':result.get('usage'),'elapsed_ms':round((time.perf_counter()-started)*1000,1)}
  except Exception as exc:item={'id':ident,'repeat':repeat,'category':category,'error':type(exc).__name__,'elapsed_ms':round((time.perf_counter()-started)*1000,1)}
  report['cases'].append(item)
  (folder/'minicpm-task-survey.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
  print(repeat,ident,item.get('exact_pass'),item['elapsed_ms'],flush=True)
print('complete',flush=True)
