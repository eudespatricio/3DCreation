/**
 * Forge3D Studio Web — Workspace 2: Catálogo de Saídas & Inspetor 3D (Viewport, Texturas/Concept, QC G1-G16, Manifesto).
 */

import { api, esc, fmtBytes, fmtNum, toast } from './api.js';
import { Viewer3D } from './viewer3d.js';

export class OutputsView {
  constructor(rootEl, { onJumpVerify, onJumpExport, onOpenLightbox } = {}) {
    this.root = rootEl;
    this.onJumpVerify = onJumpVerify;
    this.onJumpExport = onJumpExport;
    this.onOpenLightbox = onOpenLightbox;
    this.filters = { q: '', projeto: '', perfil: '', rota: '', destino: '', max_tris: '' };
    this.catalog = { total: 0, filtros: { projetos: [], perfis: [], rotas: [] }, ativos: [] };
    this.destinos = [];
    this.selected = null; // response from /api/asset
    this.subTab = 'viewport'; // 'viewport' | 'textures' | 'qc' | 'manifest'
    this.viewer = null;
    this.viewerStatus = { mode: 'init', label: 'Inicializando Viewport 3D...', clips: [] };
  }

  async init(destinations) {
    if (destinations?.ok) this.destinos = destinations.destinos || [];
    this._renderSkeleton();
    await this.refreshAssets();
  }

  async openAsset(destino, assetId) {
    if (!destino || !assetId) return;
    const res = await api.asset(destino, assetId);
    if (!res.ok) return toast(`Falha ao abrir asset ${assetId}: ${res.mensagem}`, 'error');
    this.selected = res;
    this._renderList();
    this._renderInspector();
    this._loadSelectedIntoViewer();
  }

  async refreshAssets() {
    const res = await api.assets(this.filters);
    if (res.ok) {
      this.catalog = {
        total: res.total ?? (res.ativos || []).length,
        filtros: res.filtros || { projetos: [], perfis: [], rotas: [] },
        ativos: res.ativos || [],
      };
    }
    this._populateFilterOptions();
    this._renderList();
    if (!this.selected && this.catalog.ativos.length > 0) {
      const first = this.catalog.ativos[0];
      await this.openAsset(first.destino, first.asset_id);
    } else {
      this._renderInspector();
    }
  }

  _renderSkeleton() {
    this.root.innerHTML = `
      <div class="out-layout">
        <aside class="out-sidebar card">
          <div class="card-header">
            <h3>Catálogo de Assets Publicados</h3>
            <button class="btn btn-xs btn-sec" id="out-btn-refresh">↻ Atualizar</button>
          </div>
          <div class="out-filters">
            <input type="search" id="out-f-q" placeholder="Buscar por asset_id, tag, projeto..." value="${esc(this.filters.q)}" />
            <div class="form-grid-2">
              <select id="out-f-projeto"><option value="">Todos projetos</option></select>
              <select id="out-f-perfil"><option value="">Todos perfis</option></select>
              <select id="out-f-rota"><option value="">Todas rotas</option></select>
              <input type="number" id="out-f-tris" placeholder="Máx tris" value="${esc(this.filters.max_tris)}" />
            </div>
            <select id="out-f-destino"><option value="">Todos destinos autorizados</option></select>
          </div>
          <div id="out-kpi-bar" class="kpi-mini-row"></div>
          <div id="out-asset-list" class="out-asset-list"></div>
        </aside>

        <section class="out-inspector card">
          <div class="out-inspector-header">
            <div id="out-title-box"><h3>Selecione um asset no catálogo</h3></div>
            <div class="subtab-bar">
              ${[['viewport', 'Viewport 3D'], ['textures', 'Texturas & Concept 2D'], ['qc', 'QC Gates G1–G16 & Geometria'], ['manifest', 'Manifesto & Arquivos']].map(([k, lbl]) => `<button class="btn btn-sm ${this.subTab === k ? 'active' : ''}" data-subtab="${k}">${lbl}</button>`).join('')}
            </div>
          </div>

          <div id="out-pane-viewport" class="out-subpane ${this.subTab === 'viewport' ? '' : 'hidden'}">
            <div class="vp-toolbar">
              <span id="vp-engine-badge" class="badge badge-info">${esc(this.viewerStatus.label)}</span>
              <div class="btn-group">
                ${[['iso', '3/4'], ['front', 'Frente'], ['back', 'Costas'], ['left', 'Esq'], ['right', 'Dir'], ['top', 'Topo'], ['reset', 'Reset']].map(([p, lbl]) => `<button class="btn btn-xs" data-cam="${p}">${lbl}</button>`).join('')}
              </div>
              <div class="btn-group">
                <label class="chk-pill"><input type="checkbox" id="vp-opt-rot" /> Auto-Rotate</label>
                <label class="chk-pill"><input type="checkbox" id="vp-opt-grid" checked /> Grade</label>
                <select id="vp-opt-unit" class="input-xs"><option value="1m">1m (Godot)</option><option value="stud">1 stud (0,28m)</option></select>
                <label class="chk-pill"><input type="checkbox" id="vp-opt-axes" checked /> Eixos</label>
                <label class="chk-pill"><input type="checkbox" id="vp-opt-wire" /> Wireframe</label>
                <label class="chk-pill"><input type="checkbox" id="vp-opt-col" /> Colisor</label>
                <label class="chk-pill"><input type="checkbox" id="vp-opt-pins" checked /> Sockets/Âncoras</label>
              </div>
              <div class="vp-selectors">
                <select id="vp-sel-lod" class="input-xs"><option value="">LOD0 (Principal)</option></select>
                <select id="vp-sel-parte" class="input-xs"><option value="">Malha Completa</option></select>
              </div>
            </div>
            <div id="vp-canvas-wrap" class="vp-canvas-wrap"></div>
            <div class="vp-anim-bar">
              <label class="field-inline"><span>Animação:</span><select id="vp-anim-clip" class="input-xs"><option value="">(sem clipes)</option></select></label>
              <button class="btn btn-xs btn-sec" id="vp-anim-toggle">⏸ Pausar</button>
              <label class="field-inline"><span>Vel:</span>
                <select id="vp-anim-speed" class="input-xs"><option value="0.25">0.25x</option><option value="0.5">0.5x</option><option value="1" selected>1.0x</option><option value="1.5">1.5x</option><option value="2">2.0x</option></select>
              </label>
              <input type="range" id="vp-anim-scrub" min="0" max="100" value="0" style="flex:1" />
            </div>
          </div>

          <div id="out-pane-dynamic" class="out-subpane ${this.subTab === 'viewport' ? 'hidden' : ''}"></div>
        </section>
      </div>`;

    const wrap = this.root.querySelector('#vp-canvas-wrap');
    this.viewer = new Viewer3D(wrap, (st) => {
      this.viewerStatus = { ...this.viewerStatus, ...st };
      const b = this.root.querySelector('#vp-engine-badge');
      if (b && st.label) b.textContent = st.label;
      if (st.clips) this._populateClipsDropdown(st.clips);
    });
    this._bindSkeletonEvents();
  }

  _populateFilterOptions() {
    const shortLabel = (s) => {
      const str = String(s || '');
      if (str.length <= 34) return str;
      const parts = str.split('/').filter(Boolean);
      return parts.length >= 2 ? `…/${parts.slice(-2).join('/')}` : `…${str.slice(-31)}`;
    };
    const setOpts = (sel, items, cur, placeholder, shorten = false) => {
      const el = this.root.querySelector(sel);
      if (!el) return;
      el.innerHTML = `<option value="">${esc(placeholder)}</option>` + (items || []).map((v) => `<option value="${esc(v)}" title="${esc(v)}" ${v === cur ? 'selected' : ''}>${esc(shorten ? shortLabel(v) : v)}</option>`).join('');
    };
    const f = this.catalog.filtros || {};
    setOpts('#out-f-projeto', f.projetos, this.filters.projeto, 'Todos projetos');
    setOpts('#out-f-perfil', f.perfis, this.filters.perfil, 'Todos perfis');
    setOpts('#out-f-rota', f.rotas, this.filters.rota, 'Todas rotas');
    const destPaths = [...new Set([...(this.destinos || []).map((d) => d.caminho), ...(this.catalog.ativos || []).map((a) => a.destino)].filter(Boolean))];
    setOpts('#out-f-destino', destPaths, this.filters.destino, 'Todos destinos', true);
  }

  _bindSkeletonEvents() {
    const q = (sel) => this.root.querySelector(sel);
    q('#out-btn-refresh')?.addEventListener('click', () => this.refreshAssets());
    const bindF = (sel, key) => q(sel)?.addEventListener('change', (e) => { this.filters[key] = e.target.value; this.refreshAssets(); });
    q('#out-f-q')?.addEventListener('input', (e) => { this.filters.q = e.target.value; this.refreshAssets(); });
    bindF('#out-f-projeto', 'projeto');
    bindF('#out-f-perfil', 'perfil');
    bindF('#out-f-rota', 'rota');
    bindF('#out-f-destino', 'destino');
    bindF('#out-f-tris', 'max_tris');

    this.root.querySelectorAll('[data-subtab]').forEach((btn) => btn.addEventListener('click', () => {
      this.subTab = btn.dataset.subtab;
      this.root.querySelectorAll('[data-subtab]').forEach((b) => b.classList.toggle('active', b.dataset.subtab === this.subTab));
      q('#out-pane-viewport')?.classList.toggle('hidden', this.subTab !== 'viewport');
      q('#out-pane-dynamic')?.classList.toggle('hidden', this.subTab === 'viewport');
      if (this.subTab === 'viewport') this.viewer?.resize();
      else this._renderInspector();
    }));

    this.root.querySelectorAll('[data-cam]').forEach((btn) => btn.addEventListener('click', () => this.viewer?.setCameraPreset(btn.dataset.cam)));
    q('#vp-opt-rot')?.addEventListener('change', (e) => this.viewer?.setOption('autoRotate', e.target.checked));
    q('#vp-opt-grid')?.addEventListener('change', (e) => this.viewer?.setOption('showGrid', e.target.checked));
    q('#vp-opt-unit')?.addEventListener('change', (e) => this.viewer?.setOption('gridUnit', e.target.value));
    q('#vp-opt-axes')?.addEventListener('change', (e) => this.viewer?.setOption('showAxes', e.target.checked));
    q('#vp-opt-wire')?.addEventListener('change', (e) => this.viewer?.setOption('wireframe', e.target.checked));
    q('#vp-opt-col')?.addEventListener('change', (e) => this.viewer?.setOption('showCollider', e.target.checked));
    q('#vp-opt-pins')?.addEventListener('change', (e) => this.viewer?.setOption('showPins', e.target.checked));

    q('#vp-sel-lod')?.addEventListener('change', (e) => { if (e.target.value) this.viewer?.loadGlb(e.target.value, this._currentViewerExtras()); else this._loadSelectedIntoViewer(); });
    q('#vp-sel-parte')?.addEventListener('change', (e) => { if (e.target.value) this.viewer?.loadGlb(e.target.value, this._currentViewerExtras()); else this._loadSelectedIntoViewer(); });
    q('#vp-anim-clip')?.addEventListener('change', (e) => this.viewer?.selectClip(e.target.value));
    q('#vp-anim-toggle')?.addEventListener('click', (e) => {
      const next = !this.viewer?.opts.playing;
      this.viewer?.setPlaying(next);
      e.target.textContent = next ? '⏸ Pausar' : '▶ Reproduzir';
    });
    q('#vp-anim-speed')?.addEventListener('change', (e) => this.viewer?.setOption('speed', Number(e.target.value)));
    q('#vp-anim-scrub')?.addEventListener('input', (e) => this.viewer?.scrubNormalized(Number(e.target.value) / 100));
  }

  _renderList() {
    const kpi = this.root.querySelector('#out-kpi-bar');
    const list = this.root.querySelector('#out-asset-list');
    const ativos = this.catalog.ativos || [];
    const okCount = ativos.filter((a) => a.qc_aprovado !== false).length;
    const sumTris = ativos.reduce((acc, a) => acc + (Number(a.triangulos) || 0), 0);
    if (kpi) kpi.innerHTML = `<span><b>${ativos.length}</b> assets</span><span>QC OK: <b>${okCount}</b></span><span>Tris: <b>${fmtNum(sumTris)}</b></span>`;
    if (!list) return;
    if (!ativos.length) {
      list.innerHTML = '<p class="muted" style="padding:12px">Nenhum asset publicado encontrado para os filtros atuais.</p>';
      return;
    }
    list.innerHTML = ativos.map((a) => {
      const active = this.selected?.asset_id === a.asset_id && this.selected?.destino === a.destino;
      const thumb = a.preview_image_url ? `<img src="${esc(a.preview_image_url)}" class="asset-thumb" loading="lazy" />` : '<div class="asset-thumb asset-thumb-placeholder">3D</div>';
      return `
        <div class="asset-card ${active ? 'active' : ''}" data-aid="${esc(a.asset_id)}" data-dest="${esc(a.destino)}">
          ${thumb}
          <div class="asset-card-body">
            <div class="asset-card-top">
              <strong>${esc(a.asset_id)}</strong>
              <span class="badge ${a.qc_aprovado !== false ? 'badge-ok' : 'badge-err'}">${a.qc_aprovado !== false ? 'QC OK' : 'QC FALHOU'} ${a.gates_total ? `(${a.gates_ok}/${a.gates_total})` : ''}</span>
            </div>
            <div class="asset-card-meta">${esc(a.projeto)} · <code>${esc(a.perfil)}</code> · <span class="badge badge-route">${esc(a.rota)}</span></div>
            <div class="asset-card-sub">
              <span>${fmtNum(a.triangulos)} tris</span>
              <span>${fmtBytes(a.bytes)}</span>
              ${a.tem_lod ? '<span class="tag-xs">LOD</span>' : ''}
              ${a.tem_colisao ? '<span class="tag-xs">COL</span>' : ''}
              ${a.tem_partes ? '<span class="tag-xs">R15</span>' : ''}
              ${a.tem_texturas ? '<span class="tag-xs">PBR</span>' : ''}
            </div>
          </div>
        </div>`;
    }).join('');

    list.querySelectorAll('.asset-card').forEach((card) => card.addEventListener('click', () => this.openAsset(card.dataset.dest, card.dataset.aid)));
  }

  _currentViewerExtras() {
    if (!this.selected) return {};
    const m = this.selected.manifesto || {};
    const colFile = this.selected.colisor || (this.selected.arquivos || []).find((f) => f.papel === 'colisor');
    const colliderUrl = colFile?.url || (colFile?.caminho_abs ? api.fileUrl(colFile.caminho_abs) : null);
    const pins = [
      ...(m.sockets || []).map((s) => ({ nome: s.nome, osso: s.osso, posicao: s.posicao, tipo: 'socket' })),
      ...((m.rig || {}).ancoras || []).map((a) => ({ nome: a.junta || a.parte, posicao: a.posicao, tipo: 'ancora' })),
    ];
    return { colliderUrl, pins };
  }

  _loadSelectedIntoViewer() {
    if (!this.selected || !this.viewer) return;
    const arqs = this.selected.arquivos || [];
    const mainGlb = arqs.find((f) => f.papel === 'malha_principal' || (f.caminho || '').endsWith('.glb'));
    const mainUrl = mainGlb?.url || (mainGlb?.caminho_abs ? api.fileUrl(mainGlb.caminho_abs) : null);

    const lodSel = this.root.querySelector('#vp-sel-lod');
    if (lodSel) {
      const lods = this.selected.lods || arqs.filter((f) => (f.papel || '').startsWith('lod'));
      lodSel.innerHTML = `<option value="${esc(mainUrl || '')}">LOD0 (Principal)</option>` + lods.map((l, i) => {
        const u = l.url || (l.caminho_abs ? api.fileUrl(l.caminho_abs) : '');
        return `<option value="${esc(u)}">${esc(l.papel || `LOD${i + 1}`)} (${esc(l.caminho || '')})</option>`;
      }).join('');
    }

    const parteSel = this.root.querySelector('#vp-sel-parte');
    if (parteSel) {
      const partes = this.selected.partes || arqs.filter((f) => (f.papel || '').includes('parte'));
      parteSel.innerHTML = `<option value="${esc(mainUrl || '')}">Malha Completa</option>` + partes.map((p) => {
        const u = p.url || (p.caminho_abs ? api.fileUrl(p.caminho_abs) : '');
        return `<option value="${esc(u)}">${esc(p.nome || p.papel || p.caminho)}</option>`;
      }).join('');
    }

    const m = this.selected.manifesto || {};
    this._populateClipsDropdown((m.animacoes || []).map((a) => ({ name: a.nome, duration: a.duracao_s })));
    if (mainUrl) this.viewer.loadGlb(mainUrl, this._currentViewerExtras());
  }

  _populateClipsDropdown(clips = []) {
    const sel = this.root.querySelector('#vp-anim-clip');
    if (!sel) return;
    if (!clips.length) {
      sel.innerHTML = '<option value="">(sem clipes)</option>';
      return;
    }
    sel.innerHTML = clips.map((c) => `<option value="${esc(c.name)}">${esc(c.name)}${c.duration ? ` (${Number(c.duration).toFixed(2)}s)` : ''}</option>`).join('');
  }

  _renderInspector() {
    const titleBox = this.root.querySelector('#out-title-box');
    const dyn = this.root.querySelector('#out-pane-dynamic');
    if (!this.selected) {
      if (titleBox) titleBox.innerHTML = '<h3>Selecione um asset no catálogo</h3>';
      if (dyn) dyn.innerHTML = '<p class="muted">Nenhum asset selecionado.</p>';
      return;
    }
    const m = this.selected.manifesto || {};
    const qcOk = m.qc?.aprovado !== false;
    if (titleBox) {
      titleBox.innerHTML = `
        <div class="inspector-title-row">
          <h3><code>${esc(this.selected.asset_id)}</code></h3>
          <span class="badge ${qcOk ? 'badge-ok' : 'badge-err'}">${qcOk ? 'QC APROVADO' : 'QC REPROVADO'}</span>
          <span class="badge">${esc(m.schema || 'forge3d/manifest@7')}</span>
          <span class="badge badge-info">${esc(m.perfil || '')} · ${esc(m.determinism || 'D1')}</span>
        </div>`;
    }
    if (!dyn || this.subTab === 'viewport') return;
    if (this.subTab === 'textures') dyn.innerHTML = this._htmlTextures(m);
    else if (this.subTab === 'qc') dyn.innerHTML = this._htmlQc(m);
    else if (this.subTab === 'manifest') dyn.innerHTML = this._htmlManifest(m);

    dyn.querySelectorAll('[data-lightbox]').forEach((img) => img.addEventListener('click', () => this.onOpenLightbox?.(img.dataset.lightbox, img.dataset.title)));
    dyn.querySelector('#out-btn-verify-dest')?.addEventListener('click', () => this.onJumpVerify?.(this.selected.destino));
    dyn.querySelector('#out-btn-export-asset')?.addEventListener('click', () => this.onJumpExport?.(this.selected));
  }

  _htmlTextures(m) {
    const arqs = this.selected.arquivos || [];
    const imgs = this.selected.texturas?.length
      ? this.selected.texturas
      : arqs.filter((f) => /\.(png|jpg|jpeg|webp)$/i.test(f.caminho || ''));
    const cj = this.selected.concept_json || null;
    return `
      <div class="inspector-scroll">
        <h4>Mapas PBR &amp; Concept Sheets 2D (${imgs.length})</h4>
        ${imgs.length ? `<div class="tex-gallery">${imgs.map((img) => {
          const url = img.url || api.fileUrl(img.caminho_abs || img.caminho);
          return `<div class="tex-card"><img src="${esc(url)}" data-lightbox="${esc(url)}" data-title="${esc(img.papel || img.caminho)}" /><div class="tex-card-meta"><strong>${esc(img.papel || 'textura')}</strong><span>${esc(img.caminho)} · ${fmtBytes(img.bytes)}</span></div></div>`;
        }).join('')}</div>` : '<p class="muted">Este asset utiliza paleta de vértices/material sem texturas PNG externas.</p>'}
        ${cj ? `<div class="card" style="margin-top:12px"><h4>Proveniência de Concept 2D (<code>_concept.json</code>)</h4><div class="kv-grid"><div><span>Modelo:</span><code>${esc(cj.modelo || cj.provider || '—')}</code></div><div><span>Seed:</span><code>${esc(cj.seed ?? '—')}</code></div><div><span>Vistas:</span><code>${esc(cj.vistas ?? 1)}</code></div><div><span>Dimensões:</span><code>${esc(cj.largura || '?')}×${esc(cj.altura || '?')}</code></div></div><p style="margin-top:6px"><b>Prompt Final:</b> <code>${esc(cj.prompt_final || cj.prompt || '—')}</code></p></div>` : ''}
      </div>`;
  }

  _htmlQc(m) {
    const gates = m.qc?.gates || [];
    const g = m.geometry || {};
    const bbox = (g.bbox_m || []).map((n) => Number(n).toFixed(3)).join(' × ');
    const u = m.unidades_export || {};
    const o = m.orientacao_export || {};
    const rig = m.rig || {};
    return `
      <div class="inspector-scroll">
        <div class="kpi-row">
          <div class="kpi-box"><span>Triângulos</span><strong>${fmtNum(g.triangulos)}</strong></div>
          <div class="kpi-box"><span>Vértices</span><strong>${fmtNum(g.vertices)}</strong></div>
          <div class="kpi-box"><span>Materiais</span><strong>${fmtNum(g.materiais)}</strong></div>
          <div class="kpi-box"><span>BBox (m)</span><strong>${esc(bbox || '—')}</strong></div>
          <div class="kpi-box"><span>Escala Saída</span><strong>${esc(u.escala_saida ?? 1)} (${esc(u.metros_por_unidade ?? 1)} m/u)</strong></div>
          <div class="kpi-box"><span>Eixos glTF</span><strong>F:${esc(o.frente_gltf || '+Z')} C:${esc(o.cima_gltf || '+Y')}</strong></div>
        </div>
        <h4>Portões de Qualidade (Gates G1–G16 · ${gates.length} avaliados)</h4>
        <div class="table-scroll"><table class="data-table">
          <thead><tr><th>Gate</th><th>Status</th><th>Medido</th><th>Limite</th><th>Código</th></tr></thead>
          <tbody>
            ${gates.map((gt) => `<tr><td><strong>${esc(gt.id)}</strong></td><td><span class="badge ${gt.status === 'ok' ? 'badge-ok' : gt.status === 'warn' ? 'badge-warn' : 'badge-err'}">${esc(gt.status)}</span></td><td><code class="code-wrap">${esc(JSON.stringify(gt.medido || {}))}</code></td><td><code class="code-wrap">${esc(JSON.stringify(gt.limite || {}))}</code></td><td><code>${esc(gt.codigo || '—')}</code></td></tr>`).join('')}
          </tbody>
        </table></div>
        <div class="form-grid-2" style="margin-top:12px">
          <div class="card">
            <h4>Rig, Esqueleto &amp; Sockets</h4>
            <p>Modo: <code>${esc(rig.modo || 'none')}</code> · Esqueleto: <code>${esc(rig.esqueleto || m.esqueleto || '—')}</code> · Ossos: <b>${esc(rig.ossos ?? (m.ossos || []).length)}</b></p>
            ${(m.sockets || []).length ? `<div class="table-scroll"><table class="data-table"><thead><tr><th>Socket</th><th>Osso</th><th>Posição</th></tr></thead><tbody>${(m.sockets || []).map((s) => `<tr><td><code>${esc(s.nome)}</code></td><td>${esc(s.osso)}</td><td><code>${esc((s.posicao || []).map((v) => Number(v).toFixed(3)).join(', '))}</code></td></tr>`).join('')}</tbody></table></div>` : '<p class="muted">Sem sockets declarados.</p>'}
          </div>
          <div class="card">
            <h4>Clipes de Animação (${(m.animacoes || []).length})</h4>
            ${(m.animacoes || []).length ? `<div class="table-scroll"><table class="data-table"><thead><tr><th>Clipe</th><th>Duração</th><th>FPS</th><th>Frames</th></tr></thead><tbody>${(m.animacoes || []).map((a) => `<tr><td><code>${esc(a.nome)}</code></td><td>${esc(a.duracao_s ?? '—')}s</td><td>${esc(a.fps ?? 24)}</td><td>${esc(a.frames ?? '—')}</td></tr>`).join('')}</tbody></table></div>` : '<p class="muted">Sem animações no manifesto.</p>'}
          </div>
        </div>
      </div>`;
  }

  _htmlManifest(m) {
    const arqs = [...(this.selected.arquivos || []), ...(this.selected.exports_adjacentes || [])];
    const zipUrl = this.selected.bundle_zip_url || api.bundleZipUrl(this.selected.destino, this.selected.asset_id);
    return `
      <div class="inspector-scroll">
        <div class="sb-toolbar-group" style="margin-bottom:10px">
          <a class="btn btn-pri" href="${esc(zipUrl)}" download>⬇ Baixar Pacote (.zip)</a>
          <button class="btn btn-sec" id="out-btn-verify-dest">✔ Verificar Destino (verify)</button>
          <button class="btn btn-sec" id="out-btn-export-asset">⇄ Exportar este Asset (.rbxlx / sync)</button>
        </div>
        <h4>Arquivos Publicados &amp; Hashes SHA-256 (${arqs.length})</h4>
        <div class="table-scroll"><table class="data-table">
          <thead><tr><th>Arquivo</th><th>Papel</th><th>Tamanho</th><th>SHA-256</th><th>Status</th><th>Download</th></tr></thead>
          <tbody>
            ${arqs.map((f) => {
              const dl = f.download_url || api.fileUrl(f.caminho_abs || f.caminho, true);
              return `<tr><td><code>${esc(f.caminho)}</code></td><td><span class="badge">${esc(f.papel || 'export')}</span></td><td>${fmtBytes(f.bytes)}</td><td><code>${esc((f.sha256 || '').slice(0, 24))}…</code></td><td><span class="badge ${f.existe !== false ? 'badge-ok' : 'badge-err'}">${f.existe !== false ? 'Íntegro' : 'Ausente'}</span></td><td><a class="btn btn-xs btn-sec" href="${esc(dl)}" download>Baixar</a></td></tr>`;
            }).join('')}
          </tbody>
        </table></div>
        <h4 style="margin-top:12px">Documento Completo (<code>${esc(this.selected.asset_id)}.manifest.json</code>)</h4>
        <pre class="json-viewer">${esc(JSON.stringify(m, null, 2))}</pre>
      </div>`;
  }
}
