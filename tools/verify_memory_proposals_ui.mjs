// Shipped UI with synthetic memory responses; no personal writes or model calls.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)(process.argv[2]);
const browser=await chromium.launch({channel:'msedge',headless:true});
try {
  const page=await browser.newPage();
  let state={scope:{role_id:'fixture',project_id:'default'},revision:'r1',memories:[],relations:[],
    proposals:[{event_id:'fixture:user:0',text:'用户喜欢绿茶。',quote:'我喜欢绿茶',source:'model_proposal'},
      {event_id:'fixture:user:1',text:'用户住在成都。',quote:'我住在成都',source:'model_proposal'}]};
  const writes=[];
  await page.route('**/api/roles',r=>r.fulfill({json:{active:{id:'fixture'},roles:[{id:'fixture',name:'验收角色',complete:true}]}}));
  await page.route('**/api/manage/roles/fixture/**',r=>{
    const action=new URL(r.request().url()).pathname.split('/').pop();
    if(action==='usage')return r.fulfill({json:{groups:[]}});
    if(r.request().method()==='POST'){
      const data=r.request().postDataJSON();writes.push({action,...data});
      assert.equal(data.confirmed,true);
      assert.equal(data.expected_revision,state.revision);
      const p=state.proposals.find(p=>p.event_id===data.event_id);
      p.status=action==='accept_proposal'?'accepted':'rejected';
      if(p.status==='accepted')state.memories.push({id:1,text:p.text,source:'user-confirmed'});
      state.revision+='x';
    }
    return r.fulfill({json:state});
  });
  await page.goto('http://127.0.0.1:8765/#settings');
  await page.locator('.set-nav [data-section="data"]').waitFor();
  await page.locator('#gnav [data-go="shelf"]').click();
  await page.locator('.cap-card[data-capability-id="memory"]').click();
  await page.getByLabel('模型记忆提议（需确认）',{exact:true}).waitFor({state:'visible'});
  assert.equal(await page.getByLabel('模型记忆提议（需确认）',{exact:true}).isChecked(),false);
  await page.getByRole('button',{name:'管理角色记忆与关系',exact:true}).click();
  await page.getByText('用户原话：我喜欢绿茶',{exact:true}).waitFor();
  page.on('dialog',d=>d.accept());
  await page.getByRole('button',{name:'确认记住',exact:true}).first().click();
  await page.getByRole('heading',{name:'待确认记忆（1）',exact:true}).waitFor();
  await page.getByRole('button',{name:'忽略',exact:true}).click();
  await page.getByRole('heading',{name:'待确认记忆（0）',exact:true}).waitFor();
  assert.deepEqual(writes.map(w=>w.action),['accept_proposal','reject_proposal']);
  assert.equal(state.memories.length,1);
  console.log('PASS: disabled default, source quote, explicit accept, reject, revision, single fact; synthetic data only');
} finally {await browser.close();}
