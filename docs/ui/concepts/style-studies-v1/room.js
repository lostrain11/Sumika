import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const AVATAR_URL = '/assets/AvatarSample_A.vrm';
const activeRooms = new WeakMap();
const themes = {
  a: { wall: '#f2f4ef', floor: '#d3c5aa', wood: '#e2d3b8', fabric: '#9eb8a4', accent: '#bc9394', trim: '#657d72', sky: '#cce4e4', cameraX: 0.65, exposure: 1.08 },
  b: { wall: '#f7f8f6', floor: '#ded9cc', wood: '#e8deca', fabric: '#a4cbd1', accent: '#e8a9a8', trim: '#759c98', sky: '#bde5f2', cameraX: -0.1, exposure: 1.13 },
  c: { wall: '#f0f7f7', floor: '#e1e9e6', wood: '#edf1e9', fabric: '#a4d5d3', accent: '#e2c56c', trim: '#59989e', sky: '#c8edf1', cameraX: 1.65, exposure: 1.09 },
  d: { wall: '#f5eeee', floor: '#ded2c4', wood: '#e6d5c4', fabric: '#aabcab', accent: '#d7a8b1', trim: '#827b86', sky: '#d4e8e6', cameraX: -0.4, exposure: 1.08 },
  e: { wall: '#fcfcfa', floor: '#e4e6de', wood: '#f4f1e5', fabric: '#86ced3', accent: '#ee8d83', trim: '#e8c659', sky: '#c6eaf4', cameraX: 0.45, exposure: 1.12 },
};

function seededRandom(seed) {
  let state = seed;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

function canvasTexture(width, height, paint) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Canvas 2D is unavailable for room textures.');
  paint(context, width, height);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

function woodTexture() {
  return canvasTexture(512, 512, (context, width, height) => {
    const random = seededRandom(114);
    context.fillStyle = '#f0ece3';
    context.fillRect(0, 0, width, height);
    for (let plank = 0; plank < 8; plank += 1) {
      context.fillStyle = ['#ece7dd', '#f0ede5', '#e6e1d6', '#f5f1e8'][plank % 4];
      context.fillRect(plank * 64, 0, 63, height);
      for (let grain = 0; grain < 28; grain += 1) {
        const origin = plank * 64 + random() * 61;
        context.strokeStyle = `rgba(105, 92, 72, ${0.025 + random() * 0.055})`;
        context.lineWidth = 0.6 + random();
        context.beginPath();
        context.moveTo(origin, 0);
        context.bezierCurveTo(origin + 5, 160, origin - 6, 360, origin, height);
        context.stroke();
      }
      context.fillStyle = 'rgba(99, 88, 70, 0.12)';
      context.fillRect(plank * 64, (plank % 3) * 156 + 25, 64, 1);
    }
  });
}

function fabricTexture() {
  return canvasTexture(256, 256, (context, width, height) => {
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, width, height);
    context.fillStyle = '#eeefec';
    for (let thread = 0; thread < width; thread += 4) {
      context.fillRect(thread, 0, 1, height);
      context.fillRect(0, thread, width, 1);
    }
  });
}

function landscapeTexture(theme) {
  return canvasTexture(768, 640, (context, width, height) => {
    const random = seededRandom(274);
    context.fillStyle = theme.sky;
    context.fillRect(0, 0, width, height);
    context.fillStyle = '#f4faf7';
    for (let cloud = 0; cloud < 3; cloud += 1) {
      context.beginPath();
      context.ellipse(80 + cloud * 310, 110 + cloud * 48, 150, 19, -0.03, 0, Math.PI * 2);
      context.fill();
    }
    context.fillStyle = '#b9d6cb';
    context.beginPath();
    context.moveTo(0, 460);
    context.bezierCurveTo(190, 390, 320, 490, 540, 410);
    context.lineTo(width, 425);
    context.lineTo(width, height);
    context.lineTo(0, height);
    context.fill();
    for (let branch = 0; branch < 8; branch += 1) {
      const tipX = 30 + random() * 160;
      const tipY = 130 + random() * 370;
      context.strokeStyle = '#8eaa95';
      context.lineWidth = 5;
      context.beginPath();
      context.moveTo(30, height);
      context.quadraticCurveTo(70, tipY + 60, tipX, tipY);
      context.stroke();
      for (let leaf = 0; leaf < 18; leaf += 1) {
        context.fillStyle = leaf % 2 ? '#98bca3' : '#afcdb3';
        context.beginPath();
        context.ellipse(tipX + (random() - 0.5) * 120, tipY + (random() - 0.5) * 70, 17, 10, random() * Math.PI, 0, Math.PI * 2);
        context.fill();
      }
    }
  });
}

function roundedGeometry(width, height, depth, radius = 0.04) {
  const corner = Math.min(radius, width / 3, height / 3);
  const shape = new THREE.Shape();
  shape.moveTo(-width / 2 + corner, -height / 2);
  shape.lineTo(width / 2 - corner, -height / 2);
  shape.quadraticCurveTo(width / 2, -height / 2, width / 2, -height / 2 + corner);
  shape.lineTo(width / 2, height / 2 - corner);
  shape.quadraticCurveTo(width / 2, height / 2, width / 2 - corner, height / 2);
  shape.lineTo(-width / 2 + corner, height / 2);
  shape.quadraticCurveTo(-width / 2, height / 2, -width / 2, height / 2 - corner);
  shape.lineTo(-width / 2, -height / 2 + corner);
  shape.quadraticCurveTo(-width / 2, -height / 2, -width / 2 + corner, -height / 2);
  const bevel = Math.min(0.015, depth / 5, corner / 3);
  const geometry = new THREE.ExtrudeGeometry(shape, { depth: depth - bevel * 2, bevelEnabled: true, bevelSegments: 2, steps: 1, bevelSize: bevel, bevelThickness: bevel, curveSegments: 5 });
  geometry.translate(0, 0, -depth / 2 + bevel);
  return geometry;
}

function createRoom(scene, theme, variant, resources) {
  const room = new THREE.Group();
  room.name = `style-study-${variant}-furnishings`;
  scene.add(room);
  const texture = (value) => { resources.add(value); return value; };
  const woodMap = texture(woodTexture());
  woodMap.wrapS = woodMap.wrapT = THREE.RepeatWrapping;
  const fabricMap = texture(fabricTexture());
  fabricMap.wrapS = fabricMap.wrapT = THREE.RepeatWrapping;
  fabricMap.repeat.set(5, 5);
  const material = (color, properties = {}) => {
    const result = new THREE.MeshStandardMaterial({ color, roughness: 0.84, ...properties });
    resources.add(result);
    return result;
  };
  const wall = material(theme.wall);
  const wood = material(theme.wood, { map: woodMap });
  const trim = material(theme.trim);
  const upholstery = material(theme.fabric, { map: fabricMap });
  const accent = material(theme.accent, { map: fabricMap });
  const linen = material('#f6f6ef', { map: fabricMap });
  const porcelain = material('#f3f6f0', { roughness: 0.32 });
  const ink = material('#59696b');
  const metal = material('#aab8b4', { metalness: 0.5, roughness: 0.4 });
  const addMesh = (parent, geometry, surface, position, rotation = [0, 0, 0]) => {
    resources.add(geometry);
    const mesh = new THREE.Mesh(geometry, surface);
    mesh.position.set(...position);
    mesh.rotation.set(...rotation);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    parent.add(mesh);
    return mesh;
  };
  const box = (parent, size, position, surface, radius = 0) => addMesh(parent, radius ? roundedGeometry(...size, radius) : new THREE.BoxGeometry(...size), surface, position);
  const cylinder = (parent, top, bottom, height, position, surface) => addMesh(parent, new THREE.CylinderGeometry(top, bottom, height, 28), surface, position);
  const sphere = (parent, scale, position, surface) => {
    const mesh = addMesh(parent, new THREE.SphereGeometry(1, 18, 12), surface, position);
    mesh.scale.set(...scale);
    return mesh;
  };
  const bar = (parent, start, end, radius, surface) => {
    const origin = new THREE.Vector3(...start);
    const target = new THREE.Vector3(...end);
    const direction = target.clone().sub(origin);
    const mesh = cylinder(parent, radius, radius, direction.length(), origin.clone().add(target).multiplyScalar(0.5).toArray(), surface);
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.normalize());
    return mesh;
  };

  const floorMap = texture(woodMap.clone());
  floorMap.repeat.set(3, 3);
  box(room, [14, 0.1, 10], [0, -0.055, 1.5], material(theme.floor, { map: floorMap }));
  const windowX = variant === 'c' ? -1.8 : -1.48;
  const windowWidth = variant === 'b' ? 2.75 : variant === 'a' ? 1.95 : 2.3;
  const windowLeft = windowX - windowWidth / 2;
  const windowRight = windowX + windowWidth / 2;
  box(room, [windowLeft + 7, 4.5, 0.12], [(-7 + windowLeft) / 2, 2.25, -1.8], wall);
  box(room, [7 - windowRight, 4.5, 0.12], [(7 + windowRight) / 2, 2.25, -1.8], wall);
  box(room, [windowWidth, 0.78, 0.12], [windowX, 0.39, -1.8], wall);
  box(room, [windowWidth, 1.8, 0.12], [windowX, 3.6, -1.8], wall);
  box(room, [0.12, 4.5, 8], [-6.9, 2.25, 2.14], wall);
  box(room, [14, 0.07, 0.06], [0, 0.06, -1.7], wood);
  const landscape = new THREE.MeshBasicMaterial({ map: texture(landscapeTexture(theme)), toneMapped: false });
  resources.add(landscape);
  const view = addMesh(room, new THREE.PlaneGeometry(windowWidth + 0.02, 1.96), landscape, [windowX, 1.75, -1.89]);
  view.castShadow = view.receiveShadow = false;
  for (const positionX of [windowLeft, windowRight]) box(room, [0.055, 2, 0.16], [positionX, 1.75, -1.72], wood);
  for (const positionY of [0.78, 2.72]) box(room, [windowWidth + 0.1, 0.06, 0.16], [windowX, positionY, -1.72], wood);
  box(room, [0.038, 1.9, 0.085], [windowX, 1.75, -1.68], wood);
  box(room, [windowWidth, 0.032, 0.085], [windowX, 1.68, -1.68], wood);
  box(room, [windowWidth + 0.22, 0.07, 0.3], [windowX, 0.74, -1.65], wood, 0.018);

  if (variant === 'a') {
    for (let slat = 1; slat < 6; slat += 1) box(room, [0.018, 1.9, 0.04], [windowLeft + slat * windowWidth / 6, 1.75, -1.63], wood);
    for (let slat = 1; slat < 5; slat += 1) box(room, [windowWidth, 0.018, 0.04], [windowX, 0.78 + slat * 1.94 / 5, -1.63], wood);
  } else {
    bar(room, [windowLeft - 0.16, 2.85, -1.47], [windowRight + 0.16, 2.85, -1.47], 0.016, metal);
    const curtain = material(variant === 'd' ? '#eddddd' : '#f7f8f3', { map: fabricMap, side: THREE.DoubleSide });
    for (const side of [-1, 1]) {
      const geometry = new THREE.PlaneGeometry(0.42, 2.04, 24, 20);
      const positions = geometry.attributes.position;
      for (let vertex = 0; vertex < positions.count; vertex += 1) {
        const positionX = positions.getX(vertex);
        const positionY = positions.getY(vertex);
        const vertical = (positionY + 1.02) / 2.04;
        const gather = Math.sin(vertical * Math.PI) * 0.13;
        positions.setXYZ(vertex, positionX * (1 - gather) + side * gather, positionY, Math.sin(positionX * 55) * 0.037);
      }
      geometry.computeVertexNormals();
      addMesh(room, geometry, curtain, [windowX + side * (windowWidth / 2 - 0.06), 1.76, -1.42]);
    }
  }

  box(room, [2.9, 0.022, 2.05], [-0.3, 0.013, 0.15], upholstery, 0.1);
  const sofa = new THREE.Group();
  sofa.position.set(variant === 'c' ? -1.85 : -1.38, 0, -0.73);
  sofa.rotation.y = 0.055;
  room.add(sofa);
  for (const positionX of [-0.64, 0.64]) {
    for (const positionZ of [-0.24, 0.24]) cylinder(sofa, 0.035, 0.027, 0.2, [positionX, 0.11, positionZ], trim);
  }
  box(sofa, [1.56, 0.16, 0.7], [0, 0.25, 0], wood, 0.04);
  box(sofa, [1.48, 0.47, 0.19], [0, 0.57, -0.29], upholstery, 0.1);
  for (const positionX of [-0.38, 0.38]) box(sofa, [0.72, 0.18, 0.63], [positionX, 0.38, 0.045], upholstery, 0.07);
  for (const positionX of [-0.79, 0.79]) box(sofa, [0.12, 0.27, 0.68], [positionX, 0.46, 0.01], wood, 0.04);
  const pillow = box(sofa, [0.36, 0.35, 0.15], [-0.44, 0.61, -0.13], accent, 0.085);
  pillow.rotation.set(-0.17, -0.13, -0.16);
  const secondPillow = box(sofa, [0.32, 0.32, 0.14], [0.46, 0.59, -0.13], linen, 0.08);
  secondPillow.rotation.set(-0.16, 0.12, 0.19);

  const leafMaterials = ['#739b87', '#91b39b', '#abc3a3'].map((color) => material(color));
  const stems = material('#7d9879');
  const soil = material('#666b5c');
  const plant = (parent, position, scale) => {
    const planter = new THREE.Group();
    planter.position.set(...position);
    planter.scale.setScalar(scale);
    parent.add(planter);
    cylinder(planter, 0.17, 0.12, 0.29, [0, 0.145, 0], porcelain);
    cylinder(planter, 0.155, 0.155, 0.008, [0, 0.294, 0], soil);
    for (let stem = 0; stem < 7; stem += 1) {
      const angle = stem * 2.4;
      const height = 0.53 + (stem % 3) * 0.18;
      const reach = 0.2 + (stem % 2) * 0.06;
      const tip = new THREE.Vector3(Math.cos(angle) * reach, height, Math.sin(angle) * reach);
      const curve = new THREE.QuadraticBezierCurve3(new THREE.Vector3(0, 0.27, 0), new THREE.Vector3(tip.x * 0.2, height * 0.94, tip.z * 0.2), tip);
      addMesh(planter, new THREE.TubeGeometry(curve, 10, 0.008, 5, false), stems, [0, 0, 0]);
      const leaf = sphere(planter, [0.09, 0.21, 0.019], tip.toArray(), leafMaterials[stem % 3]);
      leaf.rotation.set(0.4 + (stem % 2) * 0.3, -angle, -0.55 + (stem % 3) * 0.5);
    }
  };
  plant(room, [2.05, 0, -0.65], 1.35);
  plant(room, [windowLeft + 0.34, 0.78, -1.59], 0.4);

  const shelf = new THREE.Group();
  shelf.position.set(variant === 'a' ? 1.55 : 1.72, 0, -1.4);
  room.add(shelf);
  const shelfTop = variant === 'a' ? 1.16 : 1.8;
  box(shelf, [0.94, shelfTop - 0.08, 0.035], [0, shelfTop / 2, -0.15], material(variant === 'e' ? '#f5ded2' : theme.fabric));
  for (const positionX of [-0.49, 0.49]) box(shelf, [0.04, shelfTop, 0.36], [positionX, shelfTop / 2, 0], wood);
  const shelfLevels = variant === 'a' ? [0.15, 0.65, 1.17] : [0.15, 0.67, 1.23, 1.82];
  for (const positionY of shelfLevels) box(shelf, [1.04, 0.045, 0.4], [0, positionY, 0], wood, 0.01);
  const bookMaterials = [theme.fabric, theme.accent, theme.trim, '#d9dfd6', '#f4f2e7'].map((color) => material(color));
  const random = seededRandom(35);
  for (const level of shelfLevels.slice(0, -1)) {
    for (let book = 0; book < (variant === 'a' ? 4 : 7); book += 1) {
      const bookHeight = 0.22 + random() * 0.12;
      const bookX = -0.35 + book * 0.083;
      box(shelf, [0.058, bookHeight, 0.23], [bookX, level + 0.024 + bookHeight / 2, 0.035], bookMaterials[book % bookMaterials.length], 0.005);
      box(shelf, [0.036, 0.011, 0.003], [bookX, level + bookHeight * 0.76, 0.153], linen);
    }
  }
  plant(shelf, [-0.2, shelfTop + 0.05, 0], 0.4);

  const desk = new THREE.Group();
  desk.position.set(variant === 'c' ? 0.98 : variant === 'd' ? 1.03 : 1.29, 0, variant === 'c' ? 0.56 : 0.03);
  desk.rotation.y = variant === 'c' ? -0.2 : -0.04;
  room.add(desk);
  const deskWidth = variant === 'c' || variant === 'e' ? 1.42 : 1.12;
  box(desk, [deskWidth, 0.065, 0.68], [0, 0.79, 0], wood, 0.035);
  for (const positionX of [-deskWidth / 2 + 0.1, deskWidth / 2 - 0.1]) {
    for (const positionZ of [-0.23, 0.23]) bar(desk, [positionX * 1.06, 0.025, positionZ * 1.12], [positionX, 0.76, positionZ], 0.027, variant === 'c' ? metal : wood);
  }
  box(desk, [deskWidth - 0.2, 0.11, 0.055], [0, 0.69, -0.245], wood, 0.01);
  box(desk, [0.31, 0.025, 0.23], [-0.08, 0.84, 0.06], accent, 0.008);
  const notebook = box(desk, [0.285, 0.012, 0.215], [-0.08, 0.859, 0.06], linen, 0.005);
  notebook.rotation.y = -0.09;
  bar(desk, [-0.15, 0.87, 0.12], [0.02, 0.87, 0.07], 0.004, trim);
  cylinder(desk, 0.047, 0.042, 0.092, [deskWidth / 2 - 0.16, 0.87, 0.17], porcelain);
  cylinder(desk, 0.039, 0.039, 0.003, [deskWidth / 2 - 0.16, 0.917, 0.17], material('#967f66'));
  addMesh(desk, new THREE.TorusGeometry(0.029, 0.008, 8, 20), porcelain, [deskWidth / 2 - 0.107, 0.87, 0.17]);
  const lampX = deskWidth / 2 - 0.17;
  cylinder(desk, 0.093, 0.1, 0.027, [lampX, 0.84, -0.2], trim);
  bar(desk, [lampX, 0.85, -0.2], [lampX - 0.04, 1.18, -0.2], 0.012, metal);
  bar(desk, [lampX - 0.04, 1.18, -0.2], [lampX - 0.17, 1.27, -0.2], 0.011, metal);
  addMesh(desk, new THREE.CylinderGeometry(0.075, 0.14, 0.13, 28, 1, true), material(theme.accent, { side: THREE.DoubleSide }), [lampX - 0.17, 1.245, -0.2]);

  if (variant === 'c') {
    const laptop = new THREE.Group();
    laptop.position.set(-0.32, 0.836, -0.04);
    laptop.rotation.y = 0.12;
    desk.add(laptop);
    box(laptop, [0.44, 0.02, 0.28], [0, 0, 0], metal, 0.014);
    const lid = box(laptop, [0.44, 0.29, 0.019], [0, 0.14, -0.16], trim, 0.012);
    lid.rotation.x = -0.18;
    for (let row = 0; row < 4; row += 1) box(laptop, [0.34, 0.003, 0.017], [0, 0.012, -0.077 + row * 0.032], ink);
    for (let rail = 0; rail < 4; rail += 1) box(room, [1.25, 0.018, 0.025], [0.98, 2.05 + rail * 0.15, -1.69], metal);
  }

  if (variant === 'd') {
    box(room, [0.9, 0.65, 0.055], [0.62, 2.08, -1.69], accent, 0.01);
    for (let note = 0; note < 4; note += 1) {
      const page = box(room, [0.17, 0.23, 0.005], [0.31 + note * 0.2, 2.09 + (note % 2) * 0.08, -1.657], note % 2 ? linen : upholstery);
      page.rotation.z = note % 2 ? 0.05 : -0.07;
      box(room, [0.08, 0.032, 0.007], [page.position.x, page.position.y + 0.12, -1.652], wood);
    }
    box(desk, [0.18, 0.008, 0.14], [0.19, 0.838, -0.08], upholstery);
  } else {
    const artMap = texture(canvasTexture(384, 448, (context, width, height) => {
      context.fillStyle = '#f8faf6';
      context.fillRect(0, 0, width, height);
      context.fillStyle = theme.fabric;
      context.fillRect(46, 186, 118, 212);
      context.fillStyle = theme.accent;
      context.beginPath();
      context.arc(241, 140, 81, 0, Math.PI * 2);
      context.fill();
      context.fillStyle = theme.trim;
      context.beginPath();
      context.moveTo(189, 375);
      context.lineTo(330, 212);
      context.lineTo(330, 375);
      context.fill();
      context.fillStyle = '#ffffff';
      context.fillRect(69, 257, 251, 15);
    }));
    const artX = variant === 'c' ? -0.62 : 0.58;
    const artWidth = variant === 'e' ? 0.76 : 0.54;
    box(room, [artWidth + 0.055, artWidth * 1.17 + 0.055, 0.045], [artX, 2.12, -1.69], wood, 0.009);
    addMesh(room, new THREE.PlaneGeometry(artWidth, artWidth * 1.17), material('#ffffff', { map: artMap }), [artX, 2.12, -1.663]);
  }

  if (variant === 'e') {
    const music = new THREE.Group();
    music.position.set(-1.62, 0, -0.3);
    room.add(music);
    box(music, [1.38, 0.085, 0.42], [0, 0.89, 0], accent, 0.025);
    for (const side of [-1, 1]) {
      bar(music, [side * 0.52, 0.08, -0.09], [-side * 0.48, 0.85, -0.09], 0.022, metal);
      const speaker = new THREE.Group();
      speaker.position.set(side * 0.51, 1.075, -0.08);
      music.add(speaker);
      box(speaker, [0.2, 0.28, 0.2], [0, 0, 0], porcelain, 0.016);
      addMesh(speaker, new THREE.CylinderGeometry(0.062, 0.062, 0.009, 24), ink, [0, -0.035, 0.106], [Math.PI / 2, 0, 0]);
      addMesh(speaker, new THREE.CylinderGeometry(0.025, 0.025, 0.009, 20), trim, [0, 0.073, 0.106], [Math.PI / 2, 0, 0]);
    }
    for (let key = 0; key < 19; key += 1) {
      box(music, [0.044, 0.022, 0.21], [-0.43 + key * 0.048, 0.944, 0.035], linen, 0.002);
      if (![2, 6].includes(key % 7) && key < 18) box(music, [0.023, 0.018, 0.12], [-0.405 + key * 0.048, 0.963, -0.013], ink, 0.002);
    }
  }

  if (variant === 'a' || variant === 'b') {
    const floorLamp = new THREE.Group();
    floorLamp.position.set(-2.62, 0, -0.63);
    room.add(floorLamp);
    cylinder(floorLamp, 0.16, 0.18, 0.032, [0, 0.02, 0], trim);
    bar(floorLamp, [0, 0.035, 0], [0, 1.44, 0], 0.018, wood);
    addMesh(floorLamp, new THREE.CylinderGeometry(0.18, 0.24, 0.38, 32, 1, true), material('#f5f1e2', { side: THREE.DoubleSide }), [0, 1.45, 0]);
    for (let rib = 0; rib < 9; rib += 1) addMesh(floorLamp, new THREE.TorusGeometry(0.24 - rib * 0.0075, 0.003, 5, 32), linen, [0, 1.26 + rib * 0.0475, 0], [Math.PI / 2, 0, 0]);
  }
  return room;
}

function applyPose(vrm) {
  if (!vrm.humanoid) throw new Error('The sample VRM has no humanoid skeleton.');
  const versionSign = vrm.meta?.metaVersion === '1' ? 1 : -1;
  const rotate = (name, pitch, yaw, roll, required = false) => {
    const bone = vrm.humanoid.getNormalizedBoneNode(name);
    if (!bone && required) throw new Error(`The sample VRM is missing its ${name} bone.`);
    if (bone) bone.rotation.set(pitch, yaw, roll);
  };
  vrm.humanoid.resetNormalizedPose();
  rotate('leftUpperArm', 0.055, 0.015, -1.36 * versionSign, true);
  rotate('rightUpperArm', 0.035, -0.02, 1.3 * versionSign, true);
  rotate('leftLowerArm', -0.06, 0.035, -0.035 * versionSign);
  rotate('rightLowerArm', -0.1, -0.025, 0.065 * versionSign);
  rotate('leftHand', 0.04, 0, 0.07 * versionSign);
  rotate('rightHand', 0.035, 0, -0.06 * versionSign);
  rotate('spine', 0.005, 0.025 * versionSign, -0.012);
  rotate('chest', 0.008, -0.035 * versionSign, 0.014);
  rotate('neck', 0, 0.045 * versionSign, -0.025);
  rotate('head', -0.015, 0.065 * versionSign, 0.038, true);
  for (const side of ['left', 'right']) {
    for (const finger of ['Index', 'Middle', 'Ring', 'Little']) {
      for (const [joint, curl] of [['Proximal', 0.19], ['Intermediate', 0.25], ['Distal', 0.17]]) rotate(`${side}${finger}${joint}`, 0, 0, (side === 'left' ? -curl : curl) * versionSign);
    }
    rotate(`${side}ThumbProximal`, 0, side === 'left' ? 0.2 : -0.2, 0);
  }
  vrm.scene.rotation.y += -0.16;
  vrm.expressionManager?.setValue('happy', 0.12);
  if (vrm.lookAt) vrm.lookAt.autoUpdate = false;
  vrm.humanoid.update();
  vrm.nodeConstraintManager?.update();
  vrm.expressionManager?.update();
  vrm.scene.updateMatrixWorld(true);
  const bounds = new THREE.Box3().setFromObject(vrm.scene, true);
  const height = bounds.max.y - bounds.min.y;
  if (!Number.isFinite(height) || height < 0.1) throw new Error('The sample VRM has invalid visible bounds.');
  vrm.scene.scale.multiplyScalar(1.68 / height);
  vrm.scene.updateMatrixWorld(true);
  bounds.setFromObject(vrm.scene, true);
  vrm.scene.position.x += 0.1 - (bounds.min.x + bounds.max.x) / 2;
  vrm.scene.position.y += 0.034 - bounds.min.y;
  vrm.scene.position.z += 0.22 - (bounds.min.z + bounds.max.z) / 2;
  vrm.scene.updateMatrixWorld(true);
  vrm.springBoneManager?.reset();
  vrm.update(0);
  vrm.scene.updateMatrixWorld(true);
  vrm.scene.traverse((object) => {
    if (!object.isMesh) return;
    object.castShadow = true;
    object.receiveShadow = false;
    object.frustumCulled = false;
  });
}

function faceCenter(vrm) {
  const head = vrm.humanoid.getRawBoneNode('head') || vrm.humanoid.getNormalizedBoneNode('head');
  if (!head) throw new Error('The sample VRM is missing its head bone.');
  return head.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0, 0.055, 0.025));
}

function frameCamera(camera, vrm, theme, variant, compact, width, height) {
  const aspect = width / height;
  const viewHeight = Math.max(compact ? 1.16 : variant === 'b' ? 1.58 : 1.64, 0.9 / aspect);
  const viewWidth = viewHeight * aspect;
  const face = faceCenter(vrm);
  const faceHalfWidth = 0.115 * height / viewHeight;
  const faceX = compact
    ? Math.min(width - faceHalfWidth - 16, Math.max(width * 245 / 480, 176 + faceHalfWidth + 12))
    : width * (variant === 'b' ? 0.52 : 0.54);
  const faceY = compact ? height / 3 : variant === 'b' ? Math.max(90, (height - 185) * 0.39) : height * 0.31;
  camera.position.copy(face).add(new THREE.Vector3(theme.cameraX, compact ? 0.07 : 0.13, 6.8));
  camera.lookAt(face);
  camera.left = -faceX / width * viewWidth;
  camera.right = camera.left + viewWidth;
  camera.top = faceY / height * viewHeight;
  camera.bottom = camera.top - viewHeight;
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld(true);
}

function disposeScene(scene, resources) {
  const skeletons = new Set();
  const images = new Set();
  const collectTexture = (texture) => {
    if (!texture?.isTexture) return;
    resources.add(texture);
    if (texture.source?.data?.close) images.add(texture.source.data);
  };
  scene.traverse((object) => {
    if (object.geometry) resources.add(object.geometry);
    if (object.skeleton) skeletons.add(object.skeleton);
    object.shadow?.dispose();
    const materials = Array.isArray(object.material) ? object.material : object.material ? [object.material] : [];
    for (const material of materials) {
      resources.add(material);
      for (const value of Object.values(material)) collectTexture(value);
      for (const uniform of Object.values(material.uniforms || {})) collectTexture(uniform.value);
    }
  });
  for (const skeleton of skeletons) skeleton.dispose();
  for (const resource of resources) resource.dispose();
  for (const image of images) image.close();
  resources.clear();
  scene.clear();
}

export async function mountRoom(container, { variant = 'a', compact = false, transparent = false } = {}) {
  if (!(container instanceof HTMLElement)) throw new TypeError('mountRoom requires an HTML container.');
  if (!Object.hasOwn(themes, variant)) throw new Error(`Unknown room variant: ${String(variant)}.`);
  activeRooms.get(container)?.dispose();
  const theme = themes[variant];
  const scene = new THREE.Scene();
  const resources = new Set();
  const camera = new THREE.OrthographicCamera(-2, 2, 1.5, -1.5, 0.05, 40);
  const canvas = document.createElement('canvas');
  canvas.className = 'style-study-room-canvas';
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', `VRoid sample avatar in room study ${variant.toUpperCase()}`);
  Object.assign(canvas.style, { display: 'block', width: '100%', height: '100%', minWidth: '0', minHeight: '0', background: 'transparent', border: '0' });
  container.append(canvas);
  container.dataset.roomReady = 'false';
  container.dataset.roomStatus = 'loading';
  delete container.dataset.roomError;
  container.setAttribute('aria-busy', 'true');
  const abortController = new AbortController();
  let renderer = null;
  let furnishings = null;
  let vrm = null;
  let resizeObserver = null;
  let intersectionObserver = null;
  let lifecycleObserver = null;
  let errorElement = null;
  let loadTimer = 0;
  let disposed = false;
  let visible = true;
  let ready = false;
  let queued = false;
  let lastWidth = 0;
  let lastHeight = 0;
  let lastPixelRatio = 0;
  let wasConnected = container.isConnected;
  let failure = null;
  let rejectCancelled;
  const cancelled = new Promise((resolve, reject) => { rejectCancelled = reject; });
  cancelled.catch(() => {});

  const release = () => {
    if (disposed) return;
    disposed = true;
    abortController.abort();
    clearTimeout(loadTimer);
    resizeObserver?.disconnect();
    intersectionObserver?.disconnect();
    lifecycleObserver?.disconnect();
    document.removeEventListener('visibilitychange', requestRender);
    window.removeEventListener('resize', requestRender);
    canvas.removeEventListener('webglcontextlost', contextLost);
    disposeScene(scene, resources);
    renderer?.dispose();
    renderer?.forceContextLoss();
    canvas.remove();
    renderer = null;
    furnishings = null;
    vrm = null;
  };
  const showError = (cause) => {
    const error = cause instanceof Error ? cause : new Error(String(cause));
    if (disposed) return failure || error;
    failure = error;
    release();
    container.dataset.roomReady = 'false';
    container.dataset.roomStatus = 'error';
    container.dataset.roomError = error.message;
    container.setAttribute('aria-busy', 'false');
    errorElement = document.createElement('p');
    errorElement.setAttribute('role', 'alert');
    errorElement.textContent = `Room rendering failed: ${error.message}`;
    Object.assign(errorElement.style, { color: '#843e3e', background: '#fff6f5', padding: '16px', margin: '0', overflowWrap: 'anywhere', font: '14px/1.6 system-ui, sans-serif' });
    container.append(errorElement);
    rejectCancelled(error);
    return error;
  };
  const canRender = () => {
    if (disposed || !vrm || !visible || document.hidden || !canvas.isConnected) return false;
    if (!container.clientWidth || !container.clientHeight || !canvas.getClientRects().length) return false;
    if (canvas.checkVisibility && !canvas.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
    const bounds = canvas.getBoundingClientRect();
    return bounds.bottom > 0 && bounds.right > 0 && bounds.top < window.innerHeight && bounds.left < window.innerWidth;
  };
  const render = () => {
    if (!canRender()) return;
    try {
      const width = container.clientWidth;
      const height = container.clientHeight;
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
      if (width !== lastWidth || height !== lastHeight || pixelRatio !== lastPixelRatio) {
        lastWidth = width;
        lastHeight = height;
        lastPixelRatio = pixelRatio;
        renderer.setPixelRatio(pixelRatio);
        renderer.setSize(width, height, false);
        frameCamera(camera, vrm, theme, variant, compact, width, height);
      }
      furnishings.visible = !transparent;
      scene.background = transparent ? null : new THREE.Color(theme.wall);
      renderer.setClearColor(transparent ? '#000000' : theme.wall, transparent ? 0 : 1);
      renderer.shadowMap.needsUpdate = true;
      renderer.render(scene, camera);
      if (renderer.getContext().isContextLost()) throw new Error('The WebGL graphics context was lost.');
      if (renderer.info.render.calls === 0) throw new Error('The room did not produce a visible render.');
      ready = true;
      container.dataset.roomReady = 'true';
      container.dataset.roomStatus = 'ready';
      container.setAttribute('aria-busy', 'false');
    } catch (error) {
      showError(error);
    }
  };
  function requestRender() {
    if (queued || !canRender()) return;
    queued = true;
    queueMicrotask(() => {
      queued = false;
      render();
    });
  }
  function contextLost(event) {
    event.preventDefault();
    showError(new Error('The WebGL graphics context was lost. Please remount the room.'));
  }
  const api = {
    dispose() {
      release();
      errorElement?.remove();
      if (activeRooms.get(container) === api) {
        activeRooms.delete(container);
        container.dataset.roomReady = 'false';
        container.dataset.roomStatus = 'disposed';
        container.setAttribute('aria-busy', 'false');
      }
      rejectCancelled(new DOMException('Room mounting was cancelled.', 'AbortError'));
    },
    setVisible(value) {
      if (disposed) return;
      visible = Boolean(value);
      canvas.style.visibility = visible ? 'visible' : 'hidden';
      if (visible) requestRender();
    },
    setTransparent(value) {
      if (disposed || transparent === Boolean(value)) return;
      transparent = Boolean(value);
      requestRender();
    },
    getFaceBounds() {
      if (!ready || !canRender()) return null;
      const bounds = canvas.getBoundingClientRect();
      const center = faceCenter(vrm).project(camera);
      const width = 0.23 / (camera.right - camera.left) * bounds.width;
      const height = 0.25 / (camera.top - camera.bottom) * bounds.height;
      const centerX = bounds.left + (center.x + 1) * bounds.width / 2;
      const centerY = bounds.top + (1 - center.y) * bounds.height / 2;
      const left = centerX - width / 2;
      const top = centerY - height / 2;
      return { x: left, y: top, left, top, right: left + width, bottom: top + height, width, height, centerX, centerY };
    },
  };
  activeRooms.set(container, api);
  try {
    lifecycleObserver = new MutationObserver(() => {
      if ((wasConnected && !container.isConnected) || !container.contains(canvas)) {
        api.dispose();
        return;
      }
      const attached = !wasConnected && container.isConnected;
      wasConnected ||= container.isConnected;
      if (attached) requestRender();
    });
    lifecycleObserver.observe(document.documentElement, { childList: true, subtree: true });
    lifecycleObserver.observe(container, { childList: true });
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'low-power', preserveDrawingBuffer: true });
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = theme.exposure;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.shadowMap.autoUpdate = false;
    renderer.debug.onShaderError = (context, program) => { throw new Error(`Room shader compilation failed: ${context.getProgramInfoLog(program) || 'GPU shader error'}`); };
    canvas.addEventListener('webglcontextlost', contextLost);
    scene.add(new THREE.HemisphereLight('#ffffff', '#bac5bb', 1.9));
    const sunlight = new THREE.DirectionalLight('#fff8ee', 1.7);
    sunlight.position.set(-3.8, 4.9, 3.2);
    sunlight.target.position.set(0, 0.9, -0.2);
    sunlight.castShadow = true;
    sunlight.shadow.mapSize.set(2048, 2048);
    Object.assign(sunlight.shadow.camera, { left: -5, right: 5, top: 5, bottom: -5, near: 0.1, far: 18 });
    sunlight.shadow.normalBias = 0.03;
    sunlight.shadow.bias = -0.0002;
    sunlight.shadow.radius = 3;
    scene.add(sunlight, sunlight.target);
    const faceLight = new THREE.DirectionalLight('#ffffff', 0.8);
    faceLight.position.set(0.2, 1.9, 4);
    scene.add(faceLight);
    furnishings = createRoom(scene, theme, variant, resources);
    loadTimer = window.setTimeout(() => showError(new Error(`Timed out while loading ${AVATAR_URL}. Check the local asset route.`)), 60000);
    const response = await Promise.race([fetch(AVATAR_URL, { signal: abortController.signal, redirect: 'error', mode: 'same-origin' }), cancelled]);
    if (!response.ok) throw new Error(`Cannot load ${AVATAR_URL}: HTTP ${response.status}.`);
    const source = await Promise.race([response.arrayBuffer(), cancelled]);
    if (disposed) throw new DOMException('Room mounting was cancelled.', 'AbortError');
    const manager = new THREE.LoadingManager();
    manager.setURLModifier((url) => {
      if (url.startsWith('blob:') || url.startsWith('data:')) return url;
      throw new Error('The sample VRM must contain embedded textures and buffers.');
    });
    const loader = new GLTFLoader(manager);
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const parsing = loader.parseAsync(source, new URL('/assets/', window.location.href).href).then((result) => {
      if (disposed) {
        disposeScene(result.scene, new Set());
        throw new DOMException('Room mounting was cancelled.', 'AbortError');
      }
      return result;
    });
    const gltf = await Promise.race([parsing, cancelled]);
    if (disposed) {
      disposeScene(gltf.scene, new Set());
      throw new DOMException('Room mounting was cancelled.', 'AbortError');
    }
    scene.add(gltf.scene);
    vrm = gltf.userData.vrm;
    if (!vrm) throw new Error('The asset loaded, but the VRM plugin returned no avatar.');
    VRMUtils.rotateVRM0(vrm);
    applyPose(vrm);
    clearTimeout(loadTimer);
    container.dataset.roomStatus = 'loaded';
    container.setAttribute('aria-busy', 'false');
    resizeObserver = new ResizeObserver(() => {
      if (lastWidth !== container.clientWidth || lastHeight !== container.clientHeight || !ready) requestRender();
    });
    resizeObserver.observe(container);
    if (typeof IntersectionObserver !== 'undefined') {
      intersectionObserver = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) requestRender();
      });
      intersectionObserver.observe(canvas);
    }
    document.addEventListener('visibilitychange', requestRender);
    window.addEventListener('resize', requestRender);
    render();
    if (failure) throw failure;
    return api;
  } catch (error) {
    throw showError(error);
  }
}
