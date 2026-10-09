// Owned public tutorial browser. No user profile, credentials or PCM persistence.
import {spawn} from 'node:child_process';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {loadPlaywright} from './lib/playwright.mjs';

const [outputArg,python,helper,model,productRoot,sensevoiceModel,asrSite,voicePython,pauseAtArg]=process.argv.slice(2);
if(!outputArg || !python || !helper || !model) throw Error('output python helper model required');
const output=resolve(outputArg);
await mkdir(output,{recursive:true});
const title=`Sumika audio acceptance ${Date.now()}`;
const {chromium}=loadPlaywright();
const browser=await chromium.launchPersistentContext(resolve(output,'profile'),{
  channel:'msedge',headless:false,args:['--autoplay-policy=no-user-gesture-required'],
});
let child;
let pauseTimer, pauseTask;
let logs='',errors='';
const report={passed:false,scope:productRoot
  ? 'Owned Bilibili -> product HTTP bridge/worker/fusion/withdrawal; no paid model or microphone'
  : 'Owned Bilibili real audio -> process loopback -> Vosk; no paid model or microphone'};
try {
  const page=browser.pages()[0];
  await page.goto('https://www.bilibili.com/video/BV1Lf4y1M72V/',{waitUntil:'domcontentloaded',timeout:30000});
  await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2,null,{timeout:20000});
  await page.evaluate(label=>{
    document.querySelector('video').pause();document.title=label;
    // The player asynchronously rewrites its page title after initialization.
    window.sumikaAcceptanceTitleTimer=setInterval(()=>{document.title=label;},100);
  },title);
  child=spawn(python,['-X','utf8','-B','tools/verify_application_audio_live.py',
    '--title',title,'--helper',helper,'--model',model,'--output',resolve(output,'audio'),
    ...(sensevoiceModel ? ['--sensevoice-model',resolve(sensevoiceModel)] : []),
    ...(asrSite ? ['--asr-site',resolve(asrSite)] : []),
    ...(voicePython ? ['--voice-python',resolve(voicePython)] : []),
    ...(productRoot ? ['--product-root',resolve(productRoot)] : [])],
    {cwd:resolve('.'),env:{...process.env,PYTHONPATH:resolve('.')},windowsHide:true,stdio:['ignore','pipe','pipe']});
  const exited=new Promise((done,reject)=>{child.once('error',reject);child.once('exit',code=>done(code));});
  child.stderr.on('data',chunk=>{errors+=chunk;});
  const lines=createInterface({input:child.stdout});
  await new Promise((done,reject)=>{
    const timer=setTimeout(()=>reject(Error('capture readiness timeout')),60000);
    lines.on('line',line=>{logs+=line+'\n';if(line==='READY'){clearTimeout(timer);done();}});
    exited.then(code=>{clearTimeout(timer);reject(Error(`capture exited before ready: ${code}`));},reject);
  });
  await page.evaluate(async()=>{const video=document.querySelector('video');video.currentTime=0;video.muted=false;video.volume=0.65;await video.play();});
  report.start=await page.evaluate(()=>({time:document.querySelector('video').currentTime,paused:document.querySelector('video').paused}));
  if(pauseAtArg !== undefined){
    const pauseAt=Number(pauseAtArg);
    if(!Number.isFinite(pauseAt) || pauseAt<1 || pauseAt>20) throw Error('bounded pause time required');
    pauseTimer=setTimeout(()=>{
      pauseTask=(async()=>{
        report.pause=await page.evaluate(()=>{const v=document.querySelector('video');v.pause();return {time:v.currentTime,paused:v.paused};});
        // The browser/player and WASAPI loopback can retain a bounded tail
        // after pause. Allow that tail to drain before checking VAD silence;
        // this does not extend the worker's total acceptance duration.
        await new Promise(done=>setTimeout(done,5000));
        await page.evaluate(()=>document.querySelector('video').play());
        report.resumed=true;
      })().catch(error=>{report.pause_failure=error.message;});
    },pauseAt*1000);
  }
  const code=await exited;
  report.end=await page.evaluate(()=>{const v=document.querySelector('video');v.pause();return {time:v.currentTime,paused:v.paused};});
  await writeFile(resolve(output,'worker.log'),logs+errors);
  report.worker_exit_code=code;
  if(productRoot && sensevoiceModel && pauseAtArg!==undefined){
    const audioReport=JSON.parse(await readFile(resolve(output,'audio/report.json'),'utf8'));
    report.silence_endpoint_verified=audioReport.transcripts.some(item=>
      item.metadata?.segmentation==='silero-vad' && item.metadata.segment_end_reason==='silence');
  }
  report.passed=code===0 && !report.start.paused && report.end.time>report.start.time+20
    && (pauseAtArg===undefined || (report.pause?.paused && report.resumed && !report.pause_failure))
    && (!(productRoot && sensevoiceModel && pauseAtArg!==undefined) || report.silence_endpoint_verified);
} finally {
  clearTimeout(pauseTimer);
  if(pauseTask) await pauseTask;
  if(child && child.exitCode===null){child.kill();await new Promise(done=>child.once('exit',done));}
  await browser.close();
  await writeFile(resolve(output,'worker.log'),logs+errors);
  await writeFile(resolve(output,'report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
}
if(!report.passed) throw Error('real Bilibili audio acceptance failed');
