import { NormalBlending } from 'three';

// MMDLoader 把贴图透明检测结果写在 Texture 上，需转交给 Material。
// 否则半透明毛发会直接覆盖身体的 alpha，桌面背景便会透过身体。
export function configureMaterials(materials) {
  const alphaCache = new Map();
  function hasAlpha(texture) {
    if (!texture?.image) return false;
    if (alphaCache.has(texture)) return alphaCache.get(texture);
    const image = texture.image;
    let pixels = image.data;
    if (!pixels) {
      const canvas = document.createElement('canvas');
      canvas.width = image.width;
      canvas.height = image.height;
      const context = canvas.getContext('2d', { willReadFrequently: true });
      context.drawImage(image, 0, 0);
      pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    }
    let transparent = false;
    if (pixels.length === image.width * image.height * 4) {
      for (let i = 3; i < pixels.length; i += 4) {
        if (pixels[i] < 255) { transparent = true; break; }
      }
    }
    alphaCache.set(texture, transparent);
    return transparent;
  }
  for (const material of materials) {
    material.transparent = material.opacity < 1 || hasAlpha(material.map);
    // 标准 source-over 保证透明毛发叠在身体上时，主体 alpha 仍为 1。
    material.blending = NormalBlending;
    material.premultipliedAlpha = false;
    material.depthWrite = !material.transparent;
    material.alphaTest = material.transparent ? 0.02 : 0;
    // 将 MMD 环境项乘以贴图颜色，避免给深色衣服加一层灰。
    material.onBeforeCompile = shader => {
      shader.fragmentShader = shader.fragmentShader.replace(
        '#include <emissivemap_fragment>',
        '#include <emissivemap_fragment>\ntotalEmissiveRadiance *= diffuseColor.rgb;'
      );
    };
    material.customProgramCacheKey = () => 'hsin-textured-ambient-v1';
    material.needsUpdate = true;
  }
  return {
    opaque: materials.filter(m => !m.transparent).length,
    transparent: materials.filter(m => m.transparent).length,
    body_opacity: materials.filter(m => /^(Face_|Up_|Down_|Cloth)$/.test(m.name))
      .map(m => ({ name: m.name, opacity: m.opacity, transparent: m.transparent })),
  };
}
