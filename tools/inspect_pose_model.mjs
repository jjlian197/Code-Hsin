import fs from 'node:fs';
import { Parser } from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';
const dir=fs.readdirSync('.').find(n=>n.startsWith('鸣潮_'));
const bytes=fs.readFileSync(`${dir}/心_一阶段/心.pmx`);
const data=new Parser().parsePmx(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),true);
fs.writeFileSync('.runtime/pose-model-inspection.json',JSON.stringify({bones:data.bones,rigidBodies:data.rigidBodies,materials:data.materials.map(m=>({name:m.name,faceCount:m.faceCount}))},null,2));
console.log(JSON.stringify({bones:data.bones.map((b,i)=>({i,name:b.name,parent:data.bones[b.parentIndex]?.name,position:b.position,grant:b.grant,ik:b.ik}))
  .filter(b=>/^(全て|センター|グルーブ|腰|下半身|上半身|頭|首|[左右](肩|腕|ひじ|手首|足|ひざ|足首|つま先))/.test(b.name)),
  cloth:data.bones.filter(b=>/skirt|袖|dress|Hair|髪|Cloth/i.test(b.name)).slice(0,35).map(b=>({name:b.name,position:b.position,parent:data.bones[b.parentIndex]?.name})),
  materials:data.materials.map(m=>({name:m.name,faces:m.faceCount}))},null,2));
