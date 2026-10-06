// 自包含骨架预览：不携带 PMX 网格/贴图，不依赖网络或修改角色配置。
import fs from 'node:fs';
export function renderPreview(report) {
  const payload = JSON.stringify(report).replace(/</g, '\\u003c');
  // 内嵌同一份纯 JS 模块，保证离线 HTML 校正与 CLI 重算使用相同规则。
  const editorCode=['schema','matcher','editor'].map(name=>fs.readFileSync(new URL(`../../src/assets/pmx_viewer/rig/${name}.js`,import.meta.url),'utf8')
    .replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'')).join('\n');
  return `<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hsin 骨架匹配预览</title><style>
*{box-sizing:border-box}body{margin:0;background:#101522;color:#e8edf7;font:14px system-ui}
header{padding:18px 24px;border-bottom:1px solid #35405b}h1{font-size:21px;margin:0 0 8px}
main{display:grid;grid-template-columns:minmax(340px,1fr) minmax(350px,480px);height:calc(100vh - 150px)}
.stage{position:relative;min-height:420px}canvas{width:100%;height:100%;touch-action:none}
.controls{position:absolute;top:12px;left:18px;display:flex;gap:12px;flex-wrap:wrap}
aside{overflow:auto;padding:12px;background:#171e30}.inspector{position:sticky;top:-12px;background:#171e30;padding:8px 0;z-index:1}button,select{background:#28334d;color:#fff;border:1px solid #596684;border-radius:5px;padding:6px}
table{width:100%;border-collapse:collapse}td,th{text-align:left;border-bottom:1px solid #303b54;padding:8px 5px}
tr{cursor:pointer}tr.selected{background:#354367}.matched,.manual{color:#72e2b4}.review{color:#ffca75}.missing,.disabled{color:#adb6c9}
#detail{white-space:pre-wrap;line-height:1.6;padding:12px;background:#0e1422;max-height:120px;overflow:auto}.edit{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}.edit select{max-width:100%}#message{color:#ffca75;white-space:pre-wrap}footer{padding:10px 24px;color:#b4bed0}
@media(max-width:760px){main{display:block;height:auto}.stage{height:480px}aside{max-height:600px}}
</style><header><h1>Hsin 骨架匹配预览</h1><div id="summary"></div></header>
<main><div class="stage"><div class="controls"><button id="front">正面复位</button><label><input id="all" type="checkbox">显示全部辅助骨</label><span>拖动旋转 · 滚轮缩放 · 点击骨点或表格定位</span></div><canvas id="canvas"></canvas></div>
<aside><div class="inspector"><p>绿色：已接受；橙色：待确认；灰色：辅助骨。此处只检查骨架，不代表动作兼容。</p>
<select id="filter"><option value="all">全部语义骨</option><option value="required">必需骨</option><option value="review">待确认</option><option value="missing">缺失</option></select>
<div id="detail">选择语义骨查看候选与匹配依据。</div></div><table><thead><tr><th>语义</th><th>状态 / 原骨名</th></tr></thead><tbody id="rows"></tbody></table></aside></main>
<footer>修改只保存在本页；导出修正 JSON 后用 --overrides 重新生成 rig_map.json，再供运行时加载。未验证新模型的骨轴、动作或物理。</footer>
<script type="application/json" id="data">${payload}</script><script>
${editorCode}
let report=JSON.parse(document.getElementById('data').textContent);const bones=report.skeleton,editor=new RigEditor(report);
const canvas=document.getElementById('canvas'), ctx=canvas.getContext('2d');
let entries,accepted;
function refreshReport(){report=editor.report;entries=Object.entries(report.bones);accepted=new Map(entries.filter(([,m])=>m.index!==undefined).map(([id,m])=>[m.index,id]));
document.getElementById('summary').textContent=report.model.name+' · '+bones.length+' 骨 · 已接受 '+(report.summary.matched+report.summary.manual)+'（人工 '+report.summary.manual+'） · 待确认 '+report.summary.review+' · 必需未解决 '+report.summary.requiredUnresolved.length+' · 结构警告 '+report.issues.length;}
refreshReport();
let yaw=0,pitch=0,zoom=1,selected=null,points=[],pointer=null;
const controls=document.createElement('div');controls.className='edit';
const choice=document.createElement('select');choice.setAttribute('aria-label','指定骨骼');
for(const [value,text] of [['auto','恢复自动匹配'],['disabled','禁用此语义'],...bones.map(b=>[String(b.index),'#'+b.index+' '+b.name])]){const option=document.createElement('option');option.value=value;option.textContent=text;choice.append(option);}
choice.disabled=true;const apply=document.createElement('button');apply.textContent='应用校正';apply.disabled=true;
const save=document.createElement('button');save.textContent='导出修正 JSON';const load=document.createElement('input');load.type='file';load.accept='.json,application/json';load.setAttribute('aria-label','导入修正 JSON');
const message=document.createElement('div');message.id='message';message.setAttribute('role','status');controls.append(choice,apply,save,load);
document.getElementById('detail').after(controls,message);
function updateEditor(run){try{run();refreshReport();renderRows();if(selected)choose(selected);else draw();message.textContent=report.issues.length?'已应用；有结构警告，需检查后再接入运行时。':'已应用，记得导出修正 JSON。';}catch(error){message.textContent=error.message;}}
apply.onclick=()=>{if(!selected)return;updateEditor(()=>choice.value==='auto'?editor.reset(selected):editor.set(selected,choice.value==='disabled'?null:Number(choice.value)));};
save.onclick=()=>{const url=URL.createObjectURL(new Blob([editor.export()],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='overrides-'+report.model.sha256.slice(0,12)+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);message.textContent='已生成下载，请保存修正 JSON；原 PMX 与当前角色配置未改变。';};
load.onchange=async()=>{const file=load.files[0];if(!file)return;try{const parsed=JSON.parse(await file.text());updateEditor(()=>editor.apply(parsed));}catch(error){message.textContent=error.message;}load.value='';};
const bounds=[0,1,2].map(axis=>[Math.min(...bones.map(b=>b.position[axis])),Math.max(...bones.map(b=>b.position[axis]))]);
const center=bounds.map(b=>(b[0]+b[1])/2), span=Math.max(...bounds.map(b=>b[1]-b[0]),1e-5);
function choose(id){selected=id;const m=report.bones[id];
 choice.disabled=false;apply.disabled=false;choice.value=m.status==='disabled'?'disabled':m.index!==undefined?String(m.index):'auto';
 document.getElementById('detail').textContent=id+' · '+m.status+'\\n'+(m.index!==undefined?'已选择 #'+m.index+' '+m.name+'\\n':'')+
 (m.note?m.note+'\\n':'')+report.issues.filter(i=>i.semantic===id).map(i=>'警告：'+i.type+'\\n').join('')+m.candidates.map(c=>'#'+c.index+' '+c.name+' · '+c.score+' · '+c.reasons.join(', ')+(c.warnings.length?' · 注意 '+c.warnings.join(', '):'')).join('\\n');
 renderRows();draw();}
function renderRows(){const body=document.getElementById('rows');body.replaceChildren();const filter=document.getElementById('filter').value;
 for(const [id,m] of entries){if(filter==='required'&&!m.required||['review','missing'].includes(filter)&&m.status!==filter)continue;
  const tr=document.createElement('tr');if(id===selected)tr.className='selected';
  const a=document.createElement('td'),b=document.createElement('td');a.textContent=id+(m.required?' *':'');
  b.className=m.status;b.textContent=m.status+' / '+(m.name??m.candidates[0]?.name??'—');tr.append(a,b);tr.onclick=()=>choose(id);body.append(tr);}}
function draw(){const r=canvas.getBoundingClientRect(),dpr=devicePixelRatio||1;canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,r.width,r.height);
 const scale=Math.min(r.width,r.height-100)/span*.8*zoom;
 points=bones.map(b=>{const [x,y,z]=b.position.map((v,i)=>v-center[i]);const xx=x*Math.cos(yaw)+z*Math.sin(yaw),zz=-x*Math.sin(yaw)+z*Math.cos(yaw);return [r.width/2+xx*scale,r.height/2-(y*Math.cos(pitch)-zz*Math.sin(pitch))*scale];});
 const m=selected?report.bones[selected]:null, focus=m?.index??m?.candidates[0]?.index;
 const candidates=new Set(m?.candidates.map(c=>c.index)??[]),showAll=document.getElementById('all').checked;
 const visible=i=>showAll||accepted.has(i)||candidates.has(i);
 const parentPoint=i=>{let parent=bones[i].parentIndex;while(parent>=0&&!visible(parent))parent=bones[parent].parentIndex;return points[parent];};
 for(const b of bones){if(!visible(b.index))continue;const p=points[b.index],parent=parentPoint(b.index);ctx.strokeStyle=b.index===focus?'#ffe074':accepted.has(b.index)?'#72e2b4':'#465472';ctx.lineWidth=b.index===focus?3:1;
 if(parent){ctx.beginPath();ctx.moveTo(...parent);ctx.lineTo(...p);ctx.stroke();}
 ctx.fillStyle=b.index===focus?'#ffe074':accepted.has(b.index)?'#72e2b4':candidates.has(b.index)?'#ffca75':'#66738e';ctx.beginPath();ctx.arc(...p,b.index===focus?6:3,0,Math.PI*2);ctx.fill();}
 if(focus!==undefined){const p=points[focus],parent=parentPoint(focus);ctx.strokeStyle='#ffe074';ctx.lineWidth=3;if(parent){ctx.beginPath();ctx.moveTo(...parent);ctx.lineTo(...p);ctx.stroke();}ctx.fillStyle='#ffe074';ctx.beginPath();ctx.arc(...p,6,0,Math.PI*2);ctx.fill();ctx.font='13px system-ui';ctx.fillStyle='#fff';ctx.fillText('#'+focus+' '+bones[focus].name,p[0]+10,p[1]-8);}}
canvas.onpointerdown=e=>{pointer={x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY};canvas.setPointerCapture(e.pointerId);};
canvas.onpointermove=e=>{if(!pointer)return;yaw+=(e.clientX-pointer.x)*.01;pitch=Math.max(-1.3,Math.min(1.3,pitch+(e.clientY-pointer.y)*.01));pointer.x=e.clientX;pointer.y=e.clientY;draw();};
canvas.onpointerup=e=>{if(pointer&&Math.hypot(e.clientX-pointer.startX,e.clientY-pointer.startY)<4){const r=canvas.getBoundingClientRect();let best=null,dist=12;
 for(const [index,id] of accepted){const p=points[index],d=Math.hypot(p[0]-e.clientX+r.left,p[1]-e.clientY+r.top);if(d<dist){dist=d;best=id;}}if(best)choose(best);}pointer=null;};
canvas.onpointercancel=()=>pointer=null;
canvas.onwheel=e=>{e.preventDefault();zoom=Math.max(.3,Math.min(5,zoom*Math.exp(-e.deltaY*.001)));draw();};
document.getElementById('front').onclick=()=>{yaw=0;pitch=0;zoom=1;draw();};document.getElementById('all').onchange=draw;document.getElementById('filter').onchange=renderRows;
window.onresize=draw;renderRows();draw();
</script></html>`;
}
