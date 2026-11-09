// LUNG RT adapter; inference math and preprocessing use the pinned MIT upstream modules.
import * as ort from './vendor/nvreason/vendor/ort/ort.webgpu.min.mjs';
import {preprocess} from './vendor/nvreason/lib/preprocess.js';
import {loadNV,EOS} from './vendor/nvreason/lib/nvreason.js';
ort.env.wasm.wasmPaths = new URL('/api/lung-plugin/runtime/',self.location.origin).href;
ort.env.wasm.numThreads = 1;
ort.env.logLevel='error';
let currentStage='loading';
const post=(type,values={})=>{if(type==='progress')currentStage=values.stage;self.postMessage({type,...values});};
let stopped=false;
self.onmessage=async({data})=>{
 if(data.stop){stopped=true;return;}
 if(!data.run)return;
 const signal=data.run;
 const expires=()=>stopped||Date.now()>=signal.deadline*1000;
 const closeFailed=error=>{stopped=true;post('error',{error});self.close();};
 const deadlineTimer=setTimeout(()=>closeFailed('timeout'),Math.max(1,signal.deadline*1000-Date.now()));
 const heartbeat=setInterval(async()=>{
  try{const response=await fetch('/api/lung-plugin/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'report_progress',id:signal.id,lease:signal.lease,stage:currentStage})});if(!response.ok)closeFailed('browser_disconnected');}
  catch(error){closeFailed('browser_disconnected');}
 },5000);
 try{
  const adapter=await self.navigator.gpu?.requestAdapter({powerPreference:'high-performance'});
  if(!adapter)throw new Error('webgpu_unavailable');
  post('progress',{stage:'loading',fraction:0});
  const spec=await (await fetch('/api/lung-plugin/provider-manifest',{cache:'no-store'})).json();
  const entries=new Map(spec.files.map(f=>[f.path,f]));
  const total=spec.files.reduce((a,f)=>a+f.size,0);let received=0;
  const blobs={};
  for(const file of spec.files){
   if(expires())throw new Error('cancelled');
   const response=await fetch('/api/lung-plugin/models/'+file.path,{cache:'no-store'});
   if(!response.ok)throw new Error('model_load_failed');
   const reader=response.body.getReader();const chunks=[];let size=0;
   while(true){const {done,value}=await reader.read();if(done)break;chunks.push(value);size+=value.length;received+=value.length;post('progress',{stage:'loading',fraction:received/total});}
   if(size!==file.size)throw new Error('model_load_failed');
   blobs[file.path]=new Blob(chunks); // Server verifies pinned SHA256 before streaming each resource.
  }
  const make=async(prefix,name)=>{const man=JSON.parse(await blobs[prefix+name+'.json'].text());return {man,blobs:Object.fromEntries([man.onnx,...man.data.map(x=>x.name)].map(n=>[n,blobs[prefix+n]]))};};
  const files={vision:await make('','vision'),decoder:await make('int4/','decoder'),tokenizer:blobs['tokenizer.json'],tokenizerConfig:blobs['tokenizer_config.json']};
  const R=await loadNV(ort,{files,device:'webgpu',log:()=>{}});
  if(R.device!=='webgpu')throw new Error('webgpu_unavailable');
  post('progress',{stage:'preprocessing',fraction:0});
  const vox=new Float32Array(signal.buffer),meta=signal.meta,plane=meta.dims[0]*meta.dims[1];
  const vol={...meta,slice:async k=>vox.subarray(k*plane,(k+1)*plane)};
  const {img}=await preprocess(vol,'chest',()=>{},f=>post('progress',{stage:'preprocessing',fraction:f}));
  post('progress',{stage:'encoding'});await R.setVolume(img);
  post('progress',{stage:'prefill',fraction:0});
  const original=await R.ask('Write a structured chest CT draft report in English with Findings and Impression. Describe only observations supported by this volume. Do not invent clinical history, prior studies or measurements. State uncertainty. This is an experimental draft requiring medical review.',{
   thinking:false,max:4096,shouldStop:expires,progress:f=>post('progress',{stage:'prefill',fraction:f}),onText:()=>post('progress',{stage:'generating'})});
  let tokens=R.lastTokens.length;let eos=EOS.has(R.pending)&&!stopped;let translated=original;
  if(eos&&signal.language!=='en'){
   const names={'pt-BR':'Brazilian Portuguese',de:'German',es:'Spanish',fr:'French',it:'Italian',pl:'Polish',ar:'Arabic',bn:'Bengali',ko:'Korean','zh-CN':'Simplified Chinese',ja:'Japanese'};
   post('progress',{stage:'translating'});
   translated=await R.ask('Translate only your previous draft into '+names[signal.language]+'. Preserve its uncertainty and structure. Add no findings, measurements, explanation or commentary.',{
    thinking:false,max:4096,shouldStop:expires,onText:()=>post('progress',{stage:'translating'})});
   eos=eos&&EOS.has(R.pending)&&!stopped;tokens=Math.max(tokens,R.lastTokens.length);
  }
  R.reset();await R.vision.release();await R.decoder.release();
  post('result',{original,translated,tokens,eos,truncated:!eos||tokens>=4096});
 }catch(error){post('error',{error:['webgpu_unavailable','model_load_failed','cancelled','timeout','browser_disconnected'].includes(error.message)?error.message:'worker_failed'});}
 finally{clearInterval(heartbeat);clearTimeout(deadlineTimer);}
};
