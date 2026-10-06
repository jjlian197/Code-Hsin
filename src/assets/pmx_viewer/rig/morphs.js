import {expressions,behaviorMorphNames} from '../behavior.js';

// 角色包只包含数据；仅接受当前支持的顶点 Morph，不猜测组合/骨骼 Morph。
export function validateMorphMap(profile, names) {
  if(!profile || profile.version!==1 || !profile.aliases || typeof profile.aliases!=='object' || Array.isArray(profile.aliases) ||
    !profile.expressions || typeof profile.expressions!=='object' || Array.isArray(profile.expressions))throw new Error('表情映射格式不支持');
  const available=new Set(names);
  for(const [source,target] of Object.entries(profile.aliases)) {
    if(!behaviorMorphNames.includes(source) || (target!==null && (typeof target!=='string'||!available.has(target))))throw new Error(`表情别名无效：${source}`);
  }
  if(!profile.expressions.normal || Object.keys(profile.expressions.normal).length)throw new Error('平常表情必须为空');
  for(const [id,weights] of Object.entries(profile.expressions)) {
    if(!(id in expressions)||!weights||Array.isArray(weights)||typeof weights!=='object')throw new Error(`表情无效：${id}`);
    for(const [name,value] of Object.entries(weights))if(!available.has(name)||typeof value!=='number'||!Number.isFinite(value)||value<0||value>1)throw new Error(`表情权重无效：${name}`);
  }
  return profile;
}

export const mappedMorphNames=profile=>[...new Set([...behaviorMorphNames,
  ...Object.values(profile?.aliases||{}).filter(v=>v!==null),
  ...Object.values(profile?.expressions||{}).flatMap(weights=>Object.keys(weights))])];
