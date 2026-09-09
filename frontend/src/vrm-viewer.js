import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";
import {
  VRMAnimationLoaderPlugin,
  createVRMAnimationClip,
} from "@pixiv/three-vrm-animation";
import { createHomeRoom, fitHomeRoomCamera, HOME_ROOM_COLOR } from "./home-room.js";

const activeViewers = new WeakMap();

function fail(container, message) {
  container.dataset.vrmStatus = "error";
  container.dataset.vrmError = message;
  container.setAttribute("aria-busy", "false");
  const status = container.querySelector(".vrm-renderer-status");
  if (status) {
    status.hidden = false;
    status.setAttribute("role", "alert");
    status.textContent = message;
  }
  const canvas = container.querySelector("canvas");
  if (canvas) canvas.hidden = true;
  throw new Error(message);
}

function clamp(value, min, max, fallback) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? Math.min(max, Math.max(min, numeric)) : fallback;
}

function damp(current, target, speed, delta) {
  return current + (target - current) * (1 - Math.exp(-Math.max(0, speed) * Math.max(0, delta)));
}

function fitCamera(camera, box) {
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const height = Math.max(size.y, 0.001);
  const verticalFov = THREE.MathUtils.degToRad(camera.fov);
  const distanceForHeight = (height * 0.5) / Math.tan(verticalFov * 0.5) * 1.05;
  const distanceForWidth = size.x * 0.55 / (Math.tan(verticalFov * 0.5) * camera.aspect);
  const distance = Math.max(distanceForHeight, distanceForWidth, size.z * 2.2) + size.z / 2;
  camera.position.set(center.x, center.y + height * 0.02, center.z + distance);
  camera.near = Math.max(0.0001, height / 100);
  camera.far = Math.max(100, distance * 8);
  camera.lookAt(center.x, center.y + height * 0.04, center.z);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld(true);
}

function clampRotationSpeed(value) {
  return clamp(value, 0.05, 0.4, 0.12);
}

/**
 * Runtime-only T-pose to relaxed standing pose adapter.
 *
 * The bone choices follow the behavior of Super Agent Party's VRM helper,
 * while the implementation and lifecycle belong to Sumika. No model bytes
 * or imported pose files are changed.
 */
export class NaturalPoseAdapter {
  constructor(vrm, options = {}) {
    this.vrm = vrm;
    this.enabled = options.enabled !== false;
    this.originalRotations = new Map();
    this.appliedBoneCount = 0;
    this.status = "disabled";
    this.versionSign = vrm?.meta?.metaVersion === "1" ? 1 : -1;
  }

  bone(name) {
    return this.vrm?.humanoid?.getNormalizedBoneNode?.(name) || null;
  }

  remember(name, node) {
    if (!this.originalRotations.has(name)) this.originalRotations.set(name, node.rotation.clone());
  }

  setRotation(name, values) {
    const node = this.bone(name);
    if (!node) return false;
    this.remember(name, node);
    if (values.x !== undefined) node.rotation.x = values.x;
    if (values.y !== undefined) node.rotation.y = values.y;
    if (values.z !== undefined) node.rotation.z = values.z;
    this.appliedBoneCount += 1;
    return true;
  }

  apply() {
    if (!this.enabled) {
      this.status = "disabled";
      return this.status;
    }
    if (!this.vrm?.humanoid) {
      this.status = "static-fallback";
      return this.status;
    }

    const v = this.versionSign;
    this.appliedBoneCount = 0;
    this.setRotation("leftUpperArm", { z: -0.45 * Math.PI * v, x: 0.05 });
    this.setRotation("rightUpperArm", { z: 0.45 * Math.PI * v, x: 0.05 });
    this.setRotation("leftHand", { z: 0.1 * v, x: 0.05 });
    this.setRotation("rightHand", { z: -0.1 * v, x: 0.05 });

    const fingerBones = [
      "leftThumbProximal", "leftThumbIntermediate", "leftThumbDistal",
      "leftIndexProximal", "leftIndexIntermediate", "leftIndexDistal",
      "leftMiddleProximal", "leftMiddleIntermediate", "leftMiddleDistal",
      "leftRingProximal", "leftRingIntermediate", "leftRingDistal",
      "leftLittleProximal", "leftLittleIntermediate", "leftLittleDistal",
      "rightThumbProximal", "rightThumbIntermediate", "rightThumbDistal",
      "rightIndexProximal", "rightIndexIntermediate", "rightIndexDistal",
      "rightMiddleProximal", "rightMiddleIntermediate", "rightMiddleDistal",
      "rightRingProximal", "rightRingIntermediate", "rightRingDistal",
      "rightLittleProximal", "rightLittleIntermediate", "rightLittleDistal",
    ];
    for (const name of fingerBones) {
      const left = name.startsWith("left");
      if (name.includes("Thumb")) {
        this.setRotation(name, { y: left ? 0.35 : -0.35 });
      } else if (name.includes("Proximal")) {
        this.setRotation(name, { z: (left ? -0.35 : 0.35) * v });
      } else if (name.includes("Intermediate")) {
        this.setRotation(name, { z: (left ? -0.45 : 0.45) * v });
      } else if (name.includes("Distal")) {
        this.setRotation(name, { z: (left ? -0.3 : 0.3) * v });
      }
    }
    this.status = this.appliedBoneCount ? "active" : "static-fallback";
    return this.status;
  }

  restore() {
    for (const [name, rotation] of this.originalRotations) {
      const node = this.bone(name);
      if (node) node.rotation.copy(rotation);
    }
  }
}

class OneEuroFilter {
  constructor(minCutoff, beta, derivativeCutoff) {
    this.minCutoff = minCutoff;
    this.beta = beta;
    this.derivativeCutoff = derivativeCutoff;
    this.previous = null;
    this.previousDerivative = 0;
    this.previousTime = null;
  }

  alpha(delta, cutoff) {
    const ratio = 2 * Math.PI * cutoff * delta;
    return ratio / (ratio + 1);
  }

  filter(value, time) {
    if (this.previousTime === null) {
      this.previous = value;
      this.previousTime = time;
      return value;
    }
    const delta = time - this.previousTime;
    if (delta <= 0) return this.previous;
    const derivativeAlpha = this.alpha(delta, this.derivativeCutoff);
    const derivative = (value - this.previous) / delta;
    const filteredDerivative = derivativeAlpha * derivative + (1 - derivativeAlpha) * this.previousDerivative;
    const cutoff = this.minCutoff + this.beta * Math.abs(filteredDerivative);
    const filteredAlpha = this.alpha(delta, cutoff);
    const filtered = filteredAlpha * value + (1 - filteredAlpha) * this.previous;
    this.previous = filtered;
    this.previousDerivative = filteredDerivative;
    this.previousTime = time;
    return filtered;
  }

  reset() {
    this.previous = null;
    this.previousDerivative = 0;
    this.previousTime = null;
  }
}

/**
 * Pointer follow is split into an eye target and a slower additive head pass.
 * The split mirrors N.E.K.O's cursor-follow behavior without copying its code.
 */
export class AvatarCursorFollowController {
  constructor(vrm, scene, camera, container, options = {}) {
    this.vrm = vrm;
    this.scene = scene;
    this.camera = camera;
    this.container = container;
    // Listen on the complete Avatar surface so the gaze remains responsive
    // when the pointer is over the stage around the model, matching desktop-pet
    // behavior while keeping the renderer canvas itself non-interactive.
    this.eventTarget = container.closest(".avatar-stage, .desktop-overlay-avatar") || container.parentElement || container;
    this.lookAtStrength = clamp(options.lookAtStrength, 0, 1, 1);
    this.headFollowStrength = clamp(options.headFollowStrength, 0, 1, 0.35);
    this.activityWeight = clamp(options.activityWeight, 0, 1, 1);
    this.eyeEnabled = options.lookAtEnabled !== false && Boolean(vrm?.lookAt) && this.lookAtStrength > 0;
    this.headEnabled = options.headFollowEnabled !== false && this.headFollowStrength > 0;
    this.head = vrm?.humanoid?.getNormalizedBoneNode?.("head") || null;
    this.neck = vrm?.humanoid?.getNormalizedBoneNode?.("neck") || null;
    this.headEnabled = this.headEnabled && Boolean(this.head || this.neck);
    this.pointer = new THREE.Vector2();
    this.targetPointer = new THREE.Vector2();
    this.headYaw = 0;
    this.headPitch = 0;
    this.targetHeadYaw = 0;
    this.targetHeadPitch = 0;
    this.headBase = this.head?.quaternion.clone() || null;
    this.neckBase = this.neck?.quaternion.clone() || null;
    this.pointerActive = false;
    this.elapsed = 0;
    this.lookAtTarget = null;
    this.previousLookAtTarget = null;
    this.previousLookAtAutoUpdate = null;
    this.lookAtTargetConfigured = false;
    this.targetPosition = new THREE.Vector3();
    this.worldCameraPosition = new THREE.Vector3();
    this.unprojectedPointer = new THREE.Vector3();
    this.pointerDirection = new THREE.Vector3();
    this.headEuler = new THREE.Euler(0, 0, 0, "YXZ");
    this.headQuaternion = new THREE.Quaternion();
    this.eyeFilterX = new OneEuroFilter(1.5, 0.5, 1);
    this.eyeFilterY = new OneEuroFilter(1.5, 0.5, 1);
    this.headFilterYaw = new OneEuroFilter(0.8, 0.3, 1);
    this.headFilterPitch = new OneEuroFilter(0.8, 0.3, 1);

    this.onPointerMove = (event) => {
      const rect = this.eventTarget.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      this.targetPointer.set(
        clamp(((event.clientX - rect.left) / rect.width) * 2 - 1, -1, 1, 0),
        clamp(1 - ((event.clientY - rect.top) / rect.height) * 2, -1, 1, 0),
      );
      this.pointerActive = true;
    };
    this.onPointerLeave = () => {
      this.targetPointer.set(0, 0);
      this.pointerActive = false;
    };
    this.eventTarget.addEventListener("pointermove", this.onPointerMove, { passive: true });
    this.eventTarget.addEventListener("mousemove", this.onPointerMove, { passive: true });
    this.eventTarget.addEventListener("pointerleave", this.onPointerLeave, { passive: true });
    this.eventTarget.addEventListener("pointercancel", this.onPointerLeave, { passive: true });

    if (this.eyeEnabled) {
      this.lookAtTarget = new THREE.Object3D();
      this.lookAtTarget.name = "SumikaCursorFollowEyeTarget";
      scene.add(this.lookAtTarget);
      this.previousLookAtTarget = vrm.lookAt.target || null;
      this.previousLookAtAutoUpdate = vrm.lookAt.autoUpdate;
      try {
        vrm.lookAt.target = this.lookAtTarget;
        vrm.lookAt.autoUpdate = true;
        this.lookAtTargetConfigured = true;
      } catch {
        try {
          vrm.lookAt.target = this.previousLookAtTarget;
          if (this.previousLookAtAutoUpdate !== null) vrm.lookAt.autoUpdate = this.previousLookAtAutoUpdate;
        } catch {
          // A partially writable LookAt implementation can reject restoration too.
        }
        this.eyeEnabled = false;
        scene.remove(this.lookAtTarget);
        this.lookAtTarget = null;
      }
    }

    this.eyeStatus = this.eyeEnabled ? "active" : options.lookAtEnabled === false ? "disabled" : "static-fallback";
    this.headStatus = this.headEnabled ? "active" : options.headFollowEnabled === false ? "disabled" : "static-fallback";
    this.status = this.eyeEnabled || this.headEnabled ? "active" : "static-fallback";
  }

  setActivityWeight(value) {
    this.activityWeight = clamp(value, 0, 1, 1);
  }

  update(delta) {
    if (!Number.isFinite(delta) || delta <= 0) return;
    this.pointer.x = damp(this.pointer.x, this.targetPointer.x, 12, delta);
    this.pointer.y = damp(this.pointer.y, this.targetPointer.y, 12, delta);
    this.elapsed += delta;
    const now = this.elapsed;
    const eyeX = this.eyeFilterX.filter(this.pointer.x * this.lookAtStrength * this.activityWeight, now);
    const eyeY = this.eyeFilterY.filter(this.pointer.y * this.lookAtStrength * this.activityWeight, now);

    if (this.lookAtTarget && this.eyeEnabled) {
      this.camera.updateMatrixWorld();
      this.camera.getWorldPosition(this.worldCameraPosition);
      this.unprojectedPointer.set(eyeX, eyeY, 0.55).unproject(this.camera);
      this.pointerDirection.subVectors(this.unprojectedPointer, this.worldCameraPosition).normalize();
      this.targetPosition.copy(this.worldCameraPosition).addScaledVector(this.pointerDirection, 2.2);
      this.lookAtTarget.position.lerp(this.targetPosition, 1 - Math.exp(-14 * delta));
    }

    const rawYaw = this.pointer.x * THREE.MathUtils.degToRad(54) * this.headFollowStrength * this.activityWeight;
    const rawPitch = this.pointer.y * THREE.MathUtils.degToRad(34) * this.headFollowStrength * this.activityWeight;
    this.targetHeadYaw = this.headFilterYaw.filter(rawYaw, now);
    this.targetHeadPitch = this.headFilterPitch.filter(rawPitch, now);
    this.headYaw = damp(this.headYaw, this.headEnabled ? this.targetHeadYaw : 0, 3, delta);
    this.headPitch = damp(this.headPitch, this.headEnabled ? this.targetHeadPitch : 0, 3, delta);
  }

  applyAfterVrmUpdate() {
    if (this.neck && this.neckBase) this.neck.quaternion.copy(this.neckBase);
    if (this.head && this.headBase) this.head.quaternion.copy(this.headBase);
    if (!this.headEnabled) return;
    const neckWeight = this.neck ? 0.6 : 0;
    const headWeight = this.head ? (this.neck ? 0.4 : 1) : 0;
    if (this.neck) {
      this.headEuler.set(this.headPitch * neckWeight, this.headYaw * neckWeight, 0, "YXZ");
      this.headQuaternion.setFromEuler(this.headEuler);
      this.neck.quaternion.multiply(this.headQuaternion);
    }
    if (this.head) {
      this.headEuler.set(this.headPitch * headWeight, this.headYaw * headWeight, 0, "YXZ");
      this.headQuaternion.setFromEuler(this.headEuler);
      this.head.quaternion.multiply(this.headQuaternion);
    }
    this.container.dataset.vrmHeadYaw = this.headYaw.toFixed(3);
    this.container.dataset.vrmHeadPitch = this.headPitch.toFixed(3);
    this.container.dataset.vrmPointerState = this.pointerActive ? "active" : "centered";
    this.container.dataset.vrmFollowWeight = this.activityWeight.toFixed(2);
  }

  destroy() {
    this.eventTarget.removeEventListener("pointermove", this.onPointerMove);
    this.eventTarget.removeEventListener("mousemove", this.onPointerMove);
    this.eventTarget.removeEventListener("pointerleave", this.onPointerLeave);
    this.eventTarget.removeEventListener("pointercancel", this.onPointerLeave);
    if (this.lookAtTarget) this.scene.remove(this.lookAtTarget);
    if (this.vrm.lookAt && this.lookAtTargetConfigured) {
      try {
        this.vrm.lookAt.target = this.previousLookAtTarget;
        if (this.previousLookAtAutoUpdate !== null) this.vrm.lookAt.autoUpdate = this.previousLookAtAutoUpdate;
      } catch {
        // A model can expose a read-only LookAt implementation.
      }
    }
    if (this.neck && this.neckBase) this.neck.quaternion.copy(this.neckBase);
    if (this.head && this.headBase) this.head.quaternion.copy(this.headBase);
  }
}

/** Optional VRMA boundary. No animation asset is bundled by Sumika. */
export function validateVrmaManifest(manifest) {
  if (!manifest || manifest.kind !== "vrma") throw new Error("VRMA manifest kind must be vrma");
  if (typeof manifest.path !== "string" || !manifest.path.trim()) throw new Error("VRMA manifest path is required");
  if (!manifest.license || typeof manifest.license.spdx !== "string" || !manifest.license.spdx.trim()) {
    throw new Error("VRMA manifest license.spdx is required before loading an animation");
  }
  return manifest;
}

export class VrmaAdapter {
  constructor(vrm) {
    this.vrm = vrm;
    this.mixer = null;
    this.action = null;
    this.previousAutoUpdateHumanBones = null;
    this.disposed = false;
  }

  async load(source, options = {}) {
    if (this.disposed) throw new Error("VRMA adapter is disposed");
    if (typeof source !== "string" || !source.trim()) throw new Error("VRMA source is required");
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMAnimationLoaderPlugin(parser));
    const gltf = await loader.loadAsync(source);
    if (this.disposed) {
      VRMUtils.deepDispose(gltf.scene);
      throw new Error("VRMA adapter is disposed");
    }
    const animation = gltf.userData?.vrmAnimations?.[0];
    if (!animation) throw new Error("VRMA file contains no VRM animation");
    const clip = createVRMAnimationClip(animation, this.vrm);
    this.mixer = this.mixer || new THREE.AnimationMixer(this.vrm.scene);
    this.action?.stop();
    this.action = this.mixer.clipAction(clip);
    this.action.reset();
    this.action.setLoop(options.loop === false ? THREE.LoopOnce : THREE.LoopRepeat);
    this.action.clampWhenFinished = options.loop === false;
    this.action.play();
    if (this.vrm.humanoid) {
      this.previousAutoUpdateHumanBones = this.vrm.humanoid.autoUpdateHumanBones;
      // VRMA tracks target the normalized rig. Keep the loader's bridge to
      // the model skeleton enabled so VRM 1 animations are visible as well.
      this.vrm.humanoid.autoUpdateHumanBones = true;
    }
    return { duration: clip.duration, name: clip.name, source };
  }

  async loadManifest(manifest, options = {}) {
    validateVrmaManifest(manifest);
    return this.load(manifest.path, options);
  }

  update(delta) {
    if (!this.disposed) this.mixer?.update(delta);
  }

  stop() {
    this.action?.stop();
    this.action = null;
    if (this.vrm.humanoid && this.previousAutoUpdateHumanBones !== null) {
      this.vrm.humanoid.autoUpdateHumanBones = this.previousAutoUpdateHumanBones;
      this.previousAutoUpdateHumanBones = null;
    }
  }

  dispose() {
    this.disposed = true;
    this.stop();
    if (this.mixer) {
      const root = this.mixer.getRoot();
      this.mixer.stopAllAction();
      if (root) this.mixer.uncacheRoot(root);
    }
    this.mixer = null;
  }
}

/** Small procedural animation layer for models without embedded clips. */
export class AvatarMotionController {
  constructor(vrm, options = {}) {
    this.vrm = vrm;
    this.idleMotion = options.idleMotion !== false;
    this.autoRotate = options.autoRotate === true;
    this.rotationSpeed = clampRotationSpeed(options.rotationSpeed);
    this.elapsed = 0;
    this.nextBlinkAt = 3.4;
    this.blinkStartedAt = -1;
    this.blinkNames = [];
    this.bones = [];
    this.addBone("upperChest", 0.012, 0.008, 0.15);
    this.addBone("chest", 0.018, 0.01, 0.25);
    this.addBone("spine", 0.01, 0.006, 0.4);
    this.addBone("hips", 0.006, 0.012, 0.55);
    const expressionManager = vrm.expressionManager;
    const expressionMap = expressionManager?.expressionMap || {};
    this.blinkNames = ["blink", "blinkLeft", "blinkRight"].filter((name) => Boolean(expressionMap[name]));
    this.hasIdleMotion = Boolean(this.idleMotion && (this.bones.length || this.blinkNames.length));
  }

  addBone(name, pitchAmount, rollAmount, phase) {
    const node = this.vrm.humanoid?.getNormalizedBoneNode?.(name);
    if (!node) return;
    this.bones.push({ node, base: node.rotation.clone(), pitchAmount, rollAmount, phase });
  }

  update(delta) {
    if (!Number.isFinite(delta) || delta <= 0) return;
    this.elapsed += delta;
    if (this.autoRotate) this.vrm.scene.rotation.y += this.rotationSpeed * delta;
    if (!this.hasIdleMotion) return;
    const breathing = Math.sin(this.elapsed * 1.55) * 0.5 + Math.sin(this.elapsed * 0.78) * 0.2;
    for (const bone of this.bones) {
      bone.node.rotation.copy(bone.base);
      bone.node.rotation.x += breathing * bone.pitchAmount;
      bone.node.rotation.z += Math.sin(this.elapsed * 1.2 + bone.phase) * bone.rollAmount;
    }
    this.updateBlink();
  }

  updateBlink() {
    if (!this.blinkNames.length) return;
    if (this.elapsed >= this.nextBlinkAt && this.blinkStartedAt < 0) this.blinkStartedAt = this.elapsed;
    let weight = 0;
    if (this.blinkStartedAt >= 0) {
      const progress = this.elapsed - this.blinkStartedAt;
      if (progress < 0.18) {
        weight = Math.sin((progress / 0.18) * Math.PI);
      } else {
        this.blinkStartedAt = -1;
        this.nextBlinkAt = this.elapsed + 4.2;
      }
    }
    try {
      for (const name of this.blinkNames) this.vrm.expressionManager.setValue(name, weight);
    } catch {
      this.blinkNames = [];
    }
  }
}

export class AvatarRenderLoop {
  constructor(update, scheduler = globalThis) {
    this.update = update;
    this.scheduler = scheduler;
    this.active = false;
    this.disposed = false;
    this.frame = null;
    this.previousTime = null;
    this.tick = (timestamp) => {
      this.frame = null;
      if (!this.active || this.disposed) return;
      const delta = this.previousTime === null ? 0 : Math.min(0.05, Math.max(0, (timestamp - this.previousTime) / 1000));
      this.previousTime = timestamp;
      try {
        this.update(delta);
      } finally {
        if (this.active && !this.disposed) this.frame = this.scheduler.requestAnimationFrame(this.tick);
      }
    };
  }

  setActive(value) {
    if (this.disposed || this.active === Boolean(value)) return;
    this.active = Boolean(value);
    this.previousTime = null;
    if (this.active) {
      this.frame = this.scheduler.requestAnimationFrame(this.tick);
    } else if (this.frame !== null) {
      this.scheduler.cancelAnimationFrame(this.frame);
      this.frame = null;
    }
  }

  destroy() {
    this.setActive(false);
    this.disposed = true;
  }
}

export function projectVrmFaceBounds(vrm, camera, rect, modelBounds) {
  const head = vrm?.humanoid?.getRawBoneNode?.("head") || vrm?.humanoid?.getNormalizedBoneNode?.("head");
  if (!head || !rect.width || !rect.height) return null;
  const height = modelBounds.getSize(new THREE.Vector3()).y;
  const center = head.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0, height * 0.032, 0));
  camera.updateMatrixWorld(true);
  const viewCenter = center.clone().applyMatrix4(camera.matrixWorldInverse);
  if (viewCenter.z >= -camera.near || viewCenter.z <= -camera.far) return null;
  const rightAxis = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0).multiplyScalar(height * 0.075);
  const upAxis = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1).multiplyScalar(height * 0.085);
  const points = [];
  for (const horizontal of [-1, 1]) {
    for (const vertical of [-1, 1]) points.push(center.clone().addScaledVector(rightAxis, horizontal).addScaledVector(upAxis, vertical).project(camera));
  }
  const left = rect.left + (Math.min(...points.map((point) => point.x)) + 1) * rect.width / 2;
  const right = rect.left + (Math.max(...points.map((point) => point.x)) + 1) * rect.width / 2;
  const top = rect.top + (1 - Math.max(...points.map((point) => point.y))) * rect.height / 2;
  const bottom = rect.top + (1 - Math.min(...points.map((point) => point.y))) * rect.height / 2;
  return { top, right, bottom, left, width: right - left, height: bottom - top };
}

export async function mountVrmViewer(container, source, options = {}) {
  if (!(container instanceof HTMLElement)) throw new TypeError("VRM container is required");
  if (typeof source !== "string" || !source) throw new TypeError("VRM source is required");

  activeViewers.get(container)?.();
  container.dataset.vrmStatus = "loading";
  container.dataset.vrmRenderStatus = "loading";
  delete container.dataset.vrmError;
  container.setAttribute("aria-busy", "true");
  const canvas = document.createElement("canvas");
  canvas.className = "vrm-renderer-canvas";
  canvas.setAttribute("aria-label", "VRM Avatar 实时渲染");
  canvas.hidden = true;
  const status = document.createElement("p");
  status.className = "vrm-renderer-status";
  status.setAttribute("role", "status");
  status.textContent = "正在加载 VRM 模型…";
  container.replaceChildren(status, canvas);

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: "high-performance" });
  } catch (error) {
    return fail(container, `WebGL 不可用：${error?.message || "unknown error"}`);
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(28, 1, 0.01, 100);
  const ambientLight = new THREE.HemisphereLight(0xdffbf4, 0x1b2229, 1.8);
  scene.add(ambientLight);
  const keyLight = new THREE.DirectionalLight(0xffffff, 2.4);
  keyLight.position.set(1.5, 2.5, 3.5);
  scene.add(keyLight);
  const fillLight = new THREE.DirectionalLight(0x9bded5, 0.8);
  fillLight.position.set(-2, 1, 1);
  scene.add(fillLight);

  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));
  let vrm = null;
  let loadedScene = null;
  let modelBounds = null;
  let room = null;
  let naturalPose = null;
  let cursorFollow = null;
  let vrma = null;
  let disposed = false;
  let visible = true;
  let roomVisible = options.roomEnabled === true;
  let pageSuspended = false;
  let minimized = false;
  let intersecting = true;
  let resizeObserver = null;
  let intersectionObserver = null;
  let loop = null;
  let nativeCheck = 0;
  const nativeUnlisteners = [];

  const canRender = () => !disposed && visible && !document.hidden && !pageSuspended && !minimized && intersecting
    && container.isConnected && container.contains(canvas) && container.clientWidth > 0 && container.clientHeight > 0
    && (!canvas.checkVisibility || canvas.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }));

  const syncVisibility = () => {
    if (disposed) return;
    const active = canRender();
    loop?.setActive(active);
    container.dataset.vrmRenderStatus = active ? "running" : "paused";
  };

  const updateRoom = () => {
    if (roomVisible && !room) {
      room = createHomeRoom(modelBounds);
      scene.add(room.root);
    }
    if (room) room.root.visible = roomVisible;
    scene.background = roomVisible ? new THREE.Color(HOME_ROOM_COLOR) : null;
    renderer.setClearColor(roomVisible ? HOME_ROOM_COLOR : 0x000000, roomVisible ? 1 : 0);
    ambientLight.color.setHex(roomVisible ? 0xffffff : 0xdffbf4);
    ambientLight.groundColor.setHex(roomVisible ? 0xb8b0a0 : 0x1b2229);
    keyLight.color.setHex(roomVisible ? 0xfff5e7 : 0xffffff);
    keyLight.intensity = roomVisible ? 1.8 : 2.4;
    fillLight.color.setHex(roomVisible ? 0xffffff : 0x9bded5);
    container.dataset.vrmRoomVisible = String(roomVisible);
  };

  const resize = () => {
    if (disposed) return;
    const width = container.clientWidth;
    const height = container.clientHeight;
    if (!width || !height) {
      syncVisibility();
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    if (modelBounds) {
      if (roomVisible) fitHomeRoomCamera(camera, modelBounds, width, height);
      else fitCamera(camera, modelBounds);
    }
    syncVisibility();
  };

  const suspend = () => { pageSuspended = true; syncVisibility(); };
  const resume = () => { pageSuspended = false; resize(); };
  const release = () => {
    loop?.destroy();
    resizeObserver?.disconnect();
    intersectionObserver?.disconnect();
    document.removeEventListener("visibilitychange", resize);
    document.removeEventListener("freeze", suspend);
    document.removeEventListener("resume", resume);
    window.removeEventListener("pagehide", suspend);
    window.removeEventListener("pageshow", resume);
    window.removeEventListener("resize", resize);
    canvas.removeEventListener("webglcontextlost", contextLost);
    for (const unlisten of nativeUnlisteners.splice(0)) unlisten();
    cursorFollow?.destroy();
    vrma?.dispose();
    naturalPose?.restore();
    room?.dispose();
    if (loadedScene) {
      loadedScene.removeFromParent();
      VRMUtils.deepDispose(loadedScene);
      loadedScene = null;
    }
    renderer.dispose();
  };
  const destroy = () => {
    if (disposed) return;
    disposed = true;
    release();
    if (activeViewers.get(container) === destroy) {
      activeViewers.delete(container);
      container.replaceChildren();
      container.dataset.vrmStatus = "disposed";
      container.dataset.vrmRenderStatus = "disposed";
      container.setAttribute("aria-busy", "false");
    }
  };
  const contextLost = (event) => {
    event.preventDefault();
    if (disposed) return;
    disposed = true;
    release();
    activeViewers.delete(container);
    try { fail(container, "WebGL 上下文丢失，请重新加载模型"); } catch { }
    container.dataset.vrmRenderStatus = "error";
  };
  const api = {
    destroy,
    setVisible(value) {
      if (disposed) return;
      visible = Boolean(value);
      canvas.hidden = !visible;
      resize();
    },
    setRoomVisible(value) {
      if (disposed || roomVisible === Boolean(value)) return;
      roomVisible = Boolean(value);
      updateRoom();
      resize();
    },
    faceBounds() {
      if (!canRender() || !vrm || !modelBounds) return null;
      return projectVrmFaceBounds(vrm, camera, canvas.getBoundingClientRect(), modelBounds);
    },
  };
  activeViewers.set(container, destroy);

  const watchNativeWindow = async () => {
    if (!window.__TAURI_INTERNALS__) return;
    try {
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      if (disposed) return;
      const nativeWindow = getCurrentWindow();
      const checkMinimized = async () => {
        const generation = ++nativeCheck;
        try {
          const value = await nativeWindow.isMinimized();
          if (disposed || generation !== nativeCheck) return;
          minimized = value;
          container.dataset.vrmWindowVisibility = minimized ? "minimized" : "visible";
          resize();
        } catch {
          if (!disposed) container.dataset.vrmWindowVisibility = "page-visibility-fallback";
        }
      };
      for (const subscribe of [() => nativeWindow.onResized(checkMinimized), () => nativeWindow.onFocusChanged(checkMinimized)]) {
        const unlisten = await subscribe();
        if (disposed) { unlisten(); return; }
        nativeUnlisteners.push(unlisten);
      }
      await checkMinimized();
    } catch {
      if (!disposed) container.dataset.vrmWindowVisibility = "page-visibility-fallback";
    }
  };

  try {
    const gltf = await loader.loadAsync(source);
    if (disposed) {
      VRMUtils.deepDispose(gltf.scene);
      throw new DOMException("VRM mounting was cancelled", "AbortError");
    }
    loadedScene = gltf.scene;
    vrm = gltf.userData.vrm;
    if (!vrm) throw new Error("VRM loader did not return a model");
    VRMUtils.rotateVRM0(vrm);
    VRMUtils.removeUnnecessaryVertices(vrm.scene);
    VRMUtils.combineSkeletons(vrm.scene);
    scene.add(vrm.scene);
    naturalPose = new NaturalPoseAdapter(vrm, { enabled: options.naturalPose !== false });
    naturalPose.apply();
    vrm.update(0);
    vrm.scene.updateMatrixWorld(true);
    modelBounds = new THREE.Box3().setFromObject(vrm.scene, true);
    updateRoom();
    cursorFollow = new AvatarCursorFollowController(vrm, scene, camera, container, options);
    if (options.vrmaSource) {
      vrma = new VrmaAdapter(vrm);
      await vrma.load(options.vrmaSource, { loop: options.vrmaLoop !== false });
      if (disposed) throw new DOMException("VRM mounting was cancelled", "AbortError");
      container.dataset.vrmVrmaStatus = "active";
    } else {
      container.dataset.vrmVrmaStatus = "reserved";
    }
    const motion = new AvatarMotionController(vrm, options);
    container.dataset.vrmIdleMotion = String(motion.idleMotion);
    container.dataset.vrmAutoRotate = String(motion.autoRotate);
    container.dataset.vrmRotationSpeed = String(motion.rotationSpeed);
    container.dataset.vrmMotionStatus = motion.hasIdleMotion ? "active" : "static-fallback";
    container.dataset.vrmNaturalPose = String(options.naturalPose !== false);
    container.dataset.vrmNaturalPoseStatus = naturalPose.status;
    container.dataset.vrmLookAtStatus = cursorFollow.eyeStatus;
    container.dataset.vrmHeadFollowStatus = cursorFollow.headStatus;
    container.dataset.vrmFollowStatus = cursorFollow.status;
    container.dataset.vrmFollowWeight = "1.00";
    container.dataset.vrmStatus = "ready";
    container.setAttribute("aria-busy", "false");
    status.hidden = true;
    canvas.hidden = false;

    loop = new AvatarRenderLoop((delta) => {
      if (!canRender()) { syncVisibility(); return; }
      motion.update(delta);
      const actionActive = Boolean(vrma?.action?.isRunning?.());
      const activityWeight = actionActive ? 0.25 : motion.hasIdleMotion ? 0.85 : 1;
      cursorFollow.setActivityWeight(activityWeight);
      container.dataset.vrmFollowActivity = actionActive ? "action" : motion.hasIdleMotion ? "idle" : "static";
      cursorFollow.update(delta);
      vrma?.update(delta);
      vrm.update(delta);
      cursorFollow.applyAfterVrmUpdate();
      container.dataset.vrmYaw = vrm.scene.rotation.y.toFixed(3);
      renderer.render(scene, camera);
    });
    resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(container);
    if (typeof IntersectionObserver !== "undefined") {
      intersectionObserver = new IntersectionObserver((entries) => {
        intersecting = entries.some((entry) => entry.isIntersecting);
        syncVisibility();
      });
      intersectionObserver.observe(container);
    }
    document.addEventListener("visibilitychange", resize);
    document.addEventListener("freeze", suspend);
    document.addEventListener("resume", resume);
    window.addEventListener("pagehide", suspend);
    window.addEventListener("pageshow", resume);
    window.addEventListener("resize", resize);
    canvas.addEventListener("webglcontextlost", contextLost);
    resize();
    void watchNativeWindow();
  } catch (error) {
    if (disposed) throw error;
    disposed = true;
    release();
    activeViewers.delete(container);
    container.dataset.vrmRenderStatus = "error";
    return fail(container, `VRM 加载失败：${error?.message || "unknown error"}`);
  }

  return api;
}
