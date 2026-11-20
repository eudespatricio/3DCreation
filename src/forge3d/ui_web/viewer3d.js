/**
 * Forge3D Studio Web — Viewport 3D Dual-Layer (Three.js 0.170.0 PBR + Zero-Dep GLB Canvas Fallback).
 * Camada 1: Three.js ESM (OrbitControls, GLTFLoader, RoomEnvironment, AnimationMixer).
 * Camada 2: Parser binário GLB (JSON + BIN accessors POSITION/INDICES) + Canvas 3D interativo offline.
 */

const THREE_BASE = 'https://cdn.jsdelivr.net/npm/three@0.170.0';

export function parseGlbBinary(buffer) {
  const dv = new DataView(buffer);
  if (buffer.byteLength < 20 || dv.getUint32(0, true) !== 0x46546c67) {
    throw new Error('Cabeçalho GLB inválido (magic != glTF)');
  }
  const version = dv.getUint32(4, true);
  let [offset, gltf, binChunk] = [12, null, null];
  while (offset + 8 <= buffer.byteLength) {
    const chunkLen = dv.getUint32(offset, true);
    const chunkType = dv.getUint32(offset + 4, true);
    const dataStart = offset + 8;
    if (dataStart + chunkLen > buffer.byteLength) break;
    if (chunkType === 0x4e4f534a) {
      gltf = JSON.parse(new TextDecoder('utf-8').decode(new Uint8Array(buffer, dataStart, chunkLen)));
    } else if (chunkType === 0x004e4942) {
      binChunk = new DataView(buffer, dataStart, chunkLen);
    }
    offset = dataStart + chunkLen;
  }
  if (!gltf) throw new Error('Chunk JSON ausente no GLB');

  const [positions, edges] = [[], []];
  let triCount = 0;
  const [min, max] = [[Infinity, Infinity, Infinity], [-Infinity, -Infinity, -Infinity]];
  const [accessors, bufferViews] = [gltf.accessors || [], gltf.bufferViews || []];

  function readAccessor(accIdx) {
    const acc = accessors[accIdx];
    const bv = acc && acc.bufferView !== undefined && binChunk ? bufferViews[acc.bufferView] : null;
    if (!bv) return null;
    const baseOffset = (bv.byteOffset || 0) + (acc.byteOffset || 0);
    const [count, compType] = [acc.count || 0, acc.componentType];
    const numComp = acc.type === 'VEC3' ? 3 : acc.type === 'VEC2' ? 2 : acc.type === 'VEC4' ? 4 : 1;
    const elemBytes = compType === 5126 || compType === 5125 ? 4 : compType === 5123 ? 2 : 1;
    const stride = bv.byteStride || numComp * elemBytes;
    const out = new Float64Array(count * numComp);
    for (let i = 0; i < count; i += 1) {
      const rowOff = baseOffset + i * stride;
      for (let c = 0; c < numComp; c += 1) {
        const p = rowOff + c * elemBytes;
        if (p + elemBytes > binChunk.byteLength) break;
        if (compType === 5126) out[i * numComp + c] = binChunk.getFloat32(p, true);
        else if (compType === 5125) out[i * numComp + c] = binChunk.getUint32(p, true);
        else if (compType === 5123) out[i * numComp + c] = binChunk.getUint16(p, true);
        else if (compType === 5121) out[i * numComp + c] = binChunk.getUint8(p);
        else if (compType === 5122) out[i * numComp + c] = binChunk.getInt16(p, true);
      }
    }
    return { data: out, count, numComp };
  }

  for (const mesh of gltf.meshes || []) {
    for (const prim of mesh.primitives || []) {
      const posAcc = prim.attributes?.POSITION !== undefined ? readAccessor(prim.attributes.POSITION) : null;
      if (!posAcc || posAcc.numComp < 3) continue;
      const [vOffset, posData] = [positions.length / 3, posAcc.data];
      for (let i = 0; i < posAcc.count; i += 1) {
        const [x, y, z] = [posData[i * 3], posData[i * 3 + 1], posData[i * 3 + 2]];
        positions.push(x, y, z);
        if (x < min[0]) min[0] = x; if (y < min[1]) min[1] = y; if (z < min[2]) min[2] = z;
        if (x > max[0]) max[0] = x; if (y > max[1]) max[1] = y; if (z > max[2]) max[2] = z;
      }
      const idxAcc = prim.indices !== undefined ? readAccessor(prim.indices) : null;
      const nTris = Math.floor((idxAcc ? idxAcc.count : posAcc.count) / 3);
      triCount += nTris;
      const step = Math.max(1, Math.ceil(nTris / 3000));
      for (let t = 0; t < nTris && edges.length < 9000; t += step) {
        const a = idxAcc ? vOffset + idxAcc.data[t * 3] : vOffset + t * 3;
        const b = idxAcc ? vOffset + idxAcc.data[t * 3 + 1] : a + 1;
        const c = idxAcc ? vOffset + idxAcc.data[t * 3 + 2] : a + 2;
        edges.push(a, b, b, c, c, a);
      }
    }
  }
  if (!Number.isFinite(min[0])) { min.splice(0, 3, -0.5, 0, -0.5); max.splice(0, 3, 0.5, 1, 0.5); }
  const animations = (gltf.animations || []).map((a, idx) => ({ name: a.name || `clipe_${idx + 1}`, channels: (a.channels || []).length }));
  const boneCount = (gltf.skins || []).reduce((acc, s) => acc + ((s.joints || []).length || 0), 0) || (gltf.nodes || []).length;
  return {
    version, gltf, positions: new Float32Array(positions), edges: new Uint32Array(edges),
    vertexCount: positions.length / 3, triCount, meshCount: (gltf.meshes || []).length,
    materialCount: (gltf.materials || []).length, boneCount, animations, min, max,
  };
}

export class Viewer3D {
  constructor(containerEl, statusCallback = null) {
    this.container = containerEl;
    this.onStatus = statusCallback;
    this.mode = 'init';
    this.clips = [];
    this.opts = {
      autoRotate: false, gridUnit: '1m', showGrid: true, showAxes: true,
      wireframe: false, showCollider: false, showPins: true, playing: true, speed: 1.0,
    };
    this.fb = {
      canvas: null, ctx: null, mainData: null, colliderData: null, pins: [],
      yaw: 0.65, pitch: 0.38, distance: 3.0, target: [0, 0.5, 0],
      dragging: false, lastX: 0, lastY: 0, animTime: 0,
    };
    this._initPromise = this._initEngine();
  }

  async _initEngine() {
    try {
      const [THREE, { OrbitControls }, { GLTFLoader }, { RoomEnvironment }] = await Promise.all([
        import(`${THREE_BASE}/build/three.module.js`),
        import(`${THREE_BASE}/examples/jsm/controls/OrbitControls.js`),
        import(`${THREE_BASE}/examples/jsm/loaders/GLTFLoader.js`),
        import(`${THREE_BASE}/examples/jsm/environments/RoomEnvironment.js`),
      ]);
      this.three = { THREE, OrbitControls, GLTFLoader, RoomEnvironment };
      this._setupThree();
      this.mode = 'three';
      this._notify({ mode: 'three', label: 'Three.js 0.170.0 PBR' });
    } catch {
      this._setupFallbackCanvas();
      this.mode = 'fallback';
      this._notify({ mode: 'fallback', label: 'Canvas 3D Wireframe (Fallback Offline)' });
    }
    this._startLoop();
  }

  _notify(info) { if (typeof this.onStatus === 'function') this.onStatus(info); }

  _setupThree() {
    const { THREE, OrbitControls, RoomEnvironment } = this.three;
    this.container.innerHTML = '';
    const [w, h] = [this.container.clientWidth || 720, this.container.clientHeight || 440];
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0b1120);
    this.camera = new THREE.PerspectiveCamera(45, w / h, 0.01, 500);
    this.camera.position.set(2.2, 1.7, 2.4);

    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    this.renderer.setSize(w, h);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.08;
    this.container.appendChild(this.renderer.domElement);

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    const key = new THREE.DirectionalLight(0xffffff, 1.4); key.position.set(4, 7, 5);
    const rim = new THREE.DirectionalLight(0x38bdf8, 0.55); rim.position.set(-4, 3, -5);
    this.scene.add(new THREE.HemisphereLight(0xe2e8f0, 0x1e293b, 0.8), key, rim);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.target.set(0, 0.7, 0);

    this.mainGroup = new THREE.Group();
    this.colliderGroup = new THREE.Group();
    this.pinsGroup = new THREE.Group();
    this.axesHelper = new THREE.AxesHelper(1.2);
    this.scene.add(this.mainGroup, this.colliderGroup, this.pinsGroup, this.axesHelper);
    this._rebuildGridThree();
    this.clock = new THREE.Clock();
    window.addEventListener('resize', () => this.resize());
  }

  _rebuildGridThree() {
    if (!this.three || !this.scene) return;
    const { THREE } = this.three;
    if (this.gridHelper) this.scene.remove(this.gridHelper);
    const sz = this.opts.gridUnit === 'stud' ? 28 : 10;
    this.gridHelper = new THREE.GridHelper(sz, sz, 0x38bdf8, 0x1e293b);
    this.gridHelper.visible = this.opts.showGrid;
    this.scene.add(this.gridHelper);
  }

  _setupFallbackCanvas() {
    this.container.innerHTML = '';
    const canvas = document.createElement('canvas');
    canvas.className = 'viewer-fallback-canvas';
    canvas.width = this.container.clientWidth || 720;
    canvas.height = this.container.clientHeight || 440;
    this.container.appendChild(canvas);
    this.fb.canvas = canvas;
    this.fb.ctx = canvas.getContext('2d');
    canvas.addEventListener('pointerdown', (e) => {
      this.fb.dragging = true; this.fb.lastX = e.clientX; this.fb.lastY = e.clientY;
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener('pointermove', (e) => {
      if (!this.fb.dragging) return;
      this.fb.yaw -= (e.clientX - this.fb.lastX) * 0.01;
      this.fb.pitch = Math.max(-1.45, Math.min(1.45, this.fb.pitch + (e.clientY - this.fb.lastY) * 0.01));
      this.fb.lastX = e.clientX; this.fb.lastY = e.clientY;
    });
    canvas.addEventListener('pointerup', () => { this.fb.dragging = false; });
    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      this.fb.distance = Math.max(0.3, Math.min(80, this.fb.distance * (e.deltaY > 0 ? 1.12 : 0.89)));
    }, { passive: false });
    window.addEventListener('resize', () => this.resize());
  }

  resize() {
    if (!this.container) return;
    const [w, h] = [Math.max(300, this.container.clientWidth || 720), Math.max(260, this.container.clientHeight || 440)];
    if (this.mode === 'three' && this.renderer && this.camera) {
      this.camera.aspect = w / h; this.camera.updateProjectionMatrix(); this.renderer.setSize(w, h);
    } else if (this.fb.canvas) {
      this.fb.canvas.width = w; this.fb.canvas.height = h;
    }
  }

  async loadGlb(url, { colliderUrl = null, pins = [] } = {}) {
    await this._initPromise;
    this.setPins(pins);
    if (!url) return;
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status} ao carregar GLB`);
      const buffer = await res.arrayBuffer();
      const parsed = parseGlbBinary(buffer);
      this.fb.mainData = parsed;
      this.fb.colliderData = null;
      if (colliderUrl) {
        try {
          const cRes = await fetch(colliderUrl);
          if (cRes.ok) this.fb.colliderData = parseGlbBinary(await cRes.arrayBuffer());
        } catch { this.fb.colliderData = null; }
      }
      if (this.mode === 'three') await this._loadIntoThree(buffer);
      this._fitBounds(parsed.min, parsed.max);
      this._notify({
        mode: this.mode, summary: parsed,
        clips: this.mode === 'three' && this.clips.length
          ? this.clips.map((c) => ({ name: c.name, duration: c.duration })) : parsed.animations,
      });
    } catch (err) {
      this._notify({ mode: this.mode, error: err instanceof Error ? err.message : String(err) });
    }
  }

  async _loadIntoThree(buffer) {
    const { THREE, GLTFLoader } = this.three;
    const gltf = await new Promise((resolve, reject) => new GLTFLoader().parse(buffer, '', resolve, reject));
    this.mainGroup.clear();
    this.mainGroup.add(gltf.scene);
    this.clips = gltf.animations || [];
    this.mixer = new THREE.AnimationMixer(gltf.scene);
    if (this.clips.length > 0) this.selectClip(0); else this.currentAction = null;
    this.setWireframe(this.opts.wireframe);
    this._rebuildColliderThree();
    this._rebuildPinsThree();
  }

  _rebuildColliderThree() {
    if (this.mode !== 'three' || !this.colliderGroup) return;
    const { THREE } = this.three;
    this.colliderGroup.clear();
    this.colliderGroup.visible = this.opts.showCollider;
    const col = this.fb.colliderData;
    if (!col?.positions?.length) return;
    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(col.positions, 3));
    if (col.edges.length) geom.setIndex(new THREE.BufferAttribute(col.edges, 1));
    const mat = new THREE.LineBasicMaterial({ color: 0x22d3ee, transparent: true, opacity: 0.75 });
    this.colliderGroup.add(new THREE.LineSegments(geom, mat));
  }

  setPins(pins = []) {
    this.fb.pins = Array.isArray(pins) ? pins : [];
    if (this.mode === 'three') this._rebuildPinsThree();
  }

  _rebuildPinsThree() {
    if (this.mode !== 'three' || !this.pinsGroup) return;
    const { THREE } = this.three;
    this.pinsGroup.clear();
    this.pinsGroup.visible = this.opts.showPins;
    for (const pin of this.fb.pins) {
      const pos = pin.posicao || pin.pos || [0, 0, 0];
      const mesh = new THREE.Mesh(
        new THREE.SphereGeometry(0.045, 12, 12),
        new THREE.MeshBasicMaterial({ color: pin.tipo === 'ancora' ? 0xf59e0b : 0xec4899 }),
      );
      mesh.position.set(Number(pos[0]) || 0, Number(pos[1]) || 0, Number(pos[2]) || 0);
      this.pinsGroup.add(mesh);
    }
  }

  _fitBounds(min, max) {
    const [cx, cy, cz] = [(min[0] + max[0]) * 0.5, (min[1] + max[1]) * 0.5, (min[2] + max[2]) * 0.5];
    const span = Math.max(max[0] - min[0], max[1] - min[1], max[2] - min[2], 0.5);
    this.fb.target = [cx, cy, cz];
    this.fb.distance = span * 1.9;
    if (this.mode === 'three' && this.camera && this.controls) {
      this.controls.target.set(cx, cy, cz);
      this.camera.position.set(cx + span * 1.35, cy + span * 0.95, cz + span * 1.45);
      this.controls.update();
    }
  }

  setCameraPreset(preset) {
    const [cx, cy, cz] = this.fb.target;
    const d = this.fb.distance || 2.5;
    const map = {
      iso: { yaw: 0.68, pitch: 0.38, pos: [cx + d * 0.7, cy + d * 0.5, cz + d * 0.7] },
      front: { yaw: 0, pitch: 0.1, pos: [cx, cy + d * 0.15, cz + d] },
      back: { yaw: Math.PI, pitch: 0.1, pos: [cx, cy + d * 0.15, cz - d] },
      left: { yaw: -Math.PI / 2, pitch: 0.1, pos: [cx - d, cy + d * 0.15, cz] },
      right: { yaw: Math.PI / 2, pitch: 0.1, pos: [cx + d, cy + d * 0.15, cz] },
      top: { yaw: 0, pitch: 1.42, pos: [cx, cy + d * 1.2, cz + 0.01] },
      reset: { yaw: 0.68, pitch: 0.38, pos: [cx + d * 0.7, cy + d * 0.5, cz + d * 0.7] },
    };
    const cfg = map[preset] || map.iso;
    this.fb.yaw = cfg.yaw; this.fb.pitch = cfg.pitch;
    if (this.mode === 'three' && this.camera && this.controls) {
      this.camera.position.set(...cfg.pos); this.controls.target.set(cx, cy, cz); this.controls.update();
    }
  }

  setOption(key, value) {
    this.opts[key] = value;
    if (this.mode === 'three') {
      if (key === 'gridUnit' || key === 'showGrid') this._rebuildGridThree();
      if (key === 'showAxes' && this.axesHelper) this.axesHelper.visible = Boolean(value);
      if (key === 'wireframe') this.setWireframe(Boolean(value));
      if (key === 'showCollider' && this.colliderGroup) this.colliderGroup.visible = Boolean(value);
      if (key === 'showPins' && this.pinsGroup) this.pinsGroup.visible = Boolean(value);
      if (key === 'autoRotate' && this.controls) this.controls.autoRotate = Boolean(value);
      if (key === 'speed' && this.mixer) this.mixer.timeScale = Number(value) || 1;
    }
  }

  setWireframe(enabled) {
    this.opts.wireframe = enabled;
    if (this.mode === 'three' && this.mainGroup) {
      this.mainGroup.traverse((obj) => {
        if (obj.isMesh && obj.material) {
          for (const m of Array.isArray(obj.material) ? obj.material : [obj.material]) m.wireframe = enabled;
        }
      });
    }
  }

  selectClip(indexOrName) {
    if (this.mode !== 'three' || !this.mixer || !this.clips.length) return;
    const clip = typeof indexOrName === 'number'
      ? this.clips[indexOrName] : this.clips.find((c) => c.name === indexOrName) || this.clips[0];
    if (!clip) return;
    this.mixer.stopAllAction();
    this.currentAction = this.mixer.clipAction(clip);
    this.currentAction.play();
    this.currentAction.paused = !this.opts.playing;
  }

  setPlaying(playing) {
    this.opts.playing = Boolean(playing);
    if (this.currentAction) this.currentAction.paused = !this.opts.playing;
  }

  scrubNormalized(t01) {
    if (this.mode === 'three' && this.currentAction && this.mixer) {
      const clip = this.currentAction.getClip();
      if (clip?.duration > 0) {
        this.currentAction.paused = true; this.opts.playing = false;
        this.currentAction.time = Math.max(0, Math.min(1, Number(t01))) * clip.duration;
        this.mixer.update(0);
      }
    }
  }

  _startLoop() {
    const tick = () => {
      requestAnimationFrame(tick);
      if (this.mode === 'three' && this.renderer && this.scene && this.camera) {
        const dt = this.clock ? this.clock.getDelta() : 0.016;
        if (this.mixer && this.opts.playing) this.mixer.update(dt);
        if (this.controls) { this.controls.autoRotate = this.opts.autoRotate; this.controls.update(); }
        this.renderer.render(this.scene, this.camera);
      } else if (this.fb.ctx) {
        if (this.opts.autoRotate && !this.fb.dragging) this.fb.yaw += 0.008;
        if (this.opts.playing) this.fb.animTime += 0.016 * (this.opts.speed || 1);
        this._renderFallbackFrame();
      }
    };
    tick();
  }

  _renderFallbackFrame() {
    const { ctx, canvas, mainData, colliderData, pins, yaw, pitch, distance, target } = this.fb;
    const [w, h] = [canvas.width, canvas.height];
    ctx.fillStyle = '#0b1120'; ctx.fillRect(0, 0, w, h);
    const [cosY, sinY, cosP, sinP] = [Math.cos(yaw), Math.sin(yaw), Math.cos(pitch), Math.sin(pitch)];
    const fov = Math.min(w, h) * 0.92;
    const project = (x, y, z) => {
      const [dx, dy, dz] = [x - target[0], y - target[1], z - target[2]];
      const rx = dx * cosY - dz * sinY;
      const rz1 = dx * sinY + dz * cosY;
      const ry = dy * cosP - rz1 * sinP;
      const rz = dy * sinP + rz1 * cosP + distance;
      return rz <= 0.05 ? null : [w * 0.5 + (rx / rz) * fov, h * 0.5 - (ry / rz) * fov, rz];
    };

    if (this.opts.showGrid) {
      const step = this.opts.gridUnit === 'stud' ? 0.28 : 0.5;
      const ext = step * 5;
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.16)'; ctx.lineWidth = 1; ctx.beginPath();
      for (let i = -5; i <= 5; i += 1) {
        const g = i * step;
        for (const [a, b] of [[project(g, 0, -ext), project(g, 0, ext)], [project(-ext, 0, g), project(ext, 0, g)]]) {
          if (a && b) { ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); }
        }
      }
      ctx.stroke();
    }

    if (this.opts.showAxes) {
      const o = project(0, 0, 0);
      if (o) {
        for (const [pt, col] of [[project(0.8, 0, 0), '#ef4444'], [project(0, 0.8, 0), '#22c55e'], [project(0, 0, 0.8), '#3b82f6']]) {
          if (!pt) continue;
          ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.beginPath();
          ctx.moveTo(o[0], o[1]); ctx.lineTo(pt[0], pt[1]); ctx.stroke();
        }
      }
    }

    const drawEdges = (data, stroke) => {
      if (!data?.positions || !data?.edges) return;
      const { positions: pos, edges: ed } = data;
      ctx.strokeStyle = stroke; ctx.lineWidth = 1; ctx.beginPath();
      for (let i = 0; i < ed.length; i += 2) {
        const [a, b] = [ed[i] * 3, ed[i + 1] * 3];
        const [p1, p2] = [project(pos[a], pos[a + 1], pos[a + 2]), project(pos[b], pos[b + 1], pos[b + 2])];
        if (p1 && p2) { ctx.moveTo(p1[0], p1[1]); ctx.lineTo(p2[0], p2[1]); }
      }
      ctx.stroke();
    };

    drawEdges(mainData, this.opts.wireframe ? '#38bdf8' : '#94a3b8');
    if (mainData?.min && mainData?.max) {
      const [[x0, y0, z0], [x1, y1, z1]] = [mainData.min, mainData.max];
      const c = [[x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1], [x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1]].map((p) => project(...p));
      ctx.strokeStyle = 'rgba(245, 158, 11, 0.42)'; ctx.beginPath();
      for (const [i, j] of [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]]) {
        if (c[i] && c[j]) { ctx.moveTo(c[i][0], c[i][1]); ctx.lineTo(c[j][0], c[j][1]); }
      }
      ctx.stroke();
      ctx.fillStyle = 'rgba(15, 23, 42, 0.78)'; ctx.fillRect(10, 10, 340, 40);
      ctx.fillStyle = '#cbd5e1'; ctx.font = '11px monospace';
      ctx.fillText(`GLB v${mainData.version} · ${mainData.triCount} tris · ${mainData.vertexCount} verts · ${mainData.meshCount} mesh`, 16, 25);
      ctx.fillText(`Mats: ${mainData.materialCount} · Ossos: ${mainData.boneCount} · Clipes: ${mainData.animations.length}`, 16, 41);
    }
    if (this.opts.showCollider && colliderData) drawEdges(colliderData, 'rgba(34, 211, 238, 0.75)');
    if (this.opts.showPins && pins.length) {
      for (const pin of pins) {
        const pos = pin.posicao || pin.pos || [0, 0, 0];
        const pt = project(Number(pos[0]) || 0, Number(pos[1]) || 0, Number(pos[2]) || 0);
        if (!pt) continue;
        ctx.fillStyle = pin.tipo === 'ancora' ? '#f59e0b' : '#ec4899';
        ctx.beginPath(); ctx.arc(pt[0], pt[1], 4.5, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = '#e2e8f0'; ctx.font = '11px monospace'; ctx.fillText(pin.nome || '', pt[0] + 7, pt[1] + 3);
      }
    }
  }
}
