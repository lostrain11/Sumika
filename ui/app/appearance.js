// Optional local background: browser-owned data, never sent to the UI server.
let activeUrl;
async function database() {
  return new Promise((resolve,reject)=>{
    const request=indexedDB.open('sumika-appearance',1);
    request.onupgradeneeded=()=>request.result.createObjectStore('preferences');
    request.onsuccess=()=>resolve(request.result);
    request.onerror=()=>reject(request.error);
  });
}
async function storage(action,value) {
  const db=await database();
  try {
    return await new Promise((resolve,reject)=>{
      const tx=db.transaction('preferences',action==='read'?'readonly':'readwrite');
      const store=tx.objectStore('preferences');
      const request=action==='read'?store.get('background'):action==='save'?store.put(value,'background'):store.delete('background');
      tx.oncomplete=()=>resolve(request.result);
      tx.onerror=()=>reject(tx.error);
      tx.onabort=()=>reject(tx.error || new Error('背景保存已中止'));
    });
  }finally{db.close();}
}
function render(blob) {
  if(activeUrl)URL.revokeObjectURL(activeUrl);
  activeUrl=blob?URL.createObjectURL(blob):null;
  const stage=document.querySelector('#screen-room .stage');
  stage.style.backgroundImage=activeUrl?`url("${activeUrl}")`:'';
  stage.style.backgroundSize=activeUrl?'cover':'';
  stage.style.backgroundPosition=activeUrl?'center':'';
  stage.dataset.customBackground=String(Boolean(blob));
}
export async function bindBackground(card) {
  const row=[...card.querySelectorAll('.set-row')].find(r=>r.textContent.trim().startsWith('背景'));
  if(!row)return;
  row.replaceChildren();
  const label=document.createElement('div');label.textContent='背景';
  const note=document.createElement('small');
  note.textContent='图片仅保存在当前浏览器；保留角色与陈设，清除浏览器数据会恢复默认。';label.append(note);
  const status=document.createElement('small');status.setAttribute('role','status');
  const picker=document.createElement('input');picker.type='file';picker.accept='image/png,image/jpeg,image/webp';picker.hidden=true;
  picker.setAttribute('aria-label','选择本地背景图片');
  const choose=document.createElement('button');choose.type='button';choose.className='mini-btn';choose.textContent='本地背景图…';
  const reset=document.createElement('button');reset.type='button';reset.className='mini-btn';reset.textContent='恢复部室午后';
  const busy=value=>{choose.disabled=value;reset.disabled=value;};
  choose.onclick=()=>picker.click();
  picker.onchange=async()=>{
    const file=picker.files?.[0];if(!file)return;
    busy(true);
    try {
      if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>12*1024*1024)throw new Error('请选择不超过 12 MiB 的 PNG、JPEG 或 WebP 图片');
      const bitmap=await createImageBitmap(file);
      const pixels=bitmap.width*bitmap.height;bitmap.close();
      if(pixels>32_000_000)throw new Error('图片分辨率过大，请缩小到 3200 万像素以内');
      await storage('save',file);render(file);status.textContent='已保存本地背景';
    }catch(error){status.textContent=`背景未更改：${error.message}`;}
    finally{picker.value='';busy(false);}
  };
  reset.onclick=async()=>{
    busy(true);
    try{await storage('delete');render(null);status.textContent='已恢复默认背景';}
    catch(error){status.textContent=`恢复失败：${error.message}`;}
    finally{busy(false);}
  };
  row.append(label,choose,reset,picker,status);
  try{const blob=await storage('read');render(blob);status.textContent=blob?'当前使用本地背景':'当前使用部室午后';}
  catch(error){status.textContent=`无法读取本地背景：${error.message}`;}
}
