import {RIG_SCHEMA, SCHEMA_VERSION, normalizeName} from './schema.js';

const distance = (a, b) => Math.hypot(...a.map((v, i) => v - b[i]));
export function isDescendant(bones, child, ancestor) {
  const seen = new Set();
  for (let i = bones[child]?.parentIndex; i >= 0 && i < bones.length && !seen.has(i); i = bones[i].parentIndex) {
    if (i === ancestor) return true;
    seen.add(i);
  }
  return false;
}

export function classifyBone(bone, physical = false) {
  if (bone.ik) return 'ik';
  if (/捩|twist|調整|adjust|IK親|lim|肩[PC]$|足[dD]$|EX$/i.test(bone.name)
    || (/先$/.test(bone.name) && !/つま先$/.test(bone.name))) return 'helper';
  if (/髪|hair|裙|skirt|袖|sleeve|cloth|dress/i.test(bone.name)) return 'cloth';
  if (physical) return 'physics';
  return 'unclassified';
}

export function matchRig(data, model, overrides = null) {
  const bones = data.bones;
  if (!Array.isArray(bones) || !bones.length) throw new Error('PMX 没有骨骼');
  if (overrides && overrides.modelSha256 !== model.sha256) throw new Error('人工映射的模型哈希不匹配');
  if (overrides && (!overrides.bones || typeof overrides.bones !== 'object' || Array.isArray(overrides.bones))) throw new Error('人工映射必须提供 bones 对象');
  const reserved = new Map();
  for (const id of Object.keys(overrides?.bones ?? {})) {
    if (!RIG_SCHEMA.some(s => s.id === id)) throw new Error(`未知语义骨：${id}`);
    const index = overrides.bones[id];
    if (index === null) continue;
    if (!Number.isInteger(index) || !bones[index]) throw new Error(`人工映射 ${id} 骨骼索引无效`);
    if (reserved.has(index)) throw new Error(`人工映射重复使用骨骼 ${index}`);
    reserved.set(index,id);
  }
  const physical = new Set((data.rigidBodies ?? []).map(b => b.boneIndex));
  const issues = [];
  const snapshot = bones.map((b, index) => {
    if (!Array.isArray(b.position) || b.position.length !== 3 || b.position.some(v => !Number.isFinite(v))) {
      throw new Error(`骨骼 ${index} 坐标无效`);
    }
    if (!Number.isInteger(b.parentIndex) || b.parentIndex < -1 || b.parentIndex >= bones.length || b.parentIndex === index) throw new Error(`骨骼 ${index} 父索引无效`);
    return {index, name:b.name, englishName:b.englishName ?? '', parentIndex:b.parentIndex,
      position:b.position, category:classifyBone(b, physical.has(index)),
      ik:b.ik ?? null, grant:b.grant ?? null, fixedAxis:b.fixAxis ?? null,
      localAxes:b.localXVector ? {x:b.localXVector, z:b.localZVector} : null};
  });
  for (let index = 0; index < bones.length; index++) {
    const seen = new Set();
    for (let parent = index; parent >= 0; parent = bones[parent].parentIndex) {
      if (seen.has(parent)) throw new Error(`骨骼 ${index} 父子关系存在环`);
      seen.add(parent);
    }
  }
  // 同一模型的相对位置判断左右，避免将整体平移误判为左右颠倒。
  const centerNames = new Set(['センター','hips','pelvis','下半身'].map(normalizeName));
  const origin = bones.find(b => centerNames.has(normalizeName(b.name)))?.position ?? [0,0,0];
  const height = Math.max(...bones.map(b => b.position[1])) - Math.min(...bones.map(b => b.position[1]));
  const tolerance = Math.max(height * .005, 1e-5);
  const matches = {};
  const used = new Map();
  const candidatesFor = semantic => {
    const aliases = new Set(semantic.aliases.map(normalizeName));
    const parent = matches[semantic.parent]?.index;
    const candidates = [];
    bones.forEach((b, index) => {
      const reasons = [];
      const warnings = [];
      let score = 0;
      if (aliases.has(normalizeName(b.name))) {score = .98; reasons.push('name');}
      else if (b.englishName && aliases.has(normalizeName(b.englishName))) {score = .96; reasons.push('english_name');}
      const category = snapshot[index].category;
      if (!score && semantic.required && parent !== undefined && semantic.group === 'body' && isDescendant(bones, index, parent)
        && !['helper','ik','cloth','physics'].includes(category) && distance(b.position, bones[parent].position) > tolerance) {
        // 只建议最近的未知人体骨；已知其他语义、深层手指/衣物不能冒充缺失关节。
        const knownOther = RIG_SCHEMA.some(s => s.id !== semantic.id && s.aliases.some(a => normalizeName(a) === normalizeName(b.name)));
        let p = b.parentIndex;
        while (p >= 0 && p !== parent && snapshot[p].category === 'helper') p = bones[p].parentIndex;
        if (!knownOther && p === parent) {score = .55; reasons.push('topology');}
      }
      if (!score) return;
      if (semantic.side && semantic.group !== 'ik') {
        const x = b.position[0] - origin[0];
        if (Math.abs(x) <= tolerance) {
          if (semantic.id.endsWith('_shoulder') && reasons.includes('name')) reasons.push('shoulder_at_midline');
          else warnings.push('side_uncertain');
        }
        else if ((semantic.side === 'left' ? x > 0 : x < 0)) reasons.push('side');
        else warnings.push('side_conflict');
      }
      if (parent !== undefined) {
        if (isDescendant(bones, index, parent)) reasons.push('parent_chain');
        else warnings.push('parent_conflict');
      }
      if (category === 'helper') warnings.push('helper_bone');
      if ((semantic.group === 'ik') !== Boolean(b.ik)) warnings.push('ik_role_conflict');
      if (used.has(index)) warnings.push('already_assigned');
      if (reserved.has(index) && reserved.get(index) !== semantic.id) warnings.push('reserved_manual');
      if (warnings.length) score = Math.min(score, .69);
      candidates.push({index, name:b.name, score, reasons, warnings});
    });
    return candidates.sort((a,b) => b.score - a.score || a.index - b.index).slice(0, 5);
  };
  for (const semantic of RIG_SCHEMA) {
    const candidates = candidatesFor(semantic);
    const override = overrides?.bones?.[semantic.id];
    const top = candidates[0];
    const ambiguous = top && candidates[1] && top.score - candidates[1].score < .08;
    let status = top ? 'review' : 'missing';
    let selected = null;
    if (override === null) status = 'disabled';
    else if (override !== undefined) {
      if (!Number.isInteger(override) || !bones[override]) throw new Error(`人工映射 ${semantic.id} 骨骼索引无效`);
      if (used.has(override)) throw new Error(`人工映射重复使用骨骼 ${override}：${semantic.id}/${used.get(override)}`);
      selected = {index:override, name:bones[override].name, score:1, reasons:['manual'], warnings:[]};
      status = 'manual';
    } else if (top && top.score >= .9 && !ambiguous && !top.warnings.length) {
      selected = top; status = 'matched';
    }
    matches[semantic.id] = {required:semantic.required, group:semantic.group, status,
      ...(selected ?? {}), candidates, ...(ambiguous ? {note:'ambiguous_candidates'} : {})};
    if (selected) used.set(selected.index, semantic.id);
  }
  // 人工指定保留用户选择，但仍报告左右、层级和 IK 问题。
  for (const semantic of RIG_SCHEMA) {
    const m = matches[semantic.id];
    if (m.index === undefined) continue;
    const parent = matches[semantic.parent]?.index;
    if (parent !== undefined && !isDescendant(bones, m.index, parent)) issues.push({type:'parent_conflict', semantic:semantic.id});
    if (semantic.side && semantic.group !== 'ik') {
      const x = bones[m.index].position[0] - origin[0];
      if (Math.abs(x) > tolerance && (semantic.side === 'left' ? x < 0 : x > 0)) issues.push({type:'side_conflict', semantic:semantic.id});
    }
    if ((semantic.group === 'ik') !== Boolean(bones[m.index].ik)) issues.push({type:'ik_role_conflict', semantic:semantic.id});
    if (snapshot[m.index].category === 'helper') issues.push({type:'helper_bone', semantic:semantic.id});
  }
  const summary = Object.fromEntries(['matched','manual','review','missing','disabled'].map(status =>
    [status, Object.values(matches).filter(m => m.status === status).length]));
  summary.requiredUnresolved = RIG_SCHEMA.filter(s => s.required && matches[s.id].index === undefined).map(s => s.id);
  const capabilities = Object.fromEntries([
    ['head_tracking',['neck','head']],
    ['basic_arms',['left_upper_arm','left_lower_arm','left_hand','right_upper_arm','right_lower_arm','right_hand']],
    ['leg_mapping',['hips','left_upper_leg','left_lower_leg','left_foot','right_upper_leg','right_lower_leg','right_foot']],
  ].map(([id, required]) => [id, {mapped:required.every(s => matches[s].index !== undefined), runtimeValidated:false}]));
  return {schema:'hsin.standard-rig', schemaVersion:SCHEMA_VERSION, model, coordinateSystem:'right-handed, Y-up, anatomical-left=+X',
    scoreMeaning:'规则可信度，不是统计概率；拓扑/空间推断只供人工确认', summary, issues, capabilities, bones:matches, skeleton:snapshot};
}
