// Owned browser compatibility probe. Login remains a user's interactive action.
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {loadPlaywright} from './lib/playwright.mjs';

const output=resolve(process.argv[2] || 'E:/SumikaBuild/learning-sites-probe');
await mkdir(output,{recursive:true});
const {chromium}=loadPlaywright();
const browser=await chromium.launchPersistentContext(resolve(output,'profile'),{
  channel:'msedge',headless:false,args:['--force-renderer-accessibility'],
  viewport:{width:1280,height:800},
});
const report={scope:'Owned public Bilibili search/video and WeRead landing; no model/audio calls or account credential reads',sites:{}};
const script=await readFile('extensions/companion/browser_video_snapshot.js','utf8');
try {
  const video=browser.pages()[0] || await browser.newPage();
  try {
    await video.goto('https://search.bilibili.com/all?keyword='+encodeURIComponent('导数 教程'),{waitUntil:'domcontentloaded',timeout:30000});
    await video.waitForTimeout(2500);
    const href=await video.locator('a[href*="/video/BV"]').first().getAttribute('href');
    if(!href) throw Error('public tutorial video link unavailable');
    const url=new URL(href,video.url());
    if(url.protocol!=='https:' || !['www.bilibili.com','bilibili.com'].includes(url.hostname)) throw Error('unexpected tutorial origin');
    await video.goto(url.href,{waitUntil:'domcontentloaded',timeout:30000});
    await video.waitForTimeout(5000);
    const sample=await video.evaluate(`(${script})({origin:'https://www.bilibili.com'})`);
    await video.evaluate(()=>document.querySelector('video')?.pause());
    report.sites.bilibili={url:video.url().split('?')[0],sample};
    await video.screenshot({path:resolve(output,'bilibili.png')});
  } catch(error) {report.sites.bilibili={status:'unavailable',reason:error.message};}
  const reader=await browser.newPage();
  try {
    await reader.goto('https://weread.qq.com/',{waitUntil:'domcontentloaded',timeout:30000});
    await reader.waitForTimeout(2000);
    report.sites.weread={url:reader.url().split('?')[0],status:'awaiting_user_login_or_book_selection'};
    await reader.screenshot({path:resolve(output,'weread-landing.png')});
  } catch(error) {report.sites.weread={status:'unavailable',reason:error.message};}
  await writeFile(resolve(output,'report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({report:resolve(output,'report.json'),sites:report.sites}));
  // Retain only this owned browser for the user to log in and choose a book.
  console.log('Owned browser remains open for login/book selection; interrupt the probe to close it.');
  await new Promise(done=>{process.once('SIGINT',done);process.once('SIGTERM',done);});
} finally {await browser.close();}
