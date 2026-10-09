import assert from 'node:assert/strict';
import fs from 'node:fs';
import crypto from 'node:crypto';
import {Parser} from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';
import {AEMEATH_MODEL_HASH,AEMEATH_PATCHED_HASH,applyAemeathChestRig,adaptAemeathChestPhysics} from '../src/assets/pmx_viewer/aemeath_physics.js';

const pkg=JSON.parse(fs.readFileSync('.runtime/characters/aemeath/character.json'));
const bytes=fs.readFileSync(pkg.model.path);
assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),AEMEATH_MODEL_HASH);
const parse=b=>new Parser().parsePmx(b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength),true);
const data=parse(bytes),before=structuredClone(data);
assert.equal(applyAemeathChestRig(data,'unknown'),0);
assert.deepEqual(data,before);
assert.equal(applyAemeathChestRig(data,AEMEATH_MODEL_HASH),10);
const expected=structuredClone(before);
expected.bones[172].parentIndex=171;expected.bones[177].parentIndex=176;
for(let i=171;i<=180;i++)expected.bones[i].flag|=0x1000;
assert.deepEqual(data,expected,'只修改指定胸骨的父链和物理后标记');
const patched=fs.readFileSync('.runtime/aemeath-chest/model/爱弥斯_胸骨改绑_物理后.pmx');
assert.equal(crypto.createHash('sha256').update(patched).digest('hex'),AEMEATH_PATCHED_HASH);
assert.deepEqual(parse(patched),expected,'文件副本与运行时改骨一致');
assert.equal(applyAemeathChestRig(data,AEMEATH_PATCHED_HASH),10);
assert.deepEqual(data,expected,'副本重复加载不会重复改骨');
const mmd={rigidBodies:structuredClone(data.rigidBodies),constraints:structuredClone(data.constraints)};
const original=structuredClone(mmd),mesh={geometry:{userData:{MMD:mmd}},skeleton:{bones:data.bones}};
assert.equal(adaptAemeathChestPhysics(mesh,'unknown'),0);assert.deepEqual(mmd,original);
assert.equal(adaptAemeathChestPhysics(mesh,AEMEATH_MODEL_HASH),6);
for(let i=0;i<mmd.rigidBodies.length;i++){
  if(i>=22&&i<=27)assert.deepEqual(mmd.rigidBodies[i],{...original.rigidBodies[i],type:2});
  else assert.deepEqual(mmd.rigidBodies[i],original.rigidBodies[i]);
}
assert.deepEqual(mmd.constraints.slice(8),original.constraints.slice(8),'衣发和其他关节不改变');
for(const c of mmd.constraints.slice(0,8)){
  assert.deepEqual(c.translationLimitation1,[0,0,0]);assert.deepEqual(c.translationLimitation2,[0,0,0]);
  c.rotationLimitation1.forEach((v,i)=>assert(v===-c.rotationLimitation2[i]));
  assert(c.springRotation.every(v=>v===0||v===8));
}
console.log('PASS: verified hashes, exact bone patch, matching PMX copy, six rotation-only bodies, eight symmetric joints and untouched clothing');
