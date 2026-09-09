import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const AVATAR_URL = '/assets/AvatarSample_A.vrm';
const activeRooms = new WeakMap();
const themes = {
  afternoon: { sky: '#adcfd3', horizon: '#f4e3bf', foliage: '#719482', wall: '#f0e9dd', ambient: 1.65, sunlight: 2.1, exposure: 1.05 },
  evening: { sky: '#283456', horizon: '#6d7195', foliage: '#35435b', wall: '#b9aaa4', ambient: 0.42, sunlight: 0.3, exposure: 0.94 },
  work: { sky: '#b5d4da', horizon: '#edf0de', foliage: '#72988b', wall: '#e9e6da', ambient: 1.7, sunlight: 1.65, exposure: 1.02 },
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
  if (!context) throw new Error('Canvas 2D is unavailable for the room textures.');
  paint(context, width, height);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

function woodTexture() {
  return canvasTexture(512, 512, (context, width, height) => {
    const random = seededRandom(114);
    context.fillStyle = '#c7ac86';
    context.fillRect(0, 0, width, height);
    for (let plank = 0; plank < 8; plank += 1) {
      context.fillStyle = ['#cdb18b', '#d2ba97', '#c7ad89', '#d7bf9d'][plank % 4];
      context.fillRect(plank * 64, 0, 63, height);
      for (let grain = 0; grain < 28; grain += 1) {
        const origin = plank * 64 + random() * 61;
        context.strokeStyle = `rgba(105, 82, 57, ${0.025 + random() * 0.055})`;
        context.lineWidth = 0.6 + random();
        context.beginPath();
        context.moveTo(origin, 0);
        context.bezierCurveTo(origin + 5, 160, origin - 6, 360, origin, height);
        context.stroke();
      }
      context.fillStyle = 'rgba(99, 78, 56, 0.18)';
      context.fillRect(plank * 64, (plank % 3) * 156 + 25, 64, 1);
    }
  });
}

function fabricTexture() {
  return canvasTexture(256, 256, (context, width, height) => {
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, width, height);
    context.fillStyle = '#e5e4e0';
    for (let thread = 0; thread < width; thread += 4) {
      context.fillRect(thread, 0, 1, height);
      context.fillRect(0, thread, width, 1);
    }
  });
}

function landscapeTexture(theme, evening) {
  return canvasTexture(1024, 768, (context, width, height) => {
    const random = seededRandom(274);
    const sky = context.createLinearGradient(0, 0, 0, height);
    sky.addColorStop(0, theme.sky);
    sky.addColorStop(1, theme.horizon);
    context.fillStyle = sky;
    context.fillRect(0, 0, width, height);
    if (evening) {
      context.fillStyle = '#f9ecd3';
      context.beginPath();
      context.arc(735, 145, 29, 0, Math.PI * 2);
      context.fill();
      context.fillStyle = '#e0dce7';
      for (let star = 0; star < 27; star += 1) {
        context.fillRect(random() * width, random() * height * 0.5, 1.6, 1.6);
      }
    } else {
      context.fillStyle = 'rgba(255, 255, 249, 0.42)';
      for (let cloud = 0; cloud < 3; cloud += 1) {
        context.beginPath();
        context.ellipse(190 + cloud * 335, 140 + cloud * 45, 140, 18, -0.04, 0, Math.PI * 2);
        context.fill();
      }
    }
    context.fillStyle = evening ? '#68738f' : '#a8bfb0';
    context.beginPath();
    context.moveTo(0, 595);
    context.bezierCurveTo(220, 495, 345, 630, 590, 535);
    context.bezierCurveTo(785, 470, 945, 555, width, 515);
    context.lineTo(width, height);
    context.lineTo(0, height);
    context.fill();
    const branch = (originX, originY, length, angle, depth) => {
      const tipX = originX + Math.cos(angle) * length;
      const tipY = originY + Math.sin(angle) * length;
      context.strokeStyle = evening ? '#424862' : '#6b8271';
      context.lineWidth = depth * 2.4;
      context.lineCap = 'round';
      context.beginPath();
      context.moveTo(originX, originY);
      context.quadraticCurveTo(originX + 12, (originY + tipY) / 2, tipX, tipY);
      context.stroke();
      if (depth > 1) {
        branch(tipX, tipY, length * 0.7, angle - 0.47, depth - 1);
        branch(tipX, tipY, length * 0.73, angle + 0.44, depth - 1);
      } else {
        for (let leaf = 0; leaf < 24; leaf += 1) {
          context.fillStyle = leaf % 3 ? theme.foliage : evening ? '#596485' : '#8eab89';
          context.beginPath();
          context.ellipse(tipX + (random() - 0.5) * 110, tipY + (random() - 0.5) * 70, 14 + random() * 15, 8 + random() * 11, random() * Math.PI, 0, Math.PI * 2);
          context.fill();
        }
      }
    };
    branch(85, height + 65, 222, -1.29, 5);
    branch(width + 15, height + 10, 210, -1.94, 4);
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
  const evening = variant === 'evening';
  const room = new THREE.Group();
  room.name = 'warm-home-furnishings';
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
  const wood = material('#ead8bd', { map: woodMap });
  const paleWood = material('#f0dfc3', { map: woodMap });
  const darkWood = material('#726852');
  const sage = material('#a1b5a9', { map: fabricMap });
  const linen = material('#e6ded2', { map: fabricMap });
  const dustyRose = material('#c99d96', { map: fabricMap });
  const brass = material('#a99b71', { metalness: 0.55, roughness: 0.38 });
  const porcelain = material('#e8e9de', { roughness: 0.32 });
  const ink = material('#45595b');
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
  const sphere = (parent, scale, position, surface) => {
    const mesh = addMesh(parent, new THREE.SphereGeometry(1, 20, 14), surface, position);
    mesh.scale.set(...scale);
    return mesh;
  };
  const cylinder = (parent, top, bottom, height, position, surface) => addMesh(parent, new THREE.CylinderGeometry(top, bottom, height, 32), surface, position);
  const bar = (parent, start, end, radius, surface) => {
    const origin = new THREE.Vector3(...start);
    const target = new THREE.Vector3(...end);
    const direction = target.clone().sub(origin);
    const mesh = cylinder(parent, radius, radius, direction.length(), origin.clone().add(target).multiplyScalar(0.5).toArray(), surface);
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.normalize());
    return mesh;
  };

  const floorMap = texture(woodMap.clone());
  floorMap.repeat.set(2, 2);
  const floorMaterial = material('#edddc5', { map: floorMap });
  box(room, [8.4, 0.1, 7], [0, -0.055, 0.9], floorMaterial);
  box(room, [1.65, 3.6, 0.12], [-3.375, 1.8, -1.8], wall);
  box(room, [4.55, 3.6, 0.12], [1.925, 1.8, -1.8], wall);
  box(room, [2.2, 0.79, 0.12], [-1.45, 0.395, -1.8], wall);
  box(room, [2.2, 0.9, 0.12], [-1.45, 3.15, -1.8], wall);
  box(room, [0.12, 3.6, 5.4], [-4.14, 1.8, 0.84], wall);
  box(room, [8.2, 0.07, 0.06], [0, 0.055, -1.7], paleWood);

  const landscape = new THREE.MeshBasicMaterial({ map: texture(landscapeTexture(theme, evening)), toneMapped: false });
  resources.add(landscape);
  const windowView = addMesh(room, new THREE.PlaneGeometry(2.22, 1.94), landscape, [-1.45, 1.75, -1.89]);
  windowView.castShadow = false;
  windowView.receiveShadow = false;
  for (const positionX of [-2.56, -0.34]) box(room, [0.065, 1.99, 0.16], [positionX, 1.75, -1.72], paleWood);
  for (const positionY of [0.78, 2.72]) box(room, [2.29, 0.065, 0.16], [-1.45, positionY, -1.72], paleWood);
  box(room, [0.038, 1.9, 0.085], [-1.45, 1.75, -1.68], paleWood);
  box(room, [2.2, 0.032, 0.085], [-1.45, 1.68, -1.68], paleWood);
  box(room, [2.45, 0.085, 0.34], [-1.45, 0.74, -1.65], paleWood, 0.018);
  bar(room, [-2.82, 2.85, -1.47], [-0.08, 2.85, -1.47], 0.018, brass);
  const curtainMaterial = material('#f2eee3', { map: fabricMap, side: THREE.DoubleSide, roughness: 1 });
  for (const side of [-1, 1]) {
    const curtainGeometry = new THREE.PlaneGeometry(0.5, 2.04, 28, 24);
    const positions = curtainGeometry.attributes.position;
    for (let vertex = 0; vertex < positions.count; vertex += 1) {
      const positionX = positions.getX(vertex);
      const positionY = positions.getY(vertex);
      const vertical = (positionY + 1.02) / 2.04;
      const gather = Math.sin(vertical * Math.PI) * 0.13;
      positions.setXYZ(vertex, positionX * (1 - gather) + side * gather, positionY + Math.cos(positionX * 47) * 0.012 * (1 - vertical), Math.sin(positionX * 55) * 0.037 + Math.sin(vertical * Math.PI) * 0.032);
    }
    curtainGeometry.computeVertexNormals();
    addMesh(room, curtainGeometry, curtainMaterial, [-1.45 + side * 1.04, 1.76, -1.42]);
    for (let ring = 0; ring < 6; ring += 1) {
      addMesh(room, new THREE.TorusGeometry(0.026, 0.004, 6, 12), brass, [-1.45 + side * 1.04 - 0.21 + ring * 0.084, 2.81, -1.47], [0, Math.PI / 2, 0]);
    }
  }

  const rug = box(room, [2.5, 0.026, 1.84], [-0.18, 0.015, 0.24], material('#b9c7b8', { map: fabricMap }), 0.15);
  rug.rotation.y = -0.04;
  for (const side of [-1, 1]) {
    for (let stripe = 0; stripe < 3; stripe += 1) box(room, [2.18, 0.006, 0.018], [-0.18, 0.032, 0.24 + side * (0.71 + stripe * 0.036)], linen);
  }
  const sofa = new THREE.Group();
  sofa.position.set(-1.28, 0, -0.73);
  sofa.rotation.y = 0.055;
  room.add(sofa);
  for (const positionX of [-0.64, 0.64]) {
    for (const positionZ of [-0.24, 0.24]) cylinder(sofa, 0.035, 0.027, 0.2, [positionX, 0.11, positionZ], darkWood);
  }
  box(sofa, [1.56, 0.16, 0.7], [0, 0.25, 0], wood, 0.04);
  box(sofa, [1.48, 0.47, 0.19], [0, 0.57, -0.29], sage, 0.1);
  for (const positionX of [-0.38, 0.38]) box(sofa, [0.72, 0.18, 0.63], [positionX, 0.38, 0.045], sage, 0.07);
  for (const positionX of [-0.79, 0.79]) box(sofa, [0.12, 0.27, 0.68], [positionX, 0.46, 0.01], sage, 0.05);
  const pillow = box(sofa, [0.36, 0.35, 0.15], [-0.44, 0.61, -0.13], dustyRose, 0.095);
  pillow.rotation.set(-0.17, -0.13, -0.16);
  const secondPillow = box(sofa, [0.32, 0.32, 0.14], [0.46, 0.59, -0.13], linen, 0.085);
  secondPillow.rotation.set(-0.16, 0.12, 0.19);
  box(sofa, [0.32, 0.025, 0.51], [-0.1, 0.485, 0.02], linen, 0.02);
  box(sofa, [0.32, 0.19, 0.025], [-0.1, 0.4, 0.28], linen, 0.015);

  const shelf = new THREE.Group();
  shelf.position.set(1.54, 0, -1.38);
  room.add(shelf);
  box(shelf, [0.91, 1.66, 0.036], [0, 0.9, -0.16], material('#bcbcac'));
  for (const positionX of [-0.48, 0.48]) box(shelf, [0.045, 1.78, 0.36], [positionX, 0.94, 0], wood);
  for (const positionY of [0.15, 0.61, 1.07, 1.53, 1.83]) box(shelf, [1, 0.045, 0.4], [0, positionY, 0], paleWood, 0.01);
  const bookMaterials = ['#6f9494', '#be8f81', '#d4c4a4', '#667a8c', '#a8b59a', '#e4ddcf'].map((color) => material(color));
  const random = seededRandom(35);
  for (const shelfHeight of [0.635, 1.095]) {
    for (let book = 0; book < 7; book += 1) {
      const bookHeight = 0.22 + random() * 0.12;
      const bookX = -0.36 + book * 0.072;
      box(shelf, [0.052, bookHeight, 0.23], [bookX, shelfHeight + bookHeight / 2, 0.035], bookMaterials[book % bookMaterials.length], 0.006);
      box(shelf, [0.034, 0.011, 0.003], [bookX, shelfHeight + bookHeight * 0.76, 0.153], linen);
    }
  }
  box(shelf, [0.33, 0.23, 0.28], [-0.19, 0.287, 0], linen, 0.025);
  box(shelf, [0.075, 0.025, 0.008], [-0.19, 0.315, 0.147], darkWood, 0.007);
  for (let book = 0; book < 3; book += 1) box(shelf, [0.28 - book * 0.02, 0.032, 0.23], [0.24, 0.19 + book * 0.037, 0.025], bookMaterials[book + 1], 0.005);
  cylinder(shelf, 0.055, 0.072, 0.14, [0.26, 1.62, 0], porcelain);
  sphere(shelf, [0.07, 0.09, 0.07], [0.26, 1.68, 0], porcelain);

  const leafMaterials = ['#598773', '#769984', '#9ab094'].map((color) => material(color));
  const stemMaterial = material('#61775d');
  const soil = material('#5d6250');
  const plant = (parent, position, scale) => {
    const planter = new THREE.Group();
    planter.position.set(...position);
    planter.scale.setScalar(scale);
    parent.add(planter);
    cylinder(planter, 0.17, 0.12, 0.29, [0, 0.145, 0], porcelain);
    cylinder(planter, 0.175, 0.175, 0.025, [0, 0.285, 0], porcelain);
    cylinder(planter, 0.155, 0.155, 0.008, [0, 0.294, 0], soil);
    for (let stem = 0; stem < 7; stem += 1) {
      const angle = stem * 2.4;
      const height = 0.53 + (stem % 3) * 0.18;
      const reach = 0.2 + (stem % 2) * 0.06;
      const tip = new THREE.Vector3(Math.cos(angle) * reach, height, Math.sin(angle) * reach);
      const curve = new THREE.QuadraticBezierCurve3(new THREE.Vector3(0, 0.27, 0), new THREE.Vector3(tip.x * 0.2, height * 0.94, tip.z * 0.2), tip);
      addMesh(planter, new THREE.TubeGeometry(curve, 10, 0.008, 5, false), stemMaterial, [0, 0, 0]);
      const leaf = sphere(planter, [0.09, 0.21, 0.019], tip.toArray(), leafMaterials[stem % 3]);
      leaf.rotation.set(0.4 + (stem % 2) * 0.3, -angle, -0.55 + (stem % 3) * 0.5);
    }
  };
  plant(room, [2.27, 0, -0.69], 1.25);
  plant(room, [-2.16, 0.79, -1.61], 0.42);
  plant(shelf, [-0.24, 1.855, 0], 0.38);

  const desk = new THREE.Group();
  desk.position.set(variant === 'work' ? 0.17 : 1.27, 0, variant === 'work' ? 0.96 : 0.16);
  room.add(desk);
  const deskWidth = variant === 'work' ? 1.54 : 1.15;
  box(desk, [deskWidth, 0.065, 0.69], [0, 0.79, 0], paleWood, 0.045);
  for (const positionX of [-deskWidth / 2 + 0.1, deskWidth / 2 - 0.1]) {
    for (const positionZ of [-0.23, 0.23]) bar(desk, [positionX * 1.06, 0.025, positionZ * 1.12], [positionX, 0.76, positionZ], 0.029, wood);
  }
  box(desk, [deskWidth - 0.2, 0.11, 0.055], [0, 0.69, -0.245], wood, 0.01);
  box(desk, [0.29, 0.025, 0.23], [0.06, 0.836, 0.075], bookMaterials[0], 0.009);
  const notebook = box(desk, [0.265, 0.012, 0.215], [0.06, 0.854, 0.075], linen, 0.005);
  notebook.rotation.y = -0.09;
  bar(desk, [-0.035, 0.866, 0.13], [0.13, 0.866, 0.08], 0.004, brass);
  cylinder(desk, 0.047, 0.042, 0.092, [deskWidth / 2 - 0.22, 0.87, 0.15], porcelain);
  cylinder(desk, 0.039, 0.039, 0.003, [deskWidth / 2 - 0.22, 0.917, 0.15], material('#766753'));
  addMesh(desk, new THREE.TorusGeometry(0.029, 0.008, 8, 20), porcelain, [deskWidth / 2 - 0.167, 0.87, 0.15]);
  const lampX = deskWidth / 2 - 0.16;
  cylinder(desk, 0.093, 0.1, 0.027, [lampX, 0.837, -0.2], brass);
  bar(desk, [lampX, 0.85, -0.2], [lampX - 0.04, 1.18, -0.2], 0.012, brass);
  bar(desk, [lampX - 0.04, 1.18, -0.2], [lampX - 0.17, 1.27, -0.2], 0.011, brass);
  const shade = material('#d9dac7', { side: THREE.DoubleSide, emissive: evening ? '#ffca84' : '#000000', emissiveIntensity: evening ? 0.32 : 0 });
  addMesh(desk, new THREE.CylinderGeometry(0.075, 0.14, 0.13, 36, 1, true), shade, [lampX - 0.17, 1.245, -0.2]);
  sphere(desk, [0.044, 0.025, 0.044], [lampX - 0.17, 1.2, -0.2], material('#fff0c8', { emissive: '#ffdf99', emissiveIntensity: evening ? 1.5 : 0.15 }));
  const deskLight = new THREE.PointLight('#ffd6a2', evening ? 2.7 : 0.35, 3.5, 2);
  deskLight.position.set(desk.position.x + lampX - 0.17, 1.16, desk.position.z - 0.15);
  scene.add(deskLight);
  if (variant === 'work') {
    const laptop = new THREE.Group();
    laptop.position.set(-0.4, 0.837, -0.01);
    laptop.rotation.y = 0.12;
    desk.add(laptop);
    box(laptop, [0.38, 0.019, 0.255], [0, 0, 0], ink, 0.016);
    const lid = box(laptop, [0.38, 0.25, 0.016], [0, 0.123, -0.142], ink, 0.014);
    lid.rotation.x = -0.2;
    box(laptop, [0.1, 0.055, 0.004], [0, 0.15, -0.162], material('#819c9a'), 0.012);
    for (let row = 0; row < 4; row += 1) box(laptop, [0.29, 0.003, 0.016], [0, 0.012, -0.071 + row * 0.027], material('#91a6a2'));
  }

  const floorLamp = new THREE.Group();
  floorLamp.position.set(evening ? -1.96 : -2.31, 0, -0.67);
  room.add(floorLamp);
  cylinder(floorLamp, 0.16, 0.18, 0.032, [0, 0.02, 0], brass);
  bar(floorLamp, [0, 0.035, 0], [0, 1.44, 0], 0.018, darkWood);
  const paper = material('#f0e6cc', { side: THREE.DoubleSide, emissive: '#f9be74', emissiveIntensity: evening ? 0.6 : 0.05 });
  addMesh(floorLamp, new THREE.CylinderGeometry(0.18, 0.24, 0.38, 40, 1, true), paper, [0, 1.45, 0]);
  for (let rib = 0; rib < 9; rib += 1) {
    const radius = 0.24 - rib * 0.0075;
    addMesh(floorLamp, new THREE.TorusGeometry(radius, 0.003, 5, 40), linen, [0, 1.26 + rib * 0.0475, 0], [Math.PI / 2, 0, 0]);
  }
  const lampLight = new THREE.PointLight('#ffd5a0', evening ? 5 : 0.2, 5, 2);
  lampLight.position.set(evening ? -1.86 : -2.2, 1.43, -0.43);
  scene.add(lampLight);

  const artMap = texture(canvasTexture(256, 320, (context, width, height) => {
    context.fillStyle = '#e5e7dd';
    context.fillRect(0, 0, width, height);
    context.fillStyle = '#be9385';
    context.beginPath();
    context.ellipse(128, 238, 45, 42, 0, 0, Math.PI * 2);
    context.fill();
    context.fillRect(108, 184, 40, 50);
    context.strokeStyle = '#688474';
    context.lineWidth = 3;
    context.beginPath();
    context.moveTo(128, 188);
    context.bezierCurveTo(155, 140, 88, 123, 126, 53);
    context.stroke();
    context.fillStyle = '#86a28d';
    for (let leaf = 0; leaf < 6; leaf += 1) {
      context.beginPath();
      context.ellipse(120 + (leaf % 2 ? 15 : -15), 68 + leaf * 17, 22, 8, leaf % 2 ? -0.8 : 0.65, 0, Math.PI * 2);
      context.fill();
    }
  }));
  box(room, [0.5, 0.63, 0.045], [0.35, 1.97, -1.69], wood, 0.015);
  const art = material('#ffffff', { map: artMap });
  addMesh(room, new THREE.PlaneGeometry(0.446, 0.572), art, [0.35, 1.97, -1.663]);
  return room;
}

function applyPose(vrm, variant) {
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
  rotate('head', variant === 'work' ? 0.018 : -0.015, 0.065 * versionSign, 0.038, true);
  for (const side of ['left', 'right']) {
    for (const finger of ['Index', 'Middle', 'Ring', 'Little']) {
      for (const [joint, curl] of [['Proximal', 0.19], ['Intermediate', 0.25], ['Distal', 0.17]]) {
        rotate(`${side}${finger}${joint}`, 0, 0, (side === 'left' ? -curl : curl) * versionSign);
      }
    }
    rotate(`${side}ThumbProximal`, 0, side === 'left' ? 0.2 : -0.2, 0);
  }
  vrm.scene.rotation.y += variant === 'work' ? -0.12 : -0.16;
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
  vrm.scene.position.z += (variant === 'work' ? 0.1 : 0.22) - (bounds.min.z + bounds.max.z) / 2;
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
    if (object.shadow) object.shadow.dispose();
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

export async function mountRoom(container, { variant = 'afternoon', compact = false, transparent = false } = {}) {
  if (!(container instanceof HTMLElement)) throw new TypeError('mountRoom requires an HTML container.');
  activeRooms.get(container)?.dispose();
  const theme = themes[variant];
  const scene = new THREE.Scene();
  const resources = new Set();
  const camera = new THREE.OrthographicCamera(-2, 2, 1.5, -1.5, 0.05, 40);
  const canvas = document.createElement('canvas');
  canvas.className = 'warm-home-room-canvas';
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', `VRoid sample avatar in a warm ${variant} room`);
  Object.assign(canvas.style, { display: 'block', width: '100%', height: '100%', minWidth: '0', minHeight: '0' });
  container.append(canvas);
  container.dataset.roomReady = 'false';
  container.dataset.roomStatus = 'loading';
  delete container.dataset.roomError;
  container.setAttribute('aria-busy', 'true');
  const abortController = new AbortController();
  let renderer = null;
  let furnishings = null;
  let resizeObserver = null;
  let intersectionObserver = null;
  let errorElement = null;
  let loadTimer = 0;
  let frame = 0;
  let disposed = false;
  let ready = false;
  let visible = true;
  let loaded = false;
  let lastWidth = 0;
  let lastHeight = 0;
  let lastPixelRatio = 0;
  let failure = null;
  let resolveFirstFrame;
  let rejectFirstFrame;
  const firstFrame = new Promise((resolve, reject) => { resolveFirstFrame = resolve; rejectFirstFrame = reject; });
  firstFrame.catch(() => {});

  const release = () => {
    if (disposed) return;
    disposed = true;
    abortController.abort();
    clearTimeout(loadTimer);
    cancelAnimationFrame(frame);
    resizeObserver?.disconnect();
    intersectionObserver?.disconnect();
    document.removeEventListener('visibilitychange', requestRender);
    window.removeEventListener('resize', requestRender);
    canvas.removeEventListener('webglcontextlost', contextLost);
    disposeScene(scene, resources);
    renderer?.dispose();
    renderer?.forceContextLoss();
    canvas.remove();
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
    Object.assign(errorElement.style, { color: '#843e3e', background: '#fff5ed', padding: '16px', margin: '0', overflowWrap: 'anywhere', font: '14px/1.6 system-ui, sans-serif' });
    container.append(errorElement);
    rejectFirstFrame(error);
    return error;
  };
  const canRender = () => {
    if (disposed || !loaded || !visible || document.hidden || !container.isConnected) return false;
    if (!container.clientWidth || !container.clientHeight || !container.getClientRects().length) return false;
    if (container.checkVisibility && !container.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
    const bounds = container.getBoundingClientRect();
    return bounds.bottom > 0 && bounds.right > 0 && bounds.top < window.innerHeight && bounds.left < window.innerWidth;
  };
  const render = () => {
    frame = 0;
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
        const aspect = width / height;
        const viewHeight = Math.max(compact ? 2.02 : variant === 'work' ? 2.04 : variant === 'evening' ? 3.05 : 2.69, 1.35 / aspect);
        camera.left = -viewHeight * aspect / 2;
        camera.right = viewHeight * aspect / 2;
        camera.top = viewHeight / 2;
        camera.bottom = -viewHeight / 2;
        const targetHeight = compact ? 1.12 : variant === 'work' ? 1.19 : 1.04;
        camera.position.set(0.54, targetHeight + 0.88, 7.6);
        camera.lookAt(0.06, targetHeight, 0.02);
        camera.updateProjectionMatrix();
      }
      furnishings.visible = !transparent;
      scene.background = transparent ? null : new THREE.Color(theme.wall);
      renderer.setClearColor(theme.wall, transparent ? 0 : 1);
      renderer.shadowMap.needsUpdate = true;
      renderer.render(scene, camera);
      if (renderer.getContext().isContextLost()) throw new Error('The WebGL graphics context was lost.');
      if (renderer.info.render.calls === 0) throw new Error('The room did not produce a visible render.');
      if (!ready) {
        ready = true;
        container.dataset.roomReady = 'true';
        container.dataset.roomStatus = 'ready';
        container.setAttribute('aria-busy', 'false');
        resolveFirstFrame();
      }
    } catch (error) {
      showError(error);
    }
  };
  function requestRender() {
    if (!frame && canRender()) frame = requestAnimationFrame(render);
  }
  function contextLost(event) {
    event.preventDefault();
    showError(new Error('The WebGL graphics context was lost. Please remount the room.'));
  }
  const api = {
    dispose() {
      if (!disposed) release();
      errorElement?.remove();
      if (activeRooms.get(container) === api) {
        activeRooms.delete(container);
        container.dataset.roomReady = 'false';
        container.dataset.roomStatus = 'disposed';
        container.setAttribute('aria-busy', 'false');
      }
      if (!ready) rejectFirstFrame(new DOMException('Room mounting was disposed before its first frame.', 'AbortError'));
    },
    setVisible(value) {
      if (disposed) return;
      visible = Boolean(value);
      canvas.style.visibility = visible ? 'visible' : 'hidden';
      if (!visible) {
        cancelAnimationFrame(frame);
        frame = 0;
      } else requestRender();
    },
    setTransparent(value) {
      if (disposed || transparent === Boolean(value)) return;
      transparent = Boolean(value);
      requestRender();
    },
  };
  activeRooms.set(container, api);
  try {
    if (!Object.hasOwn(themes, variant)) throw new Error(`Unknown room variant: ${String(variant)}.`);
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'low-power', preserveDrawingBuffer: true });
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = theme.exposure;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.shadowMap.autoUpdate = false;
    renderer.debug.onShaderError = (context, program) => { throw new Error(`Room shader compilation failed: ${context.getProgramInfoLog(program) || 'GPU shader error'}`); };
    canvas.addEventListener('webglcontextlost', contextLost);
    scene.add(new THREE.HemisphereLight(variant === 'evening' ? '#c9c9e8' : '#fff5e6', '#9fa99b', theme.ambient));
    const sunlight = new THREE.DirectionalLight(variant === 'evening' ? '#bdcbed' : '#fff0d4', theme.sunlight);
    sunlight.position.set(-3.8, 4.9, 2.2);
    sunlight.target.position.set(0, 0.7, -0.2);
    sunlight.castShadow = true;
    sunlight.shadow.mapSize.set(2048, 2048);
    Object.assign(sunlight.shadow.camera, { left: -4, right: 4, top: 4, bottom: -4, near: 0.1, far: 15 });
    sunlight.shadow.normalBias = 0.03;
    sunlight.shadow.bias = -0.0002;
    sunlight.shadow.radius = 3;
    scene.add(sunlight, sunlight.target);
    const faceLight = new THREE.DirectionalLight(variant === 'evening' ? '#ffe1bf' : '#fff9f0', variant === 'evening' ? 0.68 : 0.6);
    faceLight.position.set(0.8, 2.1, 4);
    scene.add(faceLight);
    furnishings = createRoom(scene, theme, variant, resources);
    loadTimer = window.setTimeout(() => {
      showError(new Error(`Timed out while loading ${AVATAR_URL}. Check the local asset route.`));
    }, 60000);
    const response = await fetch(AVATAR_URL, { signal: abortController.signal });
    if (!response.ok) throw new Error(`Cannot load ${AVATAR_URL}: HTTP ${response.status}.`);
    const source = await response.arrayBuffer();
    if (disposed) throw new DOMException('Room mounting was cancelled.', 'AbortError');
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const parsing = loader.parseAsync(source, new URL('/assets/', window.location.href).href).then((result) => {
      if (disposed) {
        disposeScene(result.scene, new Set());
        throw new DOMException('Room mounting was cancelled.', 'AbortError');
      }
      return result;
    });
    const gltf = await Promise.race([parsing, firstFrame]);
    scene.add(gltf.scene);
    const vrm = gltf.userData.vrm;
    if (!vrm) throw new Error('The asset loaded, but the VRM plugin returned no avatar.');
    VRMUtils.rotateVRM0(vrm);
    applyPose(vrm, variant);
    clearTimeout(loadTimer);
    loaded = true;
    resizeObserver = new ResizeObserver(() => {
      if (lastWidth !== container.clientWidth || lastHeight !== container.clientHeight || !ready) requestRender();
    });
    resizeObserver.observe(container);
    if (typeof IntersectionObserver !== 'undefined') {
      intersectionObserver = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) requestRender();
      });
      intersectionObserver.observe(container);
    }
    document.addEventListener('visibilitychange', requestRender);
    window.addEventListener('resize', requestRender);
    requestRender();
    await firstFrame;
    return api;
  } catch (error) {
    throw showError(error);
  }
}
