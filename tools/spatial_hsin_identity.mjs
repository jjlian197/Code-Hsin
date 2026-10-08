// Trial files were checked against their originals: only ten auxiliary parents/flags differ.
// Keep this acceptance in the spatial conversion pipeline; desktop defaults remain unchanged.
const first = '4cf8454f7a79c84b88cf3dadfaca3fe2d55d3c6349fffd204acaf24dc78ea82e';
const second = 'e766ffc90c5a69a06da2365232616b1b730d8ecfa08fe685d770da0c509b8471';
const identities = new Map([
  [first, {form: 'first', calibrationHash: first, trial: false}],
  [second, {form: 'second', calibrationHash: second, trial: false}],
  ['793b1e9ed92e44154add8616423d5f7932422303966e0541a6c0597a4ae703c3', {form: 'first', calibrationHash: first, trial: true}],
  ['247f1f0adb21ad4a6ef6bc51a03ab2293a956a4965ebb63c6a8066af3e7c02cf', {form: 'second', calibrationHash: second, trial: true}],
]);
export function spatialHsinIdentity(hash) {
  const identity = identities.get(hash);
  if (!identity) throw new Error('Uncalibrated spatial Hsin model');
  return identity;
}
