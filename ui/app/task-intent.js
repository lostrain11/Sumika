// Presentation hint only, never authorization or automatic task dispatch.
// Deliberately conservative: uncertain conversation stays in the room.
export function hasExplicitTaskIntent(text) {
  if (typeof text !== 'string') return false;
  // Quoted examples and code are not instructions addressed to the assistant.
  const plain = text.replace(/```[\s\S]*?```/g, '')
    .replace(/“[^”]*”|「[^」]*」|"[^"\n]*"|`[^`]*`/g, '');
  return plain.split(/[。！？!?\n；;]/).some(raw => {
    const sentence = raw.trim();
    if (!sentence || /不要|不用|别|暂不|先不|无需|不需要|如果|假如|假设|比如|例如|要是|以后|将来/.test(sentence)) return false;
    if (/怎么|如何|为什么|觉得|认为|是否应该|是不是应该|能不能做|能做吗|了吗$|了没$|过吗$/.test(sentence)) return false;
    const action = '(?:修复|修改|实现|新增|添加|删除|移除|优化|重构|排查|检查|测试|编写|生成|整理|翻译|更新|部署|打包|运行)';
    const addressed = new RegExp('^(?:(?:请|麻烦)(?:你)?\\s*|(?:能不能|可以|能否)(?:请)?(?:你)?\\s*)?(?:(?:帮我|替我|给我|你来|你)(?:把)?\\s*)?(?:现在|先|继续)?\\s*' + action + '(.+)$').exec(sentence);
    const objectFirst = new RegExp('^(?:(?:请|麻烦)(?:你)?|帮我|替我|给我|你)?\\s*把(.+?)(?:' + action + '|改成|改为|改好|做好|做完)').exec(sentence);
    const object = (addressed?.[1] || objectFirst?.[1] || '').trim();
    if (!object || /^(?:一下|下|吧|看看|试试|这个|那个|这些|那些|刚才|上面|之前|它)(?:吧|一下|下|看看|试试|做掉|做完|的)?$/.test(object)) return false;
    return true;
  });
}
