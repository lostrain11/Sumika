// Read-only regression: live settings and pre-auxiliary Bridge responses.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)(process.argv[2]);
const browser=await chromium.launch({channel:'msedge',headless:true});
try {
  for(const legacy of [false,true]){
    const page=await browser.newPage();
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    if(legacy)await page.route('**/api/manage/settings',async route=>{
      assert.equal(route.request().method(),'GET');
      const response=await route.fetch();const data=await response.json();
      delete data.data.auxiliary;delete data.data.model_library;
      await route.fulfill({response,json:data});
    });
    await page.goto('http://127.0.0.1:8765/#settings');
    await page.locator('.set-nav [data-section="models"]').waitFor({state:'visible',timeout:10000});
    await page.locator('.set-nav [data-section="models"]').click();
    const panel=page.locator('[data-settings-section="models"]');
    await panel.waitFor({state:'visible'});
    for(const usage of ['work','role','auxiliary']){
      await page.locator(`.model-usage-tab[data-usage="${usage}"]`).click();
      assert.equal(await page.locator(`.model-usage-panel[data-usage="${usage}"]`).isVisible(),true);
    }
    await page.locator('.set-nav [data-section="appearance"]').click();
    assert.equal(await page.locator('[data-settings-section="appearance"]').isVisible(),true);
    assert.deepEqual(errors,[]);
    assert.equal(await page.locator('[data-management-error]').count(),0);
    await page.close();
  }
  console.log('PASS: live and legacy settings navigation, all model tabs; no writes');
} finally {await browser.close();}
