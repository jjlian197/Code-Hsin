import {RIG_SCHEMA, SCHEMA_VERSION, normalizeName} from './schema.js';

// 保留真实 Bone 名称与索引；动画轨道引用真实索引，避免重命名破坏 IK/Grant。
export function createRigAccess(mesh, report, modelHash) {
  if (report.schema !== 'hsin.standard-rig' || report.schemaVersion !== SCHEMA_VERSION) throw new Error('骨架映射格式或版本不支持');
  if (!modelHash || report.model?.sha256 !== modelHash) throw new Error('骨架映射与当前 PMX 哈希不匹配');
  if (report.model.boneCount !== mesh.skeleton.bones.length) throw new Error('骨架映射骨骼数量不匹配');
  const selected = new Map(), used = new Set();
  for (const semantic of RIG_SCHEMA) {
    const m = report.bones?.[semantic.id];
    if (!m || !['matched','manual'].includes(m.status)) continue;
    const index = m.index, bone = mesh.skeleton.bones[index];
    if (!Number.isInteger(index) || !bone || bone.name !== m.name || used.has(index)) throw new Error(`骨架映射索引/名称无效：${semantic.id}`);
    if (report.issues?.some(i=>i.semantic===semantic.id)) throw new Error(`骨架映射存在未解决冲突：${semantic.id}`);
    used.add(index);selected.set(semantic.id,{index,bone});
  }
  return {
    report,
    get:id=>selected.get(id)?.bone,
    index:id=>selected.get(id)?.index,
    track:id=>selected.has(id)?`.bones[${selected.get(id).index}].quaternion`:null,
    // MMD 的上半身1/2编号可能倒序；近景基准取颈部链上最近的已映射躯干。
    upperTorso:()=>{
      const torso=new Set(['spine','spine_mid','chest','upper_chest'].map(id=>selected.get(id)?.bone).filter(Boolean));
      for(let bone=selected.get('neck')?.bone.parent;bone;bone=bone.parent)if(torso.has(bone))return bone;
      return selected.get('chest')?.bone||selected.get('spine')?.bone;
    },
    // 复杂手势仍只沿用完整的原骨名路径，不能据此宣布通用重定向。
    usesOriginalNames:RIG_SCHEMA.every(s=>{
      const original=mesh.skeleton.bones.some(b=>normalizeName(b.name)===normalizeName(s.aliases[0]));
      const chosen=selected.get(s.id);
      return chosen ? normalizeName(chosen.bone.name)===normalizeName(s.aliases[0]) : !original;
    }),
  };
}
