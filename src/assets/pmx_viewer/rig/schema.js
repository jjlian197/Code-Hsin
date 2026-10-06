// Hsin 语义骨架 v1：控制骨与解剖骨分开，名称不改变原 PMX。
export const SCHEMA_VERSION = 1;
export const normalizeName = name => String(name ?? '').normalize('NFKC').toLowerCase()
  .replace(/^mixamorig[:_]?/, '').replace(/[\s_.:\-]/g, '');
const bone = (id, aliases, parent = null, required = false, group = 'body', side = null) =>
  ({id, aliases, parent, required, group, side});
export const RIG_SCHEMA = [
  bone('root', ['全ての親', 'Root', '全局', '总父'], null, false, 'control'),
  bone('center', ['センター', 'Center', '中心'], null, false, 'control'),
  bone('groove', ['グルーブ', 'Groove'], null, false, 'control'),
  bone('hips', ['下半身', 'Hips', 'Pelvis', '骨盆'], null, true),
  bone('spine', ['上半身', 'Spine', '脊柱'], null, true),
  bone('spine_mid', ['上半身1', 'Spine1'], 'spine'),
  bone('chest', ['上半身2', 'Spine2', 'Chest', '胸腔'], 'spine'),
  bone('upper_chest', ['上半身3', 'Spine3', 'UpperChest'], 'spine'),
  bone('neck', ['首', 'Neck', '颈'], 'spine', true),
  bone('head', ['頭', 'Head', '头'], 'neck', true),
  bone('eyes', ['両目', 'Eyes', '双眼'], 'head', false, 'eye'),
];
for (const [side, jp, cn, letter] of [['left', '左', '左', 'L'], ['right', '右', '右', 'R']]) {
  const aliases = (j, en, chinese) => [jp + j, side + en, en + '_' + letter, letter + '_' + en, cn + chinese];
  RIG_SCHEMA.push(
    bone(side + '_eye', aliases('目', 'Eye', '眼'), 'head', false, 'eye', side),
    bone(side + '_shoulder', aliases('肩', 'Shoulder', '肩'), 'spine', false, 'body', side),
    bone(side + '_upper_arm', [...aliases('腕', 'Arm', '上臂'), side + 'UpperArm', 'upper_arm.' + letter], 'spine', true, 'body', side),
    bone(side + '_lower_arm', [...aliases('ひじ', 'ForeArm', '前臂'), side + 'LowerArm', jp + '肘'], side + '_upper_arm', true, 'body', side),
    bone(side + '_hand', [...aliases('手首', 'Hand', '手腕'), side + 'Wrist'], side + '_lower_arm', true, 'body', side),
    bone(side + '_upper_leg', [...aliases('足', 'UpLeg', '大腿'), side + 'Thigh', side + 'UpperLeg'], 'hips', true, 'body', side),
    bone(side + '_lower_leg', [...aliases('ひざ', 'Leg', '小腿'), side + 'Calf', side + 'LowerLeg', jp + '膝'], side + '_upper_leg', true, 'body', side),
    bone(side + '_foot', [...aliases('足首', 'Foot', '脚踝'), side + 'Ankle'], side + '_lower_leg', true, 'body', side),
    bone(side + '_toes', aliases('つま先', 'ToeBase', '脚趾'), side + '_foot', false, 'body', side),
    bone(side + '_foot_ik', [jp + '足IK', side + 'FootIK'], null, false, 'ik', side),
    bone(side + '_toe_ik', [jp + 'つま先IK', side + 'ToeIK'], null, false, 'ik', side),
  );
  for (const [finger, jpName] of [['thumb','親'], ['index','人'], ['middle','中'], ['ring','薬'], ['little','小']]) {
    for (let segment = 1; segment <= 3; segment++) {
      // MMD 拇指编号 0/1/2，其余手指 1/2/3。
      const n = finger === 'thumb' ? segment - 1 : segment;
      RIG_SCHEMA.push(bone(`${side}_${finger}_${segment}`,
        [jp + jpName + '指' + n, `${side}Hand${finger}${segment}`, `${finger}${segment}_${letter}`],
        segment === 1 ? side + '_hand' : `${side}_${finger}_${segment - 1}`, false, 'finger', side));
    }
  }
}

export const schemaById = new Map(RIG_SCHEMA.map(entry => [entry.id, entry]));
