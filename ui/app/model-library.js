// Shared model assets; never downloads, imports or starts a runtime.
export function mountModelLibrary({host,field,node,button,request,roleModel,roleProvider,auxiliaryModel,auxiliaryProvider,onSaved}){
  const panel=node('section',undefined,'sumika-record');host.append(panel);
  panel.append(node('h3','本地模型库'));
  panel.append(node('p','指定文件夹后扫描现有权重。不会复制、下载或加载模型；发现文件不代表可运行。','sumika-form-note'));
  const body=node('div');panel.append(body);
  async function render(){
    const state=await request('settings');
    body.replaceChildren();
    const paths=field('扫描目录（每行一个绝对路径）','');
    const input=document.createElement('textarea');input.rows=3;input.className='sumika-field';
    const library=state.data.model_library || {roots:[],auto_scan:false};
    input.setAttribute('aria-label','扫描目录（每行一个绝对路径）');input.value=library.roots.join('\n');
    paths.input.replaceWith(input);body.append(paths.row);
    const auto=field('打开客户端时自动扫描',library.auto_scan,'checkbox');body.append(auto.row);
    const status=node('p','','sumika-form-note'),list=node('div');
    const scan=async()=>{
      status.textContent='正在扫描已保存的目录…';
      try{
        const out=await request('model-library');list.replaceChildren();
        status.textContent=`发现 ${out.models.length} 项；${out.complete?'扫描完成':'扫描达到限制'}${out.issues.length?`，${out.issues.length} 项路径或文件需检查`:''}`;
        for(const issue of out.issues)list.append(node('p',`${issue.path||''} · ${issue.status}`,'sumika-form-note'));
        for(const item of out.models){
          const row=node('div',undefined,'sumika-record');row.append(node('h4',item.name),node('p',`${item.format} · ${(item.bytes/1024**3).toFixed(2)} GiB · ${item.status}`),node('p',item.path,'sumika-model-path'),node('p',item.note,'sumika-form-note'));
          if(item.format==='ollama'&&item.status==='registered'){
            row.append(button('填入角色模型',()=>{
              roleProvider.input.value='ollama';roleModel.input.value=item.name;
              status.textContent='已填入角色模型名称。请核对服务地址是否运行该模型库，再保存设置；尚未切换或发送请求。';
            }));
            row.append(button('填入辅助模型',()=>{
              auxiliaryProvider.input.value='ollama';auxiliaryModel.input.value=item.name;
              status.textContent='已填入辅助模型名称。请核对服务地址是否运行该模型库，再保存设置；尚未切换或发送请求。';
            }));
          }
          list.append(row);
        }
      }catch(error){status.textContent=`扫描失败：${error.message}`;}
    };
    body.append(button('保存扫描目录',async()=>{
      const saved=await request('settings',{expected_revision:state.revision,changes:{model_library:{roots:input.value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean),auto_scan:auto.input.checked}}});
      onSaved(saved);
      status.textContent='扫描目录已保存。';await render();
    }),button('扫描本地模型',scan),status,list);
    if(library.auto_scan)await scan();
  }
  return render();
}
