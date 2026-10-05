import fs from 'node:fs';
import vm from 'node:vm';
import {execFileSync} from 'node:child_process';
import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';
import {Parser} from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';
import {MMDLoader} from '../src/assets/pmx_viewer/lib/three/addons/loaders/MMDLoader.js';

// 真实 PMX 和 Ammo 检查，不启动桌面窗口或修改用户配置。
const base=new URL('../src/assets/pmx_viewer/lib/three/addons/libs/',import.meta.url);
const sandbox={console,WebAssembly,setTimeout,clearTimeout};
vm.runInNewContext(fs.readFileSync(new URL('ammo.wasm.js',base),'utf8'),sandbox);
globalThis.window={Ammo:sandbox.Ammo};
const {AnimationRuntime}=await import('../src/assets/pmx_viewer/animation_runtime.js');
const paths=JSON.parse(execFileSync('python',['-c','import json;from src.core.app_config import load_config,project_path;print(json.dumps({n:str(project_path(p)) for n,p in load_config()["sprite"]["model"]["forms"].items()}))'],{encoding:'utf8'}));
for(const [form,path] of Object.entries(paths)){
  if(form!==(process.argv[2]||'first'))continue;
  const bytes=fs.readFileSync(process.argv[4]&&!process.argv[4].startsWith('--')?process.argv[4]:path),data=new Parser().parsePmx(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),true);
  for(const fps of [Number(process.argv[3]||60)]){
    const arena={console,WebAssembly,setTimeout,clearTimeout};
    vm.runInNewContext(fs.readFileSync(new URL('ammo.wasm.js',base),'utf8'),arena);
    const ammo=await arena.Ammo({wasmBinary:fs.readFileSync(new URL('ammo.wasm.wasm',base))});
    globalThis.Ammo=ammo;
    const geometry=new MMDLoader().meshBuilder.geometryBuilder.build(data);
    const mesh=new THREE.SkinnedMesh(geometry,new THREE.MeshBasicMaterial());
    const bones=data.bones.map(b=>{const node=new THREE.Bone();node.name=b.name;node.position.fromArray(b.position);if(b.parentIndex>=0)node.position.sub(new THREE.Vector3().fromArray(data.bones[b.parentIndex].position));return node;});
    bones.forEach((b,i)=>(data.bones[i].parentIndex>=0?bones[data.bones[i].parentIndex]:mesh).add(b));
    mesh.bind(new THREE.Skeleton(bones));mesh.morphTargetInfluences=data.morphs.map(()=>0);
    const runtime=new AnimationRuntime(mesh,ammo,{behavior:{breathing:false,mouse_follow:false,random_idle:false,auto_blink:false}});
    const chest=bones.filter(b=>/^[左右]胸$/.test(b.name));
    const chestRest=chest.map(b=>b.position.clone());
    let chestOffset=0,chestAngle=0;
    if(process.argv.includes('--baseline')){
      delete runtime.physics._stepSimulation;
    }
    const clothes=runtime.dynamicBodies.filter(b=>/Dress|Sleeve|BreastTie|Tail_/.test(b.bone.name));
    let maxAngle=0,sumAngle=0,samples=0;
    for(let i=0;i<fps*20;i++){
      if(process.argv.includes('--baseline'))runtime.physicsIdleTime=0;
      const before=clothes.map(b=>b.bone.quaternion.clone());runtime.update(1/fps);
      chest.forEach((b,j)=>{chestOffset=Math.max(chestOffset,b.position.distanceTo(chestRest[j]));chestAngle=Math.max(chestAngle,b.quaternion.angleTo(new THREE.Quaternion()));});
      if(i>=fps*15)clothes.forEach((b,j)=>{const a=b.bone.quaternion.angleTo(before[j])*fps;maxAngle=Math.max(maxAngle,a);sumAngle+=a;samples++;});
    }
    if(!bones.every(b=>b.quaternion.toArray().every(Number.isFinite)))throw Error('nonfinite physics');
    if(!process.argv.includes('--baseline')){
      if(maxAngle>1e-4)throw Error('idle cloth did not settle');
      runtime.play('wave');runtime.update(1/fps);
      if(runtime.physicsRestPose||!runtime.helper.enabled.physics)throw Error('motion did not wake physics');
      for(let i=0;i<fps*8;i++)runtime.update(1/fps);
      if(!runtime.physicsRestPose)throw Error('physics did not settle after motion');
    }
    if(chest.length&&chestOffset>0.001)throw Error('chest shifted from its bone anchor');
    console.log(JSON.stringify({form,fps,cloth_bodies:clothes.length,max_rad_per_sec:maxAngle,mean_rad_per_sec:sumAngle/samples,chestOffset,chestAngle}));
  }
}
