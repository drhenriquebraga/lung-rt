import {t,language,translate} from './i18n.js';
import {folderSelection, renderScreening} from './screening.js';
const $=id=>document.getElementById(id);const mode=document.body.dataset.lungMode;
let selection=null,selectedContext=null,volume=null,meta=null,worker=null,active=null,heartbeat=null,deadlineTimer=null,stage='loading',fraction=null,lastCount=0,lastState=null,statusMotion=null;
let currentError=null,lastDisplayStatus=null,lastSync=null;
let loadedSession=null,volumeGeneration=0,volumeController=null,selectionGeneration=0;
translate();
new MutationObserver(()=>{
 translate();
 if(lastState)renderState(lastState,false);
 if(lastDisplayStatus)showStatus(...lastDisplayStatus);
 if(currentError)showError(currentError);
 if(lastSync)showSync();
 drawMpr();
}).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
if(mode==='report'){$('lung-report-option').hidden=true;$('lung-cases-section').hidden=true;}
const api=async(action,data={},options={})=>{const response=await fetch('/api/lung-plugin/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,language:language(),...data}),signal:options.signal});const value=await response.json();if(!response.ok)throw new Error(value.error||'operation_failed');return value;};
function showStatus(key,frac){
 lastDisplayStatus=[key,frac];
 const moving=['loading','preprocessing','encoding','prefill','generating','translating','exporting'].includes(key);
 if(moving&&window.uiPensando){if(!statusMotion||!$('lung-status').querySelector('.ui-pensa'))statusMotion=window.uiPensando('lung-status');statusMotion.dizer([t(key)]);}
 else{statusMotion?.parar();statusMotion=null;$('lung-status').textContent=t(key);}
 const bar=$('lung-progress');bar.hidden=false;if(Number.isFinite(frac)){bar.max=1;bar.value=frac;}else bar.removeAttribute('value');}
function showError(error){currentError=error.message||error;$('lung-error').textContent=t(currentError);}
function clearError(){currentError=null;$('lung-error').textContent='';}
function textNode(tag,text){const el=document.createElement(tag);el.textContent=text;return el;}
function button(text,onClick){const el=textNode('button',text);el.className='ui-bt';el.type='button';el.addEventListener('click',onClick);return el;}
const picker=mode==='report' && window.uiCarregarImagens?.('lung_pick',{uso:'series',chave:'lung-plugin-select',opcoes:{modalidades:['CT']},aoFim(rows,data,context){
 const container=$('lung-series');container.replaceChildren();selectedContext=context;
 for(const row of rows){if(!row.bilhete||row.mod&&row.mod!=='CT')continue;
  const label=row.desc||row.descricao||row.curto||'CT';
  container.append(button(label,async()=>{clearError();const chosen=++selectionGeneration;$('lung-start').disabled=true;try{
   const next=await api('select',{selection:{scan_id:data.v,bilhete:row.bilhete,uid:row.uid}});if(chosen!==selectionGeneration)return;selection=next;
   $('lung-selection').textContent=selection.description;container.replaceChildren();picker.fechar();
   if(await loadVolume(selection.session))$('lung-start').disabled=!!active;
  }catch(error){showError(error);}}));
 }
},aoErro:message=>showError({message})});
const folders = mode==='screening' ? folderSelection(api,showError,()=>refresh()) : null;
if(mode==='report') $('lung-select').onclick=()=>picker?.abrir($('lung-select'));
async function loadVolume(session){
 const generation=++volumeGeneration;volumeController?.abort();const controller=new AbortController();volumeController=controller;
 const mpr=document.querySelector('.lung-mpr');if(mpr){delete mpr.dataset.contourReference;delete mpr.dataset.contourReady;}
 volume=null;meta=null;loadedSession=null;
 for(const name of ['axial','coronal','sagittal']){const c=$('lung-'+name);c.getContext('2d').clearRect(0,0,c.width,c.height);}
 showStatus('encoding');
 try{
  const nextMeta=await api('volume_meta',{session},{signal:controller.signal});
  const response=await fetch('/api/lung-plugin/volume/'+encodeURIComponent(session),{cache:'no-store',signal:controller.signal});if(!response.ok)throw new Error('volume_unavailable');
  const buffer=await response.arrayBuffer();if(generation!==volumeGeneration)return false;
  const dims=nextMeta.dims;if(!Array.isArray(dims)||dims.length!==3||dims.some(v=>!Number.isSafeInteger(v)||v<=0)||dims.reduce((a,b)=>a*b,1)*4!==buffer.byteLength||buffer.byteLength>512*1024**2)throw new Error('invalid_volume');
  volume=new Float32Array(buffer);meta=nextMeta;
  for(const [axis,index] of [['x',0],['y',1],['z',2]]){$('lung-'+axis).max=meta.dims[index]-1;$('lung-'+axis).value=Math.floor(meta.dims[index]/2);$('lung-'+axis).oninput=drawMpr;}
  drawMpr();loadedSession=session;
  if(mpr&&/^[a-f0-9]{32}$/.test(String(meta.reference_ticket||''))){mpr.dataset.contourReference=meta.reference_ticket;mpr.dataset.contourReady='1';}
  lastDisplayStatus=null;statusMotion?.parar();statusMotion=null;$('lung-progress').hidden=true;$('lung-status').textContent='';return true;
 }catch(error){if(generation!==volumeGeneration||error.name==='AbortError')return false;volume=null;meta=null;loadedSession=null;throw error;}
}
function drawMpr(){
 if(!volume||!meta)return;const [X,Y,Z]=meta.dims;const at=(x,y,z)=>volume[x+X*(y+Y*z)];const px=+$('lung-x').value,py=+$('lung-y').value,pz=+$('lung-z').value;
 for(const [name,w,h,spx,spy,read] of [['axial',X,Y,meta.spacing[0],meta.spacing[1],(x,y)=>at(x,y,pz)],['coronal',X,Z,meta.spacing[0],meta.spacing[2],(x,z)=>at(x,py,Z-1-z)],['sagittal',Y,Z,meta.spacing[1],meta.spacing[2],(y,z)=>at(px,y,Z-1-z)]]){
  const canvas=$('lung-'+name),ctx=canvas.getContext('2d'),off=document.createElement('canvas');off.width=w;off.height=h;const oc=off.getContext('2d'),img=oc.createImageData(w,h);
  for(let j=0;j<h;j++)for(let i=0;i<w;i++){const q=(j*w+i)*4,v=Math.max(0,Math.min(255,(read(i,j)+1000)/1400*255));img.data[q]=img.data[q+1]=img.data[q+2]=v;img.data[q+3]=255;}oc.putImageData(img,0,0);
  ctx.fillStyle='#05070a';ctx.fillRect(0,0,512,512);const scale=Math.min(512/(w*spx),512/(h*spy));const dw=w*spx*scale,dh=h*spy*scale;ctx.drawImage(off,(512-dw)/2,(512-dh)/2,dw,dh);ctx.fillStyle='white';ctx.font='14px sans-serif';const rtl=language()==='ar';ctx.direction=rtl?'rtl':'ltr';ctx.textAlign=rtl?'right':'left';ctx.fillText(t(name),rtl?502:10,20);
 }
}
$('lung-start').onclick=async()=>{clearError();const roots=folders?[...folders]:[],session=selection?.session;
 if(!(roots.length||session))return;const generateReports=mode==='screening'&&$('lung-generate').checked;
 const approved=window.uiConfirmarDoPlugin?await window.uiConfirmarDoPlugin('lung-rt',t('confirm')):window.confirm(t('confirm'));
 if(!approved)return;try{
 if(mode==='screening'){await api('start_screening',{folders:roots,generate_reports:generateReports?1:0,confirmed:true});$('lung-start').disabled=true;$('lung-stop').disabled=false;}
 else{const report=await api('create_report',{session,confirmed:true});if(report.state==='failed')throw new Error(report.error);await execute(report.id);}
}catch(error){showError(error);}};
$('lung-stop').onclick=async()=>{try{if(active){const id=active.id;cleanup();await api('cancel_report',{id});}if(mode==='screening')await api('stop_screening');$('lung-stop').disabled=true;$('lung-start').disabled=!selection;}catch(error){showError(error);}};
function cleanup(){lastDisplayStatus=null;statusMotion?.parar();statusMotion=null;worker?.terminate();worker=null;clearInterval(heartbeat);clearTimeout(deadlineTimer);heartbeat=null;deadlineTimer=null;active=null;$('lung-progress').hidden=true;}
async function execute(id){
 if(active)return;clearError();const lease=await api('start_report',{id});if(!lease.lease)return;active=lease;stage='loading';fraction=null;$('lung-start').disabled=true;$('lung-stop').disabled=false;$('lung-text').textContent='';
 try{
  if(!meta||loadedSession!==lease.session){if(!await loadVolume(lease.session))throw new Error('volume_unavailable');}
  if(loadedSession!==lease.session)throw new Error('volume_unavailable');
  worker=new Worker('/lung-assets/report-worker.js',{type:'module'});
  const update=()=>active&&api('report_progress',{id:active.id,lease:active.lease,stage,fraction}).catch(error=>{cleanup();showError(error);});
  heartbeat=setInterval(update,5000);deadlineTimer=setTimeout(async()=>{const running=active;cleanup();if(running)await api('cancel_report',{id:running.id}).catch(()=>{});showError('timeout');},Math.max(1,lease.deadline*1000-Date.now()));
  worker.onmessage=async({data})=>{
   if(!active)return;
   if(data.type==='progress'){stage=data.stage;fraction=data.fraction??null;showStatus(stage,fraction);return;}
   if(data.type==='error'){const running=active;cleanup();await api('report_error',{id:running.id,lease:running.lease,error:data.error}).catch(()=>{});showError(data.error);return;}
   if(data.type==='result'){
    const running=active;
    try{const draft=await api('report_result',{id:running.id,lease:running.lease,...data});if(draft.state!=='exporting'){cleanup();showError('incomplete');return;}
     stage='exporting';fraction=null;showStatus(stage);$('lung-text').textContent=draft.display_text;
     const pages=await pdfPages(draft.display_text);await api('report_export',{id:running.id,lease:running.lease,pages,text_sha256:draft.text_sha256});cleanup();showStatus('completed',1);$('lung-start').disabled=!selection;$('lung-stop').disabled=true;
    }catch(error){if(active){const running=active;cleanup();await api('report_error',{id:running.id,lease:running.lease,error:'worker_failed'}).catch(()=>{});}showError(error);}
   }
  };
  worker.onerror=async()=>{if(!active)return;const running=active;cleanup();await api('report_error',{id:running.id,lease:running.lease,error:'worker_failed'}).catch(()=>{});showError('worker_failed');};
  const buffer=volume.slice().buffer;worker.postMessage({run:{buffer,meta,language:lease.language,id:lease.id,lease:lease.lease,deadline:lease.deadline}},[buffer]);
 }catch(error){const running=active;cleanup();if(running)await api('report_error',{id:running.id,lease:running.lease,error:'worker_failed'}).catch(()=>{});throw error;}
}
export async function pdfPages(text){
 await document.fonts.ready;const canvas=document.createElement('canvas');canvas.width=794;canvas.height=1123;const ctx=canvas.getContext('2d');const pages=[];const rtl=language()==='ar';let y=110;
 const begin=()=>{ctx.fillStyle='white';ctx.fillRect(0,0,794,1123);ctx.fillStyle='#8b1730';ctx.font='bold 18px sans-serif';ctx.textAlign='left';ctx.direction='ltr';ctx.fillText('UNVERIFIED DRAFT / PRELIMINARY',48,40);ctx.font='16px sans-serif';ctx.fillText(t('unverified'),48,66);ctx.fillStyle='#111';ctx.font='15px sans-serif';ctx.textAlign=rtl?'right':'left';ctx.direction=rtl?'rtl':'ltr';y=110;};
 const end=()=>pages.push({width:794,height:1123,jpeg:canvas.toDataURL('image/jpeg',.92).split(',')[1]});begin();
 const line=s=>{if(y>1040){end();begin();}ctx.fillText(s,rtl?746:48,y);y+=23;};
 for(const paragraph of text.split('\n')){let current='';const segments=Intl.Segmenter?Array.from(new Intl.Segmenter(language(),{granularity:'word'}).segment(paragraph),s=>s.segment):Array.from(paragraph);for(const part of segments){if(ctx.measureText(current+part).width>698&&current){line(current);current='';}if(ctx.measureText(part).width>698){for(const ch of Array.from(part)){if(ctx.measureText(current+ch).width>698){line(current);current='';}current+=ch;}}else current+=part;}line(current);}end();return pages;
}
function toggleNotifications(open){$('lung-morph').dataset.open=String(open);$('lung-notifications').inert=!open;$('lung-notifications').setAttribute('aria-hidden',String(!open));$('lung-bell').setAttribute('aria-expanded',String(open));if(open)$('lung-close-notifications').focus();else $('lung-bell').focus();}
$('lung-bell').onclick=()=>toggleNotifications($('lung-morph').dataset.open!=='true');
$('lung-close-notifications').onclick=()=>toggleNotifications(false);
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&$('lung-morph').dataset.open==='true')toggleNotifications(false);});
document.addEventListener('click',e=>{if(!e.target.closest('.lung-notifications')&&$('lung-morph').dataset.open==='true')toggleNotifications(false);});
function renderState(state,allowStart=true){
 lastState=state;const count=state.pending.length;$('lung-count').textContent=count>99?'99+':String(count);document.querySelector('.t-badge').dataset.open=String(count>0);
 if(count>lastCount){const ring=document.querySelector('.nb-ring');ring.classList.remove('is-ringing');void ring.offsetWidth;ring.classList.add('is-ringing');}lastCount=count;
 const pending=$('lung-pending');pending.replaceChildren();if(!count)pending.append(textNode('p',t('empty')));
 for(const item of state.pending){const el=textNode('div',t('review')+' · '+t(item.kind));el.className='lung-item';el.append(button(t('acknowledge'),async()=>{await api('review',{key:item._key,revision:item._revision});await refresh();}));pending.append(el);}
 const reports=$('lung-reports');reports.replaceChildren();for(const report of state.reports.slice(0,8)){const row=textNode('div',t(report.error||report.state));row.className='lung-item';if(report.state==='completed')row.append(button(t('review'),()=>{$('lung-text').textContent=report.display_text;}));reports.append(row);}
 if(mode==='screening') renderScreening(state.cases,api,refresh,showError);
 const cases=$('lung-cases');if(mode==='report'){cases.replaceChildren();if(!state.cases.length)cases.append(textNode('p',t('empty')));
 for(const value of state.cases){const row=textNode('div',new Date(value.created_at*1000).toLocaleString(language())+' · '+t(value.segmentation_state));row.className='lung-item';for(const lesion of value.lesions){row.append(textNode('p',String(lesion.id)+' · '+t('volume')+': '+Number(lesion.volume_mm3).toLocaleString(language())+' mm³ · '+(lesion.lobo&&lesion.lobo!=='indeterminado'?lesion.lobo:t('indeterminate'))));}for(const match of value.longitudinal_suggestions||[]){row.append(button(t('suggested')+(match.distance_mm==null?'':' · '+match.distance_mm+' mm'),async()=>{if(!confirm(t('suggested')))return;await api('confirm_link',{case_id:value.id,...match});await refresh();}));}cases.append(row);}
 }
 if(mode==='screening'&&!active){$('lung-start').disabled=state.screening.active||!folders.length;$('lung-stop').disabled=!state.screening.active;$('lung-select').disabled=state.screening.active;for(const b of $('lung-folders').querySelectorAll('button'))b.disabled=state.screening.active;$('lung-status').textContent=[t(state.screening.stage),state.screening.last_error&&t(state.screening.last_error)].filter(Boolean).join(' · ');}
 if(allowStart&&mode==='screening'&&state.screening.generate_reports===1&&!active){const next=state.reports.find(r=>r.state==='waiting_browser'&&r.can_execute);if(next)execute(next.id).catch(error=>{if(error.message!=='gpu_busy')showError(error);});}
}
async function refresh(){try{const response=await fetch('/api/lung-plugin/state',{cache:'no-store'});if(response.ok)renderState(await response.json());}catch(error){showError(error);}}
function showSync(){
 $('lung-data-status').textContent=Object.entries(lastSync).map(([key,value])=>t(key)+' · '+Number(value).toLocaleString(language())).join(' | ');
}
for(const action of ['backup','sync'])$('lung-'+action).onclick=async()=>{clearError();const folder=$('lung-data-folder').value.trim();if(!folder)return;try{const result=await api(action,{folder,confirmed:true});lastSync=action==='sync'?result:null;if(lastSync)showSync();else $('lung-data-status').textContent=result.file;}catch(error){showError(error);}};
window.addEventListener('pagehide',()=>{volumeController?.abort();worker?.terminate();});
refresh();setInterval(refresh,3000);
