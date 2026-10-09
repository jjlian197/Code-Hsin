import fs from 'node:fs';
import path from 'node:path';
import {Parser} from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';
import {analyzePmx} from './analyze_pmx_rig.mjs';
import {renderPreview} from './rig/preview.mjs';
import {validateMorphMap} from '../src/assets/pmx_viewer/rig/morphs.js';
import {isAemeathChestModel} from '../src/assets/pmx_viewer/aemeath_physics.js';

// 生成引用式本地角色包，不复制私有模型或修改源文件。
const args=process.argv.slice(2),file=args.shift();
try {
  if(!file)throw new Error('用法：node --loader ./tools/node_three_loader.mjs tools/build_character_package.mjs <PMX> --out <目录> --morphs <JSON> --name <名字> [--force]');
  const options={};
  while(args.length){const key=args.shift();if(key==='--force')options.force=true;
    else if(['--out','--morphs','--name','--overrides'].includes(key)&&args.length)options[key.slice(2)]=args.shift();else throw new Error('未知参数：'+key);}
  if(!options.out||!options.morphs||!options.name)throw new Error('需要 --out、--morphs 和 --name');
  const source=path.resolve(file),out=path.resolve(options.out),raw=fs.readFileSync(source);
  const report=analyzePmx(source,options.overrides?JSON.parse(fs.readFileSync(options.overrides,'utf8')):null);
  if(report.summary.requiredUnresolved.length||report.issues.length)throw new Error('请先校正缺失/冲突骨架');
  const data=new Parser().parsePmx(raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength),true);
  const morphs=validateMorphMap(JSON.parse(fs.readFileSync(options.morphs,'utf8')),data.morphs.filter(m=>m.type===1).map(m=>m.name));
  const textures=data.textures.map(texture=>{const target=path.resolve(path.dirname(source),texture.replaceAll('\\','/'));
    if(!fs.existsSync(target))throw new Error('贴图缺失：'+texture);return {source:texture,path:target};});
  const manifest={format:'hsin.character',version:1,name:options.name,
    model:{path:source,sha256:report.model.sha256,textures},rig:'rig_map.json',morphs:'morph_map.json',
    capabilities:{motions:isAemeathChestModel(report.model.sha256)?['idle','nod','wave','peace','finger_heart','crossed_arms','treadmill_running']:['idle','nod'],physics:data.rigidBodies.length>0}};
  const {skeleton,...rig}=report;
  const outputs={'character.json':manifest,'rig_map.json':rig,'morph_map.json':morphs,'report.json':report};
  for(const name of [...Object.keys(outputs),'preview.html']) {
    const dest=path.join(out,name);
    if([source,options.morphs,options.overrides].filter(Boolean).some(p=>path.resolve(p).toLowerCase()===dest.toLowerCase()))throw new Error('输出不能覆盖输入');
    if(!options.force&&fs.existsSync(dest))throw new Error('输出已存在，重建需要 --force');
  }
  fs.mkdirSync(out,{recursive:true});
  for(const [name,value] of Object.entries(outputs))fs.writeFileSync(path.join(out,name),JSON.stringify(value,null,2)+'\n');
  fs.writeFileSync(path.join(out,'preview.html'),renderPreview(report));
  console.log(JSON.stringify({package:path.join(out,'character.json'),name:manifest.name,capabilities:manifest.capabilities}));
}catch(error){console.error(error.message);process.exitCode=1;}
