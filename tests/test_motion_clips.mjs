import assert from 'node:assert/strict';
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';
import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';
import { MMDParser } from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';
import { gestureGeometry } from '../src/assets/pmx_viewer/calibrated_gestures.js';

// 浏览器使用 import map；Node 检查以同一份本地 Three.js 解析该导入。
const threeUrl = new URL('../src/assets/pmx_viewer/lib/three/three.module.js', import.meta.url);
const source = fs.readFileSync(new URL('../src/assets/pmx_viewer/motions.js', import.meta.url), 'utf8')
  .replace("from 'three'", `from ${JSON.stringify(threeUrl.href)}`)
  .replace("from './calibrated_gestures.js'", `from ${JSON.stringify(new URL('../src/assets/pmx_viewer/calibrated_gestures.js', import.meta.url).href)}`);
const { createBuiltinClips, palmNormal } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const paths = JSON.parse(execFileSync('python', ['-c', 'import json; from src.core.app_config import load_config,project_path; print(json.dumps([str(project_path(p)) for p in load_config()["sprite"]["model"]["forms"].values()]))'], {encoding:'utf8'}));
for (const path of paths) {
const bytes = fs.readFileSync(path);
const data = new MMDParser.Parser().parsePmx(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), true);
const mesh = new THREE.SkinnedMesh();
const bones = data.bones.map(b => { const bone = new THREE.Bone(); bone.name=b.name;
  bone.position.fromArray(b.position); if(b.parentIndex>=0)bone.position.sub(new THREE.Vector3().fromArray(data.bones[b.parentIndex].position)); return bone; });
bones.forEach((bone,i) => (data.bones[i].parentIndex>=0 ? bones[data.bones[i].parentIndex] : mesh).add(bone));
mesh.bind(new THREE.Skeleton(bones)); mesh.updateMatrixWorld(true);
const clips = createBuiltinClips(mesh);
for (const clip of Object.values(clips)) {
  assert(clip.validate(), `${clip.name} keyframes`);
  for (const track of clip.tracks) assert.equal(track.values.length, track.times.length * 4);
}
const mixer = new THREE.AnimationMixer(mesh);
mixer.clipAction(clips.idle).play();
mixer.update(0.03);
const right = bones.find(b=>b.name==='右腕'), left = bones.find(b=>b.name==='左腕');
for (const [name, boneName, axis] of [['wave','右腕','z'],['nod','頭','x']]) {
  const bone = bones.find(b=>b.name===boneName);
  const before = bone.rotation[axis];
  const action = mixer.clipAction(clips[name]).reset().setLoop(THREE.LoopOnce,1).play();
  mixer.update(0.45);
  assert(action.time > 0);
  assert(Math.abs(bone.rotation[axis] - before) > 0.05, `${name} changes bone`);
  for (let i=0;i<110;i++) {
    mixer.update(1/30); mesh.updateMatrixWorld(true);
    assert(Math.abs(left.rotation.z + 0.67) < 0.02, `${name} keeps opposite arm relaxed`);
    if(name==='nod')assert(Math.abs(right.rotation.z - 0.67)<0.02,'nod never resets arms');
    if(name==='wave' && action.time>=0.8 && action.time<=2.2)assert(palmNormal(mesh).z>0.96,'palm faces camera');
  }
  assert.equal(action.enabled, false, `${name} finishes`);
  assert(bones.every(b => b.quaternion.toArray().every(Number.isFinite)));
  action.stop();
  mixer.update(0);
  assert(Math.abs(right.rotation.z-0.67)<0.02,'completion returns directly to relaxed idle');
}
for(const name of ['peace','finger_heart','crossed_arms']) {
  const action=mixer.clipAction(clips[name]).reset().setLoop(THREE.LoopOnce,1).play();
  for(const track of clips[name].tracks) {
    assert(new THREE.Quaternion().fromArray(track.values,0).angleTo(new THREE.Quaternion())<1e-5);
    assert(new THREE.Quaternion().fromArray(track.values,track.values.length-4).angleTo(new THREE.Quaternion())<1e-5);
  }
  mixer.update(2);mesh.updateMatrixWorld(true);
  if(name==='peace')assert(palmNormal(mesh).z>0.95,`${name} palm faces camera`);
  if(name==='peace')assert(bones.find(b=>b.name==='右薬指２').quaternion.angleTo(new THREE.Quaternion())>0.8,'V 手势收起无名指');
  if(name==='finger_heart') {
    const geometry=gestureGeometry(mesh);
    assert(geometry.indexGap<.08,'双手食指上沿接合');
    assert(geometry.palmDistance>clips[name].userData.originalPalmDistance+.5,'按指长扩大掌距');
    for(const lower of geometry.lower){
      assert(Math.abs(lower.corner-90)<.03,'实际手指投影形成直角下沿');
      assert(lower.bends.flat().every(angle=>angle<.03),'后三指共线，无过度折指');
    }
    for(const side of ['左','右']) {
      const sign=side==='左'?1:-1;
      for(const finger of ['中','薬','小']){
        const start=geometry.points[side+finger+'指１'],tip=geometry.points[side+finger+'指先'];
        assert(tip[1]<start[1]&&sign*(tip[0]-start[0])<0,'指向内下方');
        assert(sign*tip[0]>0,'后三指不会越过中央接触面');
      }
    }
  }
  if(name==='crossed_arms') {
    const r=bones.find(b=>b.name==='右手首').getWorldPosition(new THREE.Vector3());
    const l=bones.find(b=>b.name==='左手首').getWorldPosition(new THREE.Vector3());
    const re=bones.find(b=>b.name==='右ひじ').getWorldPosition(new THREE.Vector3());
    const le=bones.find(b=>b.name==='左ひじ').getWorldPosition(new THREE.Vector3());
    assert(r.x>1&&l.x< -1&&r.z>2&&l.z>2,'交叉手臂在胸前且跨过身体中心');
    assert(r.y>re.y&&l.y>le.y,'X 手势前臂向上，不是抱臂');
    assert(palmNormal(mesh,'左').z>.98&&palmNormal(mesh,'右').z>.98,'两掌朝向镜头');
    assert(Math.abs(r.z-l.z)>.7,'两条前臂留出深度间隔');
  }
  for(let i=0;i<160;i++)mixer.update(1/30);
  action.stop();mixer.update(0);
  assert(Math.abs(right.rotation.z-0.67)<0.02&&Math.abs(left.rotation.z+0.67)<0.02);
  assert(bones.filter(b=>/指[１２３]$/.test(b.name)).every(b=>b.quaternion.angleTo(new THREE.Quaternion())<1e-5),'手势结束清除弯指');
}
}
console.log('PASS: both PMX forms, stable idle arms, camera-facing wave, completion and finite poses');
