import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';
import {Parser} from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';
import {createBuiltinClips, palmNormal} from '../src/assets/pmx_viewer/motions.js';
import {gestureGeometry} from '../src/assets/pmx_viewer/calibrated_gestures.js';

const paths=JSON.parse(execFileSync('python',['-X','utf8','-c','import json; from src.core.app_config import load_config,project_path; print(json.dumps({n:str(project_path(p)) for n,p in load_config()["sprite"]["model"]["forms"].items()}))'],{encoding:'utf8'}));
const report=[];
for(const [form,path] of Object.entries(paths)){
  const raw=fs.readFileSync(path), data=new Parser().parsePmx(raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength),true);
  const mesh=new THREE.SkinnedMesh();
  const bones=data.bones.map(b=>{const bone=new THREE.Bone();bone.name=b.name;bone.position.fromArray(b.position);
    if(b.parentIndex>=0)bone.position.sub(new THREE.Vector3().fromArray(data.bones[b.parentIndex].position));return bone;});
  bones.forEach((b,i)=>(data.bones[i].parentIndex>=0?bones[data.bones[i].parentIndex]:mesh).add(b));
  mesh.bind(new THREE.Skeleton(bones));mesh.updateMatrixWorld(true);
  const clips=createBuiltinClips(mesh),mixer=new THREE.AnimationMixer(mesh);mixer.clipAction(clips.idle).play();
  for(const name of ['finger_heart','crossed_arms']){
    const action=mixer.clipAction(clips[name]).setLoop(THREE.LoopOnce,1).play();mixer.update(2);mesh.updateMatrixWorld(true);
    const geometry=gestureGeometry(mesh);
    report.push({form,name,metadata:clips[name].userData,geometry,palms:['左','右'].map(s=>palmNormal(mesh,s).toArray())});
    action.stop();mixer.update(0);
  }
}
fs.mkdirSync('.runtime',{recursive:true});fs.writeFileSync('.runtime/gesture-points.json',JSON.stringify(report,null,2));
console.log(JSON.stringify(report.map(({form,name,geometry,metadata,palms})=>({form,name,metadata,indexGap:geometry.indexGap,lower:geometry.lower,palms,
  wrists:['左手首','右手首'].map(n=>geometry.points[n]),indexTips:['左人指先','右人指先'].map(n=>geometry.points[n])})),null,2));
