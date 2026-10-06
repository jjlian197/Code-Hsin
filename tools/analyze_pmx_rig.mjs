import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {Parser} from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';
import {matchRig} from '../src/assets/pmx_viewer/rig/matcher.js';
import {renderPreview} from './rig/preview.mjs';

export function analyzePmx(file, overrides = null) {
  const raw = fs.readFileSync(file);
  if (raw.subarray(0,4).toString('ascii') !== 'PMX ') throw new Error('输入不是 PMX 文件');
  const data = new Parser().parsePmx(raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength), true);
  return matchRig(data, {file:path.basename(file), name:data.metadata.modelName,
    sha256:crypto.createHash('sha256').update(raw).digest('hex'), boneCount:data.bones.length}, overrides);
}

function main(args) {
  if (args.includes('--help') || !args.length) {
    console.log('用法：node tools/analyze_pmx_rig.mjs <model.pmx> [--out <目录>] [--overrides <json>] [--force]\n输出 rig_map.json、report.json、preview.html；默认写入 .runtime/rig-import/<模型哈希前12位>。');
    return;
  }
  const file = path.resolve(args.shift());
  let out, overridePath, force = false;
  while (args.length) {
    const flag = args.shift();
    if (flag === '--force') force = true;
    else if (['--out','--overrides'].includes(flag) && args[0] && !args[0].startsWith('--')) {
      const value = path.resolve(args.shift());
      if (flag === '--out') out = value; else overridePath = value;
    } else throw new Error(`未知参数或缺少参数值：${flag}`);
  }
  const overrides = overridePath ? JSON.parse(fs.readFileSync(overridePath,'utf8')) : null;
  const report = analyzePmx(file, overrides);
  out ??= path.resolve('.runtime/rig-import', report.model.sha256.slice(0,12));
  const {skeleton, ...map} = report;
  const outputs = {'rig_map.json':JSON.stringify(map,null,2)+'\n',
    'report.json':JSON.stringify(report,null,2)+'\n', 'preview.html':renderPreview(report)};
  for (const name of Object.keys(outputs)) {
    const target = path.join(out,name);
    if ([file,overridePath].filter(Boolean).some(p=>p.toLowerCase()===target.toLowerCase())) throw new Error('输出不能覆盖输入文件');
    if (!force && fs.existsSync(target)) throw new Error(`输出已存在：${target}；确认重建时使用 --force`);
  }
  fs.mkdirSync(out,{recursive:true});
  for (const [name, text] of Object.entries(outputs)) fs.writeFileSync(path.join(out,name),text,'utf8');
  console.log(JSON.stringify({model:report.model, out, summary:report.summary, issues:report.issues},null,2));
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {main(process.argv.slice(2));} catch (error) {console.error(`骨架分析失败：${error.message}`); process.exitCode = 1;}
}
