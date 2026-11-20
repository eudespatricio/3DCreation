/**
 * Forge3D Studio Web — Workspace 1: Construtor Visual spec@6, Editor YAML, Plan G11 e Execução.
 */

import { STATIC_ENUMS, api, createDefaultSpec, esc, fmtBytes, fmtNum, specToYaml, toast } from './api.js';

const opts = (arr, cur, emptyLabel = null) =>
  (emptyLabel !== null ? `<option value="">${esc(emptyLabel)}</option>` : '') +
  arr.map((v) => `<option value="${esc(v)}" ${v === cur ? 'selected' : ''}>${esc(v)}</option>`).join('');

export class SpecBuilderView {
  constructor(rootEl, { onOpenAsset, onJobUpdate } = {}) {
    this.root = rootEl;
    this.onOpenAsset = onOpenAsset;
    this.onJobUpdate = onJobUpdate;
    this.meta = { perfis: [], exemplos: [], clipes: STATIC_ENUMS.clipes, sockets: STATIC_ENUMS.sockets, partes_r15: STATIC_ENUMS.partes_r15 };
    this.allowlist = [];
    this.doc = createDefaultSpec();
    this.yamlText = specToYaml(this.doc);
    this.viewMode = 'split';
    this.selectedExample = '';
    this.activeJobId = null;
    this._pollTimer = null;
    this.uploadsMeta = {};
  }

  init(meta, destinations) {
    if (meta?.ok) this.meta = { ...this.meta, ...meta };
    if (destinations?.ok) this.allowlist = destinations.allowlist || [];
    this.render();
  }

  getYaml() {
    return this.root.querySelector('#sb-yaml-editor')?.value ?? this.yamlText;
  }

  syncDocToYaml() {
    this.yamlText = specToYaml(this.doc);
    const ta = this.root.querySelector('#sb-yaml-editor');
    if (ta) ta.value = this.yamlText;
  }

  render() {
    const perfis = this.meta.perfis?.length
      ? this.meta.perfis
      : ['godot4', 'godot4-aa', 'roblox-r15', 'roblox-aa-80'].map((nome) => ({ nome, resumo: {} }));
    const curPerfil = perfis.find((p) => p.nome === this.doc.perfil)?.resumo || {};
    const uRaw = curPerfil.unidades;
    const unidLabel = uRaw && typeof uRaw === 'object' ? `${uRaw.metros_por_unidade ?? 1} m/u` : String(uRaw || '1 m/u');
    const escLabel = curPerfil.escala_saida ?? (uRaw && typeof uRaw === 'object' ? uRaw.escala_saida : null) ?? 1;
    const [req, pol, rbx] = [this.doc.requisicao || {}, this.doc.politica || {}, this.doc.roblox_render || {}];
    const orc = this.doc.orcamento_cena || { triangulos_max: 400000, draw_calls_max: 400, vram_mb_max: 200 };

    this.root.innerHTML = `
      <div class="sb-toolbar card">
        <div class="sb-toolbar-group">
          <label class="field-inline"><span>Exemplo:</span>
            <select id="sb-example-select"><option value="">— Selecionar exemplo —</option>
              ${(this.meta.exemplos || []).map((ex) => `<option value="${esc(ex.nome)}" ${ex.nome === this.selectedExample ? 'selected' : ''}>${esc(ex.nome)} (${esc(ex.perfil || '')} · ${esc(ex.itens ?? '?')} itens)</option>`).join('')}
            </select>
          </label>
          <button class="btn btn-sec" id="sb-btn-load-ex">Carregar</button>
          <button class="btn btn-sec" id="sb-btn-new">Novo spec@6</button>
          <button class="btn btn-sec" id="sb-btn-migrate">Migrar p/ spec@6</button>
        </div>
        <div class="sb-toolbar-group">
          <input type="text" id="sb-save-name" class="input-sm" value="${esc(this.doc.projeto || 'lote_studio')}.yaml" />
          <button class="btn btn-sec" id="sb-btn-save">Salvar Lote</button>
          <div class="btn-group">
            ${[['split', 'Split'], ['visual', 'Construtor Visual'], ['yaml', 'Editor YAML']].map(([m, lbl]) => `<button class="btn btn-sm ${this.viewMode === m ? 'active' : ''}" data-mode="${m}">${lbl}</button>`).join('')}
          </div>
        </div>
      </div>

      <div class="sb-workspace mode-${esc(this.viewMode)}">
        <div class="sb-visual-pane">
          <div class="card sb-global-card">
            <div class="card-header">
              <h3>Cabeçalho do Lote (<code>forge3d/spec@6</code>)</h3>
              <span class="badge badge-info">Perfil: ${esc(this.doc.perfil)} · Escala: ${esc(escLabel)} · Unid: ${esc(unidLabel)}</span>
            </div>
            <div class="form-grid-4">
              <label><span>Projeto (slug)</span><input type="text" data-g="projeto" value="${esc(this.doc.projeto || '')}" /></label>
              <label><span>Perfil de Exportação</span><select data-g="perfil">${opts(perfis.map((p) => p.nome), this.doc.perfil)}</select></label>
              <label><span>Estilo Global</span><select data-g="estilo_global">${opts(STATIC_ENUMS.estilos, this.doc.estilo_global)}</select></label>
              <label><span>Raiz Allowlist</span><select id="sb-allowlist-pick">${opts(this.allowlist, '', '— Escolher raiz autorizada —')}</select></label>
            </div>
            <div class="form-grid-2" style="margin-top:8px">
              <label><span>Destino de Exportação (sob allowlist / ext4)</span><input type="text" data-g="destino_exportacao" value="${esc(this.doc.destino_exportacao || '')}" /></label>
              <div>
                <span class="field-label">Paleta Global Hex (${(this.doc.paleta || []).length} cores)</span>
                <div class="swatch-bar">
                  ${(this.doc.paleta || []).map((c, idx) => `<input type="color" class="color-swatch" data-pal="${idx}" value="${esc(c)}" title="${esc(c)}" />`).join('')}
                  <button class="btn btn-xs" id="sb-add-color">+ Cor</button>
                  <button class="btn btn-xs" id="sb-del-color">−</button>
                </div>
              </div>
            </div>
            <details class="sb-details">
              <summary>Orçamento de Cena (Gate G11), Política, Requisição &amp; Roblox Render</summary>
              <div class="form-grid-4" style="margin-top:8px">
                <label><span>G11 Triângulos Cena Máx</span><input type="number" data-orc="triangulos_max" value="${esc(orc.triangulos_max ?? 400000)}" /></label>
                <label><span>G11 Draw Calls Máx</span><input type="number" data-orc="draw_calls_max" value="${esc(orc.draw_calls_max ?? 400)}" /></label>
                <label><span>G11 VRAM Texturas (MB)</span><input type="number" data-orc="vram_mb_max" value="${esc(orc.vram_mb_max ?? orc.vram_texturas_mb_max ?? 200)}" /></label>
                <label><span>Política de Falha</span><select data-pol="falha">${opts(['continuar', 'abortar'], pol.falha || 'continuar')}</select></label>
                <label><span>Custo Máx (min)</span><input type="number" data-pol="custo_max_min" value="${esc(pol.custo_max_min ?? 30)}" /></label>
                <label><span>Seed Base</span><input type="number" data-pol="seed_base" value="${esc(pol.seed_base ?? 42)}" /></label>
                <label><span>Requisição ID</span><input type="text" data-req="id" value="${esc(req.id || '')}" /></label>
                <label><span>Isolamento Cache</span><select data-req="isolamento">${opts(['padrao', 'estrito'], req.isolamento || 'padrao')}</select></label>
                <label><span>Roblox Lighting</span><select data-rbx="lighting_technology">${opts(['Future', 'ShadowMap', 'Voxel', 'Compatibility'], rbx.lighting_technology || 'Future')}</select></label>
                <label><span>RenderFidelity Padrão</span><select data-rbx="render_fidelity_padrao">${opts(['Precise', 'Automatic', 'Performance'], rbx.render_fidelity_padrao || 'Precise')}</select></label>
                <label class="chk-label"><input type="checkbox" data-rbx-bool="surface_appearance" ${rbx.surface_appearance !== false ? 'checked' : ''}/> SurfaceAppearance 4 Canais</label>
                <label class="chk-label"><input type="checkbox" data-rbx-bool="strip_embedded_textures_glb" ${rbx.strip_embedded_textures_glb !== false ? 'checked' : ''}/> Strip Texturas GLB Upload</label>
              </div>
            </details>
          </div>
          <div class="sb-items-header">
            <h3>Itens do Lote (<code>lote[]</code> · ${(this.doc.lote || []).length})</h3>
            <button class="btn btn-pri" id="sb-add-item">+ Adicionar Item ao Lote</button>
          </div>
          <div id="sb-items-list">${(this.doc.lote || []).map((item, idx) => this._renderItemCard(item, idx)).join('')}</div>
        </div>
        <div class="sb-yaml-pane card">
          <div class="card-header">
            <h3>Editor YAML (<code>spec@6</code>)</h3>
            <button class="btn btn-xs btn-sec" id="sb-sync-yaml-to-vis">⇐ Aplicar YAML no Visual</button>
          </div>
          <textarea id="sb-yaml-editor" class="yaml-textarea" spellcheck="false">${esc(this.yamlText)}</textarea>
        </div>
      </div>

      <div class="sb-exec-bar card">
        <div class="sb-exec-toggles">
          <label class="chk-label"><input type="checkbox" id="sb-opt-publish" checked /> Publicar no destino</label>
          <label class="chk-label"><input type="checkbox" id="sb-opt-nocache" /> Ignorar cache (<code>--no-cache</code>)</label>
          <label class="chk-label"><input type="checkbox" id="sb-opt-cleandest" /> Limpar órfãos no destino</label>
        </div>
        <div class="sb-exec-actions">
          <button class="btn btn-sec" id="sb-btn-validate">Validar Spec</button>
          <button class="btn btn-sec" id="sb-btn-plan">Planejar (Gate G11)</button>
          <button class="btn btn-pri" id="sb-btn-run">▶ Executar Pipeline</button>
          <button class="btn btn-danger" id="sb-btn-cancel" ${this.activeJobId ? '' : 'disabled'}>⏹ Cancelar Job</button>
        </div>
      </div>

      <div id="sb-output-drawer" class="card sb-drawer">
        <div class="card-header"><h3>Console &amp; Diagnóstico de Planejamento / Execução</h3><span id="sb-drawer-status" class="badge">Pronto</span></div>
        <div id="sb-drawer-body" class="sb-drawer-body"><p class="muted">Use <b>Validar Spec</b>, <b>Planejar (Gate G11)</b> ou <b>Executar Pipeline</b> para inspecionar o lote.</p></div>
      </div>`;
    this._bindEvents();
  }

  _renderItemCard(item, idx) {
    const clipes = this.meta.clipes?.length ? this.meta.clipes : STATIC_ENUMS.clipes;
    const sockets = this.meta.sockets?.length ? this.meta.sockets : STATIC_ENUMS.sockets;
    const [selClipes, selSockets] = [new Set(item.clipes || []), new Set(item.sockets || [])];
    const [det, rig, partesCount] = [item.detalhe_alto || {}, item.rig || {}, (item.partes || []).length];
    const mod = item.modular || { grade: [5, 2], modulos: ['sala_base', 'corredor'], setor: [0, 0], tamanho_modulo: 4.0 };
    const [origMeta, refMeta] = [this.uploadsMeta[`${idx}:origem`], this.uploadsMeta[`${idx}:referencia_estilo`]];

    return `
      <div class="card sb-item-card" data-idx="${idx}">
        <div class="card-header">
          <div class="sb-item-title">
            <span class="badge badge-accent">#${idx + 1}</span>
            <strong>${esc(item.id || 'item.sem.id')}</strong>
            <span class="badge">${esc(item.tipo || 'prop_estatico')}</span>
            <span class="badge badge-route">${esc(item.rota || 'blocky')}</span>
          </div>
          <div class="btn-group">
            <button class="btn btn-xs btn-sec" data-act="dup" data-idx="${idx}">Duplicar</button>
            <button class="btn btn-xs btn-danger" data-act="del" data-idx="${idx}">Remover</button>
          </div>
        </div>
        <div class="form-grid-4">
          <label><span>ID do Asset</span><input type="text" data-f="id" value="${esc(item.id || '')}" /></label>
          <label><span>Tipo</span><select data-f="tipo">${opts(STATIC_ENUMS.tipos, item.tipo)}</select></label>
          <label><span>Rota / Sub-rota</span><select data-f="rota">${opts(STATIC_ENUMS.rotas, item.rota)}</select></label>
          <label><span>Qualidade</span><select data-f="qualidade">${opts(STATIC_ENUMS.qualidades, item.qualidade || '', '(padrão do perfil)')}</select></label>
          <label><span>Altura (m)</span><input type="number" step="0.05" data-f-num="altura_metros" value="${esc(item.altura_metros ?? 1.0)}" /></label>
          <label><span>Pivô</span><select data-f="pivot">${opts(STATIC_ENUMS.pivots, item.pivot || 'base')}</select></label>
          <label><span>Limite Triângulos</span><input type="number" step="100" data-f-int="limite_triangulos" value="${esc(item.limite_triangulos ?? '')}" placeholder="auto perfil" /></label>
          <label><span>Qtd. em Cena (G11)</span><input type="number" min="0" data-f-int="quantidade_cena" value="${esc(item.quantidade_cena ?? 1)}" /></label>
        </div>
        <div class="form-grid-4" style="margin-top:8px">
          <label class="span-2"><span>Prompt Descritivo (mesh / concept / procedural)</span><input type="text" data-f="prompt" value="${esc(item.prompt || '')}" placeholder="Ex: bau medieval de carvalho e ferro forjado, estilizado PBR" /></label>
          <label><span>Seed (D2)</span><input type="number" data-f-int="seed" value="${esc(item.seed ?? '')}" placeholder="ex: 42" /></label>
          <label><span>LODs (%)</span><input type="text" data-f-lod="lod" value="${esc((item.lod || [100]).join(', '))}" placeholder="100, 50, 25" /></label>
          <label><span>Material</span><select data-f="material">${opts(STATIC_ENUMS.materiais, item.material || 'opaque')}</select></label>
          <label><span>Material Procedural PBR</span><select data-f="material_procedural">${opts(STATIC_ENUMS.materiais_procedurais, item.material_procedural || '', '(nenhum)')}</select></label>
          <label><span>Provider Conceito</span><select data-f="provider_conceito">${opts(STATIC_ENUMS.providers_conceito, item.provider_conceito || '', '(auto)')}</select></label>
          <label><span>Vistas Concept</span><select data-f-int="vistas"><option value="">1 (frontal)</option><option value="1" ${item.vistas === 1 ? 'selected' : ''}>1 vista</option><option value="4" ${item.vistas === 4 ? 'selected' : ''}>4 vistas (Gemini/Cycles)</option></select></label>
        </div>
        <div class="form-grid-2" style="margin-top:8px">
          <div class="upload-box" data-drop="origem" data-idx="${idx}">
            <div class="upload-row">
              <label style="flex:1"><span>Origem (<code>.glb/.obj/.png/.webp</code>)</span><input type="text" data-f="origem" value="${esc(item.origem || '')}" placeholder="Arraste arquivo ou informe caminho..." /></label>
              <label class="btn btn-xs btn-sec upload-btn">Enviar Arquivo<input type="file" data-upload="origem" data-idx="${idx}" accept=".png,.jpg,.jpeg,.webp,.glb,.gltf,.obj" hidden /></label>
            </div>
            ${origMeta ? `<div class="upload-meta">${origMeta.url.match(/\.(png|jpg|jpeg|webp)/i) ? `<img src="${esc(origMeta.url)}" class="thumb-xs"/>` : ''}<code>${esc(origMeta.sha256.slice(0, 23))}…</code> (${fmtBytes(origMeta.bytes)})</div>` : ''}
          </div>
          <div class="upload-box" data-drop="referencia_estilo" data-idx="${idx}">
            <div class="upload-row">
              <label style="flex:1"><span>Referência de Estilo (<code>referencia_estilo</code>)</span><input type="text" data-f="referencia_estilo" value="${esc(item.referencia_estilo || '')}" placeholder="Style sheet PNG/WEBP opcional..." /></label>
              <label class="btn btn-xs btn-sec upload-btn">Enviar Style<input type="file" data-upload="referencia_estilo" data-idx="${idx}" accept=".png,.jpg,.jpeg,.webp" hidden /></label>
            </div>
            ${refMeta ? `<div class="upload-meta"><img src="${esc(refMeta.url)}" class="thumb-xs"/><code>${esc(refMeta.sha256.slice(0, 23))}…</code></div>` : ''}
          </div>
        </div>
        <details class="sb-details" style="margin-top:8px">
          <summary>Colisão, Rig/Esqueleto, Partes R15 (${partesCount}), Clipes (${selClipes.size}/17), Sockets (${selSockets.size}/7), Bake High→Low &amp; Modular</summary>
          <div class="form-grid-4" style="margin-top:8px">
            <label><span>Colisão</span><select data-f="colisao">${opts(STATIC_ENUMS.colisoes, item.colisao || 'none')}</select></label>
            <label><span>Esqueleto</span><select data-f="esqueleto">${opts(STATIC_ENUMS.esqueletos, item.esqueleto || '', '(padrão perfil)')}</select></label>
            <label><span>Modo Rig (<code>rig.modo</code>)</span><select data-rig="modo">${opts(STATIC_ENUMS.rig_modos, rig.modo || '', '(nenhum)')}</select></label>
            <label><span>Peça de Kit (<code>parte</code>)</span><select data-f="parte">${opts(STATIC_ENUMS.partes_kit, item.parte || '', '(nenhuma)')}</select></label>
          </div>
          <div class="chk-row" style="margin-top:6px">
            <label class="chk-label"><input type="checkbox" data-f-bool="auto_rig" ${item.auto_rig ? 'checked' : ''}/> Auto-Rig</label>
            <label class="chk-label"><input type="checkbox" data-f-bool="skinned" ${item.skinned ? 'checked' : ''}/> Skinned</label>
            <label class="chk-label"><input type="checkbox" data-f-bool="alpha_cards" ${item.alpha_cards ? 'checked' : ''}/> Alpha Cards</label>
            <label class="chk-label"><input type="checkbox" data-det-bool="ativo" ${det.ativo ? 'checked' : ''}/> Detalhe Alto (Cycles High→Low)</label>
            <button class="btn btn-xs btn-sec" data-act="fill-r15" data-idx="${idx}">⚡ Preencher 15 Partes R15 (${partesCount}/15)</button>
            ${partesCount > 0 ? `<button class="btn btn-xs" data-act="clear-r15" data-idx="${idx}">Limpar Partes</button>` : ''}
          </div>
          <div class="chips-section">
            <span class="field-label">Clipes de Animação (17 suportados):</span>
            <div class="chips-wrap">${clipes.map((c) => `<button type="button" class="chip ${selClipes.has(c) ? 'chip-on' : ''}" data-chip-clipe="${esc(c)}" data-idx="${idx}">${esc(c)}</button>`).join('')}</div>
          </div>
          <div class="chips-section">
            <span class="field-label">Sockets de Anexo &amp; Montaria (7 suportados):</span>
            <div class="chips-wrap">${sockets.map((s) => `<button type="button" class="chip ${selSockets.has(s) ? 'chip-on' : ''}" data-chip-socket="${esc(s)}" data-idx="${idx}">${esc(s)}</button>`).join('')}</div>
          </div>
          <div class="form-grid-4" style="margin-top:8px">
            <label><span>WFC Grade (col x lin)</span><input type="text" data-mod="grade" value="${esc((mod.grade || [5, 2]).join(', '))}" /></label>
            <label><span>WFC Módulos</span><input type="text" data-mod="modulos" value="${esc((mod.modulos || []).join(', '))}" /></label>
            <label><span>WFC Setor (x, y)</span><input type="text" data-mod="setor" value="${esc((mod.setor || [0, 0]).join(', '))}" /></label>
            <label><span>Tamanho Módulo (m)</span><input type="number" step="0.5" data-mod="tamanho" value="${esc(mod.tamanho_modulo ?? 4.0)}" /></label>
          </div>
        </details>
      </div>`;
  }

  _bindEvents() {
    const q = (sel) => this.root.querySelector(sel);
    q('#sb-example-select')?.addEventListener('change', (e) => { this.selectedExample = e.target.value; });
    q('#sb-btn-load-ex')?.addEventListener('click', async () => {
      const name = q('#sb-example-select')?.value || this.selectedExample;
      if (!name) return toast('Selecione um exemplo na lista', 'warn');
      const res = await api.example(name);
      if (!res.ok) return toast(`Erro ao carregar exemplo: ${res.mensagem}`, 'error');
      this.selectedExample = name;
      if (res.doc && typeof res.doc === 'object') this.doc = res.doc;
      this.yamlText = res.yaml || specToYaml(this.doc);
      this.render();
      toast(`Exemplo ${name} carregado`, 'ok');
    });
    q('#sb-btn-new')?.addEventListener('click', () => { this.selectedExample = ''; this.doc = createDefaultSpec(); this.yamlText = specToYaml(this.doc); this.render(); });
    q('#sb-btn-migrate')?.addEventListener('click', async () => {
      const res = await api.migrate(this.getYaml());
      if (!res.ok) return toast(`Falha ao migrar: ${res.mensagem}`, 'error');
      this.yamlText = res.yaml || this.yamlText;
      const vRes = await api.validate(this.yamlText);
      if (vRes.ok && vRes.spec_canon) this.doc = vRes.spec_canon;
      this.render();
      this._showDrawerHtml('Migração spec@6', `<p><b>${esc(res.de)} ⇒ ${esc(res.para)}</b></p><ul>${(res.mudancas || []).map((m) => `<li>${esc(m)}</li>`).join('') || '<li>Nenhuma alteração estrutural necessária.</li>'}</ul>`);
    });
    q('#sb-btn-save')?.addEventListener('click', async () => {
      const res = await api.saveSpec(q('#sb-save-name')?.value || 'lote_studio.yaml', this.getYaml());
      if (!res.ok) return toast(`Erro ao salvar: ${res.mensagem}`, 'error');
      toast(`Lote salvo em ${res.caminho}`, 'ok');
    });
    this.root.querySelectorAll('[data-mode]').forEach((btn) => btn.addEventListener('click', () => { this.viewMode = btn.dataset.mode; this.render(); }));
    q('#sb-allowlist-pick')?.addEventListener('change', (e) => {
      if (!e.target.value) return;
      this.doc.destino_exportacao = `${e.target.value.replace(/\/+$/, '')}/${this.doc.projeto || 'lote'}`;
      this.syncDocToYaml(); this.render();
    });
    this.root.querySelectorAll('[data-g]').forEach((el) => el.addEventListener('input', () => {
      this.doc[el.dataset.g] = el.value; this.syncDocToYaml();
      if (el.dataset.g === 'perfil') this.render();
    }));
    this.root.querySelectorAll('[data-pal]').forEach((el) => el.addEventListener('input', () => {
      if (!Array.isArray(this.doc.paleta)) this.doc.paleta = [];
      this.doc.paleta[Number(el.dataset.pal)] = el.value;
      this.syncDocToYaml();
    }));
    q('#sb-add-color')?.addEventListener('click', () => { this.doc.paleta = [...(this.doc.paleta || []), '#10b981']; this.syncDocToYaml(); this.render(); });
    q('#sb-del-color')?.addEventListener('click', () => { if ((this.doc.paleta || []).length > 1) { this.doc.paleta.pop(); this.syncDocToYaml(); this.render(); } });

    const bindSub = (attr, key, isNum = false, isBool = false) => {
      this.root.querySelectorAll(`[${attr}]`).forEach((el) => el.addEventListener('change', () => {
        if (!this.doc[key]) this.doc[key] = {};
        this.doc[key][el.getAttribute(attr)] = isBool ? el.checked : isNum ? Number(el.value) : el.value;
        this.syncDocToYaml();
      }));
    };
    bindSub('data-orc', 'orcamento_cena', true, false);
    bindSub('data-pol', 'politica', false, false);
    bindSub('data-req', 'requisicao', false, false);
    bindSub('data-rbx', 'roblox_render', false, false);
    bindSub('data-rbx-bool', 'roblox_render', false, true);

    q('#sb-add-item')?.addEventListener('click', () => {
      const n = (this.doc.lote || []).length + 1;
      this.doc.lote = [...(this.doc.lote || []), { id: `prop.item.novo.0${n}`, tipo: 'prop_estatico', rota: 'blocky', altura_metros: 1.0, pivot: 'base', colisao: 'box', lod: [100, 50], quantidade_cena: 1 }];
      this.syncDocToYaml(); this.render();
    });

    this.root.querySelectorAll('.sb-item-card').forEach((card) => {
      const item = this.doc.lote[Number(card.dataset.idx)];
      if (!item) return;
      card.querySelectorAll('[data-f]').forEach((el) => el.addEventListener('input', () => {
        if (el.value === '') delete item[el.dataset.f]; else item[el.dataset.f] = el.value;
        this.syncDocToYaml();
      }));
      card.querySelectorAll('[data-f-num]').forEach((el) => el.addEventListener('input', () => {
        if (el.value === '') delete item[el.dataset.fNum]; else item[el.dataset.fNum] = Number(el.value);
        this.syncDocToYaml();
      }));
      card.querySelectorAll('[data-f-int]').forEach((el) => el.addEventListener('input', () => {
        if (el.value === '') delete item[el.dataset.fInt]; else item[el.dataset.fInt] = parseInt(el.value, 10);
        this.syncDocToYaml();
      }));
      card.querySelectorAll('[data-f-bool]').forEach((el) => el.addEventListener('change', () => {
        if (el.checked) item[el.dataset.fBool] = true; else delete item[el.dataset.fBool];
        this.syncDocToYaml();
      }));
      card.querySelectorAll('[data-f-lod]').forEach((el) => el.addEventListener('change', () => {
        const nums = el.value.split(',').map((s) => parseInt(s.trim(), 10)).filter((n) => Number.isFinite(n) && n >= 5 && n <= 100);
        item.lod = nums.length ? nums : [100]; this.syncDocToYaml();
      }));
      card.querySelectorAll('[data-rig]').forEach((el) => el.addEventListener('change', () => {
        if (!el.value) delete item.rig; else item.rig = { ...(item.rig || {}), modo: el.value, esqueleto: item.esqueleto || 'r15@1' };
        this.syncDocToYaml();
      }));
      card.querySelectorAll('[data-det-bool]').forEach((el) => el.addEventListener('change', () => {
        if (el.checked) item.detalhe_alto = { ativo: true, subdiv_niveis: 2, chanfro_bevel_m: 0.008, ao_cavidade_forca: 0.35 }; else delete item.detalhe_alto;
        this.syncDocToYaml();
      }));
      card.querySelectorAll('[data-mod]').forEach((el) => el.addEventListener('change', () => {
        if (item.rota !== 'modular' && !item.modular) return;
        const m = item.modular || { grade: [5, 2], modulos: ['sala_base'], setor: [0, 0], tamanho_modulo: 4.0 };
        const k = el.dataset.mod;
        if (k === 'grade' || k === 'setor') m[k] = el.value.split(',').map((x) => parseInt(x.trim(), 10) || 0).slice(0, 2);
        else if (k === 'modulos') m.modulos = el.value.split(',').map((x) => x.trim()).filter(Boolean);
        else if (k === 'tamanho') m.tamanho_modulo = Number(el.value) || 4.0;
        item.modular = m; this.syncDocToYaml();
      }));
    });

    this.root.querySelectorAll('[data-act]').forEach((btn) => btn.addEventListener('click', () => {
      const [idx, act] = [Number(btn.dataset.idx), btn.dataset.act];
      if (act === 'dup') {
        const copy = JSON.parse(JSON.stringify(this.doc.lote[idx])); copy.id = `${copy.id}_copia`;
        this.doc.lote.splice(idx + 1, 0, copy);
      } else if (act === 'del') {
        if (this.doc.lote.length <= 1) return toast('O lote exige ao menos 1 item', 'warn');
        this.doc.lote.splice(idx, 1);
      } else if (act === 'fill-r15') {
        const partes = (this.meta.partes_r15?.length ? this.meta.partes_r15 : STATIC_ENUMS.partes_r15).map((nome) => ({ nome, papel: 'r15_parte', junta: nome }));
        Object.assign(this.doc.lote[idx], { partes, esqueleto: 'r15@1', rig: { modo: 'motor6d', esqueleto: 'r15@1' } });
      } else if (act === 'clear-r15') delete this.doc.lote[idx].partes;
      this.syncDocToYaml(); this.render();
    }));

    const bindChip = (attr, prop) => {
      this.root.querySelectorAll(`[${attr}]`).forEach((chip) => chip.addEventListener('click', () => {
        const item = this.doc.lote[Number(chip.dataset.idx)];
        const val = chip.getAttribute(attr);
        const set = new Set(item[prop] || []);
        if (set.has(val)) set.delete(val); else set.add(val);
        if (set.size) item[prop] = [...set]; else delete item[prop];
        this.syncDocToYaml(); this.render();
      }));
    };
    bindChip('data-chip-clipe', 'clipes');
    bindChip('data-chip-socket', 'sockets');

    this.root.querySelectorAll('input[type="file"][data-upload]').forEach((inp) => inp.addEventListener('change', async (e) => {
      if (e.target.files?.[0]) await this._handleUpload(Number(inp.dataset.idx), inp.dataset.upload, e.target.files[0]);
    }));
    this.root.querySelectorAll('.upload-box[data-drop]').forEach((box) => {
      box.addEventListener('dragover', (e) => { e.preventDefault(); box.classList.add('drag-over'); });
      box.addEventListener('dragleave', () => box.classList.remove('drag-over'));
      box.addEventListener('drop', async (e) => {
        e.preventDefault(); box.classList.remove('drag-over');
        if (e.dataTransfer?.files?.[0]) await this._handleUpload(Number(box.dataset.idx), box.dataset.drop, e.dataTransfer.files[0]);
      });
    });

    q('#sb-yaml-editor')?.addEventListener('input', (e) => { this.yamlText = e.target.value; });
    q('#sb-sync-yaml-to-vis')?.addEventListener('click', () => this._runValidate(true));
    q('#sb-btn-validate')?.addEventListener('click', () => this._runValidate(false));
    q('#sb-btn-plan')?.addEventListener('click', () => this._runPlan());
    q('#sb-btn-run')?.addEventListener('click', () => this._runPipeline());
    q('#sb-btn-cancel')?.addEventListener('click', () => this._cancelJob());
  }

  async _handleUpload(idx, field, file) {
    toast(`Enviando ${file.name}...`, 'info');
    const res = await api.uploadFile(file, field);
    if (!res.ok) return toast(`Falha no upload: ${res.mensagem}`, 'error');
    if (this.doc.lote[idx]) {
      this.doc.lote[idx][field] = res.caminho;
      this.uploadsMeta[`${idx}:${field}`] = { url: res.url, sha256: res.sha256, bytes: res.bytes };
      this.syncDocToYaml(); this.render();
      toast(`Upload concluído (${res.sha256.slice(0, 19)}…)`, 'ok');
    }
  }

  _showDrawerHtml(badgeText, html, badgeClass = 'badge-info') {
    const [st, body] = [this.root.querySelector('#sb-drawer-status'), this.root.querySelector('#sb-drawer-body')];
    if (st) { st.className = `badge ${badgeClass}`; st.textContent = badgeText; }
    if (body) body.innerHTML = html;
  }

  async _runValidate(syncToVisual = false) {
    this._showDrawerHtml('Validando...', '<p class="muted">Validando schema e regras de negócio...</p>');
    const res = await api.validate(this.getYaml());
    if (!res.ok) return this._showDrawerHtml(res.codigo || 'Erro Spec', `<div class="alert alert-error"><strong>${esc(res.codigo || 'FORGE-E-SPEC')}:</strong> ${esc(res.mensagem)}</div>`, 'badge-err');
    if (res.spec_canon) { this.doc = res.spec_canon; if (syncToVisual) this.render(); }
    const avisos = (res.avisos || []).map((a) => `<li><code>${esc(a.codigo || 'AVISO')}</code>: ${esc(a.mensagem || JSON.stringify(a))}</li>`).join('');
    this._showDrawerHtml('Spec Válida (exit=0)', `<div class="alert alert-ok"><b>Spec válida!</b> Projeto: <code>${esc(res.projeto)}</code> · Perfil: <code>${esc(res.perfil)}</code> · Destino: <code>${esc(res.destino)}</code> · Itens: <b>${esc(res.itens)}</b></div>${avisos ? `<h4>Avisos:</h4><ul>${avisos}</ul>` : ''}`, 'badge-ok');
  }

  async _runPlan() {
    this._showDrawerHtml('Planejando (G11)...', '<p class="muted">Calculando plano de cache, preflight e orçamento de cena G11...</p>');
    const no_cache = Boolean(this.root.querySelector('#sb-opt-nocache')?.checked);
    const res = await api.plan(this.getYaml(), { no_cache, scene_budget: true });
    if (!res.ok) return this._showDrawerHtml(res.codigo || 'Erro Plan', `<div class="alert alert-error"><strong>${esc(res.codigo)}:</strong> ${esc(res.mensagem)}</div>`, 'badge-err');
    const rel = res.relatorio || {};
    const [p, orc] = [rel.plano || {}, rel.orcamento_cena || {}];
    const lim = orc.limite || { triangulos_cena_max: 400000, draw_calls_cena_max: 400, vram_texturas_mb_max: 200 };
    const [est, teto] = [orc.estimativa || orc.medido || {}, orc.teto_pior_caso || orc.medido || {}];
    const bar = (label, valEst, valTeto, max, unit = '') => {
      const pctEst = Math.min(100, Math.round(((Number(valEst) || 0) / Math.max(1, Number(max))) * 100));
      const pctTeto = Math.min(100, Math.round(((Number(valTeto) || 0) / Math.max(1, Number(max))) * 100));
      return `<div class="g11-meter"><div class="g11-meter-head"><span>${esc(label)}</span><span>Calibrado: <b>${fmtNum(valEst)}${unit}</b> (${pctEst}%) · Teto: <b>${fmtNum(valTeto)}${unit}</b> (${pctTeto}%) / Limite: ${fmtNum(max)}${unit}</span></div><div class="progress-track"><div class="progress-fill-teto" style="width:${pctTeto}%"></div><div class="progress-fill-est ${pctEst > 100 ? 'over' : ''}" style="width:${pctEst}%"></div></div></div>`;
    };
    const rows = (rel.tarefas || []).map((t) => `<tr><td><code>${esc(t.id)}</code></td><td>${esc(t.tipo)}</td><td><span class="badge">${esc(t.rota)}</span></td><td>${esc(t.provedor?.nome || '—')}</td><td>${t.cache_hit ? '<span class="badge badge-ok">HIT</span>' : '<span class="badge">MISS</span>'}</td><td><span class="badge ${t.estado_previsto === 'pronto' ? 'badge-ok' : 'badge-warn'}">${esc(t.estado_previsto)}</span> ${esc(t.razao || '')}</td></tr>`).join('');
    this._showDrawerHtml(`Plano OK · G11: ${orc.status || 'ok'}`, `
      <div class="kpi-row">
        <div class="kpi-box"><span>Total</span><strong>${fmtNum(p.total)}</strong></div>
        <div class="kpi-box"><span>Prontas</span><strong>${fmtNum(p.prontas)}</strong></div>
        <div class="kpi-box"><span>Cache Hits</span><strong>${fmtNum(p.cache_hits)}</strong></div>
        <div class="kpi-box"><span>Tempo Est.</span><strong>${esc(p.segundos_estimados ?? 0)}s</strong></div>
        <div class="kpi-box"><span>VRAM Pico</span><strong>${fmtNum(p.vram_pico_mb)} MB</strong></div>
      </div>
      <div class="g11-panel">
        <h4>Orçamento de Cena AA (Gate G11 — Estimativa Calibrada vs Teto Pior Caso)</h4>
        ${bar('Triângulos em Cena', est.triangulos_cena, teto.triangulos_cena, lim.triangulos_cena_max)}
        ${bar('Draw Calls Estimados', est.draw_calls_estimados, teto.draw_calls_estimados, lim.draw_calls_cena_max)}
        ${bar('VRAM de Texturas', est.vram_texturas_mb, teto.vram_texturas_mb, lim.vram_texturas_mb_max, ' MB')}
      </div>
      <table class="data-table"><thead><tr><th>Asset ID</th><th>Tipo</th><th>Rota</th><th>Provider</th><th>Cache</th><th>Estado</th></tr></thead><tbody>${rows}</tbody></table>`, orc.status === 'falhou' ? 'badge-err' : 'badge-ok');
  }

  async _runPipeline() {
    const nao_publicar = !this.root.querySelector('#sb-opt-publish')?.checked;
    const no_cache = Boolean(this.root.querySelector('#sb-opt-nocache')?.checked);
    const clean_dest = Boolean(this.root.querySelector('#sb-opt-cleandest')?.checked);
    this._showDrawerHtml('Iniciando Run...', '<p class="muted">Validando preflight e disparando job em background...</p>');
    const res = await api.run(this.getYaml(), { nao_publicar, no_cache, clean_dest });
    if (!res.ok) return this._showDrawerHtml(res.codigo || 'Erro Run', `<div class="alert alert-error"><strong>${esc(res.codigo)}:</strong> ${esc(res.mensagem)}</div>`, 'badge-err');
    this.activeJobId = res.job_id;
    this.root.querySelector('#sb-btn-cancel')?.removeAttribute('disabled');
    this._startJobPolling(res.job_id);
  }

  async _cancelJob() {
    if (!this.activeJobId) return;
    await api.cancelJob(this.activeJobId);
    toast('Sinal de cancelamento enviado ao job', 'warn');
  }

  _startJobPolling(jobId) {
    if (this._pollTimer) clearInterval(this._pollTimer);
    const poll = async () => {
      const res = await api.job(jobId);
      if (this.onJobUpdate) this.onJobUpdate(res);
      if (!res.ok) return;
      const logsHtml = (res.logs || []).slice(-60).map((l) => esc(l)).join('\n');
      const rel = res.resultado || {};
      const dest = rel.destino || this.doc.destino_exportacao;
      const itensHtml = (rel.itens || []).map((it) => `<tr><td><code>${esc(it.id)}</code></td><td><span class="badge ${it.estado === 'publicado' || it.estado === 'aprovado_nao_publicado' ? 'badge-ok' : 'badge-err'}">${esc(it.estado)}</span></td><td>${esc(it.qc || '—')}</td><td>${esc(it.razao || it.codigo || 'OK')}</td><td>${it.estado === 'publicado' ? `<button class="btn btn-xs btn-pri" data-inspect-id="${esc(it.id)}" data-inspect-dest="${esc(dest)}">Abrir no Inspetor 3D</button>` : ''}</td></tr>`).join('');
      this._showDrawerHtml(`Job ${res.job_id} · ${res.status}`, `<pre class="console-log">${logsHtml || 'Aguardando saída do processo...'}</pre>${itensHtml ? `<table class="data-table" style="margin-top:8px"><thead><tr><th>Asset ID</th><th>Estado</th><th>QC</th><th>Detalhe</th><th>Ação</th></tr></thead><tbody>${itensHtml}</tbody></table>` : ''}`, res.status === 'done' && res.exit_code === 0 ? 'badge-ok' : res.status === 'running' ? 'badge-info' : 'badge-err');
      this.root.querySelectorAll('[data-inspect-id]').forEach((b) => b.addEventListener('click', () => this.onOpenAsset?.(b.dataset.inspectDest, b.dataset.inspectId)));
      if (res.status !== 'running') {
        clearInterval(this._pollTimer); this._pollTimer = null; this.activeJobId = null;
        this.root.querySelector('#sb-btn-cancel')?.setAttribute('disabled', 'true');
      }
    };
    poll();
    this._pollTimer = setInterval(poll, 600);
  }
}
