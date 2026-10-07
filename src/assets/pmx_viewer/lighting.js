import * as THREE from 'three';

// 保留 toon 的轮廓与贴图层次，用正面柔光抬亮脸部，而非给材质加白色自发光。
export function createDesktopLighting(scene) {
  const ambient = new THREE.AmbientLight(0xffffff, 1.15);
  const key = new THREE.DirectionalLight(0xfff5ef, 1.25);
  key.position.set(-8, 25, 30);
  const fill = new THREE.DirectionalLight(0xffeef4, 0.65);
  fill.position.set(8, 15, 20);
  const front = new THREE.DirectionalLight(0xffffff, 0.45);
  front.position.set(0, 12, 35);
  scene.add(ambient, key, fill, front);
  function preset(brighter = true) {
    ambient.intensity = brighter ? 1.15 : 1.0;
    key.color.setHex(brighter ? 0xfff5ef : 0xffffff);
    key.intensity = brighter ? 1.25 : 0.85;
    fill.color.setHex(brighter ? 0xffeef4 : 0xffe7ed);
    fill.intensity = brighter ? 0.65 : 0.25;
    fill.position.z = brighter ? 20 : 10;
    front.intensity = brighter ? 0.45 : 0;
  }
  return { preset };
}
