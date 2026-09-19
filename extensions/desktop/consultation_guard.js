// Called only by the trusted host adapter. No page content is executable input.
(config) => {
  const fail = reason => ({ok:false, reason});
  if (location.origin !== config.origin) return fail('origin_changed');
  if (config.expectedPath != null && location.pathname !== config.expectedPath) return fail('thread_changed');
  const visible = el => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
  const editors = [...document.querySelectorAll(config.editor)].filter(visible);
  if (editors.length !== 1) return fail('ambiguous_editor');
  const editor = editors[0];
  if (editor.disabled || editor.readOnly || editor.getAttribute('aria-disabled') === 'true') return fail('editor_unavailable');
  // This endpoint is text-only. Preserve selected files even when the editor
  // itself is empty, and refuse rich embeds/mentions instead of flattening them.
  if ([...document.querySelectorAll('input[type="file"]')].some(e=>e.files?.length)) return fail('selected_files_present');
  if (editor.isContentEditable && [...editor.querySelectorAll('*')].some(e=>
      !['P','BR','DIV','SPAN'].includes(e.tagName) || e.getAttribute('contenteditable')==='false' ||
      e.hasAttribute('data-mention') || e.hasAttribute('data-attachment') || e.hasAttribute('data-type')))
    return fail('complex_draft_present');
  const value = () => {
    if ('value' in editor) return editor.value;
    // Empty rich-text editors render a placeholder paragraph/BR as a newline.
    // Do not classify attachments, mentions or other embedded nodes as empty.
    if (editor.textContent === '' && [...editor.querySelectorAll('*')].every(e =>
        ['P','BR','DIV'].includes(e.tagName) && e.getAttribute('contenteditable') !== 'false')) return '';
    // ProseMirror serializes paragraphs with one newline. innerText instead
    // counts CSS paragraph spacing (including placeholder BRs) as extra lines.
    // Preserve actual blank paragraphs and hard breaks; never trim/collapse text.
    if (editor.classList.contains('ProseMirror') && editor.childNodes.length &&
        [...editor.childNodes].every(node => node.nodeType === 1 && node.tagName === 'P')) {
      const plain = node => {
        if (node.nodeType === 3) return node.textContent;
        if (node.nodeType !== 1) return '';
        if (node.tagName === 'BR') return node.classList.contains('ProseMirror-trailingBreak')
          && node === node.parentNode.lastChild ? '' : '\n';
        return [...node.childNodes].map(plain).join('');
      };
      return [...editor.children].map(plain).join('\n');
    }
    return editor.innerText;
  };
  if (config.action === 'inspect') return {ok:true, empty:value() === ''};
  if (config.action === 'fill') {
    if (value() !== '') return fail('draft_present');
    if (editor instanceof HTMLTextAreaElement || editor instanceof HTMLInputElement) {
      const proto = editor instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(editor, config.prompt);
      editor.dispatchEvent(new Event('input', {bubbles:true}));
    } else if (editor.isContentEditable) {
      editor.focus();
      const selection = getSelection(), range = document.createRange();
      range.selectNodeContents(editor); selection.removeAllRanges(); selection.addRange(range);
      if (!document.execCommand('insertText', false, config.prompt)) return fail('editor_unsupported');
    } else return fail('editor_unsupported');
    // Lexical may commit the edit after this synchronous callback returns.
    // The following ready/submit calls still require the exact approved text.
    return {ok:true, fill_requested:true, filled:value() === config.prompt};
  }
  if (!['submit','ready'].includes(config.action)) return fail('unknown_action');
  if (value() !== config.prompt) return config.action === 'ready' && value() === ''
    ? {ok:true,ready:false} : fail('draft_changed');
  const buttons = [...document.querySelectorAll(config.submit)].filter(visible);
  if (buttons.length !== 1) return fail('ambiguous_submit');
  const button = buttons[0];
  if (button.disabled || button.getAttribute('aria-disabled') === 'true'
      || button.classList.contains('disabled') || button.classList.contains('ds-button--disabled'))
    return config.action === 'ready' ? {ok:true,ready:false} : fail('submit_disabled');
  if (config.action === 'ready') return {ok:true,ready:true};
  // Guard and click execute synchronously in this document, not separate CDP calls.
  button.click();
  return {ok:true, submitted:true};
}
