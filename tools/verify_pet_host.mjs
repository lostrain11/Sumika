import {loadPlaywright} from './lib/playwright.mjs';
const url = process.argv[2] || 'http://127.0.0.1:8897/?pet=1';
const {chromium} = loadPlaywright();
const browser = await chromium.launch({channel:'msedge', headless:true});
try {
  const page = await browser.newPage({viewport:{width:340,height:430}});
  await page.goto(url); await page.waitForTimeout(1200);
  const value = await page.evaluate(() => ({
    pet: Boolean(document.querySelector('#deskpet')),
    topbar: getComputedStyle(document.querySelector('.topbar')).display,
    main: getComputedStyle(document.querySelector('main')).display,
    chat: getComputedStyle(document.querySelector('.dp-chat')).display,
    title: document.title,
    stageVisible: document.querySelector('#deskpet .dp-chara').getBoundingClientRect().width > 0,
    screensOffscreen: [...document.querySelectorAll('.screen')].every(element => element.getBoundingClientRect().right <= 0),
  }));
  if (!value.pet || !value.stageVisible || !value.screensOffscreen || value.topbar !== 'none' || value.main !== 'none' || value.chat !== 'flex') {
    throw new Error('pet host projection is incomplete: ' + JSON.stringify(value));
  }
  await page.screenshot({path:'E:/SumikaBuild/pet-host-check-20261008/pet.png'});
  console.log(JSON.stringify({passed:true, ...value, screenshot:'E:/SumikaBuild/pet-host-check-20261008/pet.png'}));
} finally { await browser.close(); }
