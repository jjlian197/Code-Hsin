import assert from 'node:assert/strict';
import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';
import {Parser} from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';
import {analyzePmx} from '../tools/analyze_pmx_rig.mjs';
import {matchRig} from '../src/assets/pmx_viewer/rig/matcher.js';
import {RigEditor} from '../src/assets/pmx_viewer/rig/editor.js';
import {createRigAccess} from '../src/assets/pmx_viewer/rig/access.js';
import {createBuiltinClips} from '../src/assets/pmx_viewer/motions.js';
import {HsinBehavior} from '../src/assets/pmx_viewer/behavior.js';

const files=JSON.parse(execFileSync('python',['-c',
  'import json; from src.core.app_config import load_config,project_path; print(json.dumps([str(project_path(p)) for p in load_config()["sprite"]["model"]["forms"].values()]))'],{encoding:'utf8'}));
function meshFrom(data) {
  const mesh=new THREE.SkinnedMesh();
  const bones=data.bones.map(b=>{const bone=new THREE.Bone();bone.name=b.name;bone.position.fromArray(b.position);
    if(b.parentIndex>=0)bone.position.sub(new THREE.Vector3().fromArray(data.bones[b.parentIndex].position));return bone;});
  bones.forEach((b,i)=>(data.bones[i].parentIndex>=0?bones[data.bones[i].parentIndex]:mesh).add(b));
  mesh.bind(new THREE.Skeleton(bones));mesh.updateMatrixWorld(true);
  mesh.morphTargetDictionary={};mesh.morphTargetInfluences=[];return mesh;
}
for(const file of files) {
  const raw=fs.readFileSync(file),data=new Parser().parsePmx(raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength),true);
  const report=analyzePmx(file),mesh=meshFrom(data),rig=createRigAccess(mesh,report,report.model.sha256);
  assert(rig.usesOriginalNames);
  const legacy=createBuiltinClips(mesh),mapped=createBuiltinClips(mesh,rig);
  const comparable=clip=>{const value=clip.toJSON();delete value.uuid;value.tracks.sort((a,b)=>a.name.localeCompare(b.name));return value;};
  for(const name of ['idle','nod'])assert.deepEqual(comparable(mapped[name]),comparable(legacy[name]),'Hsin 基础动作轨道保持一致');
  assert.deepEqual(Object.keys(mapped),Object.keys(legacy));
  assert.equal(rig.upperTorso(),rig.get('chest'),'Hsin 原近景基准保持不变');
  const foreign={...rig,report:{...rig.report,model:{...rig.report.model,sha256:'uncalibrated-model'}}};
  assert.deepEqual(Object.keys(createBuiltinClips(mesh,foreign)),['idle','nod'],'同名骨架不代表复杂手势已校准');
  // 模拟爱弥斯的倒序编号，仍按实际颈部祖先而非名字决定近景基准。
  const neck=rig.get('neck'),parent=neck.parent;
  rig.get('spine_mid').add(neck);assert.equal(rig.upperTorso(),rig.get('spine_mid'));parent.add(neck);
  assert.throws(()=>createRigAccess(mesh,report,'wrong'),/哈希/);
  const bad=structuredClone(report);bad.bones.head.index=bad.bones.neck.index;
  assert.throws(()=>createRigAccess(mesh,bad,report.model.sha256),/索引\/名称/);

  const editor=new RigEditor(report),head=report.bones.head.index;
  editor.set('head',head);editor.set('upper_chest',null);
  const saved=JSON.parse(editor.export());
  const reopened=new RigEditor(report);reopened.apply(saved);
  assert.deepEqual(reopened.report,matchRig(data,report.model,saved));
  assert.equal(reopened.report.bones.head.status,'manual');assert.equal(reopened.report.bones.upper_chest.status,'disabled');
  const before=editor.export();assert.throws(()=>editor.apply({...saved,modelSha256:'other'}),/哈希/);assert.equal(editor.export(),before);
  assert.throws(()=>editor.set('neck',head),/重复/);assert.equal(editor.export(),before);
  editor.reset('head');assert.equal(editor.report.bones.head.status,'matched');

  // 保留真实层级/骨轴，只改核心骨名，证明基础动作通过映射而非日文硬编码寻骨。
  const custom=structuredClone(data),overrides={modelSha256:report.model.sha256,bones:{}};
  for(const [id,m] of Object.entries(report.bones))if(m.index!==undefined){custom.bones[m.index].name='custom_'+id;custom.bones[m.index].englishName='';overrides.bones[id]=m.index;}
  const customReport=matchRig(custom,report.model,overrides),customMesh=meshFrom(custom);
  const customRig=createRigAccess(customMesh,customReport,report.model.sha256),clips=createBuiltinClips(customMesh,customRig);
  assert(!customRig.usesOriginalNames);assert.deepEqual(Object.keys(clips),['idle','nod']);
  const mixer=new THREE.AnimationMixer(customMesh);mixer.clipAction(clips.idle).play();mixer.update(.05);
  assert(Math.abs(customRig.get('right_upper_arm').rotation.z-.67)<1e-6);
  const nod=mixer.clipAction(clips.nod).setLoop(THREE.LoopOnce,1).play();mixer.update(.3);
  assert(customRig.get('head').rotation.x>.17);
  const behavior=new HsinBehavior(customMesh,{random_idle:false,breathing:false},()=>.5,customRig);
  const beforeHead=customRig.get('head').quaternion.clone();behavior.setMotionClip(clips.nod);behavior.setPointer(1,0,true);behavior.advance(1);behavior.applyBones();
  assert.deepEqual(customRig.get('head').quaternion.toArray(),beforeHead.toArray(),'索引轨道所有权阻止转头叠加');
  behavior.prepareFrame();behavior.setMotionClip(null);nod.stop();mixer.update(.05);
  for(let i=0;i<60;i++){behavior.prepareFrame();behavior.advance(1/30);mixer.update(1/30);behavior.applyBones();}
  assert(customRig.get('head').rotation.y>.25,'自定义骨名实际收到视线转头');
  assert(Math.abs(customRig.get('right_upper_arm').rotation.z-.67)<1e-6);
  console.log('PASS '+file+'：校正保存/复用、冲突隔离、原动作一致、自定义骨名待机/点头/转头及所有权');
}
