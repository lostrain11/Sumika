"""Real isolated Chromium test using intercepted local fixture pages only."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from extensions.desktop.consultation import ConsultationBrowser

HTML='''<textarea id="prompt"></textarea><button id="send" onclick="let r=document.createElement('div');r.className='answer';r.textContent=document.querySelector('textarea').value;document.body.appendChild(r)">Send</button><div class="answer">old answer</div>'''
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    try:
        context=browser.new_context()
        context.route('https://sumika.invalid/**',lambda route:route.fulfill(status=200,content_type='text/html',body=HTML))
        c=ConsultationBrowser(context)
        for i in range(12):c.open(str(i),'https://sumika.invalid/'+str(i))
        r=c.consult('0','测试原文',prompt_selector='#prompt',submit_selector='#send',response_selector='.answer',approved=True)
        assert r['text']=='测试原文'
        assert len(context.pages)==12
        c.close_all();assert len(context.pages)==0
        print(json.dumps({'pages':12,'new_response_not_stale':True,'closed':True,'external_requests':0}))
    finally:browser.close()
