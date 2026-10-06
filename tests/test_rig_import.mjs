import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import vm from 'node:vm';
import {spawnSync} from 'node:child_process';
import {RIG_SCHEMA, normalizeName} from '../src/assets/pmx_viewer/rig/schema.js';
import {matchRig} from '../src/assets/pmx_viewer/rig/matcher.js';
import {renderPreview} from '../tools/rig/preview.mjs';
import {analyzePmx} from '../tools/analyze_pmx_rig.mjs';

const model = {name:'fixture', sha256:'fixture-hash'};
const b = (name, parentIndex, position, extra = {}) => ({name, parentIndex, position, ...extra});
const fixture = () => ({bones:[
  b('全ての親',-1,[0,0,0]), b('センター',0,[0,8,0]), b('下半身',1,[0,8,0]),
  b('上半身',1,[0,9,0]), b('首',3,[0,14,0]), b('頭',4,[0,15,0]),
  b('左腕',3,[2,13,0]), b('左腕捩',6,[3,13,0]), b('左ひじ',7,[4,13,0]), b('左手首',8,[6,13,0]),
  b('右腕',3,[-2,13,0]), b('右ひじ',10,[-4,13,0]), b('右手首',11,[-6,13,0]),
  b('左足',2,[1,8,0]), b('左ひざ',13,[1,4,0]), b('左足首',14,[1,1,0]),
  b('右足',2,[-1,8,0]), b('右ひざ',16,[-1,4,0]), b('右足首',17,[-1,1,0]),
]});
let checks = 0;
function check(name, run) {run();checks++;console.log('PASS '+name);}

check('控制根、中心与骨盆分别映射，辅助扭转骨不冒充关节', () => {
  const source = fixture(), before = JSON.stringify(source), r = matchRig(source,model);
  assert.equal(r.bones.root.index,0);assert.equal(r.bones.center.index,1);assert.equal(r.bones.hips.index,2);
  assert.equal(r.bones.left_lower_arm.index,8);assert.deepEqual(r.summary.requiredUnresolved,[]);
  assert.equal(new Set(Object.values(r.bones).flatMap(m=>m.index===undefined?[]:[m.index])).size,r.summary.matched);
  assert.equal(JSON.stringify(source),before);assert.equal(r.bones.chest.status,'missing');
});
check('NFKC、多语言与英文别名', () => {
  assert.equal(normalizeName('右足ＩＫ'),normalizeName('右足IK'));
  const f=fixture();f.bones[6].name='Arm_L';f.bones[8].name='左前臂';f.bones[5].name='custom';f.bones[5].englishName='mixamorig:Head';
  const r=matchRig(f,model);assert.equal(r.bones.left_upper_arm.index,6);assert.equal(r.bones.left_lower_arm.index,8);assert.equal(r.bones.head.index,5);
});
check('左右错位留待确认，整体平移不改变左右判断', () => {
  const f=fixture();for(const bone of f.bones)bone.position[0]+=20;
  assert.equal(matchRig(f,model).bones.left_hand.status,'matched');
  f.bones[6].position[0]=18;const m=matchRig(f,model).bones.left_upper_arm;
  assert.equal(m.status,'review');assert(m.candidates[0].warnings.includes('side_conflict'));
});
check('重复名称、断裂层级与 IK 角色冲突不自动接受', () => {
  const f=fixture();f.bones.push(b('左腕',3,[2,13,0]));assert.equal(matchRig(f,model).bones.left_upper_arm.status,'review');
  const g=fixture();g.bones[8].parentIndex=3;assert.equal(matchRig(g,model).bones.left_lower_arm.status,'review');
  const h=fixture();h.bones[6].ik={effector:8};assert.equal(matchRig(h,model).bones.left_upper_arm.status,'review');
});
check('未知名称的拓扑候选不能作为自动匹配结果', () => {
  const f=fixture();f.bones[5].name='custom_head';const r=matchRig(f,model);
  assert.equal(r.bones.head.status,'review');assert.equal(r.bones.head.candidates[0].index,5);
  assert(r.summary.requiredUnresolved.includes('head'));
});
check('父索引无效和骨架环明确失败', () => {
  const f=fixture();f.bones[4].parentIndex=999;assert.throws(()=>matchRig(f,model),/父索引/);
  const g=fixture();g.bones[4].parentIndex=5;assert.throws(()=>matchRig(g,model),/存在环/);
});
check('人工映射绑定哈希，保留禁用项，拒绝重复索引', () => {
  assert.throws(()=>matchRig(fixture(),model,{modelSha256:'other',bones:{}}),/哈希/);
  assert.throws(()=>matchRig(fixture(),model,{modelSha256:model.sha256,bones:{head:5,neck:5}}),/重复/);
  const r=matchRig(fixture(),model,{modelSha256:model.sha256,bones:{head:5,chest:null}});
  assert.equal(r.bones.head.status,'manual');assert.equal(r.bones.chest.status,'disabled');
  assert.throws(()=>matchRig(fixture(),model,{modelSha256:model.sha256,bones:{head:999}}),/索引/);
  assert.throws(()=>matchRig(fixture(),model,{modelSha256:model.sha256,bones:{unknown:5}}),/未知/);
});
check('人工预留优先，错误人工左右映射仍报告冲突', () => {
  const r=matchRig(fixture(),model,{modelSha256:model.sha256,bones:{right_upper_arm:6}});
  assert.equal(r.bones.right_upper_arm.status,'manual');assert.equal(r.bones.left_upper_arm.status,'review');
  assert(r.issues.some(i=>i.type==='side_conflict'));
});
check('HTML 中模型名称不能注入脚本，预览脚本语法有效', () => {
  const r=matchRig(fixture(),{...model,name:'</script><script>alert(1)</script>'});
  const html=renderPreview(r);assert(!html.includes('<script>alert(1)'));
  const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];new vm.Script(script);
  const embedded=JSON.parse(html.match(/id="data">([\s\S]*?)<\/script>/)[1]);assert.equal(embedded.model.name,r.model.name);
});

// 本机样本验收可选：不将私有 PMX 加入仓库，也不要求测试机具有角色资源。
if (process.argv[2]) {
  const samples=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
  for(const sample of samples) check('真实 PMX '+path.basename(sample.path), () => {
    const hash=()=>crypto.createHash('sha256').update(fs.readFileSync(sample.path)).digest('hex');
    const before=hash(),r=analyzePmx(sample.path);
    assert.equal(r.model.sha256,before);assert.equal(hash(),before);
    assert.deepEqual(r.summary.requiredUnresolved,[]);assert.deepEqual(r.issues,[]);
    const indices=Object.values(r.bones).flatMap(m=>m.index===undefined?[]:[m.index]);
    assert.equal(indices.length,new Set(indices).size);
    for(const s of RIG_SCHEMA.filter(s=>s.required))assert.equal(r.bones[s.id].status,'matched');
    assert.notEqual(r.bones.hips.index,r.bones.center.index);
    for(const side of ['left','right'])for(const part of ['upper_arm','lower_arm','hand','upper_leg','lower_leg','foot'])
      assert(!/捩|調整|IK|足D|EX/i.test(r.bones[side+'_'+part].name));
  });
  check('命令行生成、覆盖保护与非 PMX 错误', () => {
    const dir=fs.mkdtempSync(path.join(os.tmpdir(),'hsin-rig-'));
    try {
      const args=['tools/analyze_pmx_rig.mjs',samples[0].path,'--out',dir];
      const run=extra=>spawnSync(process.execPath,[...args,...extra],{encoding:'utf8'});
      assert.equal(run([]).status,0);assert.equal(run([]).status,1);assert.equal(run(['--force']).status,0);
      assert(fs.existsSync(path.join(dir,'preview.html')));
      const fake=path.join(dir,'fake.pmx');fs.writeFileSync(fake,'not PMX');
      const bad=spawnSync(process.execPath,['tools/analyze_pmx_rig.mjs',fake],{encoding:'utf8'});
      assert.equal(bad.status,1);assert.match(bad.stderr,/不是 PMX/);
    } finally {
      assert.equal(path.dirname(path.resolve(dir)),path.resolve(os.tmpdir()));
      assert(path.basename(dir).startsWith('hsin-rig-'));
      fs.rmSync(dir,{recursive:true,force:true});
    }
  });
}
console.log('骨架整合器检查通过：'+checks+' 项');
