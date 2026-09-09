export const studies = {
  a: { name:'和风留白', english:'A QUIET PLACE', subtitle:'留一处空白，和你慢慢说。', layout:'顶部导航 / 居所与侧边聊天', strength:'安静、直观，适合作为长期默认界面。', tradeoff:'情绪表达比较克制，角色陪伴感依赖房间和镜头。', colors:['#fcfdfb','#557a68','#c76357','#d0b493'] },
  b: { name:'动画对白', english:'A MOMENT WITH YOU', subtitle:'这一幕，只有我们。', layout:'全景舞台 / 底部对白 / 按需历史', strength:'角色最突出，适合以交流和沉浸陪伴为主。', tradeoff:'长对话需要展开历史，重度工作应进入工作台。', colors:['#fffdfd','#576d84','#cb7c89','#dce8ec'] },
  c: { name:'清透轻机能', english:'YOUR EVERYDAY PARTNER', subtitle:'生活与事情，都有各自的位置。', layout:'文字侧栏 / 分区聊天 / 能力状态面板', strength:'导航稳定、状态清晰，适合频繁使用核心工具。', tradeoff:'功能感较强，动画氛围比其他方案更克制。', colors:['#f6fafb','#267d86','#df786b','#d8e9ed'] },
  d: { name:'生活手帐', english:'OUR LITTLE JOURNAL', subtitle:'把平凡的一天，翻到这一页。', layout:'页签导航 / 左页对话 / 右页居所', strength:'亲近、有记录感，适合对话与日常陪伴。', tradeoff:'双页结构占用宽度，小窗口会降级为上下排布。', colors:['#fdfcfc','#9b6576','#718b7b','#eedde1'] },
  e: { name:'番剧日常', english:'LIFE, IN GOOD COMPANY.', subtitle:'今天，也在一起。', layout:'底部导航 / 生活主舞台 / 节奏色块', strength:'二次元识别度更强，也保留清晰的功能分组。', tradeoff:'表达更鲜明，适合喜欢番剧气质而非极简界面的用户。', colors:['#fffdfb','#303735','#dd688e','#edd870','#78bfc6'] },
};

export const categories = {
  senses:{name:'感知与交互',icon:'scan-eye',subtitle:'听见你，也看见你眼前的世界。'},
  tools:{name:'效率工具',icon:'workflow',subtitle:'从眼前的一件事情开始。'},
  life:{name:'生活与陪伴',icon:'heart',subtitle:'按你的习惯，慢慢丰富日常。'},
};

export const capabilities = {
  voice:{name:'语音对话',english:'VOICE',icon:'mic',category:'senses',description:'按住说话，听她回应。',source:'ASR / TTS',permission:'麦克风未授权',dependency:'语音识别与语音合成'},
  screen:{name:'屏幕观察',english:'SCREEN',icon:'scan-eye',category:'senses',description:'单次观察，共享眼前的画面。',source:'视觉模型',permission:'屏幕未授权',dependency:'屏幕采集与视觉模型'},
  ocr:{name:'文字识别',english:'OCR',icon:'scan-text',category:'senses',description:'从图片中提取可编辑的文字。',source:'OCR 引擎',permission:'未选择图片',dependency:'本地或远程 OCR 引擎'},
  camera:{name:'摄像头观察',english:'CAMERA',icon:'camera',category:'senses',description:'单次查看经过授权的摄像头。',source:'视觉模型',permission:'摄像头未授权',dependency:'摄像头与视觉模型'},
  translate:{name:'截屏翻译',english:'TRANSLATE',icon:'languages',category:'tools',description:'框选画面，阅读另一种语言。',source:'翻译实现',permission:'屏幕未授权',dependency:'截图、翻译及可选 OCR'},
  note:{name:'随手记',english:'NOTES',icon:'notebook-pen',category:'tools',description:'保留需要稍后整理的想法。',source:'本地存储',permission:'无设备权限',dependency:'本地笔记模块'},
  tasks:{name:'今日待办',english:'TASKS',icon:'list-todo',category:'tools',description:'让重要的事情有一个位置。',source:'待办来源',permission:'无设备权限',dependency:'本地待办模块'},
  music:{name:'音乐',english:'MUSIC',icon:'music-2',category:'life',description:'为日常选择一段背景音乐。',source:'音乐来源',permission:'无设备权限',dependency:'用户选择的音乐来源'},
};

export const demo = {
  time:'14:32',date:'09.06',name:'Sumika',
  first:'回来啦。阳光刚好落在窗边，要一起坐一会儿吗？',
  user:'先陪我待一会儿吧。',last:'好呀。不着急，我们慢慢来。',pet:'我在这里，陪你慢慢来。',
};
