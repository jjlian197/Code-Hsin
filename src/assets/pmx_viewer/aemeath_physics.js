// 爱弥斯 1.05 的六刚体胸部链，独立于心的果冻胸结构。
export const AEMEATH_MODEL_HASH='79b622d0a87ab61516d2c3008d241d9145daa905acbcbd29d070c68cc55fa437';
export const AEMEATH_PATCHED_HASH='8b7294f38ace5dfae8ba65b400d4feb13897a1d15f828e285189fc56ef6f7854';
export function isAemeathChestModel(hash){return hash===AEMEATH_MODEL_HASH||hash===AEMEATH_PATCHED_HASH;}

export function applyAemeathChestRig(data,hash){
  if(!isAemeathChestModel(hash))return 0;
  const names=['左胸上','左胸上2','左胸先','左胸下','左胸下先','右胸上','右胸上2','右胸先','右胸下','右胸下先'];
  const bones=names.map(name=>data.bones.find(b=>b.name===name));
  if(bones.some(b=>!b))throw new Error('爱弥斯胸部骨架不匹配');
  // 第二段关节连到上胸刚体，骨骼父链也采用相同层次。
  for(const side of ['左','右']){
    data.bones.find(b=>b.name===side+'胸上2').parentIndex=data.bones.findIndex(b=>b.name===side+'胸上');
  }
  bones.forEach(b=>{b.flag|=0x1000;});
  return bones.length;
}

export function adaptAemeathChestPhysics(mesh,hash){
  if(!isAemeathChestModel(hash))return 0;
  const mmd=mesh.geometry.userData.MMD;
  const names=new Set(['左胸上','左胸上2','左胸下','右胸上','右胸上2','右胸下']);
  const bodies=mmd.rigidBodies.filter(b=>names.has(b.name)&&mesh.skeleton.bones[b.boneIndex]?.name===b.name);
  if(bodies.length!==6)throw new Error('爱弥斯胸部刚体不匹配');
  // 与心采用相同原则：位置由骨骼驱动，刚体只提供有限旋转和回弹。
  bodies.forEach(b=>{b.type=2;});
  let count=0;
  for(const c of mmd.constraints){
    if(!names.has(c.name)&&c.name!=='左胸補助'&&c.name!=='右胸補助')continue;
    const link=c.name.endsWith('上2')||c.name.endsWith('補助');
    const limit=c.name.endsWith('補助')?.2:.12;
    c.translationLimitation1=[0,0,0];c.translationLimitation2=[0,0,0];
    c.rotationLimitation1=link?[-limit,0,0]:[-limit,-.12,-.08];
    c.rotationLimitation2=link?[limit,0,0]:[limit,.12,.08];
    c.springRotation=link?[8,0,0]:[8,8,8];count++;
  }
  if(count!==8)throw new Error('爱弥斯胸部关节不匹配');
  return bodies.length;
}
