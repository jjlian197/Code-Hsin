// 输出独立 PMX 副本与贴图，原模型保持不变；胸部补偿仍由播放器提供。
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {AEMEATH_MODEL_HASH,applyAemeathChestRig} from '../src/assets/pmx_viewer/aemeath_physics.js';

const [source,output]=process.argv.slice(2);
if(!output)throw new Error('用法：node tools/patch_aemeath_chest.mjs <原PMX> <新PMX>');
assert(path.resolve(source).toLowerCase()!==path.resolve(output).toLowerCase(),'不能覆盖原模型');
const raw=fs.readFileSync(source),hash=b=>crypto.createHash('sha256').update(b).digest('hex');
assert.equal(hash(raw),AEMEATH_MODEL_HASH,'仅支持已检查的爱弥斯1.05原模型');
let parser=fs.readFileSync(new URL('../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js',import.meta.url),'utf8');
parser=parser.replace('p.parentIndex = dv.getIndex( pmx.metadata.boneIndexSize );','p._parentOffset = dv.offset; p.parentIndex = dv.getIndex( pmx.metadata.boneIndexSize );')
  .replace('p.flag = dv.getUint16();','p._flagOffset = dv.offset; p.flag = dv.getUint16();');
const {Parser}=await import('data:text/javascript;base64,'+Buffer.from(parser).toString('base64'));
const parse=b=>new Parser().parsePmx(b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength),false);
const data=parse(raw),expected=structuredClone(data),patched=Buffer.from(raw),changes=[];
applyAemeathChestRig(expected,AEMEATH_MODEL_HASH);
data.bones.forEach((bone,i)=>{
  const target=expected.bones[i];
  if(bone.parentIndex===target.parentIndex&&bone.flag===target.flag)return;
  patched.writeIntLE(target.parentIndex,bone._parentOffset,data.metadata.boneIndexSize);
  patched.writeUInt16LE(target.flag,bone._flagOffset);
  changes.push({index:i,name:bone.name,parent_before:bone.parentIndex,parent_after:target.parentIndex,flag_before:bone.flag,flag_after:target.flag});
});
assert.deepEqual(parse(patched),expected,'副本只能改变指定亲骨骼与标记');
fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,patched,{flag:'wx'});
for(const texture of data.textures){
  const relative=texture.replaceAll('\\','/'),dest=path.resolve(path.dirname(output),relative);
  assert(dest.toLowerCase().startsWith(path.resolve(path.dirname(output)).toLowerCase()+path.sep),'贴图不能越出输出目录');
  const original=path.resolve(path.dirname(source),relative);
  if(path.resolve(original).toLowerCase()===dest.toLowerCase())continue;
  fs.mkdirSync(path.dirname(dest),{recursive:true});fs.copyFileSync(original,dest);
}
assert.equal(hash(fs.readFileSync(source)),AEMEATH_MODEL_HASH);
const report={source,output,source_sha256:AEMEATH_MODEL_HASH,output_sha256:hash(patched),changes};
fs.writeFileSync(path.join(path.dirname(output),'chest-patch.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify(report));
