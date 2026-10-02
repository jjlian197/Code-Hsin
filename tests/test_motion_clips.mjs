import assert from 'node:assert/strict';
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';
import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';
import { MMDParser } from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';

// 浏览器使用 import map；Node 检查以同一份本地 Three.js 解析该导入。
const threeUrl = new URL('../src/assets/pmx_viewer/lib/three/three.module.js', import.meta.url);
const source = fs.readFileSync(new URL('../src/assets/pmx_viewer/motions.js', import.meta.url), 'utf8')
  .replace("from 'three'", `from ${JSON.stringify(threeUrl.href)}`);
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
}
console.log('PASS: both PMX forms, stable idle arms, camera-facing wave, completion and finite poses');
