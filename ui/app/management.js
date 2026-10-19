import {bridgeFetch as fetch} from './bridge-client.js';
// Existing backend features, presented with the D design's form/card language.
import {bindBackground} from './appearance.js';
import {getTheme,setTheme} from './theme.js';
import {mountModelLibrary} from './model-library.js';
import {mountCompanionSession} from './companion-session.js';
import {mountPetSession} from './pet-session.js';
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
    finally { el.disabled = el.dataset.locked === 'true'; }
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
  const input = document.createElement(options ? 'select' : type==='textarea' ? 'textarea' : 'input');
  if (options) {
    options.forEach(([value,text]) => {
      const option=node('option',text);option.value=value;input.append(option);
    });
    if(value!==null && value!==undefined && !options.some(([candidate])=>String(candidate)===String(value))){
      const missing=node('option',`当前配置：${value}（未检测到）`);
      missing.value=String(value);input.append(missing);
    }
  }
  else if(type!=='textarea') input.type=type;
  if(type==='checkbox') input.checked=Boolean(value); else input.value=value ?? '';
  input.className='sumika-field';
  input.setAttribute('aria-label',label);
  row.append(input);
  if(FIELD_HELP[label]){
    const help=node('span',undefined,'sumika-field-help');
    const trigger=node('button','i','sumika-help-trigger');trigger.type='button';
    trigger.setAttribute('aria-label',`${label}说明`);
    const tip=node('span',FIELD_HELP[label],'sumika-tooltip');tip.id=`sumika-help-${++helpSequence}`;tip.setAttribute('role','tooltip');
    trigger.setAttribute('aria-describedby',tip.id);input.setAttribute('aria-describedby',tip.id);
    trigger.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();help.classList.toggle('open');});
    trigger.addEventListener('keydown',e=>{if(e.key==='Escape')help.classList.remove('open');});
    help.append(trigger,tip);row.insertBefore(help,input);
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
  const workCta=node('div',undefined,'settings-cta');
  const workCtaCopy=node('div',undefined,'settings-cta-copy');
  workCtaCopy.append(node('h3','由 DSH 工作台管理'),
    node('p','工作模型、项目会话、工具权限和审批仍以 DSH 原生配置为唯一来源。Sumika 只读取状态，不在此维护第二份模型配置。'));
  workCta.append(workCtaCopy,button('打开工作台',()=>{location.hash='#board';}));
  workPanel.append(workCta);

  const rolePanel=usageTab('role','角色模型');
  rolePanel.append(node('p','角色模型只用于活动室陪伴，不获得文件、终端、浏览器或审批权限。','sumika-form-note'));
  const roleEnabled=add(rolePanel,'启用角色模型','enabled',values.enabled,'checkbox');
  const roleOffNote=node('p','关闭后活动室仍保留历史记录，但聊天输入会显示“角色模型已关闭”，不会再向模型发请求。','sumika-form-note');
  rolePanel.append(roleOffNote);
  const roleProvider=add(rolePanel,'Provider','provider',values.provider,'text', [
    ['ollama','Ollama（本机）'],
    ['openai-compatible','OpenAI 兼容 API（云端 / 局域网）'],
    ['openai-compatible-local','OpenAI 兼容（仅本机回环）'],
  ]);
  const roleProviderNote=node('p','','sumika-form-note');rolePanel.append(roleProviderNote);
  const roleModel=add(rolePanel,'模型名称','model',values.model);
  const roleEndpoint=add(rolePanel,'服务地址','endpoint',values.endpoint);
  const roleKey=add(rolePanel,'API Key 环境变量名','key_env',values.key_env || 'DEEPSEEK_API_KEY');
  const roleContext=add(rolePanel,'上下文长度','context_length',values.context_length,'number');
  const roleMax=add(rolePanel,'回复长度上限','max_tokens',values.max_tokens,'number');
  const roleTemp=add(rolePanel,'温度','temperature',values.temperature,'number');roleTemp.input.step='any';
  const roleDependents=[roleProvider.row,roleModel.row,roleEndpoint.row,roleKey.row,roleContext.row,roleMax.row,roleTemp.row];
  const syncRoleFields=()=>{
    const off=!roleEnabled.input.checked;
    roleDependents.forEach(row=>{row.hidden=off;});
    roleProviderNote.hidden=off;
    roleOffNote.hidden=!off;
    if(off)return;
    roleKey.row.hidden=roleProvider.input.value!=='openai-compatible';
    roleProviderNote.textContent=roleProvider.input.value==='ollama'
      ? '连接本机或局域网已有的 Ollama 服务；通常填写 http://127.0.0.1:11434，不需要 API Key。'
      : roleProvider.input.value==='openai-compatible'
        ? '填写服务商或局域网的 OpenAI 兼容 HTTPS 地址；API Key 通过环境变量读取，不写进配置文件。'
        : '仅允许 127.0.0.1 / localhost 的 HTTP 服务，适合本机 llama.cpp、LM Studio、vLLM 等运行时。';
  };
  roleEnabled.input.addEventListener('change',syncRoleFields);
  roleProvider.input.addEventListener('change',syncRoleFields);
  syncRoleFields();

  const aux=values.auxiliary;
  aux.tunnel = aux.tunnel || {enabled:false,host:'',user:'',ssh_port:22,remote_port:11434,preload:false};
  const auxiliaryPanel=usageTab('auxiliary','辅助模型');
  auxiliaryPanel.append(node('p','用于提示词优化预览、角色聊天任务意图判断等轻量辅助；失败时保留原文或不确定状态，不自动切换到云端。','sumika-form-note'));
  add(auxiliaryPanel,'启用辅助模型','auxiliary.enabled',aux.enabled,'checkbox');
  const auxiliaryProvider=add(auxiliaryPanel,'Provider','auxiliary.provider',aux.provider,'text', [
    ['ollama','Ollama（本机）'],
    ['openai-compatible','OpenAI 兼容 API（云端 / 局域网）'],
    ['openai-compatible-local','OpenAI 兼容（仅本机回环）'],
  ]);
  const auxiliaryModel=add(auxiliaryPanel,'模型名称','auxiliary.model',aux.model);
  add(auxiliaryPanel,'服务地址','auxiliary.endpoint',aux.endpoint);
  const auxiliaryKey=add(auxiliaryPanel,'API Key 环境变量名','auxiliary.key_env',aux.key_env || 'AUXILIARY_MODEL_API_KEY');
  add(auxiliaryPanel,'上下文长度','auxiliary.context_length',aux.context_length,'number');
  add(auxiliaryPanel,'回复长度上限','auxiliary.max_tokens',aux.max_tokens,'number');
  add(auxiliaryPanel,'温度','auxiliary.temperature',aux.temperature,'number').input.step='any';
  const syncAuxiliaryFields=()=>{auxiliaryKey.row.hidden=auxiliaryProvider.input.value!=='openai-compatible';};
  auxiliaryProvider.input.addEventListener('change',syncAuxiliaryFields);syncAuxiliaryFields();

  const tunnelDetails=node('details',undefined,'settings-advanced');
  tunnelDetails.append(node('summary','远程模型连接（SSH 隧道，可选）'),
    node('p','只有模型运行在另一台机器、且你已配置 SSH 公钥时才需要。普通本机模型或云端 API 不需要填写。','sumika-form-note'));
  const tunnelBody=node('div');tunnelDetails.append(tunnelBody);
  add(tunnelBody,'启用 SSH 隧道','auxiliary.tunnel.enabled',aux.tunnel.enabled,'checkbox');
  add(tunnelBody,'SSH 主机','auxiliary.tunnel.host',aux.tunnel.host);
  add(tunnelBody,'SSH 用户','auxiliary.tunnel.user',aux.tunnel.user);
  add(tunnelBody,'SSH 端口','auxiliary.tunnel.ssh_port',aux.tunnel.ssh_port,'number');
  add(tunnelBody,'远端 Ollama 端口','auxiliary.tunnel.remote_port',aux.tunnel.remote_port,'number');
  add(tunnelBody,'连接后预加载模型','auxiliary.tunnel.preload',aux.tunnel.preload,'checkbox');
  const tunnelStatus=node('p','隧道状态：未读取','sumika-form-note');tunnelStatus.setAttribute('role','status');
  const tunnelActions=node('div',undefined,'sumika-settings-actions');
  let tunnelState=null;
  const tunnelText=()=>{
    const s=tunnelState;
    if(!s)return '隧道状态：未读取';
    if(!s.enabled)return '隧道未启用';
    const preload=!s.preload||s.preload==='idle'?'':s.preload==='warming'?' · 模型预加载中'
      :s.preload==='ready'?' · 模型已预加载':s.preload==='error'?' · 预加载失败：'+(s.preload_error||'未知'):'';
    if(s.healthy)return `隧道已连接：127.0.0.1:${s.local_port} → ${s.remote}${preload}`;
    if(s.running)return `隧道进程在运行，但健康检查未通过${s.last_error?'：'+s.last_error:''}${preload}`;
    return `隧道未运行${s.last_error?'：'+s.last_error:''}`;
  };
  const refreshTunnel=async()=>{try{tunnelState=await request('tunnel');tunnelStatus.textContent=tunnelText();}catch(error){tunnelStatus.textContent='隧道状态读取失败：'+error.message;}};
  tunnelActions.append(
    button('启动隧道',async()=>{tunnelState=await request('tunnel',{action:'start'});tunnelStatus.textContent=tunnelText();}),
    button('停止隧道',async()=>{tunnelState=await request('tunnel',{action:'stop'});tunnelStatus.textContent=tunnelText();}),
    button('刷新状态',refreshTunnel));
  tunnelBody.append(tunnelActions,tunnelStatus);
  auxiliaryPanel.append(tunnelDetails);
  auxiliaryPanel.append(node('p',`允许的辅助任务：${aux.capabilities.includes('prompt_enhancement')?'提示词优化预览':'无'}${aux.capabilities.includes('task_intent')?'、任务意图建议':''}。任务派发和权限始终由宿主决定。`,'sumika-form-note'));

  const libraryPanel=usageTab('library','本地模型库');
  await mountModelLibrary({host:libraryPanel,field,node,button,request,roleModel,roleProvider,auxiliaryModel,auxiliaryProvider,onSaved:s=>{currentSettings=s;}});
  await refreshTunnel();
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
  const dataSection=(title,description)=>{
    const section=node('section',undefined,'data-section');
    section.append(node('h3',title));
    if(description)section.append(node('p',description,'sumika-form-note'));
    dataCard.append(section);
    return section;
  };
  const storage=await request('personal-data');
  const directorySection=dataSection('个人数据目录','迁移会保留旧目录和备份，不移动外部模型库；完成后重启生效。');
  const locationRow=field('当前目录',storage.directory);locationRow.input.readOnly=true;
  directorySection.append(locationRow.row);
  const storageActions=node('div',undefined,'sumika-settings-actions');
  const storageStatus=node('p','','sumika-form-note');storageStatus.setAttribute('role','status');
  const beginRelocation=(fromBackup=false)=>{
    const pane=dialog(fromBackup?'从备份恢复到新目录':'迁移个人数据');
    const target=field('新的个人数据目录','');pane.append(target.row);
    let snapshot;
    if(fromBackup){snapshot=field('备份目录（含 snapshot.json）','');pane.append(snapshot.row);}
    pane.append(node('p','将退出当前客户端，复制并校验后自动重新启动。原数据保留；外部模型库不复制。请先结束正在进行的任务。','sumika-form-note'));
    pane.append(button('确认并重启',async()=>{
      if(!target.input.value.trim())throw new Error('请输入新的目录');
      const result=await request('personal-data/migrate',{destination:target.input.value.trim(),snapshot:snapshot?.input.value.trim()||null,confirmed:true});
      storageStatus.textContent=`迁移已准备，正在退出。失败记录：${result.job}`;pane.close();
      const response=await fetch('/api/lifecycle/shutdown',{method:'POST',headers:{'Content-Type':'application/json','X-Sumika-CSRF':csrf},body:'{}'});
      if(!response.ok)throw new Error('退出未完成，迁移不会开始，请先处理活动任务');
      storageStatus.textContent='正在复制并校验个人数据；完成后客户端会重启。请勿重复操作。';
      storageActions.querySelectorAll('button').forEach(b=>b.disabled=true);
      let attempts=0;
      const poll=setInterval(async()=>{
        try{const fresh=await request('personal-data');if(fresh.directory!==storage.directory){clearInterval(poll);location.reload();}}
        catch{}
        if(++attempts>=120){clearInterval(poll);storageStatus.textContent=`尚未确认重启结果，请查看 ${result.job}；不要重复迁移。`;}
      },1500);
    }));
  };
  storageActions.append(button('打开目录',()=>request('personal-data/open',{})),
    button('迁移数据',()=>beginRelocation()),button('从备份恢复',()=>beginRelocation(true)));
  directorySection.append(storageActions,storageStatus);
  const usageSection=dataSection('用量记录','保存角色聊天的 token 使用记录，供查看历史消耗；不是账户余额。关闭后停止新增统计，保留历史。');
  add(usageSection,'记录角色用量','usage.enabled',values.usage.enabled,'checkbox');
  const recommendationSection=dataSection('本地模型推荐','按本机内存和推理设备给出建议；不会自动下载、安装或切换当前模型。');
  const modelRecStatus=node('p','正在检测本机硬件…','sumika-form-note');
  recommendationSection.append(modelRecStatus);
  fetch('/api/manage/behavior',{method:'POST',
    headers:{'Content-Type':'application/json','X-Sumika-CSRF':csrf},
    body:JSON.stringify({action:'model_recommendation'})})
    .then(r=>r.json()).then(rec=>{
      const hw=rec.hardware||{};
      const role=rec.recommended?.role_play;
      const aux=rec.recommended?.auxiliary;
      if(!role||!aux){modelRecStatus.textContent='硬件检测不可用';return;}
      modelRecStatus.textContent=
        `本机 RAM ${hw.total_ram_gb}GB（可用 ${hw.usable_for_model_gb}GB）`+
        `${hw.has_nvidia_gpu?' · 有 NVIDIA GPU':' · 纯 CPU 推理'}`;
      const roleLine=node('p','','data-recommendation');
      roleLine.innerHTML=`<b>角色扮演推荐</b>：${role.label}（${role.tag}）`+
        (role.installed?' <span class="data-ok">已安装 ✓</span>'
                        :` <code>ollama pull ${role.tag}</code>`);
      roleLine.title=role.use||'';
      const auxLine=node('p','','data-recommendation');
      auxLine.innerHTML=`<b>辅助任务推荐</b>：${aux.label}（${aux.tag}）`+
        (aux.installed?' <span class="data-ok">已安装 ✓</span>'
                       :` <code>ollama pull ${aux.tag}</code>`);
      auxLine.title=aux.use||'';
      recommendationSection.append(roleLine,auxLine);
    }).catch(()=>{modelRecStatus.textContent='模型推荐不可用';});
  const behaviorSection=dataSection('行为子记忆','观察事实、当前解释、用户确认与派生模式分别保留来源。不会定期自动删除。删除不影响历史手动备份。');
  await mountBehaviorData(behaviorSection,{embedded:true});
  const about=group('关于','about');about.card.append(node('p','Sumika · 晴日部室。工作台由受管 DSH 提供，新增能力通过独立扩展接入。','sumika-form-note'));main.append(about.el);
  const permissions=sections.find(el=>el.dataset.settingsSection==='permissions');
  await mountBehaviorPermissions(permissions.querySelector('.set-card'));
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
  const readPath=(value,path)=>path.reduce((current,key)=>current==null?undefined:current[key],value);
  const writePath=(target,path,value)=>{
    let current=target;
    for(const key of path.slice(0,-1)){
      if(!current[key]||typeof current[key]!=='object')current[key]={};
      current=current[key];
    }
    current[path[path.length-1]]=value;
  };
  const actions=node('div',undefined,'sumika-settings-actions');
  const status=node('span','', 'sumika-form-note');
  actions.append(button('保存设置',async()=>{
    const changes={};
    for(const c of controls) {
      const value=c.type==='checkbox'?c.input.checked:c.type==='number'?Number(c.input.value):c.type==='device'?(c.input.value===''?null:Number(c.input.value)):c.input.value;
      const parts=c.key.split('.');
      const old=readPath(currentSettings.data,parts);
      if(value===old)continue;
      writePath(changes,parts,value);
    }
    if(!Object.keys(changes).length){status.textContent='没有需要保存的修改';return;}
    currentSettings=await request('settings',{expected_revision:currentSettings.revision,changes});
    window.dispatchEvent(new CustomEvent('sumika:workbench-settings',{detail:{
        prompt_enhancement:currentSettings.data.prompt_enhancement,
        auxiliary:currentSettings.data.auxiliary}}));
    window.dispatchEvent(new Event('sumika:settings-changed'));
    status.textContent='已保存';await readStartup();await refreshTunnel();
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

window.sumikaOpenRoles = openRoles;
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
        row.append(button('纠正',async()=>{
          const text=prompt('纠正这条事实（旧版本会保留为历史，不再用于召回）',m.text);
          if(text===null)return;
          if(!text.trim())throw new Error('纠正后的事实不能为空。');
          if(text===m.text)return;
          if(!confirm(`确认将这条事实纠正为：\n${text}`))return;
          await mutate('correct',{record_id:m.record_id,text,request_id:crypto.randomUUID(),confirmed:true});
        }),button('遗忘',async()=>{if(confirm('遗忘这条记忆？'))await mutate('forget',{id:m.id,confirmed:true});}));list.append(row);
      });
    };filter.input.addEventListener('input',renderList);renderList();
    content.append(node('h3',`关系（${state.relations.length}）`));
    const subject=field('主体','用户'),predicate=field('关系',''),object=field('对象','');
    content.append(subject.row,predicate.row,object.row,button('添加关系',()=>mutate('relate',{subject:subject.input.value,predicate:predicate.input.value,object:object.input.value})));
    for(const relation of state.relations){
      const row=node('div',undefined,'sumika-record');row.append(node('p',`${relation.subject} → ${relation.predicate} → ${relation.object}`));
      row.append(button('编辑',async()=>{
        const value=prompt('新的关系对象（只更新当前这一条关系）',relation.object);
        if(value!==null)await mutate('edit_relation',{...relation,new_object:value});
      }),button('删除',async()=>{if(confirm('删除这项关系？'))await mutate('delete_relation',{...relation,confirmed:true});}));content.append(row);
    }
    const usage=await request(`roles/${encodeURIComponent(roleId)}/usage`);
    if(requestRevision!==loadRevision || !modal.isConnected)return;
    content.append(node('h3','角色用量'));
    if(!usage.groups.length)content.append(node('p','本房间会话暂无已记录用量；不代表消耗为零。','sumika-form-note'));
    for(const u of usage.groups) content.append(node('p',`${u.model} · ${u.status} · ${u.total_tokens??'未知'} token（${u.requests} 次记录）`,'sumika-form-note'));
    // P6/F-10: every business category shows here with the metrics that
    // apply to it — audio seconds are not missing tokens, and unmetered
    // rows stay an explicit unknown instead of folding into zero.
    content.append(node('h3','当前项目用量（全部业务类别）'));
    content.append(node('p','以下汇总当前项目的所有角色和业务类别；不含工作台 DSH 自行记录的用量。输入、输出与合计分别展示，不重复相加。','sumika-form-note'));
    const categoryLabels={room:'角色房间',companion:'桌宠陪伴',routing:'路由',
      behavior:'行为观察',audio:'音轨识别',vision:'视觉分析',unknown:'未分类'};
    const metricLabel=(metric,value)=>metric==='audio_seconds'?`音频 ${value==null?'未知':`${Math.round(value*10)/10} 秒`}`
      :metric==='vision_calls'?`视觉调用 ${value==null?'未知':`${value} 次`}`
      :`${metric==='prompt_tokens'?'输入':metric==='completion_tokens'?'输出':'合计'} ${value==null?'未知':`${value} token`}`;
    if(!usage.categories?.length)content.append(node('p','暂无已记录的项目用量。','sumika-form-note'));
    for(const c of usage.categories||[]){
      const label=categoryLabels[c.category]||c.category;
      const known=Object.entries(c.known_sum||{}).map(([metric,value])=>metricLabel(metric,value)).join('、');
      const knownText=known?`已知小计：${known}`:'无已计量数据';
      const statuses=[['estimated','估算'],['reported','上报'],['unknown','未知']]
        .filter(([key])=>c.by_status?.[key]).map(([key,text])=>`${text} ${c.by_status[key]}`).join(' · ');
      content.append(node('p',`${label}（${c.requests} 次记录）：${knownText}；`+
        `${c.unknown_count?`${c.unknown_count} 次记录计量不完整`:'无计量缺失'}${statuses?` · ${statuses}`:''}`,'sumika-form-note'));
    }
  }
  choice.input.addEventListener('change',()=>loadRole().catch(e=>showError(modal,e)));
  await loadRole();
}

async function openRoleResources(roleId) {
  const roles=await (await fetch('/api/roles')).json();
  roleId=roleId||roles.active?.id||roles.roles?.[0]?.id;
  if(!roleId)throw Error('请先导入角色');
  const state=await request(`roles/${encodeURIComponent(roleId)}/resources`);
  const modal=dialog('角色资源');
  modal.classList.add('role-resource-editor');
  const choice=field('资源所属角色',roleId,'text',(roles.roles||[]).map(r=>[r.id,r.name]));
  modal.append(choice.row);choice.input.addEventListener('change',()=>{
    openRoleResources(choice.input.value).then(()=>{modal.close();modal.remove();}).catch(error=>showError(modal,error));
  });
  modal.append(node('p',`角色：${state.name} · ${roleId}`,'sumika-form-note'));
  modal.append(node('p',`已绑定：${state.assets.join('、') || '无'}`,'sumika-form-note'));
  if(!state.editable){modal.append(node('p','自带示例资源只读。'));return;}
  const status=node('p','','sumika-form-note');
  let revision=state.revision;
  const mutate=async(action,data={})=>{
    const result=await request(`roles/${encodeURIComponent(roleId)}/resources/${action}`,{expected_revision:revision,...data});
    revision=result.revision||revision;
    modal.querySelector('[data-management-error]')?.remove();
    status.textContent=`已完成，恢复副本：${result.backup || result.path}`;
    window.dispatchEvent(new Event('sumika-role-resources-changed'));
    return result;
  };
  const name=field('客户端显示名',state.name);modal.append(name.row,button('保存显示名',()=>mutate('rename',{name:name.input.value})));
  const background=field('背景设定',state.background,'textarea');background.input.rows=5;background.input.maxLength=32000;
  modal.append(node('h3','背景与世界书'),background.row,
    node('p','世界书按关键词触发；常驻条目无需关键词。高级触发字段随条目保留。保存后用于下一次角色回复。','sumika-form-note'));
  const entries=structuredClone(state.worldbook||[]),book=node('div');modal.append(book);
  function renderBook(){
    book.replaceChildren();
    entries.forEach((entry,index)=>{
      const row=node('section',undefined,'sumika-record');row.append(node('h4',`条目 ${index+1}`));
      const content=field('条目内容',entry.content||'','textarea');content.input.rows=3;content.input.maxLength=32000;
      const keys=field('关键词（每行一个）',(entry.keys||[]).join('\n'),'textarea');keys.input.rows=2;
      const enabled=field('启用条目',entry.enabled!==false,'checkbox'),constant=field('常驻条目',entry.constant===true,'checkbox');
      content.input.addEventListener('input',()=>entry.content=content.input.value);
      keys.input.addEventListener('input',()=>entry.keys=keys.input.value.split('\n').map(s=>s.trim()).filter(Boolean));
      enabled.input.addEventListener('change',()=>entry.enabled=enabled.input.checked);
      constant.input.addEventListener('change',()=>entry.constant=constant.input.checked);
      row.append(content.row,keys.row,enabled.row,constant.row,
        button('删除条目',()=>{if(confirm('从本次编辑中删除此条目？保存后生效。')){entries.splice(index,1);renderBook();}}));
      book.append(row);
    });
  }
  renderBook();modal.append(button('添加世界书条目',()=>{entries.push({content:'',keys:[],enabled:true,constant:false});renderBook();}));
  const accent=field('角色主色（#RRGGBB，留空用默认）',state.theme?.accent||'');
  const soft=field('角色浅色（#RRGGBB，留空用默认）',state.theme?.soft||'');
  modal.append(node('h3','角色主题配色'),accent.row,soft.row,button('保存背景、世界书与配色',async()=>{
    const theme={...state.theme};
    for(const [key,input] of [['accent',accent.input],['soft',soft.input]]){
      const value=input.value.trim();if(value)theme[key]=value;else delete theme[key];
    }
    await mutate('edit-context',{changes:{background:background.input.value,worldbook:entries,theme}});
  }));
  const kind=field('资源类型','model_3d','text',[['model_3d','3D 模型'],['model_2d','2D 模型'],['voice','语音'],['scene','场景']]);
  const path=field('本机资源文件或目录路径','');modal.append(kind.row,path.row,button('绑定资源',async()=>{
    if(confirm('绑定将先备份角色资源包，再更新对应资源。2D、语音和场景可填写专用资源目录，将完整导入目录内文件并保留相对路径；不会执行或安装其中代码，也不代表运行兼容。3D 请填写独立 VRM 文件。继续？'))await mutate('attach',{kind:kind.input.value,path:path.input.value});
  }));
  modal.append(button('导出角色资源包',()=>mutate('export')),button('从名册移除并归档',async()=>{
    if(!confirm('移除后资源保留在个人备份目录；记忆不会删除。继续？'))return;
    await mutate('archive',{confirmed:true});
    modal.querySelectorAll('button,input,select,textarea').forEach(el=>el.disabled=true);
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

window.sumikaOpenSchedules = openSchedules;
async function openSchedules() {
  const modal=dialog('定时任务');
  async function render(){
    const state=await request('schedules');modal.querySelector('[data-schedules]')?.remove();
    const body=node('div');body.dataset.schedules='';modal.append(body);
    body.append(node('p','提醒保存在本机；新建执行任务交给 DSH，在所选会话到期投递。投递成功不代表模型已完成任务。旧执行定义保持原状。','sumika-form-note'),button('打开原生自动化任务',()=>window.dispatchEvent(new Event('sumika:open-native-schedules'))));
    const edit=(old={})=>{
      body.querySelector('form')?.remove();
      const form=node('form');
      const action=field('任务内容',old.action||'');
      const kind=field('周期',old.kind||'daily','text',[['once','一次性'],['daily','每日'],['weekly','每周']]);
      const expression=field('时间表达式',old.expression||'09:00');
      const zone=field('时区',old.timezone_name||Intl.DateTimeFormat().resolvedOptions().timeZone);
      const mode=field('类型',old.mode||'reminder','text',[['reminder','提醒'],['execute','执行（需要单独绑定）']]);
      form.append(action.row,kind.row,expression.row,zone.row,mode.row,node('p','每日 HH:MM；每周 0..6 HH:MM（0 为周一）；一次性 ISO 日期时间（含时区）。','sumika-form-note'));
      const binding=node('div'),resultNote=node('p','','sumika-form-note');
      let selectedProject,selectedSession,ready=false,busy=false,settled=false;
      const requestId=crypto.randomUUID();
      const submit=button('保存定义',async()=>{
        if(busy||settled)return;
        if(mode.input.value==='execute' && !old.id){
          if(!ready||!selectedProject.input.value||!selectedSession.input.value)throw Error('请先选择项目和会话');
          const detail=`项目：${selectedProject.input.selectedOptions[0].textContent}\n会话：${selectedSession.input.value}\n${kind.input.value} · ${expression.input.value} · ${zone.input.value}\n内容：${action.input.value}\n将创建原生任务，到期可调用模型及已授权工具。确认创建？`;
          if(!confirm(detail))return;
          busy=true;submit.disabled=true;
          try{
            const result=await request('schedules/native-create',{confirmed:true,request_id:requestId,workspace_id:selectedProject.input.value,session_id:selectedSession.input.value,definition:{id:requestId,action:action.input.value,kind:kind.input.value,expression:expression.input.value,timezone_name:zone.input.value,mode:'execute',enabled:true}});
            settled=true;
            resultNote.textContent=result.state==='created'?`已创建原生任务 ${result.record?.id||''}；请到“原生自动化任务”管理。`:'创建结果未确认。请到原生自动化任务核对，勿再次新建相同任务。';
          }catch(error){
            // Transport errors can occur after native persistence. Keep this
            // form fenced until the user has inspected the authoritative list.
            settled=true;resultNote.textContent=`未确认创建结果：${error.message}。请到原生自动化任务核对，勿重复创建。`;
          }finally{busy=false;submit.dataset.locked=String(settled);submit.disabled=settled;}
          return;
        }
        await request('schedules/save',{expected_revision:state.revision,definition:{id:old.id||crypto.randomUUID(),action:action.input.value,kind:kind.input.value,expression:expression.input.value,timezone_name:zone.input.value,mode:mode.input.value,enabled:old.enabled??false}});await render();
      });
      const updateMode=()=>{
        binding.hidden=mode.input.value!=='execute'||Boolean(old.id);
        submit.textContent=mode.input.value==='execute'&&!old.id?'确认并创建原生任务':'保存定义';
        submit.disabled=settled||(!binding.hidden&&!ready);
      };
      mode.input.addEventListener('change',updateMode);
      form.append(binding,submit,resultNote);body.prepend(form);updateMode();
      if(old.id){
        if(old.mode==='execute')resultNote.textContent='这是旧本地定义，仍不会自动执行。需要原生执行时请显式新建，原定义与历史不会迁移。';
      }else request('schedules/targets').then(targets=>{
        if(!targets.ready){binding.append(node('p',targets.reason||'请先启动工作台','sumika-form-note'));return;}
        selectedProject=field('目标项目','','text',[['','请选择项目'],...targets.projects.map(p=>[p.id,p.name])]);
        selectedSession=field('目标会话','','text',[['','请选择会话']]);
        selectedProject.input.addEventListener('change',()=>{
          selectedSession.input.replaceChildren();
          for(const sid of ['',...(targets.projects.find(p=>p.id===selectedProject.input.value)?.sessions||[])]){
            const option=node('option',sid||'请选择会话');option.value=sid;selectedSession.input.append(option);
          }
        });
        binding.append(selectedProject.row,selectedSession.row);ready=true;updateMode();
      }).catch(error=>binding.append(node('p',error.message,'sumika-form-note')));
    };
    body.append(button('新建任务',()=>edit()));
    for(const item of state.definitions){
      const row=node('div',undefined,'sumika-record');row.append(node('p',item.action),node('small',`${item.kind} · ${item.expression} · ${item.enabled?'已启用':'已停用'} · 下次计划 ${item.next_due||(item.enabled?'无后续计划':'停用中')}`));
      if(state.status?.blocked?.some(blocked=>blocked.id===item.id))row.append(node('p','执行后端未绑定，此任务不会自动执行。','sumika-form-note'));
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
    // Device discovery must not block text study or the permission controls.
    // Keep the saved value while unavailable so saving another field cannot
    // silently clear a previously selected microphone.
    const savedDevice=values.voice.input_device;
    const device=add('输入设备','voice.input_device',savedDevice,'device',[
      [savedDevice===null?'':String(savedDevice),'正在读取输入设备…']]);
    device.input.disabled=true;
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),8000);
    void (async()=>{
      try{
        const response=await fetch('/api/voice/devices',{signal:controller.signal});
        if(!response.ok)throw Error('device discovery failed');
        const devices=await response.json();
        if(!host.isConnected)return;
        if(devices.error || !Array.isArray(devices.devices))throw Error('device discovery unavailable');
        const options=[['','请选择输入设备'],...devices.devices.map(d=>[String(d.index),`${d.name}${d.is_default?'（默认）':''}`])];
        if(savedDevice!==null && !options.some(([value])=>value===String(savedDevice)))
          options.push([String(savedDevice),`已保存设备 ${savedDevice}（当前不可用）`]);
        device.input.replaceChildren(...options.map(([value,label])=>{const option=node('option',label);option.value=value;return option;}));
        device.input.value=savedDevice===null?'':String(savedDevice);
        device.input.disabled=false;
      }catch{
        if(host.isConnected)device.input.options[0].textContent='设备列表暂不可用，已保留配置；重开详情可刷新';
      }finally{clearTimeout(timer);}
    })();
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
  mountCompanionSession(host);
  host.dataset.ready='true';
}

window.sumikaOpenBrowsers = openBrowsers;
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
  // 名册标题锚点：版C 把名册改为底部收起条，容器类名随之从 .roster 变为
  // .roster-head；两种都试，避免结构再调整时这个按钮静默消失。
  const head=document.querySelector('.roster-head h3, .roster h3');
  head?.after(button('管理角色与记忆',openRoles));
  document.querySelector('.cap-head')?.append(button('管理模块',openModules));
  window.addEventListener('sumika-capability-selected',event=>{
    const side=document.querySelector('.cap-side');const previous=side.querySelector('[data-extra-action]');
    const id=event.detail.id;
    if(previous && id && previous.dataset.capabilityId===id && previous.dataset.preserveOnce==='true'){
      delete previous.dataset.preserveOnce;return;
    }
    previous?.remove();
    if(id==='pet'){
      const host=node('section',undefined,'panel sumika-capability-settings');host.dataset.extraAction='';
      host.dataset.capabilityId=id;side.querySelector('.hero-d').after(host);
      mountPetSession(host);
    }else if(id==='speech'||id==='memory'){
      const host=node('section',undefined,'panel sumika-capability-settings');host.dataset.extraAction='';
      host.dataset.capabilityId=id;
      host.append(node('p','正在读取配置…'));side.querySelector('.hero-d').after(host);
      capabilitySettings(id,host).catch(error=>{if(host.isConnected)showError(host,error);});
    }else if(id==='role-resources'){
      const action=button('管理角色资源',()=>openRoleResources());
      action.dataset.extraAction='';side.prepend(action);
    }
  });
} catch(error) {showError(document.querySelector('.set-main'),error);}


// Approved P16 controls stay in the existing permissions/data sections.
async function mountBehaviorPermissions(host) {
  const section=node('section'); section.dataset.behaviorPermissions='';
  section.append(node('h3','行为观察许可'),node('p','仅跟随已授权前台，自动排除 Sumika 自身；画面、文字和应用声音仍遵从陪学会话各自授权。暂停会持续到手动解除。','sumika-form-note'));
  const form=node('div'),status=node('p','','sumika-form-note'); status.setAttribute('role','status');section.append(form,status);host.append(section);
  async function render() {
    const state=await request('behavior',{action:'permission_status'}), controls={};
    form.replaceChildren();
    if(state.status==='unavailable' || !state.permission){status.textContent=`行为许可不可用：${state.error || '请检查行为目录'}`;return;}
    for(const [key,label] of [['recording','允许记录行为特征'],['use_memory','允许参考行为记忆'],['questions','允许主动行为询问'],['startup_resume','随 Sumika 启动恢复已保存许可']]){
      const item=field(label,state.permission[key],'checkbox');controls[key]=item.input;form.append(item.row);
    }
    const questionProfile = field('询问频率','medium','text',[
      ['quiet','少打扰 · 30分钟 / 3次每天'],
      ['medium','适中 · 10分钟 / 6次每天'],
      ['active','积极 · 5分钟 / 12次每天'],
    ]);
    questionProfile.input.value = ['quiet','medium','active'].includes(state.permission.question_profile)
      ? state.permission.question_profile : 'medium';
    controls.question_profile = questionProfile.input;
    form.append(questionProfile.row);
    status.textContent=permissionSummary(state.effective);
    form.append(button('保存行为许可',async()=>{
      const mutations=Object.fromEntries(Object.entries(controls).map(([key,input])=>[
        key, key === 'question_profile' ? input.value : input.checked,
      ]));
      // A new explicit save may grant again after a previous revoke.
      mutations.revoked=false;
      const result=await request('behavior',{action:'permission_save',revision:state.permission.revision,mutations});
      await render();status.textContent='许可已保存。'+permissionSummary(result.effective);
    }));
    const excludes=field('排除应用（进程名，每行一个）',state.permission.excluded_apps.join('\n'));
    const area=node('textarea');area.className='sumika-field';area.value=excludes.input.value;area.rows=4;area.setAttribute('aria-label','排除应用（进程名，每行一个）');excludes.input.replaceWith(area);form.append(excludes.row);
    form.append(button('保存排除应用',async()=>{
      const excluded_apps=[...new Set(area.value.split(/[\n,，]/).map(x=>x.trim().toLowerCase()).filter(Boolean))];
      await request('behavior',{action:'permission_save',revision:state.permission.revision,mutations:{excluded_apps}});await render();
    }));
    form.append(button(state.effective.paused?'解除暂停':'暂停行为观察',async()=>{
      const result=await request('behavior',{action:state.effective.paused?'permission_resume':'permission_pause',revision:state.permission.revision});
      await render();status.textContent=permissionSummary(result.effective);
    }),button('撤销行为许可',async()=>{
      if(!confirm('撤销行为记录、记忆参考和询问许可？历史数据保留。'))return;
      await request('behavior',{action:'permission_revoke',revision:state.permission.revision});await render();
    }));
  }
  try{await render();}catch(error){status.textContent=`行为许可不可用：${error.message}`;}
}
function permissionSummary(effective={}) {
  return `${effective.paused?'已暂停；':effective.revoked?'许可已撤销；':''}行为记录：${effective.can_record?'许可有效':'未启用'} · 记忆参考：${effective.can_use_memory?'许可有效':'未启用'} · 主动询问：${effective.can_answer_questions?'许可有效':'未启用'}`;
}
async function mountBehaviorData(host, options={}) {
  const section=node('section');section.dataset.behaviorData='';
  if(!options.embedded)section.append(node('h3','行为子记忆'),node('p','观察事实、当前解释、用户确认与派生模式分别保留来源。不会定期自动删除。删除不影响历史手动备份。','sumika-form-note'));
  const status=node('p','','sumika-form-note');status.setAttribute('role','status');
  const overview=node('div');overview.dataset.behaviorOverview='';
  const declarations=node('div');declarations.dataset.behaviorDeclarations='';
  const view=node('div');section.append(status,overview,declarations,view);host.append(section);
  let state;
  const refresh=async()=>{
    state=await request('behavior',{action:'status'});
    if(state.status==='unavailable'){status.textContent=`行为数据不可用：${state.error || '请检查行为目录'}`;return;}
    const capacity=state.capacity || {};
    const size=value=>Number.isFinite(value)?`${(value/1024/1024).toFixed(1)} MiB`:'未知';
    status.textContent=`目录：${state.root} · 已用 ${size(capacity.usage_bytes)} · 磁盘可用 ${size(capacity.free_bytes)}${capacity.paused?' · 空间保护已暂停记录':''}${capacity.notice?' · 存储空间达到提醒阈值，请检查可用空间':''}`;
  };
  const types={interest:'兴趣',preference:'偏好',goal:'目标',constraint:'限制',routine:'日常习惯'};
  const editDeclaration=async(item=null)=>{
    const baseline=await request('behavior',{action:'status'});
    const pane=dialog(item?'更正你的声明':'告诉我你的偏好或目标');
    const type=field('记忆类别',item?.type||'interest','text',Object.entries(types));
    const label=field('你希望记住的内容',item?.label||'');label.input.maxLength=256;
    const polarity=field('态度',item?.polarity||'positive','text',[['positive','喜欢 / 希望 / 适用'],['negative','不喜欢 / 避免 / 不适用']]);
    pane.append(type.row,label.row,polarity.row,node('p','仅保存你明确提交的内容；不会根据使用次数认定你喜欢某事。','sumika-form-note'));
    pane.append(button('保存声明',async()=>{
      await request('behavior',{action:'declare',event_id:item?.event_id,revision:baseline.revision,
        declaration:{type:type.input.value,label:label.input.value.trim(),polarity:polarity.input.value}});
      pane.close();await refresh();await loadOverview();
    }));
  };
  const loadOverview=async()=>{
    const [data,decl,habits]=await Promise.all([request('behavior',{action:'activity_overview',days:7}),request('behavior',{action:'declarations'}),request('behavior',{action:'habits'})]);
    overview.replaceChildren(node('h4','当前项目 · 最近 7 天'));
    const minutes=value=>(Number(value||0)/60).toFixed(1);
    const stat=(label,value)=>{const card=node('div',undefined,'data-stat');card.append(node('b',value),node('span',label));return card;};
    const stats=node('div',undefined,'data-stats');stats.append(stat('已观察前台',`${minutes(data.effective_seconds)} 分钟`),stat('应用切换',`${data.switch_count||0} 次`));overview.append(stats);
    overview.append(node('p','统计仅覆盖已授权、连续核验的前台时段，不代表注意力、学习成果或电脑总使用时长。未记录时段不会补算。','sumika-form-note'));
    if(data.truncated)overview.append(node('p','统计分组已达到上限，请缩小查询范围。','sumika-form-note'));
    const rows=data.buckets||[];
    if(!rows.length)overview.append(node('p','暂无前台时段记录；启用记录后，新数据会逐步积累。','sumika-form-note'));
    const apps=new Map();for(const row of rows)apps.set(row.app_name,(apps.get(row.app_name)||0)+row.effective_seconds);
    for(const [app,seconds] of [...apps.entries()].sort((a,b)=>b[1]-a[1]).slice(0,10))overview.append(node('p',`${app} · ${minutes(seconds)} 分钟`));
    if(rows.length){const detail=node('details');detail.append(node('summary','按日期与小时查看'));
      for(const row of rows.slice(0,100))detail.append(node('p',`${row.date} ${String(row.hour).padStart(2,'0')}:00 · ${row.app_name} · ${minutes(row.effective_seconds)} 分钟`));
      if(rows.length>100)detail.append(node('p','此处展示前 100 个时段；其余可导出查看。','sumika-form-note'));overview.append(detail);}
    const ops=Object.entries(data.operations||{});if(ops.length)overview.append(node('p','已记录操作片段：'+ops.map(([k,v])=>`${k} ${v}`).join(' · ')));
    const counts=data.feature_counts||{};
    const categories={text_entry:'文字输入',navigation:'导航',editing:'编辑',function:'功能键',modifier:'组合修饰键',other:'其他',find:'查找',copy:'复制',paste:'粘贴',cut:'剪切',undo:'撤销',redo:'重做',save:'保存',select_all:'全选',print:'打印',left:'左击',right:'右击',middle:'中击',double_click_candidates:'双击候选',moves:'鼠标移动'};
    for(const [name,title] of [['key_categories','按键类别'],['shortcuts','快捷操作'],['mouse','鼠标操作']]){
      const values=Object.entries(counts[name]||{}).filter(([,v])=>v>0);
      if(values.length)overview.append(node('p',`${title}：`+values.map(([k,v])=>`${categories[k]||k} ${v}`).join(' · ')));
    }
    for(const q of data.input_quality||[])overview.append(node('p',`输入覆盖：${q.quality} · ${q.frames} 帧 · 缺失 ${q.dropped||0}`,'sumika-form-note'));
    for(const p of data.progress||[])overview.append(node('p',`材料 ${String(p.material||p.record_id).slice(0,14)}… · 最近观察位置 ${JSON.stringify(p.position)} · 已观察 ${minutes(p.effective_seconds)} 分钟`));
    if(data.activity_affinity?.length){overview.append(node('h4','持续活动参考 · 推测'));
      for(const a of data.activity_affinity)overview.append(node('p',`${a.app_name} 在 ${a.day_count} 天出现；其含义和喜好尚未确认。`));}
    if(habits.records?.length){overview.append(node('h4','根据你过去解释的参考'));
      for(const h of habits.records)overview.append(node('p',`${h.label} · ${h.sample_count} 次 / ${h.session_count} 个会话 · 同情境支持 ${(h.support_ratio*100).toFixed(0)}% · ${h.stable?'稳定参考':'样本有限'} · ${h.match_quality==='legacy'?'旧记录，情境不完整':h.app_name||'应用未知'}；当前意图仍是推测。`));}
    declarations.replaceChildren(node('h4','你明确告诉我的偏好与目标'));
    if(!decl.records?.length)declarations.append(node('p','暂无明确声明。','sumika-form-note'));
    for(const item of decl.records||[]){const row=node('div',undefined,'behavior-memory-row');row.dataset.declarationId=item.event_id;
      row.append(node('p',`${types[item.type]||item.type} · ${item.polarity==='negative'?'避免 / 不喜欢':'希望 / 喜欢'} · ${item.label}`),
        node('p',`来源：你明确提交 · ${item.at} · 版本 ${item.version}`,'sumika-form-note'),
        button('更正',()=>editDeclaration(item)),button('删除',async()=>{
          const baseline=await request('behavior',{action:'status'});if(!confirm('仅删除这条声明？'))return;
          await request('behavior',{action:'forget_declaration',event_id:item.event_id,revision:baseline.revision});await refresh();await loadOverview();
        }));declarations.append(row);}
    if(decl.has_more)declarations.append(node('p','此处展示最近 50 条声明，其余可通过导出查看。','sumika-form-note'));
    declarations.append(button('添加偏好或目标',()=>editDeclaration()));
  };
  let layer='feedback',cursor=0;
  const loadLayer=async(append=false)=>{
    const data=await request('behavior',{action:'list_layer',layer,cursor:append?cursor:0,limit:20});
    if(!append)view.replaceChildren();
    view.querySelector('[data-next-page]')?.remove();
    if(!data.records?.length&&!append)view.append(node('p','这一层暂无记录。','sumika-form-note'));
    for(const item of data.records||[]){const row=node('div',undefined,'behavior-memory-row');
      const label=item.label||item.corrected||item.kind||item.pattern||item.source||layer;
      row.append(node('p',String(label)),node('p',`${item.at||item.ended_at||''} · ${item.source|| (layer==='feedback'?'用户反馈':'观察 / 派生数据')}`,'sumika-form-note'));
      if(layer==='feedback'){
        row.dataset.feedbackId=item.feedback_id;
        row.append(node('p','历史解释，仅适用于当时情境；不代表当前意图已确认。','sumika-form-note'));
        row.append(button('更正解释',async()=>{
          const baseline=await request('behavior',{action:'status'}),pane=dialog('更正这条行为解释'),corrected=field('真实含义或解释',item.label||item.corrected||'');pane.append(corrected.row);
          pane.append(button('保存更正',async()=>{await request('behavior',{action:'correct',feedback_id:item.feedback_id,corrected:corrected.input.value.trim(),revision:baseline.revision});pane.close();await refresh();await loadOverview();await loadLayer();}));
        }),button('删除解释',async()=>{
          const baseline=await request('behavior',{action:'status'});if(!confirm('仅删除这条解释？相关习惯参考会重新计算。'))return;
          await request('behavior',{action:'forget_feedback',feedback_id:item.feedback_id,revision:baseline.revision});await refresh();await loadOverview();await loadLayer();
        }));
      }
      const detail=node('details');detail.append(node('summary','查看来源与结构'),node('pre',JSON.stringify(item,null,2),'behavior-records'));row.append(detail);view.append(row);
    }
    cursor=data.next_cursor;
    if(cursor!==null&&cursor!==undefined){const more=button('加载更多',()=>loadLayer(true));more.dataset.nextPage='';view.append(more);}
  };
  const selector=field('选择记录层','feedback','text',[['feedback','用户行为解释'],['events','活动与观察'],['episodes','操作片段'],['patterns','派生模式'],['progress','材料进度'],['prompts','询问记录']]);
  selector.input.addEventListener('change',()=>{layer=selector.input.value;cursor=0;loadLayer().catch(e=>showError(selector.input,e));});
  section.append(node('h4','记录层'),selector.row);
  const layerActions=node('div',undefined,'sumika-action-row');
  layerActions.append(button('查看分层记录',()=>loadLayer()),button('刷新使用概览',async()=>{await refresh();await loadOverview();}),
  button('导出行为数据',async()=>download('sumika-behavior.json',await request('behavior',{action:'export'}))),button('迁移行为目录',async()=>{
    const pane=dialog('迁移行为目录'),target=field('新的专用行为目录','');pane.append(target.row,node('p','将暂停记录并复制校验，原目录保留；请选择新的本地专用子目录。','sumika-form-note'));
    pane.append(button('确认迁移',async()=>{
      if(!target.input.value.trim())throw Error('请输入新目录');
      const result=await request('behavior',{action:'migrate',destination:target.input.value.trim(),confirmed:true});
      if(result.status!=='complete')throw Error(`迁移尚未完成：${result.status}`);pane.close();await refresh();
    }));
  }),button('删除全部行为记录',async()=>{
    const baseline=await request('behavior',{action:'status'});
    if(!confirm('删除全部行为事实、片段、反馈、模式和进度，并取消待回答询问？历史手动备份仍保留。'))return;
    await request('behavior',{action:'delete',all_records:true,confirmed:true,revision:baseline.revision});view.replaceChildren();await refresh();await loadOverview();
  }));
  section.append(layerActions);
  try{await refresh();if(state.status!=='unavailable')await loadOverview();}catch(error){status.textContent=`行为数据不可用：${error.message}`;}
}
