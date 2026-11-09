import {t,language,translate} from './i18n.js';
const $=id=>document.getElementById(id);const mode=document.body.dataset.lungMode;
let selection=null,selectedContext=null,volume=null,meta=null,worker=null,active=null,heartbeat=null,deadlineTimer=null,stage='loading',fraction=null,lastCount=0,lastState=null,statusMotion=null;
translate();new MutationObserver(()=>translate()).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
if(mode==='report'){$('lung-report-option').hidden=true;$('lung-cases-section').hidden=true;}
const api=async(action,data={})=>{const response=await fetch('/api/lung-plugin/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,language:language(),...data})});const value=await response.json();if(!response.ok)throw new Error(value.error||'operation_failed');return value;};
function showStatus(key,frac){
 const moving=['loading','preprocessing','encoding','prefill','generating','translating','exporting'].includes(key);
 if(moving&&window.uiPensando){if(!statusMotion||!$('lung-status').querySelector('.ui-pensa'))statusMotion=window.uiPensando('lung-status');statusMotion.dizer([t(key)]);}
 else{statusMotion?.parar();statusMotion=null;$('lung-status').textContent=t(key);}
 const bar=$('lung-progress');bar.hidden=false;if(Number.isFinite(frac)){bar.max=1;bar.value=frac;}else bar.removeAttribute('value');}
function showError(error){$('lung-error').textContent=t(error.message||error);}
function clearError(){$('lung-error').textContent='';}
function textNode(tag,text){const el=document.createElement(tag);el.textContent=text;return el;}
function button(text,onClick){const el=textNode('button',text);el.className='ui-bt';el.type='button';el.addEventListener('click',onClick);return el;}
const picker=window.uiCarregarImagens?.('lung_pick',{uso:'series',chave:'lung-plugin-select',opcoes:{modalidades:['CT']},aoFim(rows,data,context){
 const container=$('lung-series');container.replaceChildren();selectedContext=context;
 for(const row of rows){if(!row.bilhete||row.mod&&row.mod!=='CT')continue;
  const label=row.desc||row.descricao||row.curto||'CT';
  container.append(button(label,async()=>{clearError();try{
   selection=await api('select',{selection:{scan_id:data.v,bilhete:row.bilhete,uid:row.uid}});
   $('lung-selection').textContent=selection.description;$('lung-start').disabled=false;container.replaceChildren();picker.fechar();
   await loadVolume(selection.session);
  }catch(error){showError(error);}}));
 }
},aoErro:message=>showError({message})});
$('lung-select').onclick=()=>picker?.abrir($('lung-select'));
async function loadVolume(session){
 showStatus('encoding');meta=await api('volume_meta',{session});const response=await fetch('/api/lung-plugin/volume/'+encodeURIComponent(session),{cache:'no-store'});if(!response.ok)throw new Error('volume_unavailable');volume=new Float32Array(await response.arrayBuffer());
 for(const [axis,index] of [['x',0],['y',1],['z',2]]){$('lung-'+axis).max=meta.dims[index]-1;$('lung-'+axis).value=Math.floor(meta.dims[index]/2);$('lung-'+axis).oninput=drawMpr;}
 drawMpr();$('lung-progress').hidden=true;$('lung-status').textContent='';
}
function drawMpr(){
 if(!volume||!meta)return;const [X,Y,Z]=meta.dims;const at=(x,y,z)=>volume[x+X*(y+Y*z)];const px=+$('lung-x').value,py=+$('lung-y').value,pz=+$('lung-z').value;
 for(const [name,w,h,spx,spy,read] of [['axial',X,Y,meta.spacing[0],meta.spacing[1],(x,y)=>at(x,y,pz)],['coronal',X,Z,meta.spacing[0],meta.spacing[2],(x,z)=>at(x,py,Z-1-z)],['sagittal',Y,Z,meta.spacing[1],meta.spacing[2],(y,z)=>at(px,y,Z-1-z)]]){
  const canvas=$('lung-'+name),ctx=canvas.getContext('2d'),off=document.createElement('canvas');off.width=w;off.height=h;const oc=off.getContext('2d'),img=oc.createImageData(w,h);
  for(let j=0;j<h;j++)for(let i=0;i<w;i++){const q=(j*w+i)*4,v=Math.max(0,Math.min(255,(read(i,j)+1000)/1400*255));img.data[q]=img.data[q+1]=img.data[q+2]=v;img.data[q+3]=255;}oc.putImageData(img,0,0);
  ctx.fillStyle='#05070a';ctx.fillRect(0,0,512,512);const scale=Math.min(512/(w*spx),512/(h*spy));const dw=w*spx*scale,dh=h*spy*scale;ctx.drawImage(off,(512-dw)/2,(512-dh)/2,dw,dh);ctx.fillStyle='white';ctx.font='14px sans-serif';ctx.fillText(name.toUpperCase(),10,20);
 }
}
$('lung-start').onclick=async()=>{clearError();if(!selection||!window.confirm(t('confirm')))return;try{
 if(mode==='screening'){await api('start_screening',{session:selection.session,generate_reports:$('lung-generate').checked?1:0,confirmed:true});$('lung-start').disabled=true;$('lung-stop').disabled=false;}
 else{const report=await api('create_report',{session:selection.session,confirmed:true});if(report.state==='failed')throw new Error(report.error);await execute(report.id);}
}catch(error){showError(error);}};
$('lung-stop').onclick=async()=>{try{if(active){const id=active.id;cleanup();await api('cancel_report',{id});}if(mode==='screening')await api('stop_screening');$('lung-stop').disabled=true;$('lung-start').disabled=!selection;}catch(error){showError(error);}};
function cleanup(){statusMotion?.parar();statusMotion=null;worker?.terminate();worker=null;clearInterval(heartbeat);clearTimeout(deadlineTimer);heartbeat=null;deadlineTimer=null;active=null;$('lung-progress').hidden=true;}
async function execute(id){
 if(active)return;clearError();const lease=await api('start_report',{id});if(!lease.lease)return;active=lease;stage='loading';fraction=null;$('lung-start').disabled=true;$('lung-stop').disabled=false;$('lung-text').textContent='';
 try{
  if(!meta||selection?.session!==lease.session)await loadVolume(lease.session);
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
function renderState(state){
 lastState=state;const count=state.pending.length;$('lung-count').textContent=count>99?'99+':String(count);document.querySelector('.t-badge').dataset.open=String(count>0);
 if(count>lastCount){const ring=document.querySelector('.nb-ring');ring.classList.remove('is-ringing');void ring.offsetWidth;ring.classList.add('is-ringing');}lastCount=count;
 const pending=$('lung-pending');pending.replaceChildren();if(!count)pending.append(textNode('p',t('empty')));
 for(const item of state.pending){const el=textNode('div',t('review')+' · '+item.kind);el.className='lung-item';el.append(button(t('acknowledge'),async()=>{await api('review',{key:item._key,revision:item._revision});await refresh();}));pending.append(el);}
 const reports=$('lung-reports');reports.replaceChildren();for(const report of state.reports.slice(0,8)){const row=textNode('div',t(report.error||report.state));row.className='lung-item';if(report.state==='completed')row.append(button(t('review'),()=>{$('lung-text').textContent=report.display_text;}));reports.append(row);}
 const cases=$('lung-cases');cases.replaceChildren();if(!state.cases.length)cases.append(textNode('p',t('empty')));
 for(const value of state.cases){const row=textNode('div',new Date(value.created_at*1000).toLocaleString()+' · '+t(value.segmentation_state));row.className='lung-item';for(const lesion of value.lesions){row.append(textNode('p',String(lesion.id)+' · '+t('volume')+': '+Number(lesion.volume_mm3).toLocaleString()+' mm³ · '+(lesion.lobo&&lesion.lobo!=='indeterminado'?lesion.lobo:t('indeterminate'))));}for(const match of value.longitudinal_suggestions||[]){row.append(button(t('suggested')+(match.distance_mm==null?'':' · '+match.distance_mm+' mm'),async()=>{if(!confirm(t('suggested')))return;await api('confirm_link',{case_id:value.id,...match});await refresh();}));}cases.append(row);}
 if(mode==='screening'&&!active){$('lung-start').disabled=state.screening.active||!selection;$('lung-stop').disabled=!state.screening.active;$('lung-status').textContent=t(state.screening.stage);}
 if(mode==='screening'&&state.screening.generate_reports===1&&!active){const next=state.reports.find(r=>r.state==='waiting_browser'&&r.can_execute);if(next)execute(next.id).catch(error=>{if(error.message!=='gpu_busy')showError(error);});}
}
async function refresh(){try{const response=await fetch('/api/lung-plugin/state',{cache:'no-store'});if(response.ok)renderState(await response.json());}catch(error){showError(error);}}
for(const action of ['backup','sync'])$('lung-'+action).onclick=async()=>{clearError();const folder=$('lung-data-folder').value.trim();if(!folder)return;try{const result=await api(action,{folder,confirmed:true});$('lung-data-status').textContent=action==='backup'?result.file:Object.entries(result).map(([k,v])=>k+': '+v).join(' · ');}catch(error){showError(error);}};
window.addEventListener('pagehide',()=>{worker?.terminate();});
refresh();setInterval(refresh,3000);
