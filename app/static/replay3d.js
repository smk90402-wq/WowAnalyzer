// 3D 리플레이 렌더러 — three.js(로컬 vendor/three.module.js) 기반.
// main.js 의 rc 상태(트랙·시계·필터)를 그대로 읽고, rcDraw() 가 3D 모드일 때
// window.Replay3D.draw() 로 위임한다 (2D/3D 동시 렌더 없음 — 렌더러만 교체).
// 지형: /api/replay/{id}/terrain 높이 그리드 → 메시,
//       맵 PNG(/api/replay/map/{id}.png)를 world_to_px 로 UV 계산해 표면에 입힘.
// 지형을 못 받으면 평평한 바닥(높이 0)으로 폴백.

'use strict';

window.Replay3D = (() => {
  let THREE = null;        // 최초 3D 진입 때 dynamic import (평소엔 로드 안 함)
  let renderer = null;     // WebGL 렌더러 — 리플레이 바꿔도 캔버스째 재사용
  let canvas = null;
  let scene = null;
  let camera = null;
  let terrain = null;      // {grid_w, grid_h, world_rect, heights} (평면 폴백도 같은 포맷)
  let flat = false;        // 지형 404 → 평평한 바닥 모드
  const center = { x: 0, y: 0, h: 0 };  // 월드 중심(씬 원점) + 기준 높이
  let units = {};          // unitId → {group, mat, label, r, u}
  let skulls = {};         // meta.deaths 인덱스 → {sprite|null}
  let rings = [];          // 보스 기믹 링 풀 (재사용)
  let selRing = null;      // 선택 유닛 발밑 링 (rc.selectedUnit)
  let builtFor = null;     // 씬을 만든 replayId
  let ready = false;
  let renderQueued = false;
  let epoch = 0;           // reset()/새 enter() 마다 증가 — 진행 중이던 이전 enter() 무효화
  // sx/sy/moved: pointerdown 위치·이동 여부 — 4px 미만 이동이면 클릭(픽킹)으로 인정
  const cam = { yaw: 0, pitch: Math.PI / 4, dist: 120, target: null, drag: 0, px: 0, py: 0,
                sx: 0, sy: 0, moved: false };

  // 월드 → 씬: 동쪽(-Y월드) = +X, 북쪽(+X월드) = -Z, 높이 = +Y (2D 지도와 같은 방위)
  const sceneX = (wy) => -(wy - center.y);
  const sceneZ = (wx) => -(wx - center.x);

  // 지형 그리드 바이리니어 높이 (구멍 null 은 이웃 평균으로 메움)
  function heightAt(wx, wy) {
    if (!terrain) return 0;
    const wr = terrain.world_rect;
    const gw = terrain.grid_w, gh = terrain.grid_h, hs = terrain.heights;
    const fr = (wx - wr.minX) / Math.max(1e-9, wr.maxX - wr.minX) * (gh - 1);
    const fc = (wy - wr.minY) / Math.max(1e-9, wr.maxY - wr.minY) * (gw - 1);
    const r0 = Math.min(gh - 2, Math.max(0, Math.floor(fr)));
    const c0 = Math.min(gw - 2, Math.max(0, Math.floor(fc)));
    const dr = Math.min(1, Math.max(0, fr - r0));
    const dc = Math.min(1, Math.max(0, fc - c0));
    const q = [hs[r0 * gw + c0], hs[r0 * gw + c0 + 1],
               hs[(r0 + 1) * gw + c0], hs[(r0 + 1) * gw + c0 + 1]];
    const vals = q.filter(v => v != null);
    if (!vals.length) return center.h;
    const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
    const g = (v) => (v == null ? avg : v);
    const top = g(q[0]) * (1 - dc) + g(q[1]) * dc;
    const bot = g(q[2]) * (1 - dc) + g(q[3]) * dc;
    return top * (1 - dr) + bot * dr;
  }

  function note3d(msg) {
    const note = document.querySelector('#rc-note');
    if (!note) return;
    if (note.dataset.base == null) note.dataset.base = note.textContent || '';
    const base = note.dataset.base;
    note.textContent = base ? `${base} · ${msg}` : msg;
  }

  // 3D 안내문을 지우고 원래 문구로 복원 (2D 복귀·지형 정상 진입 시)
  function restoreNote() {
    const note = document.querySelector('#rc-note');
    if (note && note.dataset.base != null) note.textContent = note.dataset.base;
  }

  function ensureRenderer() {
    if (renderer) return true;
    try {
      canvas = document.createElement('canvas');
      canvas.id = 'rc-canvas3d';
      renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      camera = new THREE.PerspectiveCamera(50, 1.6, 0.5, 6000);
      bindControls();
    } catch (e) {
      renderer = null;
      return false;
    }
    return true;
  }

  function attach() {
    const stage = document.querySelector('.rc-stage');
    if (stage && canvas.parentElement !== stage) stage.appendChild(canvas);
    sizeToStage();
  }

  let sizedW = 0;   // 마지막으로 맞춘 스테이지 폭/높이 — draw 에서 변화 감지용
  let sizedH = 0;

  function sizeToStage() {
    if (!renderer || !canvas.parentElement) return;
    const w = Math.max(320, canvas.parentElement.clientWidth || 1000);
    // 스테이지(.rc-stage)가 CSS 비율·상한으로 높이를 정함 — 버퍼를 그 실제 크기에 맞춰
    // 영상 화면과 같은 px 높이가 된다 (스테이지 높이를 못 읽으면 0.62 비율 폴백)
    const h = Math.max(200, canvas.parentElement.clientHeight || Math.round(w * 0.62));
    renderer.setSize(w, h, false);   // 버퍼만 — CSS 는 width/height 100%
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    sizedW = canvas.parentElement.clientWidth || 0;
    sizedH = canvas.parentElement.clientHeight || 0;
  }

  // ── 카메라: 드래그 회전 · 휠 줌 · 우클릭(또는 Shift) 팬, 틸트 10°~85° ──
  function updateCamera() {
    cam.pitch = Math.min(Math.max(cam.pitch, 0.17), 1.48);
    cam.dist = Math.min(Math.max(cam.dist, 15), 2500);
    const cp = Math.cos(cam.pitch);
    camera.position.set(
      cam.target.x + Math.sin(cam.yaw) * cp * cam.dist,
      cam.target.y + Math.sin(cam.pitch) * cam.dist,
      cam.target.z + Math.cos(cam.yaw) * cp * cam.dist);
    camera.lookAt(cam.target);
  }

  function scheduleRender() {
    if (renderQueued) return;
    renderQueued = true;
    requestAnimationFrame(() => {
      renderQueued = false;
      // 재생 중이면 기존 rAF 루프(rcStep→rcDraw)가 그리므로 여기선 정지 상태만
      if (!rc.playing && rc.is3d) draw();
    });
  }

  function bindControls() {
    canvas.addEventListener('contextmenu', e => e.preventDefault());
    canvas.addEventListener('pointerdown', e => {
      if (!ready) return;
      // 좌클릭 = 팬(이동), 우클릭/Shift = 시점 회전 (2026-07-11 사용자 요청으로 스왑)
      cam.drag = (e.button === 2 || e.shiftKey) ? 1 : 2;
      cam.px = e.clientX; cam.py = e.clientY;
      cam.sx = e.clientX; cam.sy = e.clientY; cam.moved = false;
      try { canvas.setPointerCapture(e.pointerId); } catch (_) {}
      e.preventDefault();
    });
    canvas.addEventListener('pointermove', e => {
      if (!cam.drag || !ready) return;
      if (!cam.moved && Math.hypot(e.clientX - cam.sx, e.clientY - cam.sy) >= 4) cam.moved = true;
      const dx = e.clientX - cam.px, dy = e.clientY - cam.py;
      cam.px = e.clientX; cam.py = e.clientY;
      if (cam.drag === 1) {          // 회전
        cam.yaw -= dx * 0.0055;
        cam.pitch += dy * 0.0055;
      } else {                       // 팬 (바닥 평면에서 이동)
        const s = cam.dist * 0.0016;
        const fx = -Math.sin(cam.yaw), fz = -Math.cos(cam.yaw);   // 화면 위쪽 방향
        cam.target.x += (-fz) * -dx * s + fx * dy * s;            // right=(-fz,0,fx)
        cam.target.z += fx * -dx * s + fz * dy * s;
      }
      updateCamera();
      scheduleRender();
    });
    canvas.addEventListener('pointerup', e => {
      const wasPan = cam.drag === 2;
      cam.drag = 0;
      // 4px 미만 이동 + 좌클릭만 클릭으로 인정 — 카메라 드래그와 충돌 없음
      if (wasPan && !cam.moved && ready && e.button === 0 && !e.shiftKey) pickAt(e);
    });
    canvas.addEventListener('pointercancel', () => { cam.drag = 0; });
    canvas.addEventListener('wheel', e => {
      if (!ready) return;
      e.preventDefault();
      cam.dist *= Math.pow(1.0015, e.deltaY);
      updateCamera();
      scheduleRender();
    }, { passive: false });
    window.addEventListener('resize', () => {
      if (rc.is3d && ready) { sizeToStage(); scheduleRender(); }
    });
  }

  // 클릭 픽킹 — 유닛 구체/화살표/이름표를 Raycaster 로 집음, 빈 곳이면 선택 해제
  function pickAt(e) {
    if (!scene || !camera || !rc.is3d) return;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const ndc = new THREE.Vector2(
      (e.clientX - rect.left) / rect.width * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, camera);
    const targets = Object.values(units).filter(r => r.group.visible).map(r => r.group);
    // 죽은 유닛은 마커가 숨고 해골만 남음 — 해골도 클릭해 선택 가능하게
    for (const s of Object.values(skulls)) if (s.sprite && s.sprite.visible) targets.push(s.sprite);
    let uid = null;
    for (const hit of ray.intersectObjects(targets, true)) {
      let o = hit.object;
      while (o && !(o.userData && o.userData.uid)) o = o.parent;
      if (o) { uid = o.userData.uid; break; }
    }
    // 선택 상태는 main.js 의 rc 가 갖고, 패널 갱신도 거기서 한다
    if (typeof window.rcSelectUnit === 'function') window.rcSelectUnit(uid);
    else scheduleRender();
  }

  // ── 씬 구성 ────────────────────────────────────────────────────────────
  function disposeScene() {
    if (scene) {
      scene.traverse(o => {
        if (o.geometry) o.geometry.dispose();
        const mats = Array.isArray(o.material) ? o.material : (o.material ? [o.material] : []);
        for (const m of mats) { if (m.map) m.map.dispose(); m.dispose(); }
      });
    }
    scene = null; units = {}; skulls = {}; rings = []; selRing = null;
    terrain = null; ready = false; builtFor = null;
  }

  async function fetchTerrain(id) {
    const r = await fetch(`/api/replay/${encodeURIComponent(id)}/terrain`);
    if (!r.ok) {
      let why = `HTTP ${r.status}`;
      try { const e = await r.json(); if (e.detail) why = e.detail; } catch (_) {}
      return { grid: null, why };
    }
    return { grid: await r.json(), why: '' };
  }

  // 지형 없을 때: 유닛 궤적 bbox + 20% 마진(최소 10yd)의 평평한 2×2 그리드
  function flatGrid() {
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const track of Object.values(rc.tracks)) {
      for (const s of track) {
        if (s[1] < minX) minX = s[1];
        if (s[1] > maxX) maxX = s[1];
        if (s[2] < minY) minY = s[2];
        if (s[2] > maxY) maxY = s[2];
      }
    }
    if (!isFinite(minX)) return null;
    const pad = Math.max(10, (maxX - minX) * 0.2, (maxY - minY) * 0.2);
    return {
      grid_w: 2, grid_h: 2,
      world_rect: { minX: minX - pad, maxX: maxX + pad, minY: minY - pad, maxY: maxY + pad },
      heights: [0, 0, 0, 0],
    };
  }

  function buildTerrainMesh(grid) {
    const gw = grid.grid_w, gh = grid.grid_h, wr = grid.world_rect, hs = grid.heights;
    const map = (rc.meta && rc.meta.map) || {};
    const M = map.world_to_px;
    const pos = new Float32Array(gw * gh * 3);
    const uvs = new Float32Array(gw * gh * 2);
    for (let r = 0; r < gh; r++) {
      const wx = wr.minX + (wr.maxX - wr.minX) * r / (gh - 1);
      for (let c = 0; c < gw; c++) {
        const wy = wr.minY + (wr.maxY - wr.minY) * c / (gw - 1);
        const i = r * gw + c;
        const h = hs[i];
        pos[i * 3] = sceneX(wy);
        pos[i * 3 + 1] = (h == null ? center.h : h) - center.h;
        pos[i * 3 + 2] = sceneZ(wx);
        if (M) {
          // 2D 와 같은 world→px 행렬로 맵 PNG 를 지형 표면에 드레이프
          uvs[i * 2] = (M.a * wx + M.b * wy + M.c) / (map.px_w || 1);
          uvs[i * 2 + 1] = 1 - (M.d * wx + M.e * wy + M.f) / (map.px_h || 1);
        }
      }
    }
    const idx = [];
    for (let r = 0; r < gh - 1; r++) {
      for (let c = 0; c < gw - 1; c++) {
        const a = r * gw + c, b = a + 1, d = a + gw, e = d + 1;
        if (hs[a] == null || hs[b] == null || hs[d] == null || hs[e] == null) continue;
        idx.push(a, d, b, b, d, e);   // 위쪽(+Y)이 앞면이 되는 순서
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
    geo.setIndex(idx);
    geo.computeVertexNormals();
    let mat;
    if (rc.mapImg && M && !map.error) {
      const tex = new THREE.Texture(rc.mapImg);
      tex.needsUpdate = true;
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
      mat = new THREE.MeshLambertMaterial({ map: tex, side: THREE.DoubleSide });
    } else {
      mat = new THREE.MeshLambertMaterial({ color: 0x3a4150, side: THREE.DoubleSide });
    }
    return new THREE.Mesh(geo, mat);
  }

  function makeTextSprite(text, color) {
    const cnv = document.createElement('canvas');
    const ctx = cnv.getContext('2d');
    const font = 'bold 44px sans-serif';
    ctx.font = font;
    const w = Math.ceil(ctx.measureText(text).width) + 18;
    const h = 58;
    cnv.width = w; cnv.height = h;
    ctx.font = font;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.lineWidth = 7;
    ctx.strokeStyle = '#10141a';
    ctx.strokeText(text, w / 2, h / 2);
    ctx.fillStyle = color;
    ctx.fillText(text, w / 2, h / 2);
    const tex = new THREE.CanvasTexture(cnv);
    tex.colorSpace = THREE.SRGBColorSpace;
    const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
    const k = 0.06;                       // 텍스처 px → yd
    spr.scale.set(w * k, h * k, 1);
    return spr;
  }

  function makeUnit(u) {
    // 플레이어 = 직업색 원통 (종족 모델은 정지 포즈라 의미 없어 폐기 — 2026-07-11 사용자 결정),
    // 보스/NPC = 구체 유지.
    const color = new THREE.Color(rcUnitColor(u));
    const r = u.kind === 'boss' ? 2.4 : (u.kind === 'npc' ? 0.7 : 1.1);
    const mat = new THREE.MeshLambertMaterial({ color, transparent: true });
    let body;
    if (u.kind === 'player') {
      body = new THREE.Mesh(new THREE.CylinderGeometry(r * 0.65, r * 0.65, 2.0, 18), mat);
      body.position.y = 1.0 + 0.3;        // 원통 중심 = 키/2 + 바닥 여유
    } else {
      body = new THREE.Mesh(new THREE.SphereGeometry(r, 20, 14), mat);
      body.position.y = r + 0.5;          // 바닥에서 0.5yd 띄움
    }
    const arrow = new THREE.Mesh(new THREE.ConeGeometry(r * 0.45, r * 1.3, 10), mat);
    arrow.rotation.x = Math.PI / 2;       // 시선(facing) 방향 = 그룹 +Z
    arrow.position.set(0, r * 0.6 + 0.5, r + 0.9);
    const group = new THREE.Group();
    group.userData.uid = u.id;   // 클릭 픽킹에서 유닛 식별
    group.add(body);
    group.add(arrow);
    let label = null;
    if (u.kind === 'boss') {
      label = makeTextSprite(`★ ${String(u.name || '').split('-')[0]}`, '#ffd8d8');
      label.position.y = r * 2 + 3.2;
      group.add(label);
    }
    group.visible = false;
    scene.add(group);
    units[u.id] = { group, mat, label, r, u };
  }

  function ensureLabel(rec) {
    if (rec.label) return;
    rec.label = makeTextSprite(String(rec.u.name || rec.u.id).split('-')[0], '#f0f0f0');
    rec.label.scale.multiplyScalar(0.62);   // 플레이어 이름은 작게 — 20명 겹칠 때 가독성
    rec.label.position.y = rec.r * 2 + 2.6;
    rec.group.add(rec.label);
  }

  function getMechanicMesh(i, shape, angleDeg, innerRatio) {
    const meshKey = `${shape}:${Number(angleDeg) || 0}:${Number(innerRatio) || 0}`;
    if (rings[i] && rings[i].userData.meshKey !== meshKey) {
      scene.remove(rings[i]);
      rings[i].geometry.dispose();
      rings[i].material.dispose();
      rings[i] = null;
    }
    if (!rings[i]) {
      const mat = new THREE.MeshBasicMaterial({
        color: 0xffffff, transparent: true, side: THREE.DoubleSide,
        depthWrite: false, depthTest: false,   // 경사·줌아웃에서 지형에 깎여 잘리지 않게
      });
      // 지형 드레이프용 내부 분할 포함 지오메트리 (드레이프는 drapeToTerrain 참고)
      let geometry;
      if (shape === 'circle') {
        geometry = new THREE.RingGeometry(0.001, 1, 48, 6);
      } else if (shape === 'donut') {
        geometry = new THREE.RingGeometry(Math.max(0.05, Number(innerRatio) || 0.5), 1, 48, 6);
      } else if (shape === 'cone') {
        const half = (Number(angleDeg) || 90) * Math.PI / 360;
        // thetaStart 는 +X 축 기준 CCW — 부채꼴 중심을 로컬 +Y(전방)에 맞춘다
        geometry = new THREE.RingGeometry(0.01, 1, 24, 6, Math.PI / 2 - half, half * 2);
      } else if (shape === 'line') {
        geometry = new THREE.PlaneGeometry(1, 1, 2, 12);
        geometry.translate(0, 0.5, 0);
      } else {
        geometry = new THREE.RingGeometry(0.82, 1, 40, 2);
      }
      const mesh = new THREE.Mesh(geometry, mat);
      mesh.rotation.x = -Math.PI / 2;     // 지면에 눕힌 원형 링
      // 기본 오일러 순서(XYZ)는 rotation.y(시전 방향)가 눕히기 전에 적용돼
      // 부채꼴/직선이 지면에서 기울어 파묻힌다 — 눕힌 뒤 방향을 돌리는 YXZ 로
      mesh.rotation.order = 'YXZ';
      mesh.renderOrder = -1;              // 유닛·이름표보다 먼저 그려 장판이 그 위를 덮지 않게
      mesh.frustumCulled = false;         // 드레이프가 정점 높이를 바꿔 원래 경계구가 안 맞음
      mesh.userData.meshKey = meshKey;
      mesh.visible = false;
      scene.add(mesh);
      rings[i] = mesh;
    }
    return rings[i];
  }

  // 눕힌 장판 메시의 각 정점을 지형 높이 + lift 로 맞춘다 (경사에서 파묻힘/공중부양 방지).
  // 전제: rotation.order='YXZ' + rotation.x=-π/2 → 월드 높이 = 로컬 z·scale.z + position.y
  // (검증: 정점 (x,y,z) → 월드 (x·cosθ−y·sinθ, z, −x·sinθ−y·cosθ), θ=rotation.y 무관)
  function drapeToTerrain(mesh, lift) {
    const attr = mesh.geometry.attributes.position;
    const sx = mesh.scale.x, sy = mesh.scale.y, sz = mesh.scale.z || 1;
    const cy = Math.cos(mesh.rotation.y), sn = Math.sin(mesh.rotation.y);
    for (let i = 0; i < attr.count; i++) {
      const lx = attr.getX(i) * sx, ly = attr.getY(i) * sy;
      const X = mesh.position.x + cy * lx - sn * ly;   // 씬 좌표 오프셋 (Ry 적용 후)
      const Z = mesh.position.z - sn * lx - cy * ly;
      const wx = center.x - Z, wy = center.y - X;      // sceneX/sceneZ 역변환
      attr.setZ(i, (heightAt(wx, wy) - center.h + lift - mesh.position.y) / sz);
    }
    attr.needsUpdate = true;
  }

  function buildScene(grid) {
    disposeScene();
    terrain = grid;
    const wr = grid.world_rect;
    center.x = (wr.minX + wr.maxX) / 2;
    center.y = (wr.minY + wr.maxY) / 2;
    const vals = grid.heights.filter(v => v != null).sort((a, b) => a - b);
    center.h = vals.length ? vals[Math.floor(vals.length / 2)] : 0;   // 기준 = 중앙값

    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x10141a);
    scene.add(new THREE.HemisphereLight(0xcfd8ea, 0x2a251f, 1.05));
    const sun = new THREE.DirectionalLight(0xffffff, 1.0);
    sun.position.set(120, 260, 160);
    scene.add(sun);
    scene.add(buildTerrainMesh(grid));
    for (const u of (rc.meta && rc.meta.units) || []) makeUnit(u);

    // 카메라: 방 중앙 바닥을 45도 틸트로 내려다봄, 북쪽이 화면 위 (2D 와 동일 방위)
    const span = Math.max(wr.maxX - wr.minX, wr.maxY - wr.minY);
    cam.target = new THREE.Vector3(0, heightAt(center.x, center.y) - center.h, 0);
    cam.yaw = 0;
    cam.pitch = Math.PI / 4;
    cam.dist = Math.max(40, span * 0.95);
    sizeToStage();
    updateCamera();
  }

  // ── 공개 API ───────────────────────────────────────────────────────────
  async function enter() {
    if (!rc.meta || !rc.replayId) return false;
    const id = rc.replayId;
    const myEpoch = ++epoch;   // 이 진입보다 뒤에 reset()/재진입이 있었으면 아래에서 중단
    try {
      THREE ??= await import('/static/vendor/three.module.js');
    } catch (e) {
      note3d('3D 엔진 파일을 불러오지 못했어요');
      return false;
    }
    if (epoch !== myEpoch || rc.replayId !== id) return false;
    if (!ensureRenderer()) { note3d('이 브라우저에서는 3D 화면을 열 수 없어요'); return false; }
    attach();
    if (builtFor === id && ready) {
      canvas.style.display = '';
      if (flat) note3d('지형 정보를 못 받아서 평평한 바닥으로 보여드려요');
      else restoreNote();
      return true;
    }
    canvas.style.display = 'none';
    let grid = null;
    flat = false;
    try {
      const res = await fetchTerrain(id);
      // 기다리는 동안 리플레이가 바뀌었거나 같은 리플레이를 다시 열었으면 중단
      if (epoch !== myEpoch || rc.replayId !== id || !rc.meta) return false;
      grid = res.grid;
      if (!grid) { flat = true; note3d(`지형 정보를 못 받아서 평평한 바닥으로 보여드려요 (${res.why})`); }
    } catch (e) {
      if (epoch !== myEpoch || rc.replayId !== id || !rc.meta) return false;
      flat = true;
      note3d('지형 정보를 못 받아서 평평한 바닥으로 보여드려요');
    }
    if (!grid) grid = flatGrid();
    if (!grid) { note3d('좌표 데이터가 없어 3D 화면을 만들 수 없어요'); return false; }
    if (!flat) restoreNote();
    buildScene(grid);
    builtFor = id;
    ready = true;
    canvas.style.display = '';
    return true;
  }

  function hide() {
    if (canvas) canvas.style.display = 'none';
    restoreNote();
  }

  function reset() {
    epoch++;                          // 진행 중이던 enter() 무효화
    hide();
    disposeScene();
    if (canvas) canvas.remove();      // 옛 리플레이 상세 DOM 이 캔버스에 붙잡혀 남지 않게
  }

  function isReady() {
    return ready && builtFor === rc.replayId;
  }

  // 매 프레임: rc.t 기준으로 유닛/해골/기믹 링 갱신 후 렌더 (rcDraw 가 호출)
  function draw() {
    if (!ready || !scene || !rc.meta) return;
    // 스테이지 크기가 바뀌었으면(목록 접기, 창 크기 등) 버퍼 다시 맞춤
    const pw = canvas.parentElement ? canvas.parentElement.clientWidth : 0;
    const ph = canvas.parentElement ? canvas.parentElement.clientHeight : 0;
    if ((pw && Math.abs(pw - sizedW) > 2) || (ph && Math.abs(ph - sizedH) > 2)) sizeToStage();
    const t = rc.t;
    const anyHl = Object.values(rc.mode).includes(1);

    for (const rec of Object.values(units)) {
      const u = rec.u;
      const mode = rc.mode[u.id] || 0;
      const track = rc.tracks[u.id];
      const cur = track ? rcTrackAt(track, t) : null;
      // 샘플 끊김: 네임드는 마지막 위치에 계속 표시(살짝 흐리게), 나머지는 숨김
      const stale = !!(cur && cur.age > RC_STALE_S);
      let show = mode !== 2 && cur && (!stale || u.kind === 'boss');
      if (show) {
        // 마지막 죽음 이후 새 샘플 없음 = 지금 죽어 있음 → 마커 숨김 (해골만)
        const dts = rc.deathsBy[u.id] || [];
        let lastDeath = -1;
        for (const dt of dts) if (dt <= t && dt > lastDeath) lastDeath = dt;
        if (lastDeath >= 0 && cur.srcT <= lastDeath) show = false;
      }
      rec.group.visible = !!show;
      // dome 은 씬 직속이라 그룹 숨김에 안 딸려감 — 스킵 경로에서 명시적으로 숨김
      if (!show) { if (rec.dome) rec.dome.visible = false; continue; }
      const gy = heightAt(cur.x, cur.y) - center.h;
      rec.group.position.set(sceneX(cur.y), gy, sceneZ(cur.x));
      if (cur.facing != null) {
        rec.group.rotation.y = Math.atan2(-Math.sin(cur.facing), -Math.cos(cur.facing));
      }
      const hl = mode === 1;
      rec.mat.opacity = (anyHl && !hl ? 0.25 : 1) * (stale ? 0.5 : 1);
      // 클릭 선택 유닛은 살짝 밝게 (발밑 링은 아래에서)
      rec.mat.emissive.copy(rec.mat.color).multiplyScalar(u.id === rc.selectedUnit ? 0.45 : 0);
      const sc = hl ? 1.35 : 1;
      rec.baseScale = sc;   // 기믹 펄스가 이 값 기준으로 왕복
      rec.group.scale.set(sc, sc, sc);
      if (u.kind !== 'boss') {
        if (hl) ensureLabel(rec);
        if (rec.label) rec.label.visible = hl;
      }
      // 여명의 수정 보유 — 원통 위에 금색 수정(팔면체)이 떠서 자전
      const holding = u.kind === 'player' && rc.crystalHolds.length > 0
        && rc.crystalHolds.some(h => h.u === u.id && t >= h.s && t < h.e);
      if (holding && !rec.crystal) {
        const cm = new THREE.Mesh(
          new THREE.OctahedronGeometry(0.85),
          // transparent: 불투명 패스에 남으면 depthTest 없는 장판이 위를 덮음
          new THREE.MeshLambertMaterial({ color: 0xf5d76e, emissive: 0x9a7a22, transparent: true }));
        cm.scale.set(0.7, 1.15, 0.7);        // 세로로 길쭉한 수정 모양
        cm.position.y = 3.7;                 // 원통(키 2.0 + 바닥 0.3) 위
        rec.group.add(cm);
        rec.crystal = cm;
      }
      if (rec.crystal) {
        rec.crystal.visible = holding;
        if (holding) {
          rec.crystal.rotation.y = t * 1.6;                       // 천천히 자전
          rec.crystal.position.y = 3.7 + 0.25 * Math.sin(t * 3);  // 둥실 부유
        }
      }
      // P3: 보유자 발밑 12yd 보호 링(횃불 운반자) — 이 밖이면 '한밤' 중첩.
      // 유닛 그룹 자식이면 강조 배율(×1.35)·펄스에 딸려가 반경이 왜곡됨 — 씬 직속 12yd 고정
      if (holding && !rec.dome) {
        const dm = new THREE.Mesh(
          new THREE.RingGeometry(0.965, 1, 48, 2),
          new THREE.MeshBasicMaterial({ color: 0xf5d76e, transparent: true, opacity: 0.5,
                                        side: THREE.DoubleSide, depthWrite: false, depthTest: false }));
        dm.rotation.x = -Math.PI / 2;
        dm.scale.set(12, 12, 1);
        dm.renderOrder = -1;
        dm.frustumCulled = false;
        scene.add(dm);                    // disposeScene 의 traverse 가 정리
        rec.dome = dm;
      }
      if (rec.dome) {
        const domeOn = holding && rcSpaceAt(t)?.key === 'p3';
        rec.dome.visible = domeOn;
        if (domeOn) {
          rec.dome.position.copy(rec.group.position);
          rec.dome.position.y += 0.22;
          drapeToTerrain(rec.dome, 0.22);
        }
      }
    }

    // 선택 유닛 발밑 링
    const selRec = rc.selectedUnit ? units[rc.selectedUnit] : null;
    if (selRec && selRec.group.visible) {
      if (!selRing) {
        selRing = new THREE.Mesh(
          new THREE.RingGeometry(0.78, 1, 40, 2),
          new THREE.MeshBasicMaterial({ color: 0x7db7ff, transparent: true, opacity: 0.95,
                                        side: THREE.DoubleSide, depthWrite: false, depthTest: false }));
        selRing.rotation.x = -Math.PI / 2;
        selRing.renderOrder = -1;
        selRing.frustumCulled = false;
        scene.add(selRing);   // disposeScene 의 traverse 가 정리
      }
      const rr = selRec.r * 1.8;
      selRing.position.copy(selRec.group.position);
      selRing.position.y += 0.18;
      selRing.scale.set(rr, rr, 1);
      drapeToTerrain(selRing, 0.18);
      selRing.visible = true;
    } else if (selRing) {
      selRing.visible = false;
    }

    // 죽음 해골 (죽은 자리에 고정) — 쫄몹 제외 (2D 와 동일 규칙)
    (rc.meta.deaths || []).forEach((d, i) => {
      if (String(d.id).startsWith('n')) return;
      let s = skulls[i];
      if (!s) {
        const pos = rcTrackAt(rc.tracks[d.id], Number(d.t));
        if (!pos) { skulls[i] = { sprite: null }; return; }
        const spr = makeTextSprite('☠', '#f0f0f0');
        spr.userData.uid = d.id;   // 해골 클릭 = 죽은 유닛 선택 (pickAt)
        spr.position.set(sceneX(pos.y), heightAt(pos.x, pos.y) - center.h + 1.2, sceneZ(pos.x));
        scene.add(spr);
        s = skulls[i] = { sprite: spr };
      }
      if (s.sprite) s.sprite.visible = Number(d.t) <= t && rc.mode[d.id] !== 2;
    });

    // DB2/수동 보정으로 확인된 원형·부채꼴·직선 장판을 월드 야드 단위로 표시한다.
    let ri = 0;
    for (const it of rcRingEventsAt(t)) {
      const ev = it.ev;
      const age = it.age;
      const pos = rcTrackAt(rc.tracks[it.anchorId], t);
      if (!pos || pos.age > RC_STALE_S) continue;
      const geometry = ev.geometry || {};
      const shape = geometry.shape || 'target';
      const outerRadius = Number(geometry.radius) || 0;
      const innerRatio = outerRadius ? Number(geometry.inner_radius) / outerRadius : 0;
      const mesh = getMechanicMesh(ri++, shape, geometry.angle, innerRatio);
      const pulse = it.durable ? 1 + 0.03 * Math.sin(age * Math.PI * 2 / 1.6) : 1;
      if (shape === 'circle' && Number(geometry.radius)) {
        const radius = Number(geometry.radius) * pulse;
        mesh.scale.set(radius, radius, 1);
      } else if (shape === 'donut' && Number(geometry.radius)) {
        const radius = Number(geometry.radius) * pulse;
        mesh.scale.set(radius, radius, 1);
      } else if (shape === 'cone' && Number(geometry.radius)) {
        const radius = Number(geometry.radius) * pulse;
        mesh.scale.set(radius, radius, 1);
      } else if (shape === 'line' && Number(geometry.length)) {
        mesh.scale.set(Number(geometry.width) || 4, Number(geometry.length), 1);
      } else {
        const rr = it.durable
          ? 2.6 + 0.3 * Math.sin(age * Math.PI * 2 / 1.6)
          : 2.2 + age * 2.2;
        mesh.scale.set(rr, rr, 1);
      }
      if (shape === 'cone' || shape === 'line') {
        let facing = pos.facing;
        const dest = ev.dest_id ? rcTrackAt(rc.tracks[ev.dest_id], t) : null;
        if (facing == null && dest) facing = Math.atan2(dest.y - pos.y, dest.x - pos.x);
        mesh.rotation.y = facing == null ? 0 : facing;
      } else {
        mesh.rotation.y = 0;
      }
      mesh.position.set(sceneX(pos.y), heightAt(pos.x, pos.y) - center.h + 0.25, sceneZ(pos.x));
      drapeToTerrain(mesh, 0.3);
      mesh.material.color.set(it.danger ? '#ff5b5b'
        : ({ hit: '#b18cf0', impact: '#ef6b62', summon: '#4fc9b0' }[ev.kind] || '#e8a34c'));
      mesh.material.opacity = (shape === 'target' ? 0.9 : (it.danger ? 0.42 : 0.24)) * it.fade;
      mesh.visible = true;
      // 대상 유닛 강조: 표시 기간 내내 구체 펄스 + 이름표 (기간형은 살짝만 왕복).
      // 실반경 원 기믹(임계점 등)은 전원이 대상이라 이름을 다 띄우면 화면이 덮임 —
      // 겹침(danger)으로 빨간 원이 된 사람만 이름을 보여 범인을 바로 찾게 한다.
      const drec = units[ev.dest_id];
      if (drec && drec.group.visible) {
        const pu = 1 + (it.durable ? 0.12 : 0.25) * Math.abs(Math.sin(age * Math.PI * 2));
        const ps = (drec.baseScale || 1) * pu;
        drec.group.scale.set(ps, ps, ps);
        if (drec.u.kind !== 'boss') {
          const circleGeom = shape === 'circle' && Number(geometry.radius) > 0;
          if (!circleGeom || it.danger) {
            ensureLabel(drec);
            drec.label.visible = true;
          }
        }
      }
      if (ri >= RC_RING_MAX) break;   // main.js 상수 공유 (링 풀 상한)
    }
    for (let i = ri; i < rings.length; i++) if (rings[i]) rings[i].visible = false;

    renderer.render(scene, camera);
  }

  // 프리뷰/디버깅용 상태 요약 (UI 미사용)
  function debug() {
    const shown = Object.values(units).filter(r => r.group.visible).map(r => {
      // 화면 좌표(sx, sy)도 같이 — 프리뷰에서 클릭 픽킹 검증용
      const v = r.group.position.clone().project(camera);
      return {
        id: r.u.id, name: r.u.name, kind: r.u.kind,
        x: r.group.position.x, y: r.group.position.y, z: r.group.position.z,
        sx: (v.x + 1) / 2 * canvas.clientWidth, sy: (1 - v.y) / 2 * canvas.clientHeight,
        scale: r.group.scale.x, labelShown: !!(r.label && r.label.visible),
      };
    });
    return {
      ready, flat, builtFor,
      grid: terrain ? { w: terrain.grid_w, h: terrain.grid_h, rect: terrain.world_rect } : null,
      centerH: center.h,
      domes: Object.values(units).filter(r => r.dome)
        .map(r => ({ id: r.u.id, visible: r.dome.visible, scale: r.dome.scale.x })),
      vertices: scene ? (() => {
        let n = 0;
        scene.traverse(o => { if (o.isMesh && o.geometry.attributes.position) n += o.geometry.attributes.position.count; });
        return n;
      })() : 0,
      units: shown,
      cam: { yaw: cam.yaw, pitch: cam.pitch, dist: cam.dist },
    };
  }

  return { enter, hide, reset, draw, isReady, debug, heightAt };
})();
