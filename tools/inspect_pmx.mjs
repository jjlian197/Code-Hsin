import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { MMDParser } from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';

const root = path.resolve(import.meta.dirname, '..');
const modelConfig=JSON.parse(execFileSync('python',['-c',
  'import json; from src.core.app_config import load_config; print(json.dumps(load_config()["sprite"]["model"]))'],
  {cwd:root,encoding:'utf8'}));
const find = dir => fs.readdirSync(dir, {withFileTypes:true}).flatMap(e =>
  e.isDirectory() && !e.name.startsWith('.') ? find(path.join(dir,e.name)) :
    e.name.endsWith('.pmx') ? [path.join(dir,e.name)] : []);
for (const file of find(root)) {
  const raw = fs.readFileSync(file);
  const data = new MMDParser.Parser().parsePmx(raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength),true);
  const mins=[Infinity,Infinity,Infinity], maxs=[-Infinity,-Infinity,-Infinity];
  for(const v of data.vertices) v.position.forEach((x,i)=>{mins[i]=Math.min(mins[i],x);maxs[i]=Math.max(maxs[i],x);});
  const form=Object.entries(modelConfig.forms).find(([,p])=>path.resolve(root,p)===file)?.[0];
  const overrides=modelConfig.texture_overrides?.[form]||{};
  const missing=data.textures.filter(t=>{
    const normalized=t.replaceAll('\\','/');
    return !fs.existsSync(overrides[normalized]?path.resolve(root,overrides[normalized]):path.resolve(path.dirname(file),normalized));
  });
  console.log(JSON.stringify({file:path.relative(root,file),metadata:data.metadata,bounds:[mins,maxs],missing,
    materials:data.materials.map(m=>({name:m.name,diffuse:m.diffuse,texture:data.textures[m.textureIndex],flag:m.flag})),
    bones:data.bones.map(b=>({name:b.name,pos:b.position})).filter(b=>/腕|肩|ひじ|頭|首|arm|head/i.test(b.name)),
    morphs:data.morphs.map(m=>({name:m.name,type:m.type}))},null,2));
  if(missing.length) process.exitCode=1;
}
