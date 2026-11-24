import {language,t} from './i18n.js';

const byId = id => document.getElementById(id);
function element(tag, text) {
  const node = document.createElement(tag);
  if(text != null) node.textContent=text;
  return node;
}

export function folderSelection(api,showError,changed) {
  const folders=[];
  const list=byId('lung-folders'), choose=byId('lung-select');
  function render() {
    list.replaceChildren();
    folders.forEach((path, index)=>{
      const row=element('li'), name=element('span',path);
      const remove=element('button','×');
      remove.type='button'; remove.className='ui-bt';
      remove.setAttribute('aria-label',t('remove')+' '+path);
      remove.onclick=()=>{folders.splice(index,1);render();changed();};
      row.append(name,remove); list.append(row);
    });
  }
  api('screening_options').then(data=>{
    if(!folders.length){folders.push(...(data.folders||[]));render();changed();}
  }).catch(showError);
  choose.onclick=()=>{
    const add=path=>{
      if(!path || folders.includes(path))return;
      folders.push(path);render();changed();
    };
    if(window.uiExplorador)window.uiExplorador({titulo:t('folders'),origem:choose,aoUsar:add});
    else add(window.prompt(t('folder')));
  };
  return folders;
}

let snapshot='', generation=0;
export function renderScreening(cases,api,refresh,showError) {
  const identity=language()+JSON.stringify(cases);
  if(snapshot===identity)return;
  snapshot=identity;
  const parent=byId('lung-cases');
  parent.replaceChildren();
  if(!cases.length){parent.append(element('p',t('empty')));return;}
  const table=element('table'), header=table.createTHead().insertRow(), body=table.createTBody();
  for(const key of ['axial','case','nodule','axis','volume'])header.append(element('th',t(key)));
  const number=new Intl.NumberFormat(language(),{maximumFractionDigits:2});
  for(const exam of cases) {
    const name=[exam.description,exam.series_number==null?'':'#'+exam.series_number,
      new Date(exam.created_at*1000).toLocaleString(language()),exam.id.slice(0,8)].filter(Boolean).join(' · ');
    for(const n of exam.lesions.length?exam.lesions:[null]) {
      const row=body.insertRow(), cell=row.insertCell();
      row.insertCell().textContent=name;
      if(!n){const msg=row.insertCell();msg.colSpan=3;msg.textContent=t(exam.segmentation_state);continue;}
      const path='/api/lung-plugin/screening/'+encodeURIComponent(exam.id)+'/'+encodeURIComponent(n.id);
      row.insertCell().textContent=n.id;
      row.insertCell().textContent=Number.isFinite(n.long_axis_mm)?number.format(n.long_axis_mm)+' mm':'—';
      row.insertCell().textContent=Number.isFinite(n.volume_mm3)?number.format(n.volume_mm3)+' mm³':'—';
      const image=element('img');image.src=path+'?thumb=true';image.alt=n.id;image.loading='lazy';
      image.onerror=()=>{image.alt=t('preview_unavailable');};
      const open=element('button');open.type='button';open.className='lung-thumb';open.setAttribute('aria-label',t('axial')+' '+n.id);
      const show=async()=>{
        const current=++generation;
        try{
          const response=await fetch(path+'?info=true',{cache:'no-store'});
          if(!response.ok)throw new Error('preview_unavailable');
          const info=await response.json();if(current!==generation)return;
          const dialog=byId('lung-axial-dialog'), img=byId('lung-axial-frame'), range=byId('lung-axial-level');
          range.min=info.first_slice;range.max=info.last_slice;range.value=info.axial_index;
          const paint=()=>{img.src=path+'?z='+range.value;byId('lung-axial-index').textContent=String(Number(range.value)+1);};
          range.oninput=paint; range.disabled=info.first_slice===info.last_slice;
          img.onerror=()=>showError(new Error('preview_unavailable'));
          dialog.onwheel=e=>{if(range.disabled)return;e.preventDefault();if(e.deltaY>0)range.stepUp();else range.stepDown();paint();};
          paint();if(!dialog.open)dialog.showModal();
        }catch(error){showError(error);}
      };
      open.onclick=e=>{e.stopPropagation();show();};row.ondblclick=show;open.append(image);cell.append(open);
    }
    for(const match of exam.longitudinal_suggestions||[]){
      const cell=body.insertRow().insertCell();cell.colSpan=5;
      const link=element('button',t('suggested')+(match.distance_mm==null?'':' · '+number.format(match.distance_mm)+' mm'));
      link.className='ui-bt'; link.onclick=async()=>{
        if(window.confirm(t('suggested')))try{await api('confirm_link',{case_id:exam.id,...match});await refresh();}catch(error){showError(error);}
      };
      cell.append(link);
    }
  }
  parent.append(table);
}
