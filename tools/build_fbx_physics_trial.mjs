// 为隔离物理实验采样 Mixamo 跑步，不将动作注册为正式陪伴动作。
import fs from 'node:fs';
import path from 'node:path';
import * as THREE from 'three';
import {FBXLoader} from 'three/addons/loaders/FBXLoader.js';
import {Parser} from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';

const [fbx,pmx,output]=process.argv.slice(2);
if(!output)throw new Error('用法：node --loader ./tools/node_three_loader.mjs tools/build_fbx_physics_trial.mjs <FBX> <PMX> <输出JSON>');
if([fbx,pmx].some(file=>path.resolve(file).toLowerCase()===path.resolve(output).toLowerCase()))throw new Error('输出不能覆盖源 FBX 或 PMX');
const buffer=file=>{const b=fs.readFileSync(file);return b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength);};
const asset=new FBXLoader().parse(buffer(fbx),'');
const clip=asset.animations.find(c=>c.duration>0&&c.tracks.length>20);
if(!clip)throw new Error('缺少可采样的动画');
const source=new Map();asset.traverse(b=>{if(b.isBone)source.set(b.name.replace(/[^a-zA-Z0-9]/g,''),b);});
const s=name=>source.get('mixamorig'+name),v=()=>new THREE.Vector3(),q=()=>new THREE.Quaternion();
const mapping=[['Hips','下半身'],['Spine','上半身'],['Spine1','上半身1'],['Spine2','上半身2'],['Neck','首'],['Head','頭'],...['Right','Left'].flatMap((side,i)=>['Shoulder','Arm','ForeArm','Hand','UpLeg','Leg','Foot'].map((name,j)=>[side+name,['右','左'][i]+['肩','腕','ひじ','手首','足','ひざ','足首'][j]]))];
const data=new Parser().parsePmx(buffer(pmx),true),mesh=new THREE.SkinnedMesh();
const bones=data.bones.map(b=>{const result=new THREE.Bone();result.name=b.name;result.position.fromArray(b.position);if(b.parentIndex>=0)result.position.sub(v().fromArray(data.bones[b.parentIndex].position));return result;});
bones.forEach((b,i)=>(data.bones[i].parentIndex>=0?bones[data.bones[i].parentIndex]:mesh).add(b));mesh.bind(new THREE.Skeleton(bones));mesh.updateMatrixWorld(true);
const target=new Map(bones.map(b=>[b.name,b]));
for(const [from,to] of mapping)if(!s(from)||!target.has(to))throw new Error('缺少骨骼 '+from+'/'+to);
asset.updateMatrixWorld(true);
const sourceRest=new Map([...source].map(([name,b])=>[name,{rotation:b.getWorldQuaternion(q()),position:b.getWorldPosition(v())}]));
const targetRest=new Map(bones.map(b=>[b.name,{rotation:b.getWorldQuaternion(q()),local:b.quaternion.clone(),position:b.position.clone()}]));
const p=name=>target.get(name).getWorldPosition(v()),sp=name=>s(name).getWorldPosition(v());
const scale=p('下半身').y/sourceRest.get('mixamorigHips').position.y;
const hipRest=sourceRest.get('mixamorigHips').position;
const world=(name,rotation)=>{const b=target.get(name);b.quaternion.copy(b.parent.getWorldQuaternion(q()).invert().multiply(rotation)).normalize();mesh.updateMatrixWorld(true);};
const aim=(name,child,from,to)=>{const direction=sp(to).sub(sp(from)).normalize(),current=p(child).sub(p(name)).normalize();world(name,q().setFromUnitVectors(current,direction).multiply(target.get(name).getWorldQuaternion(q())));};
const mixer=new THREE.AnimationMixer(asset);mixer.clipAction(clip).play();
const tracks=new Map([...mapping.map(([,name])=>[name,{name:'.bones['+name+'].quaternion',type:'quaternion',times:[],values:[]}]),['センター',{name:'.bones[センター].position',type:'vector',times:[],values:[]}]]);
const count=Math.ceil(clip.duration*30);
for(let frame=0;frame<=count;frame++){
  const time=Math.min(frame/30,clip.duration);mixer.setTime(time===clip.duration?time-1e-6:time);asset.updateMatrixWorld(true);
  for(const b of bones){const rest=targetRest.get(b.name);b.quaternion.copy(rest.local);b.position.copy(rest.position);}mesh.updateMatrixWorld(true);
  // 跑步机保留上下起伏及小幅左右摆动，消除前后位移以便固定镜头比较。
  const offset=sp('Hips').sub(hipRest).multiplyScalar(scale);offset.z=0;
  target.get('センター').position.add(offset);mesh.updateMatrixWorld(true);
  for(const [from,to] of mapping)world(to,s(from).getWorldQuaternion(q()).multiply(sourceRest.get('mixamorig'+from).rotation.clone().invert()).multiply(targetRest.get(to).rotation));
  for(const [side,word] of [['右','Right'],['左','Left']]){
    aim(side+'肩',side+'腕',word+'Shoulder',word+'Arm');aim(side+'腕',side+'ひじ',word+'Arm',word+'ForeArm');aim(side+'ひじ',side+'手首',word+'ForeArm',word+'Hand');
    aim(side+'足',side+'ひざ',word+'UpLeg',word+'Leg');aim(side+'ひざ',side+'足首',word+'Leg',word+'Foot');
  }
  for(const [name,track] of tracks){track.times.push(time);track.values.push(...(track.type==='quaternion'?target.get(name).quaternion:target.get(name).position).toArray());}
}
const result={format:'hsin.physics-trial',version:1,source:path.basename(fbx),duration:clip.duration,sample_fps:30,scale,tracks:[...tracks.values()]};
if(result.tracks.some(t=>t.values.some(x=>!Number.isFinite(x))))throw new Error('重定向出现非有限值');
fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(result));
console.log(JSON.stringify({duration:result.duration,tracks:result.tracks.length,frames:count+1,scale}));
