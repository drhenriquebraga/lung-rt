"""Headless Chrome verification against the isolated synthetic server."""
from pathlib import Path
import json
import os
import tempfile
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
BASE_URL="http://127.0.0.1:"+os.environ.get("LUNG_RT_TEST_PORT","18747")
LANGS=['pt-BR','en','de','es','fr','it','pl','ar','bn','ko','zh-CN','ja']
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe')
 try:
  page=browser.new_page(viewport={"width":1440,"height":1000});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
  page.goto(BASE_URL+'/lung/laudo');page.wait_for_load_state('networkidle')
  assert page.locator('#lung-start').is_disabled()
  assert page.locator('#lung-report-option').is_hidden()
  assert page.locator('#lung-select').inner_text()
  page.locator('#lung-bell').click();page.wait_for_function("document.getElementById('lung-morph').dataset.open==='true'")
  assert page.locator('#lung-notifications').get_attribute('aria-hidden')=='false'
  page.keyboard.press('Escape');assert page.locator('#lung-bell').get_attribute('aria-expanded')=='false'
  texts=[]
  for lang in LANGS:
   page.evaluate('(lang)=>document.documentElement.lang=lang',lang)
   page.wait_for_function('(lang)=>document.documentElement.lang===lang',arg=lang)
   page.wait_for_timeout(30)
   warning=page.locator('[data-lung-key=warning]').inner_text();assert warning
   texts.append(warning)
  assert len(set(texts))==12
  page.evaluate("document.documentElement.lang='pt-BR'")
  page.route('**/api/varrer/iniciar',lambda route:route.fulfill(json={"v":"synthetic-scan","fim":True,"final":True,"linhas":[{"uid":"synthetic","bilhete":"synthetic-ticket","modalidade":"CT","desc":"SYNTHETIC TEST ONLY","cortes":12}],"series":1,"pastas":1}))
  page.locator('#lung-select').click()
  page.locator('#lung_pick_pasta').fill('SYNTHETIC TEST ONLY')
  page.locator('#lung_pick_form').evaluate("form=>form.requestSubmit()")
  page.locator('#lung-series button').wait_for(state='visible')
  assert page.locator('#lung-series').evaluate("el=>!!el.closest('[data-ui-ps]')")
  page.locator('#lung-series button').click()
  page.wait_for_function("document.getElementById('lung-z').max==='11'")
  assert page.locator('#lung-start').is_enabled()
  assert page.locator('#lung-axial').evaluate("c=>c.getContext('2d').getImageData(256,256,1,1).data[0]")>0
  page.on('dialog',lambda dialog:dialog.accept())
  page.locator('#lung-start').click()
  page.wait_for_function("document.getElementById('lung-error').textContent.includes('6 GB')")
  assert not page.locator('#lung-text').inner_text()
  pages=page.evaluate("async()=>{const m=await import('/lung-assets/lung.js');return await m.pdfPages('SYNTHETIC TEST ONLY — اختبار — পরীক্ষা — 测试');}")
  assert len(pages)==1 and pages[0]['width']==794 and pages[0]['height']==1123
  assert len(pages[0]['jpeg'])>1000
  page.emulate_media(reduced_motion='reduce')
  assert page.locator('#lung-morph').evaluate("e=>getComputedStyle(e).transitionDuration")=='0s'
  page.set_viewport_size({"width":390,"height":844})
  page.evaluate("document.documentElement.lang='pt-BR'")
  assert page.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth+2')
  page.screenshot(path=str(Path(tempfile.gettempdir())/'lung-ui-mobile.png'),full_page=True)
  page.set_viewport_size({"width":1440,"height":1000});page.goto(BASE_URL+'/lung/rastreio');page.wait_for_load_state('networkidle')
  assert not page.locator('#lung-generate').is_checked()
  assert page.locator('#lung-report-option').is_visible()
  page.screenshot(path=str(Path(tempfile.gettempdir())/'lung-ui-desktop.png'),full_page=True)
  for route,kind in (('rastreio','lung'),('laudo','lung'),('laudo/rx','rx')):
   page.goto(BASE_URL+'/lung/'+route);page.wait_for_load_state('networkidle')
   titles=[]
   for lang in LANGS:
    actual=page.evaluate('''async ({lang,kind})=>{
      const rx=kind==='rx';
      const module=await import(rx?'/lung-assets/xray-i18n.js':'/lung-assets/i18n.js');
      const t=rx?module.text:module.t;
      document.documentElement.lang=lang;
      document.documentElement.dir=lang==='ar'?'rtl':'ltr';
      await new Promise(requestAnimationFrame);
      const titleKey=rx?'title':document.body.dataset.lungMode==='report'?'reportTitle':'screeningTitle';
      const textAttr=rx?'data-rx-text':'data-lung-key';
      const labelAttr=rx?'data-rx-label':'data-lung-title';
      const failures=[];
      for(const el of document.querySelectorAll('['+textAttr+']')){
        const key=el.getAttribute(textAttr);
        if(rx&&['rx-model-state','rx-report-state'].includes(el.id))continue;
        if(!el.textContent||el.textContent!==t(key))failures.push(key);
      }
      for(const el of document.querySelectorAll('['+labelAttr+']')){
        const key=el.getAttribute(labelAttr);
        if(el.getAttribute(el.tagName==='IMG'?'alt':'aria-label')!==t(key))failures.push(key);
      }
      const title=t(titleKey);
      if(document.title!==title||document.querySelector('.ui-fn-tag').textContent.trim()!==title)failures.push(titleKey);
      return {title,failures};
    }''',{'lang':lang,'kind':kind})
    assert not actual['failures'],(route,lang,actual['failures'])
    titles.append(actual['title'])
   assert len(set(titles))>=10,(route,titles)
  assert not errors,errors
  print(json.dumps({"chrome":"passed","languages":12,"localized_routes":3,"desktop_mobile":True,"reduced_motion":True,"default_report_flag":0,"page_errors":errors}))
 finally:browser.close()
