// Portable, model-specific metadata. The native solver uses model metres, never camera motion.
export const clothBone = name => /Hair|Daimao|Dress|Sleeve|BreastTie|^Tail_|髪|髮|发|スカート|裙|袖|リボン|飘带/.test(name) && !/Hairpin|Wanzi/.test(name);
export function spatialClothConfig(definitions, indices, dynamicIndices, seams, floor, sourceHash, grants = []) {
  const included = new Set(indices), paths = new Map();
  const pathFor = index => {
    if (!paths.has(index)) {
      const parent = definitions[index].parent;
      paths.set(index, (included.has(parent) ? pathFor(parent) + '/' : '') + 'j' + index);
    }
    return paths.get(index);
  };
  const ordered = [...indices].sort((left, right) => {
    const a = pathFor(left), b = pathFor(right);
    return a.split('/').length - b.split('/').length || (a < b ? -1 : a > b ? 1 : 0);
  });
  const ordinal = new Map(ordered.map((index, slot) => [index, slot]));
  const dynamic = new Set(dynamicIndices.filter(index => included.has(index) && clothBone(definitions[index].name)));
  const movable = ordered.filter(index => dynamic.has(index));
  const particle = new Map(movable.map((index, slot) => [index, slot]));
  const nodes = movable.map(index => ({joint: ordinal.get(index), parent: particle.get(definitions[index].parent) ?? -1,
    limit: /Hair|髪|髮|发|Daimao/.test(definitions[index].name) ? .12 : .18, radius: .008}));
  const links = nodes.flatMap((node, slot) => node.parent < 0 ? [] : [{a: node.parent, b: slot, stiffness: 1}]);
  const linked = new Set(links.map(link => [link.a, link.b].sort((a, b) => a - b).join(':')));
  for (const [left, right] of seams) {
    const a = particle.get(left), b = particle.get(right), key = [a, b].sort((x, y) => x - y).join(':');
    if (a !== undefined && b !== undefined && a !== b && !linked.has(key)) { links.push({a, b, stiffness: .65}); linked.add(key); }
  }
  const names = new Map(definitions.map((bone, index) => [bone.name, index]));
  const find = (...candidates) => candidates.map(name => names.get(name)).find(index => ordinal.has(index));
  const pairs = [[['下半身'], ['上半身'], .075], [['上半身'], ['上半身2'], .07], [['上半身2'], ['首'], .08], [['首'], ['頭'], .04]];
  for (const [prefix, suffix] of [['左', '.L'], ['右', '.R']]) {
    pairs.push([[prefix + '足', '足D' + suffix], [prefix + 'ひざ', 'ひざD' + suffix], .065],
      [[prefix + 'ひざ', 'ひざD' + suffix], [prefix + '足首', '足首D' + suffix], .045],
      [[prefix + '腕', '腕' + suffix], [prefix + 'ひじ', 'ひじ' + suffix], .03],
      [[prefix + 'ひじ', 'ひじ' + suffix], [prefix + '手首', '手首' + suffix], .025]);
  }
  const colliders = pairs.flatMap(([a, b, radius]) => {
    const left = find(...a), right = find(...b);
    return left === undefined || right === undefined ? [] : [{a: ordinal.get(left), b: ordinal.get(right), radius}];
  });
  return {version: 1, sourceSHA256: sourceHash, floor,
    joints: ordered.map(index => ({name: pathFor(index), bone: definitions[index].name, parent: ordinal.get(definitions[index].parent) ?? -1})),
    // Only the verified Hsin trial rig supplies chest rotation grants; Aemeath stays excluded.
    chestSprings: grants.length === 10 ? ['左胸', '右胸'].flatMap(name => {
      const joint = names.get(name), tip = names.get(name + '先');
      return ordinal.has(joint) && tip !== undefined && definitions[tip].parent === joint
        ? [{joint: ordinal.get(joint), tip: definitions[tip].position, limitAngle: .22}] : [];
    }) : [],
    nodes, links, colliders, postGrants: grants.filter(grant => ordinal.has(grant.joint) && ordinal.has(grant.source))
      .map(grant => ({joint: ordinal.get(grant.joint), source: ordinal.get(grant.source), ratio: grant.ratio})),
    limitations: ['Bone PBD with approximate body capsules and model floor; no triangle/self/real-room collision']};
}
