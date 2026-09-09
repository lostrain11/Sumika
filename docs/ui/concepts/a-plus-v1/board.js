const themes = new URLSearchParams(location.search).has('themes');
const panels = themes ? [
  ['theme-sage.png','草绿 / 原稿延续','安静、自然'],
  ['companion.png','樱粉 / 推荐默认','日常、柔和，但不寡淡'],
  ['theme-blue.png','青蓝 / 清透感','适合冷色服装与科技系角色'],
  ['theme-berry.png','莓红 / 更鲜明','更强的角色表达，保持中性底'],
] : [
  ['companion.png','01 / 日常陪伴','纯文字导航 · 右侧聊天'],
  ['client-collapsed.png','02 / 留给场景','收起聊天 · 入口仍可找回'],
  ['wallpaper.png','03 / 壁纸构图','隐藏导航 · 独立返回入口'],
  ['wallpaper-chat.png','04 / 随时聊一句','聊天悬浮 · 不遮挡表情'],
];
if (themes) document.querySelector('h1').textContent = '同一个房间，四种角色主题色。';
document.querySelector('#board').innerHTML = panels.map(([file,title,description]) => `<figure><img src="./exports/${file}" alt="${title}"><figcaption>${title}<span>${description}</span></figcaption></figure>`).join('');
