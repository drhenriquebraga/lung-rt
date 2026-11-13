// Execute the actual loading function with controlled asynchronous volume IO.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../web/lung.js'),'utf8');
const loading=source.slice(source.indexOf('async function loadVolume(session){'),source.indexOf('function drawMpr(){'));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject};};
const mpr={dataset:{contourReference:'prior',contourReady:'1'}};
const elements=new Map(),cleared=[];
const element=id=>{if(!elements.has(id))elements.set(id,{width:512,height:512,getContext:()=>({clearRect:()=>cleared.push(id)})});return elements.get(id);};
const jobs=new Map();
const ctx=vm.createContext({AbortController,Float32Array,console,Number,Array,Error,String,meta:{dims:[9,9,9]},volume:new Float32Array(1),loadedSession:'prior',volumeGeneration:0,volumeController:null,lastDisplayStatus:null,statusMotion:null,document:{querySelector:()=>mpr},$:element,showStatus:()=>{},drawCount:0,drawMpr(){ctx.drawCount++;},api:(_,data)=>jobs.get(data.session).meta.promise,fetch:async url=>({ok:true,arrayBuffer:()=>jobs.get(decodeURIComponent(url.split('/').at(-1))).pixels.promise})});
vm.runInContext(loading,ctx);
const ticketA='a'.repeat(32),ticketB='b'.repeat(32);
function job(key,ticket){const j={meta:deferred(),pixels:deferred(),metadata:{dims:[2,3,4],spacing:[1,1,1],reference_ticket:ticket}};jobs.set(key,j);return j;}
async function complete(j){j.meta.resolve(j.metadata);j.pixels.resolve(new Float32Array(24).buffer);}
(async()=>{
 const a=job('A',ticketA),runA=ctx.loadVolume('A');assert.equal(mpr.dataset.contourReference,undefined);assert.equal(mpr.dataset.contourReady,undefined);assert.equal(ctx.volume,null);assert.equal(cleared.length,3);
 a.meta.resolve(a.metadata);await Promise.resolve();assert.equal(mpr.dataset.contourReference,undefined,'metadata alone must not enable editing');
 a.pixels.resolve(new Float32Array(24).buffer);assert.equal(await runA,true);assert.equal(mpr.dataset.contourReference,ticketA);assert.equal(ctx.loadedSession,'A');assert.equal(ctx.drawCount,1);
 const old=job('old',ticketA),runOld=ctx.loadVolume('old');const current=job('current',ticketB),runCurrent=ctx.loadVolume('current');await complete(current);assert.equal(await runCurrent,true);await complete(old);assert.equal(await runOld,false);assert.equal(mpr.dataset.contourReference,ticketB);assert.equal(ctx.loadedSession,'current');
 const bad=job('bad',ticketA),runBad=ctx.loadVolume('bad');bad.meta.resolve(bad.metadata);bad.pixels.resolve(new Float32Array(1).buffer);await assert.rejects(runBad,/invalid_volume/);assert.equal(mpr.dataset.contourReference,undefined);assert.equal(ctx.loadedSession,null);
 console.log('volume loading: full-draw gate, stale response isolation, malformed payload guard passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
