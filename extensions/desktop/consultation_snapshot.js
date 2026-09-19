// Fixed, read-only collector. Message text cannot choose selectors or execute code.
(config) => {
  if(location.origin!==config.origin)return {ok:false,reason:'origin_changed'};
  const visible=e=>e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden';
  let elements,read,generating;
  if(location.hostname==='chatgpt.com'){
    if(document.querySelectorAll('#prompt-textarea').length!==1)return {ok:false,reason:'editor_missing'};
    elements=[...document.querySelectorAll('[data-message-author-role="user"], [data-message-author-role="assistant"]')];
    generating=[...document.querySelectorAll('[data-testid="stop-button"]')].some(visible);
    read=e=>{
      const role=e.getAttribute('data-message-author-role');
      const container=e.closest('[data-conversation-screenshot-content]');
      // Long user turns include expand/collapse controls beside the prose.
      // They are UI text, not part of the approved prompt used for correlation.
      const content=role==='assistant'?e.querySelector('.markdown'):
        e.querySelector('[data-testid="collapsible-user-message-content"]')||e;
      // Controls must be outside message prose; a model's quoted HTML is not evidence.
      const controls=container&&[...container.querySelectorAll('[data-testid="copy-turn-action-button"]')].some(b=>!e.contains(b));
      return {role,id:e.getAttribute('data-message-id')||'',text:content?.innerText||'',terminal:role==='user'||Boolean(controls)};
    };
  }else if(location.hostname==='www.kimi.com'){
    if(document.querySelectorAll('.chat-input-editor').length!==1)return {ok:false,reason:'editor_missing'};
    elements=[...document.querySelectorAll('.chat-content-list > .chat-content-item')];
    generating=[...document.querySelectorAll('.stop-button,.stop-button-container,[aria-label="停止生成"]')].some(visible);
    read=e=>{
      const role=e.classList.contains('chat-content-item-user')?'user':'assistant';
      const texts=role==='user'?[...e.querySelectorAll('.user-content__text')]:
        [...e.querySelectorAll('.markdown')].filter(n=>!n.closest('.thinking-container'));
      const controls=e.querySelector('.segment-assistant-actions-content');
      return {role,id:'',text:texts.map(n=>n.innerText).join('\n'),terminal:role==='user'||Boolean(
        controls&&controls.querySelector('svg[name="Copy"]')&&controls.querySelector('svg[name="Refresh"]'))};
    };
  }else if(location.hostname==='chat.deepseek.com'){
    if(document.querySelectorAll('textarea').length!==1)return {ok:false,reason:'editor_missing'};
    elements=[...document.querySelectorAll('[data-virtual-list-item-key]')].filter(e=>e.querySelector('.ds-message'));
    generating=[...document.querySelectorAll('[aria-label="停止生成"],[aria-label="Stop generating"]')].some(visible);
    read=e=>{
      const message=e.querySelector('.ds-message');
      const content=message.querySelector('.ds-assistant-message-main-content');
      const role=content?'assistant':message.classList.contains('d29f3d7d')?'user':'unknown';
      const controls=[...e.querySelectorAll('[role="button"]')].filter(b=>!message.contains(b));
      return {role,id:e.getAttribute('data-virtual-list-item-key')||'',text:(content||message).innerText,
        terminal:role==='user'||Boolean(controls.length>=6&&controls.some(b=>['朗读','Read aloud'].includes(b.getAttribute('aria-label'))))};
    };
  }else return {ok:false,reason:'response_adapter_not_verified'};
  if(elements.length>200)return {ok:false,reason:'history_budget_exceeded'};
  const turns=elements.map(read);
  if(turns.some(t=>!['user','assistant'].includes(t.role)))return {ok:false,reason:'unknown_message_role'};
  // An unloaded history page must not masquerade as an empty new conversation.
  if(!turns.length && /\/(?:c|chat|s)\/[^/]+/.test(location.pathname))return {ok:false,reason:'history_not_loaded'};
  if(turns.some(t=>t.text.length>100000))return {ok:false,reason:'response_budget_exceeded'};
  return {ok:true,url:location.origin+location.pathname,turns,generating,truncated:false};
}
