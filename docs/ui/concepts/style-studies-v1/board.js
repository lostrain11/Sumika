import { studies } from './studies.js';

const query=new URLSearchParams(location.search);
const overview=query.get('overview')==='1';
const key=Object.hasOwn(studies,query.get('study'))?query.get('study'):'a';
const entry=studies[key];
const board=document.getElementById('board');
const heading=`<header class="board-heading"><div class="board-brand">sumika <small>すみか / 五套风格与布局对照</small></div><span>DESIGN STUDIES / 2026.09<br>独立设计示例 · 非真实客户端</span></header>`;
const label=(left,right)=>`<div class="view-label"><span>${left}</span><span>${right}</span></div>`;
if(overview) {
  board.className='overview';
  board.innerHTML=`${heading}<h1>同一个 Sumika，五种相处方式。</h1><p>每套使用同一角色与演示内容，比较视觉表达、导航位置、聊天比例与能力组织。</p><div class="overview-grid">${Object.entries(studies).map(([id,study])=>`<a class="overview-item" href="./board.html?study=${id}"><h2>${id.toUpperCase()} / ${study.name}</h2><img class="overview-home" src="./exports/${id}-companion.png" alt="${study.name}陪伴页"><div class="overview-subviews"><img src="./exports/${id}-capabilities.png" alt="${study.name}能力页"><img src="./exports/${id}-pet.png" alt="${study.name}桌宠"></div><p>${study.layout}</p><p>${study.strength}</p></a>`).join('')}<section class="overview-notes"><h2>先选相处方式，再选细节。</h2><p>A 安静而直观<br>B 全景角色与对白<br>C 功能与状态优先<br>D 对话与居所的双页<br>E 番剧日常的鲜明节奏</p><p>能力与权限分离。<br>房间与角色保持静态。<br>不会启动模型或设备。</p></section></div>`;
} else {
  board.className='board';
  board.innerHTML=`${heading}<header class="board-title"><h1>${key.toUpperCase()} / ${entry.name}</h1><p>${entry.english}</p></header><div class="board-layout"><div><section class="design-view">${label('01 / 陪伴页','1440 × 900')}<img src="./exports/${key}-companion.png" alt="${entry.name}陪伴页"></section><section class="design-view">${label('02 / 能力页','1440 × 900')}<img src="./exports/${key}-capabilities.png" alt="${entry.name}能力页"></section></div><aside class="board-aside">${label('03 / 桌宠','480 × 420')}<div class="pet-mount"><img src="./exports/${key}-pet.png" alt="${entry.name}桌宠"></div><div class="study-details"><h2>${entry.subtitle}</h2><h3>空间组织</h3><p>${entry.layout}</p><h3>适合的体验</h3><p>${entry.strength}</p><h3>需要权衡</h3><p>${entry.tradeoff}</p><div class="swatches">${entry.colors.map(color=>`<span style="background:${color}"></span>`).join('')}</div><h3>共同底线</h3><p>五个文字入口 / 三类能力 / 纯加号添加<br>未配置与未授权明确保留<br>模块添加不等于功能启用<br>同一示例角色、会话与生活状态</p>${key==='e'?'<h3>番剧气质参考</h3><p>参考《孤独摇滚》的日常色彩节奏、MyGO 与 GBC 的生活空间感。房间、标记与排版原创，没有使用作品截图、Logo 或角色素材。</p>':''}</div></aside></div><footer class="board-footer"><span>静态姿态、示例对话和未配置能力，不代表生活模拟或真实服务已实现。</span><span>HTML / CSS 排版 · 原创 Three.js 房间 · VRoid 样例角色</span></footer>`;
}
function resize(){const scale=Math.min(1,innerWidth/(overview?2400:1920));document.documentElement.style.setProperty('--scale',String(scale));document.body.style.height=`${(overview?2000:1800)*scale}px`;}
addEventListener('resize',resize);resize();
