import {bridgeFetch as fetch} from './bridge-client.js';
// Existing backend features, presented with the D design's form/card language.
import {bindBackground} from './appearance.js';
import {getTheme,setTheme} from './theme.js';
import {mountModelLibrary} from './model-library.js';
let csrf;
async function request(path, payload) {
  const response = await fetch('/api/manage/' + path, payload === undefined ? {} : {
    method: 'POST', headers: {'Content-Type':'application/json','X-Sumika-CSRF':csrf},
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
function node(tag, text, cls) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (cls) el.className = cls;
  return el;
}
function button(text, action) {
  const el = node('button', text, 'mini-btn');
  el.type = 'button';
  el.addEventListener('click', async () => {
    el.disabled = true;
    try { await action(); } catch(error) { showError(el, error); }
    finally { el.disabled = false; }
  });
  return el;
}
function showError(el, error) {
  const parent = el.closest('dialog, .set-group, .cap-side') || el.parentElement;
  let message = parent.querySelector('[data-management-error]');
  if (!message) { message=node('p', '', 'sumika-region-error'); message.dataset.managementError=''; parent.prepend(message); }
  message.textContent=error.message;
}
const FIELD_HELP={
  '自动提取记忆':'用本地规则识别“我住在…”等简单自述并保存，不额外调用模型。含糊、引用或假设通常跳过。',
  '模型记忆提议（需确认）':'角色回复时附带记忆建议，会增加少量输出用量；核对原话并确认后才会记住。不会另发一次模型请求。',
  '使用长期记忆':'开启后，聊天可检索已保存记忆。关闭停止聊天检索和自动写入，保留已有数据及管理功能。',
  '记忆检索实现':'全文检索更轻量，主要匹配关键词；语义混合检索更擅长换种说法的提问，需要已安装的本地模型并占用一些资源。',
  '记录角色用量':'保存角色聊天的token使用记录，供查看历史消耗；不是账户余额。关闭后停止新增统计，保留历史。',
  '输入设备':'选择实际使用的麦克风。选择设备不开始录音；未检测到的旧设备不会自动换成其他设备。',
  '启用语音配置':'启用已保存的语音配置。识别、朗读模块与麦克风授权仍分别控制。',
  '朗读声音':'本机语音合成使用的声音名称；可用声音取决于Windows已安装的语音包。',
  '允许麦克风采集':'允许该能力请求麦克风采集。仍须系统权限与每次执行审批；开启本开关不会开始录音。',
  '上下文长度':'模型一次可处理的对话与参考资料容量。越大通常越占内存，并受模型自身上限限制。',
  '回复长度上限':'限制一次回复生成的token数量。太小可能导致回复截断。',
  '温度':'控制回答的变化程度。较低更稳定，较高更多样；不会直接提升模型能力。',
};
let helpSequence=0;
function field(label, value, type='text', options=null) {
  const row = node('label', undefined, 'set-row');
  row.append(node('span', label));
  const input = document.createElement(options ? 'select' : 'input');
  if (options) {
    options.forEach(([value,text]) => {
      const option=node('option',text);option.value=value;input.append(option);
    });
    if(value!==null && value!==undefined && !options.some(([candidate])=>String(candidate)===String(value))){
      const missing=node('option',`当前配置：${value}（未检测到）`);
      missing.value=String(value);input.append(missing);
    }
  }
  else input.type=type;
  if(type==='checkbox') input.checked=Boolean(value); else input.value=value ?? '';
  input.className='sumika-field';
  input.setAttribute('aria-label',label);
  row.append(input);
  if(FIELD_HELP[label]){
    const help=node('span',undefined,'sumika-field-help');
    const trigger=node('button','?','sumika-help-trigger');trigger.type='button';
    trigger.setAttribute('aria-label',`${label}说明`);
    const tip=node('span',FIELD_HELP[label],'sumika-tooltip');tip.id=`sumika-help-${++helpSequence}`;tip.setAttribute('role','tooltip');
    trigger.setAttribute('aria-describedby',tip.id);input.setAttribute('aria-describedby',tip.id);
    trigger.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();help.classList.toggle('open');});
    trigger.addEventListener('keydown',e=>{if(e.key==='Escape')help.classList.remove('open');});
    help.append(trigger,tip);row.append(help);
  }
  return {row,input};
}
function group(title, id) {
  const el=node('section',undefined,'set-group');el.dataset.settingsSection=id;
  const head=node('h2');head.append(node('b',title));el.append(head);
  const card=node('div',undefined,'set-card');el.append(card);
  return {el,card};
}
function dialog(title) {
  document.querySelector('dialog.sumika-dialog')?.remove();
  const el=node('dialog',undefined,'sumika-dialog');
  const head=node('header');head.append(node('h2',title),button('关闭',()=>el.close()));el.append(head);
  el.addEventListener('close',()=>el.remove());
  document.body.append(el);el.showModal();return el;
}
function download(name, data) {
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
  const link=node('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

let currentSettings;
async function buildSettings() {
  currentSettings = await request('settings');
  const main=document.querySelector('.set-main');
  const nav=document.querySelector('.set-nav');
  const sections=[...main.querySelectorAll('.set-group')];
  const idFor=['appearance','models','permissions','data'];
  sections.forEach((el,i)=>el.dataset.settingsSection=idFor[i]||'about');
  const model=sections.find(el=>el.dataset.settingsSection==='models');
  model.querySelector('.set-card').replaceChildren();
  const values=currentSettings.data;
  values.auxiliary = values.auxiliary || {enabled:false,provider:'ollama',model:'sumika-minicpm5-2b:latest',endpoint:'http://127.0.0.1:11434',key_env:'AUXILIARY_MODEL_API_KEY',timeout_seconds:60,max_tokens:512,temperature:0.2,context_length:4096,capabilities:['prompt_enhancement']};
  values.auxiliary.capabilities = values.auxiliary.capabilities || ['prompt_enhancement'];
  values.model_library = values.model_library || {roots:[],auto_scan:false};
  const controls=[];
  const add=(card,label,key,value,type,options)=>{
    const item=field(label,value,type,options);card.append(item.row);controls.push({key,...item,type});return item;
  };
  const modelCard=model.querySelector('.set-card');
  modelCard.append(node('p','角色推理模型与工作模型分离；工作模型继续在工作台管理。','sumika-form-note'));
  const tabs=node('div',undefined,'model-usage-tabs');
  const tabBody=node('div',undefined,'model-usage-panels');
  modelCard.append(tabs,tabBody);
  const panels={};
  function usageTab(id,title){
    const b=button(title,()=>selectUsage(id)); b.className='model-usage-tab'; b.dataset.usage=id; tabs.append(b);
    const p=node('section',undefined,'model-usage-panel'); p.dataset.usage=id; panels[id]=p; tabBody.append(p); return p;
  }
  const workPanel=usageTab('work','工作模型');
  workPanel.append(node('h3','由 DSH 工作台管理'),node('p','工作模型、项目会话、工具权限和审批仍以 DSH 原生配置为唯一来源。Sumika 只读取状态，不在此维护第二份模型配置。','sumika-form-note'),button('打开工作台',()=>{location.hash='#board';}));
  const rolePanel=usageTab('role','角色模型');
  rolePanel.append(node('p','角色模型只用于活动室陪伴，不获得文件、终端、浏览器或审批权限。','sumika-form-note'));
  add(rolePanel,'启用角色模型','enabled',values.enabled,'checkbox');
  const roleProvider=add(rolePanel,'Provider','provider',values.provider,'text', [['ollama','Ollama'],['openai-compatible','OpenAI 兼容 API']]);
  const roleModel=add(rolePanel,'模型名称','model',values.model);
  add(rolePanel,'服务地址','endpoint',values.endpoint);
  add(rolePanel,'凭据环境变量名','key_env',values.key_env || 'DEEPSEEK_API_KEY');
  add(rolePanel,'上下文长度','context_length',values.context_length,'number');
  add(rolePanel,'回复长度上限','max_tokens',values.max_tokens,'number');
  add(rolePanel,'温度','temperature',values.temperature,'number').input.step='any';
  const aux=values.auxiliary;
  const auxiliaryPanel=usageTab('auxiliary','辅助模型');
  auxiliaryPanel.append(node('p','用于提示词优化预览、角色聊天任务意图判断等轻量辅助；失败时保留原文或不确定状态，不自动切换到云端。','sumika-form-note'));
  add(auxiliaryPanel,'启用辅助模型','auxiliary.enabled',aux.enabled,'checkbox');
  const auxiliaryProvider=add(auxiliaryPanel,'Provider','auxiliary.provider',aux.provider,'text', [['ollama','Ollama'],['openai-compatible','OpenAI 兼容 API']]);
  const auxiliaryModel=add(auxiliaryPanel,'模型名称','auxiliary.model',aux.model);
  add(auxiliaryPanel,'服务地址','auxiliary.endpoint',aux.endpoint);
  add(auxiliaryPanel,'凭据环境变量名','auxiliary.key_env',aux.key_env || 'AUXILIARY_MODEL_API_KEY');
  add(auxiliaryPanel,'上下文长度','auxiliary.context_length',aux.context_length,'number');
  add(auxiliaryPanel,'回复长度上限','auxiliary.max_tokens',aux.max_tokens,'number');
  add(auxiliaryPanel,'温度','auxiliary.temperature',aux.temperature,'number').input.step='any';
  auxiliaryPanel.append(node('p',`允许的辅助任务：${aux.capabilities.includes('prompt_enhancement')?'提示词优化预览':'无'}${aux.capabilities.includes('task_intent')?'、任务意图建议':''}。任务派发和权限始终由宿主决定。`,'sumika-form-note'));
  await mountModelLibrary({host:rolePanel,field,node,button,request,roleModel,roleProvider,auxiliaryModel,auxiliaryProvider,onSaved:s=>{currentSettings=s;}});
  function selectUsage(id){
    Object.entries(panels).forEach(([key,p])=>p.hidden=key!==id);
    tabs.querySelectorAll('button').forEach(b=>b.classList.toggle('active',b.dataset.usage===id));
  }
  selectUsage('role');
  const startup=group('通用与启动','startup');
  main.querySelector('.set-group').before(startup.el);
  add(startup.card,'开机自动启动','startup.auto_start',values.startup.auto_start,'checkbox');
  add(startup.card,'使用托盘','startup.tray',values.startup.tray,'checkbox');
  const actual=node('p','正在读取系统启动状态…','sumika-form-note');startup.card.append(actual);
  const readStartup=async()=>{
    const response=await fetch('/api/startup');const state=await response.json();
    actual.textContent=state.registry_present?'系统启动项：已登记':'系统启动项：未登记';
    if(!state.supported) actual.textContent='系统启动状态暂不可读取';
  };await readStartup();
  const data=sections.find(el=>el.dataset.settingsSection==='data');
  data.querySelector('h2 .rsv-tag')?.remove();
  const dataCard=data.querySelector('.set-card');dataCard.replaceChildren();
  add(dataCard,'记录角色用量','usage.enabled',values.usage.enabled,'checkbox');
  const about=group('关于','about');about.card.append(node('p','Sumika · 晴日部室。工作台由受管 DSH 提供，新增能力通过独立扩展接入。','sumika-form-note'));main.append(about.el);
  const permissions=sections.find(el=>el.dataset.settingsSection==='permissions');
  permissions.querySelector('.set-card').append(button('网页咨询授权',openBrowsers));
  const appearance=sections.find(el=>el.dataset.settingsSection==='appearance');
  appearance.querySelector('h2 .rsv-tag')?.remove();
  const theme=field('主题配色',getTheme(),'text',[['light','晴日 · 浅'],['dark','夜间'],['system','跟随系统']]);
  theme.input.addEventListener('change',()=>{
    try{setTheme(theme.input.value);}catch(error){showError(theme.input,error);}
  });
  window.addEventListener('sumika:theme-rendered',event=>theme.input.value=event.detail);
  [...appearance.querySelectorAll('.set-row')].find(row=>row.textContent.includes('主题配色'))?.replaceWith(theme.row);
  await bindBackground(appearance.querySelector('.set-card'));
  const density=field('界面密度',localStorage.getItem('sumika-density')||'comfortable','text',[['comfortable','舒适'],['compact','紧凑']]);
  density.input.addEventListener('change',()=>{
    document.documentElement.dataset.density=density.input.value;
    localStorage.setItem('sumika-density',density.input.value);
  });
  document.documentElement.dataset.density=density.input.value;
  const densityOld=[...appearance.querySelectorAll('.set-row')].find(r=>r.textContent.includes('界面密度'));
  densityOld?.replaceWith(density.row);
  const actions=node('div',undefined,'sumika-settings-actions');
  const status=node('span','', 'sumika-form-note');
  actions.append(button('保存设置',async()=>{
    const changes={};
    for(const c of controls) {
      const value=c.type==='checkbox'?c.input.checked:c.type==='number'?Number(c.input.value):c.type==='device'?(c.input.value===''?null:Number(c.input.value)):c.input.value;
      const parts=c.key.split('.');
      const old=parts.length===1?currentSettings.data[parts[0]]:currentSettings.data[parts[0]][parts[1]];
      if(value===old)continue;
      if(parts.length===1)changes[parts[0]]=value;else(changes[parts[0]]??={})[parts[1]]=value;
    }
    if(!Object.keys(changes).length){status.textContent='没有需要保存的修改';return;}
    currentSettings=await request('settings',{expected_revision:currentSettings.revision,changes});
    window.dispatchEvent(new CustomEvent('sumika:workbench-settings',{detail:currentSettings.data.prompt_enhancement}));
    status.textContent='已保存';await readStartup();
  }),status);main.append(actions);
  nav.querySelectorAll('button').forEach(b=>b.remove());
  const entries=[['startup','通用与启动'],['appearance','外观'],['models','模型与连接'],['permissions','连接与权限'],['data','数据与存储'],['about','关于']];
  function select(id) {
    main.querySelectorAll('.set-group').forEach(el=>el.hidden=el.dataset.settingsSection!==id);
    nav.querySelectorAll('button').forEach(b=>b.classList.toggle('active',b.dataset.section===id));
    const title=main.querySelector('h1');if(title)title.textContent='设置 · '+entries.find(e=>e[0]===id)[1];
    main.scrollTop=0;
  }
  for(const [id,title] of entries) {
    const b=button(title,()=>select(id));b.className='';b.dataset.section=id;
    const foot=nav.querySelector('.set-nav-foot');foot?foot.before(b):nav.append(b);
  }
  select('startup');
}

async function openRoles() {
  const response=await fetch('/api/roles');const roles=await response.json();
  const modal=dialog('角色管理');
  modal.append(button('导入／恢复角色资源包',openRolePackageImport));
  const choice=field('角色',roles.active?.id,'text',(roles.roles||[]).map(r=>[r.id,`${r.name}${r.complete?'':'（待绑定模型）'}`]));modal.append(choice.row);
  const resourceButton=button('管理角色资源',()=>openRoleResources(choice.input.value));
  modal.append(resourceButton);
  const content=node('div');modal.append(content);
  let loadRevision=0;
  async function loadRole(){
    const requestRevision=++loadRevision;
    const roleId=choice.input.value;
    content.replaceChildren(node('p','正在加载…','sumika-form-note'));
    const root=`roles/${encodeURIComponent(roleId)}/memory`;
    let state;
    try { state=await request(root); }
    catch(error) {
      if(requestRevision!==loadRevision || !modal.isConnected)return;
      content.replaceChildren(node('p',error.message,'sumika-region-error'));
      return;
    }
    if(requestRevision!==loadRevision || !modal.isConnected)return;
    content.replaceChildren();
    const notice=node('p',`记忆作用域：${state.scope.role_id} · ${state.scope.project_id}`,'sumika-form-note');content.append(notice);
    const actions=node('div',undefined,'sumika-action-row');content.append(actions);
    async function mutate(action,extra={}) {
      if(requestRevision!==loadRevision || choice.input.value!==roleId || !modal.isConnected)
        throw new Error('角色选择已变化，请在当前角色页面重新操作。');
      await request(`${root}/${action}`,{expected_revision:state.revision,...extra});
      if(requestRevision===loadRevision && modal.isConnected)await loadRole();
    }
    actions.append(button('导出记忆',async()=>{
      const out=await request(root+'/export',{expected_revision:state.revision});download(`${roleId}-memory.json`,out.data);
    }),button('恢复备份',()=>{
      const input=node('input');input.type='file';input.accept='.json';
      input.onchange=async()=>{
        try {
          const data=JSON.parse(await input.files[0].text());
          if(confirm(`恢复将覆盖 ${roleId} 的当前记忆与关系，并先保存备份。继续？`))await mutate('restore',{data,confirmed:true});
        }catch(error){showError(modal,error);}
      };input.click();
    }),button('重置到角色卡',async()=>{
      if(confirm(`重置 ${roleId} 的记忆与关系？当前数据将先备份，角色卡和模型不会删除。`))await mutate('reset',{confirmed:true});
    }));
    const add=field('新增事实','');content.append(add.row,button('保存事实',()=>mutate('remember',{text:add.input.value,request_id:crypto.randomUUID()})));
    const proposals=(state.proposals||[]).filter(p=>(p.status||'pending')==='pending');
    content.append(node('h3',`待确认记忆（${proposals.length}）`));
    for(const p of proposals){
      const row=node('div',undefined,'sumika-record');
      row.append(node('p',p.text),node('small',p.quote?`用户原话：${p.quote}`:'旧提议未记录原话，请核实后再保存。'));
      row.append(button('确认记住',async()=>{if(confirm(`将这条提议保存为事实？\n${p.text}`))await mutate('accept_proposal',{event_id:p.event_id,confirmed:true});}),
        button('忽略',()=>mutate('reject_proposal',{event_id:p.event_id,confirmed:true})));
      content.append(row);
    }
    content.append(node('h3',`记忆（${state.memories.length}）`));
    const filter=field('搜索当前列表','');content.append(filter.row);
    const list=node('div');content.append(list);
    const renderList=()=>{
      list.replaceChildren();
      state.memories.filter(m=>m.text.includes(filter.input.value)).forEach(m=>{
        const row=node('div',undefined,'sumika-record');row.append(node('p',m.text),node('small',m.source));
        row.append(button('遗忘',async()=>{if(confirm('遗忘这条记忆？'))await mutate('forget',{id:m.id,confirmed:true});}));list.append(row);
      });
    };filter.input.addEventListener('input',renderList);renderList();
    content.append(node('h3',`关系（${state.relations.length}）`));
    const subject=field('主体','用户'),predicate=field('关系',''),object=field('对象','');
    content.append(subject.row,predicate.row,object.row,button('添加关系',()=>mutate('relate',{subject:subject.input.value,predicate:predicate.input.value,object:object.input.value})));
    for(const relation of state.relations){
      const row=node('div',undefined,'sumika-record');row.append(node('p',`${relation.subject} → ${relation.predicate} → ${relation.object}`));
      row.append(button('编辑',async()=>{
        const value=prompt('新的关系对象（同作用域相同关系会一起更新）',relation.object);
        if(value!==null)await mutate('edit_relation',{...relation,new_object:value});
      }),button('删除',async()=>{if(confirm('删除这项关系？'))await mutate('delete_relation',{...relation,confirmed:true});}));content.append(row);
    }
    const usage=await request(`roles/${encodeURIComponent(roleId)}/usage`);
    if(requestRevision!==loadRevision || !modal.isConnected)return;
    content.append(node('h3','角色用量'));
    if(!usage.groups.length)content.append(node('p','暂无已记录用量；不代表消耗为零。','sumika-form-note'));
    for(const u of usage.groups) content.append(node('p',`${u.model} · ${u.status} · ${u.total_tokens??'未知'} token（${u.requests} 次记录）`,'sumika-form-note'));
  }
  choice.input.addEventListener('change',()=>loadRole().catch(e=>showError(modal,e)));
  await loadRole();
}

async function openRoleResources(roleId) {
  const state=await request(`roles/${encodeURIComponent(roleId)}/resources`);
  const modal=dialog('角色资源');
  modal.append(node('p',`角色：${state.name} · ${roleId}`,'sumika-form-note'));
  modal.append(node('p',`已绑定：${state.assets.join('、') || '无'}`,'sumika-form-note'));
  if(!state.editable){modal.append(node('p','自带示例资源只读。'));return;}
  const status=node('p','','sumika-form-note');
  let revision=state.revision;
  const mutate=async(action,data={})=>{
    const result=await request(`roles/${encodeURIComponent(roleId)}/resources/${action}`,{expected_revision:revision,...data});
    revision=result.revision||revision;
    status.textContent=`已完成，恢复副本：${result.backup || result.path}`;
    window.dispatchEvent(new Event('sumika-role-resources-changed'));
    return result;
  };
  const name=field('客户端显示名',state.name);modal.append(name.row,button('保存显示名',()=>mutate('rename',{name:name.input.value})));
  const kind=field('资源类型','model_3d','text',[['model_3d','3D 模型'],['model_2d','2D 模型'],['voice','语音'],['scene','场景']]);
  const path=field('本机资源文件路径','');modal.append(kind.row,path.row,button('绑定资源',async()=>{
    if(confirm('绑定将先备份角色资源包，再更新对应资源。继续？'))await mutate('attach',{kind:kind.input.value,path:path.input.value});
  }));
  modal.append(button('导出角色资源包',()=>mutate('export')),button('从名册移除并归档',async()=>{
    if(!confirm('移除后资源保留在个人备份目录；记忆不会删除。继续？'))return;
    await mutate('archive',{confirmed:true});
    modal.querySelectorAll('button,input,select').forEach(el=>el.disabled=true);
    modal.append(button('关闭',()=>modal.close()));
  }),status);
  modal.append(node('p','改名不修改角色卡正文。导出的资源包不包含聊天、记忆或凭据。','sumika-form-note'));
}

function openRolePackageImport() {
  const modal=dialog('导入／恢复角色资源包');
  modal.append(node('p','选择本机导出的 ZIP 资源包。恢复已归档角色时保留原角色 ID，不覆盖同名角色，也不自动切换当前角色。','sumika-form-note'));
  const source=field('ZIP 文件完整路径','');
  const status=node('p','','sumika-form-note');
  modal.append(source.row,button('导入资源包',async()=>{
    if(!confirm('将资源包导入为用户个人角色？同名角色不会被覆盖。'))return;
    const result=await request('roles/import-package',{path:source.input.value,confirmed:true});
    status.textContent=`已导入 ${result.name}${result.missing.length?'；尚待绑定：'+result.missing.join('、'):'；角色资源完整'}。记忆与聊天未改动。`;
    window.dispatchEvent(new Event('sumika-role-resources-changed'));
  }),status);
}

async function openSchedules() {
  const modal=dialog('定时任务');
  async function render(){
    const state=await request('schedules');modal.querySelector('[data-schedules]')?.remove();
    const body=node('div');body.dataset.schedules='';modal.append(body);
    body.append(node('p','定义和执行状态分别记录。当前未绑定执行的任务不会自动运行。','sumika-form-note'));
    const edit=(old={})=>{
      body.querySelector('form')?.remove();
      const form=node('form');
      const action=field('任务内容',old.action||'');
      const kind=field('周期',old.kind||'daily','text',[['once','一次性'],['daily','每日'],['weekly','每周']]);
      const expression=field('时间表达式',old.expression||'09:00');
      const zone=field('时区',old.timezone_name||Intl.DateTimeFormat().resolvedOptions().timeZone);
      const mode=field('类型',old.mode||'reminder','text',[['reminder','提醒'],['execute','执行（需要单独绑定）']]);
      form.append(action.row,kind.row,expression.row,zone.row,mode.row,node('p','每日 HH:MM；每周 0..6 HH:MM（0 为周一）；一次性 ISO 日期时间（含时区）。','sumika-form-note'));
      form.append(button('保存定义',async()=>{
        await request('schedules/save',{expected_revision:state.revision,definition:{id:old.id||crypto.randomUUID(),action:action.input.value,kind:kind.input.value,expression:expression.input.value,timezone_name:zone.input.value,mode:mode.input.value,enabled:old.enabled??false}});await render();
      }));body.prepend(form);
    };
    body.append(button('新建任务',()=>edit()));
    for(const item of state.definitions){
      const row=node('div',undefined,'sumika-record');row.append(node('p',item.action),node('small',`${item.kind} · ${item.expression} · ${item.enabled?'已启用':'已停用'} · 下次 ${item.next_due||'未知'}`));
      row.append(button('编辑',()=>edit(item)),button(item.enabled?'停用':'启用',async()=>{
        const {next_due,...definition}=item;
        await request('schedules/save',{expected_revision:state.revision,definition:{...definition,enabled:!item.enabled}});await render();
      }),button('删除',async()=>{if(confirm('删除此任务定义？历史记录保留。')){await request('schedules/remove',{expected_revision:state.revision,id:item.id,confirmed:true});await render();}}));body.append(row);
    }
    body.append(node('h3','提醒记录'));
    for(const item of state.reminders){
      const row=node('div',undefined,'sumika-record');row.append(node('p',item.action||item.text||item.key));
      if(!item.seen)row.append(button('标为已读',async()=>{await request('schedules/acknowledge',{expected_revision:state.revision,key:item.key});await render();}));body.append(row);
    }
    body.append(node('h3','执行历史'));
    for(const item of state.history||[])body.append(node('p',`${item.id||item.schedule_id||''} · ${item.state} · ${item.due||''}`,'sumika-form-note'));
  }await render();
}

async function openModules() {
  const modal=dialog('模块管理');
  async function render(){
    const state=await request('modules');modal.querySelector('[data-module-manager]')?.remove();
    const body=node('div');body.dataset.moduleManager='';modal.append(body);
    body.append(node('p','移除仅撤下模块登记，保留依赖和用户数据；重新添加默认停用。','sumika-form-note'));
    const mutate=async(action,data)=>{
      await request(`modules/${action}`,{expected_revision:state.revision,...data});
      await render();window.dispatchEvent(new Event('sumika-modules-changed'));
    };
    state.modules.forEach((item,index)=>{
      const row=node('div',undefined,'sumika-record');row.append(node('p',`${item.id} · ${item.provider}`));
      const move=offset=>{const ids=state.modules.map(m=>m.id);[ids[index],ids[index+offset]]=[ids[index+offset],ids[index]];return mutate('reorder',{ids});};
      if(index>0)row.append(button('上移',()=>move(-1)));
      if(index<state.modules.length-1)row.append(button('下移',()=>move(1)));
      const choices=state.candidates.filter(c=>c.id===item.id);
      if(choices.length){
        const provider=field('实现',item.provider,'text',choices.map(c=>[c.provider,c.provider]));row.append(provider.row);
        row.append(button('应用实现',()=>mutate('configure',{id:item.id,provider:provider.input.value})));
      }
      row.append(button('移除',async()=>{if(confirm(`移除模块 ${item.id} 的登记？`))await mutate('remove',{id:item.id,confirmed:true});}));body.append(row);
    });
    const ids=new Set(state.modules.map(m=>m.id));
    for(const candidate of state.candidates.filter(c=>!ids.has(c.id))){
      body.append(button(`添加 ${candidate.id}（${candidate.provider}）`,()=>mutate('add',{id:candidate.id,provider:candidate.provider})));
    }
  }await render();
}

async function capabilitySettings(id, host){
  const state=await request('settings');
  if(!host.isConnected)return;
  const values=state.data,controls=[];
  host.replaceChildren(node('h3',id==='speech'?'语音交互设置':'长期记忆设置'));
  const readiness=await fetch('/api/readiness').then(r=>r.json()).catch(()=>({}));
  if(!host.isConnected)return;
  const dependency=(readiness.capabilities||[]).find(r=>r.id===(id==='speech'?'voice':'memory-semantic'));
  host.append(node('p',id==='speech'
    ? `语音依赖：${dependency?(dependency.ready?'已就绪':'尚未就绪'):'状态未知'}。启用与授权分别管理。`
    : `全文检索无需额外模型；语义检索依赖：${dependency?(dependency.ready?'已就绪':'尚未就绪'):'状态未知'}。`,'sumika-form-note'));
  const add=(label,key,value,type='text',options=null)=>{
    const item=field(label,value,type,options);controls.push({...item,key,type});host.append(item.row);return item;
  };
  if(id==='speech'){
    const response=await fetch('/api/voice/devices');const devices=await response.json();
    if(!host.isConnected)return;
    add('输入设备','voice.input_device',values.voice.input_device,'device',[
      ['','请选择输入设备'],...(devices.devices||[]).map(d=>[String(d.index),`${d.name}${d.is_default?'（默认）':''}`])]);
    add('启用语音配置','voice.enabled',values.voice.enabled,'checkbox');
    add('朗读声音','voice.tts_voice',values.voice.tts_voice);
  }else{
    add('使用长期记忆','memory.enabled',values.memory.enabled!==false,'checkbox');
    add('自动提取记忆','memory.auto_extract',values.memory.auto_extract,'checkbox');
    add('模型记忆提议（需确认）','memory.model_proposals',values.memory.model_proposals,'checkbox');
    add('记忆检索实现','role.memory_provider',values.role.memory_provider,'text',[
      ['embedded','内置全文检索'],['semantic','语义混合检索']]);
    host.append(button('管理角色记忆与关系',openRoles));
  }
  const notice=node('p','','sumika-form-note');
  host.append(button('保存配置',async()=>{
    const changes={};
    for(const c of controls){
      const [section,key]=c.key.split('.');
      const value=c.type==='checkbox'?c.input.checked:c.type==='device'?(c.input.value===''?null:Number(c.input.value)):c.input.value;
      if(value!==values[section][key])(changes[section]??={})[key]=value;
    }
    if(!Object.keys(changes).length){notice.textContent='没有需要保存的修改';return;}
    try {
      await request('settings',{expected_revision:state.revision,changes});
    } catch(error) {
      try {
        const latest=await request('settings');
        state.revision=latest.revision;Object.assign(values,latest.data);
        notice.textContent='已重新读取保存状态，当前输入保留；没有自动重试保存。';
      } catch {
        notice.textContent='暂时无法确认保存状态，请重新打开详情后核对；没有自动重试。';
      }
      throw error;
    }
    delete host.dataset.ready;
    window.dispatchEvent(new Event('sumika-modules-changed'));
  }),notice);
  if(id!=='speech'){host.dataset.ready='true';return;}
  const registry=await request('modules');if(!host.isConnected)return;
  const moduleControls=new Map();
  async function recoverModuleWrite(error){
    try {
      const latest=await request('modules');
      Object.assign(registry,latest);
      for(const [id,control] of moduleControls){
        const current=latest.modules.find(m=>m.id===id);
        if(!current){
          for(const field of [control.toggle,control.allowed].filter(Boolean)){
            field.input.indeterminate=true;field.input.disabled=true;
          }
          continue;
        }
        Object.assign(control.item,current);
        control.toggle.input.checked=current.enabled;
        control.toggle.input.indeterminate=false;control.toggle.input.disabled=false;
        if(control.allowed){
          control.allowed.input.checked=current.options?.user_authorized===true;
          control.allowed.input.indeterminate=false;control.allowed.input.disabled=false;
        }
      }
      notice.textContent='已按服务端状态刷新开关；停止结果仍需核对，没有自动重试。';
      host.dataset.preserveOnce='true';
      window.dispatchEvent(new Event('sumika-modules-changed'));
    } catch {
      for(const control of moduleControls.values()){
        for(const field of [control.toggle,control.allowed].filter(Boolean)){
          field.input.indeterminate=true;field.input.disabled=true;
        }
      }
      notice.textContent='开关状态无法确认，请重新打开详情；没有自动重试。';
    }
    showError(host,error);
  }
  host.append(node('h3','子功能与权限'));
  for(const [key,label] of [['asr','语音识别'],['voice','语音朗读'],['microphone','麦克风模块']]){
    const item=registry.modules.find(m=>m.id===key);
    if(!item){host.append(node('p',`${label}：未登记，可在模块管理中添加`,'sumika-form-note'));continue;}
    const toggle=field(label,item.enabled,'checkbox');host.append(toggle.row);
    moduleControls.set(key,{toggle,item});
    toggle.input.addEventListener('change',async()=>{
      toggle.input.disabled=true;
      try{
        Object.assign(registry,await request('modules/toggle',{id:key,enabled:toggle.input.checked,expected_revision:registry.revision}));
        item.enabled=toggle.input.checked;host.dataset.preserveOnce='true';
        window.dispatchEvent(new Event('sumika-modules-changed'));toggle.input.disabled=false;
      }
      catch(error){await recoverModuleWrite(error);}
    });
    if(key!=='microphone')continue;
    const allowed=field('允许麦克风采集',item.options?.user_authorized===true,'checkbox');host.append(allowed.row);
    moduleControls.get(key).allowed=allowed;
    allowed.input.addEventListener('change',async()=>{
      const next=allowed.input.checked;allowed.input.disabled=true;
      try{
        if(next&&!confirm('允许语音交互请求麦克风采集？仍需执行审批；现在不会开始录音。')){allowed.input.checked=false;allowed.input.disabled=false;return;}
        Object.assign(registry,await request('modules/microphone_authorization',{id:key,enabled:next,confirmed:true,expected_revision:registry.revision}));
        item.options={...item.options,user_authorized:next};host.dataset.preserveOnce='true';
        window.dispatchEvent(new Event('sumika-modules-changed'));
        allowed.input.disabled=false;
      }catch(error){await recoverModuleWrite(error);}
    });
  }
  host.dataset.ready='true';
}

async function openBrowsers(){
  const modal=dialog('网页咨询授权');
  const body=node('div');modal.append(body);
  const labels={disabled:'已停用',unauthorized:'未授权读取',unbound:'未绑定',stale:'绑定已失效',unknown:'状态未知',ready:'绑定可用'};
  async function render(){
    const [state,inventoryResult,statusResult]=await Promise.all([
      request('browsers'),
      request('browser-sessions').catch(()=>null),
      request('browsers/status').catch(()=>null),
    ]);
    if(!modal.isConnected || !modal.open)return;
    const inventory=inventoryResult?.inventory==='reported' && Array.isArray(inventoryResult.sessions);
    const sessions=inventoryResult || {};
      body.replaceChildren();
      const enabled=field('启用网页咨询',state.enabled===true,'checkbox');
      enabled.input.addEventListener('change',async()=>{
        const next=enabled.input.checked;enabled.input.disabled=true;
        try{
          if(next && !confirm('启用网页咨询？仍需逐站授权，每次发送另行审批。')){enabled.input.checked=false;return;}
          await request('browsers/toggle',{enabled:next,confirmed:true});await render();
        }catch(error){enabled.input.checked=state.enabled===true;showError(modal,error);}
        finally{enabled.input.disabled=false;}
      });
      body.append(enabled.row,node('p',state.enabled===true?'每次发送仍需审批。':'已关闭。保留授权、绑定和历史，不进行新的网页操作。','sumika-form-note'));
    body.append(node('p',`BrowserSkill：${sessions.status?.status||'unknown'} · 活动会话：${inventory?sessions.sessions.length:'未知'}`,'sumika-form-note'));
    body.append(node('p','绑定可用不代表已登录。保存授权后需重新绑定；这里不会发送咨询。','sumika-form-note'));
    body.append(button('刷新状态',render));
    for(const site of state.sites){
      const section=node('section',undefined,'sumika-record');section.dataset.browserSite=site.id;
      section.append(node('h3',site.id));
      const status=statusResult?.sites?.[site.id]?.state || 'unknown';
      section.append(node('p',`连接：${labels[status]||labels.unknown} · 登录：未核验`,'sumika-form-note'));
      const profile=field('Profile',site.profile||''),read=field('允许读取',site.read,'checkbox'),send=field('允许发送',site.send,'checkbox');
        section.append(profile.row,read.row,send.row);
        const start=button('打开受管窗口',async()=>{
          if(!confirm('新建 BrowserSkill 受管窗口？不会发送咨询或自动绑定。'))return;
          await request('browsers/start',{site:site.id,confirmed:true});await render();
        });
        start.disabled=site.read!==true;section.append(start);
        const managed=(inventory?sessions.sessions:[]).filter(s=>s.session_id && s.browser_instance_id && Number.isInteger(s.agent_window_id));
        if(managed.length){
          const target=field('打开站点的受管会话','','text',[
            ['','请选择受管会话'],...managed.map((s,i)=>[String(i),`${s.session_id} · 窗口 ${s.agent_window_id}`]),
          ]);
          const open=button('打开本站页面',async()=>{
            const selected=managed[target.input.value];
            if(!selected)throw new Error('请先选择受管会话');
            if(!confirm(`在所选受管窗口打开 ${site.id}？不会发送咨询或自动绑定。`))return;
            await request('browsers/open',{site:site.id,session_id:selected.session_id,
              browser_instance_id:selected.browser_instance_id,agent_window_id:selected.agent_window_id,confirmed:true});
            await render();
          });
          open.disabled=true;
          target.input.addEventListener('change',()=>{open.disabled=site.read!==true || target.input.value==='';});
          section.append(target.row,open);
        }
      section.append(button('保存授权',async()=>{
        if(!confirm(`为 ${site.id} 保存读取/发送授权？这不是登录操作。`))return;
        await request('browsers/authorize',{site:site.id,profile:profile.input.value,read:read.input.checked,send:send.input.checked,confirmed:true});
        await render();
      }),button('撤销授权',async()=>{
        if(!confirm(`撤销 ${site.id} 的授权？`))return;
        await request('browsers/revoke',{site:site.id,confirmed:true});await render();
      }));
      const candidates=[];
      if(inventory)for(const session of sessions.sessions){
        if(!session.session_id || !Number.isInteger(session.agent_window_id))continue;
        for(const tab of sessions.tabs?.[session.session_id]||[]){
          try{
            const url=new URL(tab.url);
            if(tab.scope!=='agent' || tab.window_id!==session.agent_window_id || !Number.isInteger(tab.tab_id) ||
               url.username || url.password || url.origin!==new URL(site.url).origin)continue;
            candidates.push({session,tab,url});
          }catch(_){}
        }
      }
      if(candidates.length){
        const choice=field('受管页面','','text',[
          ['', '请选择要绑定的页面'],
          ...candidates.map((c,i)=>[String(i),`${c.session.session_id} · 标签 ${c.tab.tab_id} · ${c.url.pathname}`]),
        ]);
        const bind=button('绑定所选页面',async()=>{
          const selected=candidates[choice.input.value];
          if(!selected)throw new Error('请先选择受管页面');
          if(!confirm(`将 ${site.id} 绑定到标签 ${selected.tab.tab_id}？`))return;
          await request('browsers/bind',{site:site.id,session_id:selected.session.session_id,tab_id:selected.tab.tab_id,confirmed:true});
          await render();
        });
        bind.disabled=true;
        choice.input.addEventListener('change',()=>{bind.disabled=choice.input.value==='';});
        section.append(choice.row,bind);
      }else section.append(node('p',inventory?'没有可绑定的本站受管页面。':'受管页面列表未知，请恢复连接后刷新。','sumika-form-note'));
        if(state.enabled!==true)section.querySelectorAll('input,select,button').forEach(el=>{el.disabled=true;});
        body.append(section);
    }
  }
  await render();
}

try {
  await window.sumikaSettingsReady;
  csrf=(await request('session')).csrf;
  await buildSettings();
  const head=document.querySelector('.roster h3');
  head?.after(button('管理角色与记忆',openRoles));
  document.querySelector('.cap-head')?.append(button('管理模块',openModules));
  window.addEventListener('sumika-capability-selected',event=>{
    const side=document.querySelector('.cap-side');const previous=side.querySelector('[data-extra-action]');
    const id=event.detail.id;
    if(previous?.dataset.capabilityId===id && previous.dataset.preserveOnce==='true'){
      delete previous.dataset.preserveOnce;return;
    }
    previous?.remove();
    if(id==='speech'||id==='memory'){
      const host=node('section',undefined,'panel sumika-capability-settings');host.dataset.extraAction='';
      host.dataset.capabilityId=id;
      host.append(node('p','正在读取配置…'));side.querySelector('.hero-d').after(host);
      capabilitySettings(id,host).catch(error=>{if(host.isConnected)showError(host,error);});
    }else if(id==='schedule'){
      const action=button('管理定时任务',openSchedules);
      action.dataset.extraAction='';side.prepend(action);
    }
  });
} catch(error) {showError(document.querySelector('.set-main'),error);}
