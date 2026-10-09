import {bridgeFetch} from './bridge-client.js';

export async function sendCompanionText(question, onText) {
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),120000);
  try {
    const statusResponse=await bridgeFetch('/api/companion/microphone', {
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'status'}),signal:controller.signal,
    });
    const status=await statusResponse.json();
    if(!statusResponse.ok) throw Error(status.error || '陪学状态不可用');
    const target=status.capture?.target;
    if(!status.capture?.alive) return false;
    if(!target) throw Error('学习窗口状态未知');
    const response=await bridgeFetch('/api/companion/ask-stream',{
      method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,
      body:JSON.stringify({question,session:'companion-pet-text',
        expected_target:`window:${target.handle}:pid:${target.process_id}`}),
    });
    if(!response.ok) {const value=await response.json();throw Error(value.error || '陪学问答失败');}
    if(!response.body) throw Error('陪学回复流不可用');
    const reader=response.body.getReader(); const decoder=new TextDecoder();
    let pending='', text='', complete=false;
    try {
      while(true) {
        const {value,done}=await reader.read();
        pending+=decoder.decode(value,{stream:!done});
        if(pending.length>1_000_000) throw Error('陪学回复超过限制');
        let boundary;
        while((boundary=pending.indexOf('\n'))>=0) {
          const line=pending.slice(0,boundary);pending=pending.slice(boundary+1);
          if(!line.trim()) continue;
          const event=JSON.parse(line);
          if(complete) throw Error('陪学回复流顺序异常');
          if(event.event==='delta') {
            if(typeof event.text!=='string' || text.length+event.text.length>64000) throw Error('陪学回复超过限制');
            text+=event.text;onText(text);
          } else if(event.event==='complete') {
            if(['stale_response','cancelled','insufficient_context'].includes(event.status)) throw Error('学习内容已变化，请重新提问');
            if(typeof event.text!=='string' || !event.text.trim() || event.text.length>64000) throw Error('陪学未返回有效回答');
            complete=true;onText(event.text);
          } else {throw Error('陪学回答失败');}
        }
        if(done) break;
      }
      if(!complete || pending.trim()) throw Error('陪学回复未完整结束');
    } finally {await reader.cancel().catch(()=>{});reader.releaseLock();}
    return true;
  } finally {clearTimeout(timer);}
}
