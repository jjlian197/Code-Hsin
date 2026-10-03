import assert from 'node:assert/strict';
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';
import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';
import { Parser } from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';
import { FBXLoader } from '../src/assets/pmx_viewer/lib/three/addons/loaders/FBXLoader.js';
import { retargetLayingPose } from '../src/assets/pmx_viewer/laying_pose.js';

const config=JSON.parse(execFileSync('python',['-c',
  'import json; from src.core.app_config import load_config,project_path; c=load_config(); print(json.dumps({"pose":str(project_path(c["sprite"]["animation"]["side_lying"])),"models":[str(project_path(p)) for p in c["sprite"]["model"]["forms"].values()]}))'],{encoding:'utf8'}));
if(!fs.existsSync(config.pose)){console.log('SKIP: user FBX is not distributed with source');process.exit(0);}
const buffer=path=>{const b=fs.readFileSync(path);return b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength);};
const source=new FBXLoader().parse(buffer(config.pose),'');
for(const path of config.models){
  const data=new Parser().parsePmx(buffer(path),true),mesh=new THREE.SkinnedMesh();
  const bones=data.bones.map(b=>{const node=new THREE.Bone();node.name=b.name;node.position.fromArray(b.position);
    if(b.parentIndex>=0)node.position.sub(new THREE.Vector3().fromArray(data.bones[b.parentIndex].position));return node;});
  bones.forEach((b,i)=>(data.bones[i].parentIndex>=0?bones[data.bones[i].parentIndex]:mesh).add(b));
  mesh.bind(new THREE.Skeleton(bones));mesh.geometry.userData.MMD={rigidBodies:data.rigidBodies};
  bones.find(b=>b.name==='右腕').rotation.z=.67;
  const prior=bones.map(b=>[...b.position.toArray(),...b.quaternion.toArray()]);
  const clip=retargetLayingPose(source,mesh);
  assert(clip.validate());
  assert.deepEqual(bones.map(b=>[...b.position.toArray(),...b.quaternion.toArray()]),prior,'retargeting restores the live mesh');
  assert(clip.userData.frozenDynamicBones>600,'bind hair and clothing independently of standing simulation');
  for(const track of clip.tracks){assert([...track.values].every(Number.isFinite));assert.equal(track.values.length,track.times.length*track.getValueSize());}
  const mixer=new THREE.AnimationMixer(mesh);mixer.clipAction(clip).setLoop(THREE.LoopRepeat,Infinity).play();mixer.update(3);
  mesh.updateMatrixWorld(true);
  const position=name=>bones.find(b=>b.name===name).getWorldPosition(new THREE.Vector3());
  const hip=position('下半身'),head=position('頭');
  assert(head.x<hip.x-3,'head beside pelvis instead of upright');
  assert(position('右手首').distanceTo(head)<4,'supporting hand stays near head');
  for(const side of ['右','左']){
    assert(position(side+'足首').x>hip.x+8,'legs extend horizontally along the dress');
    const thigh=position(side+'ひざ').sub(position(side+'足')).normalize();
    const calf=position(side+'足首').sub(position(side+'ひざ')).normalize();
    assert(thigh.dot(calf)>.8,'keep knee bend below 37 degrees for the long skirt');
  }
  const pose=bones.map(b=>b.quaternion.toArray());mixer.update(20);mesh.updateMatrixWorld(true);
  assert.deepEqual(bones.map(b=>b.quaternion.toArray()),pose,'static FBX holds over multiple loops');
  mixer.stopAllAction();mixer.uncacheRoot(mesh);
  assert(bones.every(b=>b.quaternion.toArray().every(Number.isFinite)));
}
const invalid=new THREE.Group();invalid.animations=[source.animations.find(c=>c.tracks.length>20)];
assert.throws(()=>retargetLayingPose(invalid,null),/缺少 Mixamo/);
invalid.animations=[new THREE.AnimationClip('dance',10,invalid.animations[0].tracks)];
assert.throws(()=>retargetLayingPose(invalid,null),/定格 FBX/);
console.log('PASS: both forms, static FBX retargeting, shallow knee, held pose, clothing reset and live-mesh restoration');
