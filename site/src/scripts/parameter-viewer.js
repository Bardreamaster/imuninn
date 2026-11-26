// iPhone frame viewer for /parameter-definition/: a parametric phone body with the six frames of
// protocol/frames/iphone-frames.json (the same file the Python package ships), drawn with three.js.
// All text comes from the page (`strings`), so the script is language-neutral.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const ORDER = ["device", "magsafe", "cam_main_optical", "cam_ultra_wide_optical", "cam_telephoto_optical", "cam_front_optical"];
const CAMERA_OF = { cam_main_optical: "main", cam_ultra_wide_optical: "ultra_wide", cam_telephoto_optical: "telephoto", cam_front_optical: "front" };
const STORE_KEY = "imuninn-parameter-model";

/** Resolve any CSS colour (the site tokens are oklch) to a THREE.Color through a 1x1 canvas. */
const probe = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
function cssColor(root, name) {
  const value = getComputedStyle(root).getPropertyValue(name).trim() || "#888";
  probe.clearRect(0, 0, 1, 1);
  probe.fillStyle = "#888";
  probe.fillStyle = value;
  probe.fillRect(0, 0, 1, 1);
  const [r, g, b] = probe.getImageData(0, 0, 1, 1).data;
  return new THREE.Color().setRGB(r / 255, g / 255, b / 255, THREE.SRGBColorSpace);
}

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const signed = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2);
const fill = (text, values) => text.replace(/\{(\w+)\}/g, (_, k) => values[k] ?? "");

function rotationText(R) {
  const identity = R.every((row, i) => row.every((v, j) => v === (i === j ? 1 : 0)));
  if (identity) return "R = I";
  const diagonal = R.every((row, i) => row.every((v, j) => i === j || v === 0));
  if (diagonal) return "R = diag(" + R.map((row, i) => row[i]).join(", ") + ")";
  return "R = [" + R.map((row) => "[" + row.join(",") + "]").join(",") + "]";
}

function roundedRect(x0, y0, w, h, r) {
  r = Math.min(r, w / 2, h / 2);
  const s = new THREE.Shape();
  s.moveTo(x0 + r, y0);
  s.lineTo(x0 + w - r, y0); s.quadraticCurveTo(x0 + w, y0, x0 + w, y0 + r);
  s.lineTo(x0 + w, y0 + h - r); s.quadraticCurveTo(x0 + w, y0 + h, x0 + w - r, y0 + h);
  s.lineTo(x0 + r, y0 + h); s.quadraticCurveTo(x0, y0 + h, x0, y0 + h - r);
  s.lineTo(x0, y0 + r); s.quadraticCurveTo(x0, y0, x0 + r, y0);
  return s;
}

function slab(shape, z0, depth, material, bevel) {
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: Math.max(depth - 2 * bevel, 0.01), bevelEnabled: bevel > 0, bevelThickness: bevel, bevelSize: bevel,
    bevelSegments: 3, curveSegments: 24,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.z = z0 + bevel;
  return mesh;
}

function disc(r, x, y, z, color, flip) {
  const mesh = new THREE.Mesh(new THREE.CircleGeometry(r, 48),
    new THREE.MeshStandardMaterial({ color, roughness: 0.4, metalness: 0.1, side: THREE.DoubleSide }));
  mesh.position.set(x, y, z);
  if (flip) mesh.rotation.y = Math.PI;
  return mesh;
}

function circlePoints(cx, cy, r, z) {
  const pts = [];
  for (let i = 0; i <= 128; i++) { const t = (i / 128) * Math.PI * 2; pts.push(new THREE.Vector3(cx + r * Math.cos(t), cy + r * Math.sin(t), z)); }
  return pts;
}

/**
 * @param {HTMLElement} root   the .pd-app element
 * @param {Record<string, any>} strings   UI text for the page's language
 * @param {{ models: Record<string, any> }} data   protocol/frames/iphone-frames.json
 * @param {{ base: string, manifest: { models: Record<string, any> } } | null} [assets]   downloadable model
 *   files (manifest.json written by `imuninn hardware export --all --format all`); none: no download buttons
 */
export function initParameterViewer(root, strings, data, assets = null) {
  const $ = (name) => root.querySelector(`[data-pd="${name}"]`);
  const models = data.models;
  const select = $("model");
  const stage = $("stage");
  const canvas = $("canvas");
  const labelBox = $("labels");

  // ---------- model list (newest drawing first) ----------
  const keys = Object.keys(models).sort((a, b) =>
    models[b].drawing.sheet_date.localeCompare(models[a].drawing.sheet_date) || a.localeCompare(b));
  for (const key of keys) {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = `${models[key].name}  (${models[key].drawing.sheet_date.slice(0, 4)})`;
    select.appendChild(option);
  }
  let start = "iphone-17-pro";
  try { start = localStorage.getItem(STORE_KEY) || start; } catch { /* storage blocked: keep the default */ }
  const fromHash = decodeURIComponent(location.hash.slice(1));
  if (models[fromHash]) start = fromHash;
  select.value = models[start] ? start : keys[0];

  // ---------- three.js scene (skipped when WebGL is unavailable; the panel still works) ----------
  let renderer = null;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true }); } catch { $("nogl").hidden = false; }
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 1, 5000);
  const controls = renderer ? new OrbitControls(camera, canvas) : null;
  if (renderer) {
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    controls.enableDamping = true;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8890a0, 2.6));
    const key = new THREE.DirectionalLight(0xffffff, 2.0); key.position.set(120, 200, 260); scene.add(key);
    const fillLight = new THREE.DirectionalLight(0xffffff, 0.9); fillLight.position.set(-150, -80, -260); scene.add(fillLight);
  }

  let group = null;
  let labels = [];
  let selected = "device";
  let current = models[select.value];

  /** One axis as a solid arrow (WebGL draws lines 1 px wide, so the shaft is a cylinder). Drawn over the body. */
  function axisArrow(origin, dir, length, radius, color) {
    // transparent: true puts the arrow in the pass drawn after the see-through body, so the body does not tint it
    const material = new THREE.MeshBasicMaterial({ color, depthTest: false, transparent: true });
    const head = Math.min(length * 0.26, radius * 7), shaft = length - head;
    const arrow = new THREE.Group();
    const cylinder = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, shaft, 16), material);
    cylinder.position.y = shaft / 2;
    const cone = new THREE.Mesh(new THREE.ConeGeometry(radius * 2.6, head, 20), material);
    cone.position.y = shaft + head / 2;
    cylinder.renderOrder = cone.renderOrder = 10;
    arrow.add(cylinder, cone);
    arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize());
    arrow.position.copy(origin);
    return arrow;
  }

  function frameGizmo(frame, length, emphasis, colors) {
    const g = new THREE.Group();
    const R = frame.R, origin = new THREE.Vector3(...frame.origin);
    const radius = emphasis ? 0.62 : 0.45;   // mm
    for (let i = 0; i < 3; i++) {
      g.add(axisArrow(origin, new THREE.Vector3(R[0][i], R[1][i], R[2][i]), length, radius, colors.axes[i]));
    }
    const dot = new THREE.Mesh(new THREE.SphereGeometry(emphasis ? 1.6 : 1.15, 16, 12),
      new THREE.MeshBasicMaterial({ color: emphasis ? colors.accent : colors.text, depthTest: false, transparent: true }));
    dot.position.copy(origin);
    dot.renderOrder = 11;
    g.add(dot);
    return g;
  }

  /** Keep-out cone: apex at the cone base point inside the phone, opening along the frame's +Z. */
  function viewCone(frame, apex, deg, length, color) {
    const R = frame.R;
    const dir = new THREE.Vector3(R[0][2], R[1][2], R[2][2]);
    const half = THREE.MathUtils.degToRad(Math.min(deg, 170) / 2);
    const geometry = new THREE.ConeGeometry(Math.tan(half) * length, length, 48, 1, true);
    geometry.translate(0, -length / 2, 0);
    geometry.rotateX(Math.PI);   // apex at the origin, opening toward +Y
    const mesh = new THREE.Mesh(geometry,
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.12, side: THREE.DoubleSide, depthWrite: false }));
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
    mesh.position.set(...apex);
    return mesh;
  }

  function disposeGroup() {
    if (!group) return;
    scene.remove(group);
    group.traverse((o) => {
      o.geometry?.dispose();
      for (const m of [].concat(o.material ?? [])) m.dispose();
    });
    group = null;
  }

  function build(key) {
    const d = models[key];
    current = d;
    disposeGroup();
    labelBox.replaceChildren();
    labels = [];
    renderPanel(key);
    if (!renderer) return;

    const colors = {
      axes: [cssColor(root, "--pd-ax-x"), cssColor(root, "--pd-ax-y"), cssColor(root, "--pd-ax-z")],
      accent: cssColor(root, "--pd-accent"), text: cssColor(root, "--pd-text"), muted: cssColor(root, "--pd-muted"),
    };
    group = new THREE.Group();
    scene.add(group);
    const W = d.outline.width, H = d.outline.height, T = d.outline.thickness;
    const da = d.display_active_area;
    // The device origin is the centre of the display active area: (cu, cv) in the drawing's front view.
    const cu = da.left + da.width / 2, cv = da.top + da.height / 2;
    const x0 = -cu, y0 = cv - H;   // lower-left corner of the outline in the device frame
    const alpha = +$("alpha").value;
    const cornerR = Math.min(W, H) * 0.135;   // approximate, not on the drawings
    const bevel = Math.min(1.0, T * 0.12);

    // housing
    const housing = new THREE.MeshStandardMaterial({ color: 0x9aa1ab, metalness: 0.55, roughness: 0.45, transparent: true, opacity: alpha, depthWrite: alpha > 0.95 });
    group.add(slab(roundedRect(x0 + bevel, y0 + bevel, W - 2 * bevel, H - 2 * bevel, cornerR - bevel), -T, T, housing, bevel));

    // MagSafe magnet ring on the back plate (no thickness). Ring 46.00 / 54.10 mm and the clocking
    // magnet 6.00 x 19.31 mm (31.18 to 50.49 below the centre) are from Apple's Accessory Design
    // Guidelines figure 41-2, centred on the drawing's MagSafe centre.
    const ms = d.frames.magsafe;
    const noMagnets = ms && /no MagSafe/i.test(ms.note || "");
    if (ms && !noMagnets) {
      const [mx, my] = ms.origin, z = -T - 0.05;
      const ringMaterial = new THREE.MeshBasicMaterial({ color: colors.accent, transparent: true, opacity: 0.45, side: THREE.DoubleSide, depthWrite: false });
      const ring = new THREE.Mesh(new THREE.RingGeometry(23.0, 27.05, 128), ringMaterial);
      ring.position.set(mx, my, z);
      group.add(ring);
      const line = new THREE.LineBasicMaterial({ color: colors.accent });
      for (const r of [23.0, 27.05]) group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(circlePoints(mx, my, r, z - 0.01)), line));
      const clockY = my - (31.18 + 50.49) / 2;
      const clock = new THREE.Mesh(new THREE.PlaneGeometry(6.0, 19.31), ringMaterial);
      clock.position.set(mx, clockY, z);
      group.add(clock);
      const edge = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(6.0, 19.31)), line);
      edge.position.set(mx, clockY, z - 0.01);
      group.add(edge);
    } else if (ms && ms.diameter) {
      // no magnets on this model: the wireless-charging keep-out circle as a thin outline only
      group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(circlePoints(ms.origin[0], ms.origin[1], ms.diameter / 2, -T - 0.05)),
        new THREE.LineBasicMaterial({ color: colors.muted })));
    }

    // display active area on the front glass
    const display = new THREE.Mesh(
      new THREE.ShapeGeometry(roundedRect(x0 + da.left, cv - da.top - da.height, da.width, da.height, Math.max(cornerR - da.left, 2)), 24),
      new THREE.MeshStandardMaterial({ color: 0x0d1320, roughness: 0.15, metalness: 0.1, transparent: true, opacity: Math.min(1, alpha + 0.3) }));
    display.position.z = 0.02;
    group.add(display);

    // front camera cut-out (pill / notch / dot): visual only, sized from the dataset's note when it gives one
    const fc = d.frames.cam_front_optical;
    if (fc) {
      const [fx, fy] = fc.origin, source = fc.source || "";
      const pill = source.match(/pill (\d+\.\d+) x (\d+\.\d+)/) || source.match(/pill (\d+\.\d+)()/);
      let shape = null;
      if (/notch model/.test(source)) {
        const w = pill ? +pill[1] : 25.4;
        shape = roundedRect(fx - w / 2, fy - 2.85, w, (cv - da.top) - (fy - 2.85), 2.85);
      } else if (pill) {
        const length = +pill[1], h = pill[2] ? +pill[2] : 5.4;
        shape = roundedRect(fx + h / 2 - length, fy - h / 2, length, h, h / 2);
      }
      if (shape) {
        const cutout = new THREE.Mesh(new THREE.ShapeGeometry(shape, 24), new THREE.MeshBasicMaterial({ color: 0x000000 }));
        cutout.position.z = 0.04;
        group.add(cutout);
      }
      group.add(disc(1.6, fx, fy, 0.06, 0x1a2a4a, false));
    }

    // rear camera plateau (approximate outline: bounding box of the lenses plus 3 mm) and the lenses
    const heights = d.rear_heights_from_back || {};
    const zBack = -T, plateau = heights.camera_plateau, glass = heights.camera_glass;
    const rearItems = [];
    for (const name of ["main", "ultra_wide", "telephoto"]) {
      const cam = d.cameras[name];
      if (cam) rearItems.push({ p: d.frames[cam.frame].origin, r: (cam.window_diameter || 12) / 2, lens: true });
    }
    for (const e of Object.values(d.extras || {})) {
      if (e.position_in_body[2] < -0.5) rearItems.push({ p: e.position_in_body, r: (e.diameter || Math.max(e.width || 0, e.height || 0) || 3) / 2, lens: false });
    }
    let zTop = zBack;
    if (plateau && rearItems.length) {
      let a = Infinity, b = -Infinity, c = Infinity, e = -Infinity;
      for (const it of rearItems) { a = Math.min(a, it.p[0] - it.r); b = Math.max(b, it.p[0] + it.r); c = Math.min(c, it.p[1] - it.r); e = Math.max(e, it.p[1] + it.r); }
      const pad = 3;
      a = Math.max(a - pad, x0 + 1.2); b = Math.min(b + pad, x0 + W - 1.2); e = Math.min(e + pad, cv - 1.2); c -= pad;
      if (b - a > 0.6 * W) { a = x0 + 1.2; b = x0 + W - 1.2; }   // full-width camera bar (17 Pro, 18 Pro, Air)
      const material = new THREE.MeshStandardMaterial({ color: 0x80878f, metalness: 0.5, roughness: 0.35, transparent: true, opacity: Math.min(1, alpha + 0.15) });
      group.add(slab(roundedRect(a, c, b - a, e - c, Math.min(8, (e - c) / 2)), zBack - plateau, plateau, material, 0.3));
      zTop = zBack - plateau;
    }
    for (const it of rearItems) {
      if (!it.lens) continue;
      const zGlass = glass != null ? zBack - glass : zTop;
      const length = Math.max(zTop - zGlass, 0.3);
      const barrel = new THREE.Mesh(new THREE.CylinderGeometry(it.r, it.r, length, 48, 1, true),
        new THREE.MeshStandardMaterial({ color: 0x5b6169, metalness: 0.8, roughness: 0.3, side: THREE.DoubleSide }));
      barrel.rotation.x = Math.PI / 2;
      barrel.position.set(it.p[0], it.p[1], zGlass + length / 2);
      group.add(barrel);
      group.add(disc(it.r * 0.82, it.p[0], it.p[1], zGlass - 0.01, 0x0b1430, true));
    }

    // flash, microphone, LiDAR, ...
    if ($("extras").checked) {
      for (const [name, e] of Object.entries(d.extras || {})) {
        const p = e.position_in_body, r = (e.diameter || 2.5) / 2, front = p[2] > -0.5;
        group.add(disc(Math.min(r, 4), p[0], p[1], p[2] + (front ? 0.05 : -0.05), name === "flash" ? 0xf3e4b0 : 0x2a2f38, !front));
      }
    }

    // frames
    const length = Math.max(W, H) * 0.135;
    for (const name of ORDER) {
      const frame = d.frames[name];
      if (!frame) continue;
      group.add(frameGizmo(frame, name === selected ? length * 1.3 : length, name === selected, colors));
      const el = document.createElement("div");
      el.className = "pd-label" + (name === selected ? " pd-selected" : "");
      el.textContent = strings.frames[name];
      labelBox.appendChild(el);
      labels.push({ el, p: new THREE.Vector3(...frame.origin) });
      const cam = d.cameras[CAMERA_OF[name]];
      if ($("cones").checked && cam?.keepout_cone_deg && cam.keepout_cone_base) {
        group.add(viewCone(frame, cam.keepout_cone_base, cam.keepout_cone_deg, 26, colors.accent));
      }
    }
    labelBox.hidden = !$("showLabels").checked;
    controls.target.set(0, 0, -T / 2);
  }

  // ---------- panel ----------
  function frameDetails(name, frame, d) {
    const cam = d.cameras[CAMERA_OF[name]];
    const kind = name === "device" ? "device" : name === "magsafe" ? "magsafe" : name === "cam_front_optical" ? "front" : "rear";
    const lines = [esc(fill(strings.definitions[kind], { deg: frame.orientation?.rotation_deg ?? "" }))];
    for (const note of [frame.source, frame.role_basis, frame.note]) if (note) lines.push(esc(note));
    if (cam?.keepout_cone_deg) lines.push(esc(fill(strings.cone, { deg: cam.keepout_cone_deg })));
    if (frame.orientation && !frame.orientation.verified) lines.push(esc(strings.orientationUntested));
    return lines.join("<br>");
  }

  function renderPanel(key) {
    const d = models[key];
    const ids = d.identifiers.length ? d.identifiers.join(", ") : strings.identifierUnknown;
    $("drawing").innerHTML = `${esc(strings.identifier)} <code>${esc(ids)}</code><br>` +
      `${esc(strings.drawingDated)} ${esc(d.drawing.sheet_date)}, <a href="${esc(d.drawing.url)}" target="_blank" rel="noopener">${esc(strings.drawingPdf)}</a>`;
    const o = d.outline;
    $("specs").innerHTML = [[strings.width, o.width], [strings.height, o.height], [strings.thickness, o.thickness]]
      .map(([label, v]) => `<div class="pd-spec"><b>${v.toFixed(2)}</b><span>${esc(label)} mm</span></div>`).join("");

    // Who checked the dimensions: review.dimensions is "auto" until a person confirms the model.
    const review = d.review || { dimensions: "auto" };
    const human = review.dimensions === "human";
    const badge = $("review");
    badge.textContent = human ? strings.reviewHuman : strings.reviewAuto;
    badge.className = "pd-badge " + (human ? "pd-ok" : "pd-pending");
    $("reviewNote").textContent = (human ? strings.reviewHumanNote : strings.reviewAutoNote) + (human && review.date ? ` (${review.date})` : "");

    // downloads: one link per format of this model, from the manifest
    const files = assets?.manifest.models[key]?.files;
    $("downloads").hidden = !files;
    if (files) {
      $("downloadLinks").innerHTML = Object.entries(files).map(([format, file]) =>
        `<a class="pd-button" href="${esc(assets.base + file.path)}" download>${esc(strings.formats[format] ?? format)}` +
        `<span class="pd-size">${(file.bytes / 1024).toFixed(file.bytes < 10240 ? 1 : 0)} KB</span></a>`).join("");
    }

    const box = $("frames");
    box.replaceChildren();
    for (const name of ORDER) {
      const frame = d.frames[name];
      const button = document.createElement("button");
      button.type = "button";
      button.className = "pd-frame";
      button.setAttribute("aria-pressed", String(name === selected));
      if (!frame) {
        button.disabled = true;
        button.innerHTML = `<div class="pd-frame-top"><span class="pd-frame-name">${esc(strings.frames[name])}</span><span class="pd-badge">${esc(strings.missing)}</span></div>`;
        box.appendChild(button);
        continue;
      }
      const estimated = frame.provenance === "estimated";
      button.innerHTML =
        `<div class="pd-frame-top"><span class="pd-frame-name">${esc(strings.frames[name])}</span>` +
        `<span class="pd-badge${estimated ? " pd-pending" : ""}">${esc(strings.provenance[frame.provenance] ?? frame.provenance)}</span></div>` +
        `<div class="pd-frame-key">${esc(name)}　${esc(rotationText(frame.R))}</div>` +
        `<div class="pd-frame-xyz">x ${signed(frame.origin[0])}　y ${signed(frame.origin[1])}　z ${signed(frame.origin[2])}</div>` +
        `<div class="pd-frame-details">${frameDetails(name, frame, d)}</div>`;
      button.addEventListener("click", () => { selected = name; build(select.value); });
      box.appendChild(button);
    }
  }

  // ---------- views ----------
  function setView(view) {
    if (!renderer) return;
    const T = current.outline.thickness, distance = Math.max(current.outline.height, current.outline.width) * 2.6;
    const target = new THREE.Vector3(0, 0, -T / 2);
    const directions = { iso: [0.75, 0.35, -0.9], front: [0, 0, 1], back: [0, 0, -1], side: [1, 0.05, -0.0001] };
    camera.position.copy(target).add(new THREE.Vector3(...directions[view]).normalize().multiplyScalar(distance));
    camera.up.set(0, 1, 0);
    controls.target.copy(target);
    controls.update();
  }
  root.querySelectorAll("[data-pd-view]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.pdView)));

  select.addEventListener("change", () => {
    try { localStorage.setItem(STORE_KEY, select.value); } catch { /* storage blocked */ }
    history.replaceState(null, "", "#" + select.value);
    build(select.value);
    setView("iso");
  });
  window.addEventListener("hashchange", () => {
    const key = decodeURIComponent(location.hash.slice(1));
    if (models[key] && key !== select.value) { select.value = key; build(key); setView("iso"); }
  });
  for (const name of ["alpha", "cones", "extras"]) $(name).addEventListener("input", () => build(select.value));
  $("showLabels").addEventListener("change", (e) => { labelBox.hidden = !e.target.checked; });
  $("copy").addEventListener("click", () => {
    const message = $("copyMessage");
    const text = JSON.stringify(models[select.value], null, 1);
    if (!navigator.clipboard) { message.textContent = strings.copyBlocked; return; }
    navigator.clipboard.writeText(text).then(() => { message.textContent = strings.copied; }, () => { message.textContent = strings.copyBlocked; });
  });
  // The scene takes its colours from CSS: rebuild when the site theme changes.
  new MutationObserver(() => build(select.value)).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  // ---------- loop ----------
  build(select.value);
  if (!renderer) return;
  function resize() {
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(stage);
  const projected = new THREE.Vector3();
  function tick() {
    controls.update();
    renderer.render(scene, camera);
    if (!labelBox.hidden) {
      const w = stage.clientWidth, h = stage.clientHeight;
      for (const label of labels) {
        projected.copy(label.p).project(camera);
        label.el.style.left = ((projected.x + 1) / 2) * w + "px";
        label.el.style.top = ((1 - projected.y) / 2) * h + "px";
        label.el.style.display = projected.z < 1 ? "" : "none";
      }
    }
    requestAnimationFrame(tick);
  }
  resize();
  setView("iso");
  tick();
}
