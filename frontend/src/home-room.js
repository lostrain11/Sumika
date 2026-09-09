import * as THREE from "three";

export const HOME_ROOM_COLOR = 0xf2f1e9;

export function modelRoomMetrics(bounds) {
  const size = bounds.getSize(new THREE.Vector3());
  if (bounds.isEmpty() || ![...bounds.min, ...bounds.max].every(Number.isFinite) || size.y <= 0) {
    throw new Error("VRM model has invalid room bounds");
  }
  return { height: size.y, size, center: bounds.getCenter(new THREE.Vector3()), scale: size.y / 1.7 };
}

export function fitHomeRoomCamera(camera, bounds, width, height) {
  const metrics = modelRoomMetrics(bounds);
  const aspect = Math.max(1, width) / Math.max(1, height);
  const compact = height <= 360;
  const viewHeight = Math.max(metrics.height * (compact ? 1.48 : 1.28), metrics.height * 1.12 / aspect, metrics.size.x * 1.2 / aspect);
  const distance = viewHeight / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))) + metrics.size.z / 2;
  const target = metrics.center.clone();
  target.y = bounds.min.y + metrics.height * 0.58;
  camera.aspect = aspect;
  camera.position.copy(target).add(new THREE.Vector3(distance * 0.085, distance * 0.045, distance));
  camera.near = Math.max(0.0001, metrics.height / 100);
  camera.far = distance + metrics.height * 30;
  camera.lookAt(target);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld(true);
}

export function createHomeRoom(bounds) {
  const root = new THREE.Group();
  root.name = "SumikaHomeRoom";
  const resources = new Set();
  const geometry = (value) => { resources.add(value); return value; };
  const boxGeometry = geometry(new THREE.BoxGeometry(1, 1, 1));
  const sphereGeometry = geometry(new THREE.SphereGeometry(1, 12, 8));
  const cylinderGeometry = geometry(new THREE.CylinderGeometry(1, 0.85, 1, 20));
  const material = (color, basic = false) => {
    const surface = basic ? new THREE.MeshBasicMaterial({ color }) : new THREE.MeshStandardMaterial({ color, roughness: 0.88 });
    resources.add(surface);
    return surface;
  };
  const wall = material(HOME_ROOM_COLOR);
  const wood = material(0xd9c8a8);
  const woodLight = material(0xe5d7ba);
  const linen = material(0xf6f3e9);
  const sage = material(0xa3b7a2);
  const leaf = material(0x6d8974);
  const rose = material(0xc59fa0);
  const sky = material(0xd0e7e6, true);
  const hill = material(0xb6d1c4, true);
  const mesh = (name, shape, size, position, surface) => {
    const object = new THREE.Mesh(shape, surface);
    object.name = name;
    object.scale.set(...size);
    object.position.set(...position);
    root.add(object);
    return object;
  };
  const box = (name, size, position, surface) => mesh(name, boxGeometry, size, position, surface);
  box("back-wall", [12, 5, 0.12], [0, 2.5, -1.55], wall);
  box("side-wall", [0.12, 5, 8], [-5.5, 2.5, 2.4], wall);
  box("wood-floor", [12, 0.08, 10], [0, -0.041, 1.5], woodLight);
  for (let plank = 0; plank < 25; plank += 1) {
    box("floor-seam", [0.009, 0.002, 10], [-6 + plank * 0.5, 0, 1.5], wood);
  }
  box("skirting", [12, 0.07, 0.045], [0, 0.035, -1.46], wood);
  box("window-frame", [1.92, 2.08, 0.1], [-1.32, 1.72, -1.43], wood);
  box("window-sky", [1.79, 1.94, 0.015], [-1.32, 1.72, -1.369], sky);
  const landscape = mesh("window-garden", sphereGeometry, [0.88, 0.26, 0.018], [-1.32, 1.24, -1.346], hill);
  landscape.rotation.z = -0.08;
  box("window-garden-base", [1.78, 0.44, 0.02], [-1.32, 0.99, -1.34], hill);
  for (const offset of [-0.45, 0.45]) box("window-mullion", [0.036, 1.97, 0.06], [-1.32 + offset, 1.72, -1.31], woodLight);
  for (const elevation of [1.15, 1.82, 2.45]) box("window-rail", [1.82, 0.035, 0.06], [-1.32, elevation, -1.31], woodLight);
  box("window-sill", [2.03, 0.055, 0.24], [-1.32, 0.685, -1.31], woodLight);
  box("rug", [2.65, 0.008, 1.5], [0, 0.005, 0.15], linen);
  box("seat-base", [0.94, 0.12, 0.69], [-1.38, 0.28, -0.58], wood);
  box("seat-cushion", [0.83, 0.16, 0.6], [-1.38, 0.4, -0.58], sage);
  const back = box("seat-back", [0.89, 0.54, 0.13], [-1.38, 0.62, -0.87], sage);
  back.rotation.x = -0.08;
  const pillow = box("linen-pillow", [0.35, 0.32, 0.15], [-1.5, 0.63, -0.73], linen);
  pillow.rotation.z = 0.12;
  for (const side of [-1, 1]) {
    box("seat-arm", [0.08, 0.32, 0.63], [-1.38 + side * 0.49, 0.42, -0.57], woodLight);
    for (const depth of [-0.82, -0.33]) box("seat-leg", [0.065, 0.23, 0.065], [-1.38 + side * 0.37, 0.12, depth], wood);
  }
  box("desk-top", [1.14, 0.065, 0.68], [1.4, 0.79, -0.24], woodLight);
  for (const positionX of [0.94, 1.86]) {
    for (const positionZ of [-0.48, 0]) box("desk-leg", [0.055, 0.76, 0.055], [positionX, 0.38, positionZ], wood);
  }
  box("notebook-cover", [0.32, 0.024, 0.23], [1.24, 0.835, -0.18], rose);
  box("notebook-pages", [0.3, 0.012, 0.215], [1.24, 0.852, -0.18], linen);
  mesh("cup", cylinderGeometry, [0.045, 0.095, 0.045], [1.77, 0.87, -0.13], linen);
  mesh("tea", cylinderGeometry, [0.037, 0.003, 0.037], [1.77, 0.919, -0.13], wood);
  box("shelf-back", [0.84, 1.07, 0.04], [1.63, 0.61, -1.37], sage);
  for (const positionX of [1.18, 2.08]) box("shelf-side", [0.045, 1.16, 0.34], [positionX, 0.58, -1.21], wood);
  for (const elevation of [0.13, 0.64, 1.17]) {
    box("shelf-level", [0.97, 0.045, 0.38], [1.63, elevation, -1.21], woodLight);
    if (elevation > 1) continue;
    for (let book = 0; book < 4; book += 1) {
      const bookHeight = 0.23 + (book % 3) * 0.035;
      box("book", [0.063, bookHeight, 0.23], [1.32 + book * 0.09, elevation + 0.023 + bookHeight / 2, -1.17], [sage, rose, linen, leaf][book]);
    }
  }
  mesh("plant-pot", cylinderGeometry, [0.11, 0.15, 0.11], [1.71, 1.27, -1.21], linen);
  for (let branch = 0; branch < 5; branch += 1) {
    const foliage = mesh("plant-leaf", sphereGeometry, [0.055, 0.16, 0.035], [1.71 + Math.sin(branch * 2.4) * 0.085, 1.47, -1.21 + Math.cos(branch * 2.4) * 0.045], leaf);
    foliage.rotation.z = (branch - 2) * 0.32;
  }
  box("art-frame", [0.62, 0.74, 0.05], [0.94, 2.15, -1.445], wood);
  box("art-paper", [0.55, 0.67, 0.009], [0.94, 2.15, -1.414], linen);
  box("art-sage", [0.2, 0.31, 0.008], [0.83, 2.04, -1.404], sage);
  mesh("art-circle", sphereGeometry, [0.12, 0.12, 0.004], [1.04, 2.29, -1.398], rose);

  let disposed = false;
  const fitToModel = (modelBounds) => {
    const metrics = modelRoomMetrics(modelBounds);
    root.scale.setScalar(metrics.scale);
    root.position.set(metrics.center.x, modelBounds.min.y, metrics.center.z);
    root.updateMatrixWorld(true);
  };
  fitToModel(bounds);
  return {
    root,
    fitToModel,
    dispose() {
      if (disposed) return;
      disposed = true;
      root.removeFromParent();
      for (const resource of resources) resource.dispose();
      resources.clear();
      root.clear();
    },
  };
}
