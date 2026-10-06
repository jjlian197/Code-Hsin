import assert from 'node:assert/strict';
import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
import crypto from 'node:crypto';
import * as THREE from 'three';
import {MMDParser} from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';
import {applyHsinChestRig,hsinForm,runningClip} from '../src/assets/pmx_viewer/hsin_motion.js';

const paths=JSON.parse(execFileSync('python',['-c','import json; from src.core.app_config import load_config,project_path; print(json.dumps([str(project_path(p)) for p in load_config()["sprite"]["model"]["forms"].values()]))'],{encoding:'utf8'}));
for(const path of paths){
  const bytes=fs.readFileSync(path),hash=crypto.createHash('sha256').update(bytes).digest('hex');
  const data=new MMDParser.Parser().parsePmx(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),true);
  const before=structuredClone(data);
  assert.equal(applyHsinChestRig(data,'unverified'),0);
  assert.deepEqual(data,before);
  assert.equal(applyHsinChestRig(data,hash),10);
  const indices=[];
  data.bones.forEach((b,i)=>{
    if(/^ZSpring_Spine_/.test(b.name)){
      indices.push(i);assert.equal(b.flag,before.bones[i].flag|0x1000);
      assert.equal(data.bones[b.parentIndex].name,b.name.endsWith('_L')?'左胸':'右胸');
      before.bones[i].parentIndex=b.parentIndex;before.bones[i].flag=b.flag;
    }
  });
  assert.deepEqual(data,before,'只有十根辅助骨的亲骨骼和物理后标记改变');
  assert.deepEqual(indices,hsinForm(hash)==='first'?[181,182,183,184,185,186,187,188,189,190]:[175,176,177,178,179,180,181,182,183,184]);
  const mesh=new THREE.SkinnedMesh();mesh.bind(new THREE.Skeleton(data.bones.map(b=>{const bone=new THREE.Bone();bone.name=b.name;return bone;})));
  const source=JSON.parse(fs.readFileSync(new URL(`../src/assets/motions/running-${hsinForm(hash)}.json`,import.meta.url)));
  const clip=runningClip(source,mesh);
  assert.equal(clip.duration,source.duration*2);
  assert.equal(clip.tracks.length,21);
  clip.tracks.forEach((track,i)=>{
    assert.deepEqual([...track.values],source.tracks[i].values.map(Math.fround));
    assert.deepEqual([...track.times],source.tracks[i].times.map(t=>Math.fround(t*2)));
    assert([...track.values].every(Number.isFinite));
  });
}
console.log('PASS: both forms, guarded default chest rig, exact auxiliary indices and half-speed keyframes');
