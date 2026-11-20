/**
 * Forge3D Studio Web — Workspaces 3, 4 e 5:
 * (3) Exportar & Sincronizar (export-r15/anim/surface/acessorio, sync, upload-cloud)
 * (4) Verificação & Histórico (verify, runs, ledger.jsonl)
 * (5) Ambiente & Governança (doctor, conectores IA, allowlist, gc)
 */

import { STATIC_ENUMS, api, esc, fmtBytes, fmtNum, toast } from './api.js';

export class OpsView {
  constructor({ exportEl, verifyEl, envEl, onRefreshDestinations, onJobUpdate } = {}) {
    this.exportEl = exportEl;
    this.verifyEl = verifyEl;
    this.envEl = envEl;
    this.onRefreshDestinations = onRefreshDestinations;
    this.onJobUpdate = onJobUpdate;
    this.meta = { exemplos: [], clipes: STATIC_ENUMS.clipes };
    this.destinations = { sandbox: '', allowlist: [], destinos: [] };
    this.doctor = null;
    this.runs = [];
    this.ledger = [];
    this.exportType = 'r15';
  }

  async init(meta, destinations, doctorData) {
    if (meta?.ok) this.meta = { ...this.meta, ...meta };
    if (destinations?.ok) this.destinations = destinations;
    if (doctorData?.ok) this.doctor = doctorData.doctor || doctorData;
    this.renderExportTab();
    this.renderVerifyTab();
    this.renderEnvTab();
    await this.refreshHistory();
  }

  prefillExportFromAsset(assetDetail) {
    if (!assetDetail) return;
    this.renderExportTab({
      origem: assetDetail.destino || '',
      item: assetDetail.asset_id || '',
      arquivo: (assetDetail.arquivos || []).find((f) => f.papel === 'malha_principal')?.caminho_abs || '',
    });
  }

  async runVerifyForDestination(destino) {
    this.renderVerifyTab(destino);
    await this._execVerify(destino, '');
  }

  renderExportTab(prefill = {}) {
    if (!this.exportEl) return;
    const dests = (this.destinations.destinos || []).map((d) => d.caminho);
    const allow = this.destinations.allowlist || [];
    const exs = (this.meta.exemplos || []).map((e) => e.caminho || `examples/${e.nome}`);
    const defaultSpec = prefill.lote || exs.find((x) => x.includes('r15')) || exs[0] || 'examples/lote_09_r15.yaml';
    const defaultOrig = prefill.origem || dests[0] || this.destinations.sandbox || '~/.local/state/forge3d/saida/r15';
    const defaultItem = prefill.item || 'personagem.r15.guard.01';

    this.exportEl.innerHTML = `
      <div class="ops-grid-3">
        <section class="card">
          <div class="card-header">
            <h3>Exportação Roblox Studio (<code>.rbxlx</code> / <code>.rbxmx</code>)</h3>
            <div class="btn-group">
              ${[['r15', 'export-r15'], ['anim', 'export-anim'], ['surface', 'export-surface'], ['acessorio', 'export-acessorio']].map(([k, lbl]) => `<button class="btn btn-xs ${this.exportType === k ? 'active' : ''}" data-exp-type="${k}">${lbl}</button>`).join('')}
            </div>
          </div>
          <div class="form-stack">
            <label><span>Spec YAML ou Pasta de Origem Publicada</span>
              <input type="text" id="exp-origem" value="${esc(this.exportType === 'r15' || this.exportType === 'anim' ? defaultSpec : defaultOrig)}" />
            </label>
            <label><span>ID do Item (<code>--item</code>)</span>
              <input type="text" id="exp-item" value="${esc(defaultItem)}" />
            </label>
            ${this.exportType === 'r15' ? `
              <div class="form-grid-2">
                <label><span>Modo Rig Roblox</span><select id="exp-modo-rig"><option value="motor6d">motor6d (15 partes)</option><option value="bone">bone (skinned mesh)</option></select></label>
                <label><span>Pasta Texturas PBR (opcional)</span><input type="text" id="exp-tex-dir" placeholder="Auto-descoberta" /></label>
              </div>
              <label class="chk-label"><input type="checkbox" id="exp-anchored" checked /> Ancorar HumanoidRootPart (<code>--anchored-root</code>)</label>
            ` : ''}
            ${this.exportType === 'anim' ? `
              <div class="form-grid-2">
                <label><span>Clipe(s) (<code>--clipe</code>)</span><input type="text" id="exp-clipe" value="idle" placeholder="idle,walk,run" /></label>
                <label class="chk-label" style="margin-top:18px"><input type="checkbox" id="exp-todos" /> Exportar todos os 17 clipes (<code>--todos</code>)</label>
              </div>
            ` : ''}
            <label><span>Caminho de Saída Opcional (<code>--saida</code>)</span>
              <input type="text" id="exp-saida" placeholder="Padrão automático no diretório de estado/destino" />
            </label>
            <button class="btn btn-pri" id="exp-btn-run">Gerar Pacote Roblox (${esc(this.exportType)})</button>
          </div>
          <div id="exp-result-box" class="result-box"></div>
        </section>

        <section class="card">
          <div class="card-header">
            <h3>Sincronização com Projeto de Jogo (<code>forge3d sync</code>)</h3>
            <span class="badge">Godot 4 &amp; Rojo</span>
          </div>
          <div class="form-stack">
            <label><span>Origem Publicada (<code>origem</code>)</span>
              <input type="text" id="sync-origem" list="dl-destinos" value="${esc(defaultOrig)}" />
              <datalist id="dl-destinos">${dests.map((d) => `<option value="${esc(d)}"></option>`).join('')}</datalist>
            </label>
            <label><span>Destino no Jogo sob Allowlist (<code>--para</code>)</span>
              <input type="text" id="sync-para" list="dl-allow" value="${esc(allow[0] ? `${allow[0]}/sync_out` : `${this.destinations.sandbox || '~/.local/state/forge3d/saida'}/sync_out`)}" />
              <datalist id="dl-allow">${allow.map((a) => `<option value="${esc(a)}"></option>`).join('')}</datalist>
            </label>
            <div class="form-grid-2">
              <label><span>Catálogo Rojo Luau (<code>--rojo-lua</code>)</span><input type="text" id="sync-rojo" placeholder="Ex: ReplicatedStorage/Assets.lua" /></label>
              <label><span>Catálogo Godot GDScript (<code>--godot-gd</code>)</span><input type="text" id="sync-godot" placeholder="Ex: addons/forge3d/catalog.gd" /></label>
              <label><span>Classe GDScript (<code>--gd-class-name</code>)</span><input type="text" id="sync-gd-class" value="Forge3DAssets" /></label>
              <label><span>Prefixo Godot (<code>--res-prefix</code>)</span><input type="text" id="sync-res-prefix" value="res://assets" /></label>
            </div>
            <label class="chk-label"><input type="checkbox" id="sync-limpar" /> Limpar artefatos órfãos no destino (<code>--limpar</code>)</label>
            <button class="btn btn-pri" id="sync-btn-run">⇄ Executar Sincronização</button>
          </div>
          <div id="sync-result-box" class="result-box"></div>
        </section>

        <section class="card">
          <div class="card-header">
            <h3>Publicação Roblox Open Cloud (<code>upload-*</code>)</h3>
            <span class="badge badge-warn">Segurança Dry-Run</span>
          </div>
          <div class="form-stack">
            <div class="form-grid-2">
              <label><span>Tipo de Asset</span><select id="up-tipo"><option value="Model">Model (.glb / .rbxm)</option><option value="Image">Image (.png)</option><option value="Animation">Animation (.rbxlx / .rbxmx)</option></select></label>
              <label><span>Tipo de Criador</span><select id="up-creator-type"><option value="User">User</option><option value="Group">Group</option></select></label>
            </div>
            <label><span>Arquivo Local (dentro do sandbox de leitura)</span>
              <input type="text" id="up-arquivo" value="${esc(prefill.arquivo || '')}" placeholder="Caminho para .glb, .png ou .rbxlx publicado" />
            </label>
            <div class="form-grid-2">
              <label><span>Nome de Exibição</span><input type="text" id="up-nome" value="${esc(defaultItem)}" /></label>
              <label><span>Creator ID Roblox</span><input type="text" id="up-creator-id" placeholder="Ex: 11966727684" /></label>
            </div>
            <label><span>Descrição</span><input type="text" id="up-desc" value="Gerado e verificado via Forge3D Studio" /></label>
            <label class="chk-label"><input type="checkbox" id="up-strip" checked /> Remover texturas embutidas do GLB (<code>--strip-embedded-textures</code>)</label>
            <label class="chk-label"><input type="checkbox" id="up-dryrun" checked /> <b>Modo Dry-Run (Simular sem enviar para a nuvem)</b></label>
            <label class="chk-label alert-warn-box" id="up-confirm-wrap" style="display:none">
              <input type="checkbox" id="up-confirm-real" /> <b>Confirmo o envio REAL para a API Roblox Open Cloud</b>
            </label>
            <button class="btn btn-pri" id="up-btn-run">☁ Executar Upload Open Cloud</button>
          </div>
          <div id="up-result-box" class="result-box"></div>
        </section>
      </div>`;

    this.exportEl.querySelectorAll('[data-exp-type]').forEach((b) => b.addEventListener('click', () => {
      this.exportType = b.dataset.expType;
      this.renderExportTab(prefill);
    }));

    const q = (s) => this.exportEl.querySelector(s);
    q('#up-dryrun')?.addEventListener('change', (e) => {
      const wrap = q('#up-confirm-wrap');
      if (wrap) wrap.style.display = e.target.checked ? 'none' : 'flex';
      if (e.target.checked && q('#up-confirm-real')) q('#up-confirm-real').checked = false;
    });

    q('#exp-btn-run')?.addEventListener('click', async () => {
      const origemVal = q('#exp-origem')?.value || '';
      const itemVal = q('#exp-item')?.value || '';
      const saidaVal = q('#exp-saida')?.value || undefined;
      const payload = {
        tipo: this.exportType,
        lote: origemVal,
        spec: origemVal,
        origem: origemVal,
        item: itemVal,
        item_id: itemVal,
        saida: saidaVal,
        anchored_root: Boolean(q('#exp-anchored')?.checked),
        modo_rig: q('#exp-modo-rig')?.value || 'motor6d',
        texturas_dir: q('#exp-tex-dir')?.value || undefined,
        clipe: q('#exp-clipe')?.value || 'idle',
        todos: Boolean(q('#exp-todos')?.checked),
      };
      const box = q('#exp-result-box');
      if (box) box.innerHTML = '<p class="muted">Exportando pacote Roblox...</p>';
      const res = await api.exportAsset(payload);
      if (!res.ok) {
        if (box) box.innerHTML = `<div class="alert alert-error"><b>${esc(res.codigo)}:</b> ${esc(res.mensagem)}</div>`;
        return;
      }
      const dl = res.download_url || (res.relatorio?.saida ? api.fileUrl(res.relatorio.saida, true) : '');
      if (box) {
        box.innerHTML = `<div class="alert alert-ok"><b>Exportado com sucesso!</b> ${dl ? `<a class="btn btn-xs btn-pri" href="${esc(dl)}" download>⬇ Baixar Arquivo</a>` : ''}</div><pre class="json-viewer">${esc(JSON.stringify(res.relatorio || res, null, 2))}</pre>`;
      }
    });

    q('#sync-btn-run')?.addEventListener('click', async () => {
      const box = q('#sync-result-box');
      if (box) box.innerHTML = '<p class="muted">Sincronizando artefatos verificados...</p>';
      const res = await api.sync({
        origem: q('#sync-origem')?.value || '',
        para: q('#sync-para')?.value || '',
        limpar: Boolean(q('#sync-limpar')?.checked),
        rojo_lua: q('#sync-rojo')?.value || undefined,
        godot_gd: q('#sync-godot')?.value || undefined,
        gd_class_name: q('#sync-gd-class')?.value || 'Forge3DAssets',
        res_prefix: q('#sync-res-prefix')?.value || 'res://assets',
      });
      if (!res.ok) {
        if (box) box.innerHTML = `<div class="alert alert-error"><b>${esc(res.codigo)}:</b> ${esc(res.mensagem)}</div>`;
        return;
      }
      if (box) box.innerHTML = `<div class="alert alert-ok"><b>Sincronização concluída!</b></div><pre class="json-viewer">${esc(JSON.stringify(res.relatorio || res, null, 2))}</pre>`;
    });

    q('#up-btn-run')?.addEventListener('click', async () => {
      const dry_run = Boolean(q('#up-dryrun')?.checked);
      const confirmar_envio_real = Boolean(q('#up-confirm-real')?.checked);
      const box = q('#up-result-box');
      if (!dry_run && !confirmar_envio_real) {
        return toast('Marque a confirmação explícita para envio real à nuvem', 'warn');
      }
      if (box) box.innerHTML = '<p class="muted">Processando upload Open Cloud...</p>';
      const res = await api.uploadCloud({
        tipo: q('#up-tipo')?.value || 'Model',
        arquivo: q('#up-arquivo')?.value || '',
        nome: q('#up-nome')?.value || '',
        descricao: q('#up-desc')?.value || '',
        creator_id: q('#up-creator-id')?.value || '',
        creator_type: q('#up-creator-type')?.value || 'User',
        strip_embedded_textures: Boolean(q('#up-strip')?.checked),
        dry_run,
        confirmar_envio_real,
      });
      if (!res.ok) {
        if (box) box.innerHTML = `<div class="alert alert-error"><b>${esc(res.codigo)}:</b> ${esc(res.mensagem)}</div>`;
        return;
      }
      if (res.job_id) {
        if (box) box.innerHTML = `<div class="alert alert-info">Job de upload iniciado: <code>${esc(res.job_id)}</code></div>`;
        this.onJobUpdate?.({ job_id: res.job_id, status: 'running', tipo: 'upload-cloud' });
      } else if (box) {
        box.innerHTML = `<div class="alert alert-ok"><b>${dry_run ? 'Dry-Run Validado' : 'Upload Concluído'}!</b></div><pre class="json-viewer">${esc(JSON.stringify(res.relatorio || res, null, 2))}</pre>`;
      }
    });
  }

  renderVerifyTab(prefillDestino = '') {
    if (!this.verifyEl) return;
    const dests = this.destinations.destinos || [];
    const defaultDest = prefillDestino || dests[0]?.caminho || this.destinations.sandbox || '';
    this.verifyEl.innerHTML = `
      <div class="ops-grid-2">
        <section class="card">
          <div class="card-header">
            <h3>Portão de Verificação de Destino (<code>forge3d verify</code> · I4/I8/I10/G11)</h3>
            <span id="ver-badge" class="badge">Aguardando</span>
          </div>
          <div class="form-stack">
            <label><span>Destino Publicado para Auditar</span>
              <input type="text" id="ver-destino" list="ver-dl-dest" value="${esc(defaultDest)}" />
              <datalist id="ver-dl-dest">${dests.map((d) => `<option value="${esc(d.caminho)}">${esc(d.nome)} (${d.ativos} ativos)</option>`).join('')}</datalist>
            </label>
            <div>
              <span class="field-label">Escopo (<code>--only</code> · vazio executa auditoria completa G1–G13 + G11 + SHA-256):</span>
              <div class="chk-row">
                ${['manifesto', 'hash', 'escala', 'pivo', 'gates'].map((k) => `<label class="chk-label"><input type="checkbox" data-ver-only="${k}" /> ${k}</label>`).join('')}
              </div>
            </div>
            <button class="btn btn-pri" id="ver-btn-run">✔ Executar Verificação Completa</button>
          </div>
          <div id="ver-result-box" class="result-box"></div>
        </section>

        <section class="card">
          <div class="card-header">
            <h3>Histórico de Execuções (<code>runs/</code>) &amp; Ledger (<code>ledger.jsonl</code>)</h3>
            <button class="btn btn-xs btn-sec" id="ver-btn-refresh-hist">↻ Atualizar Histórico</button>
          </div>
          <div id="ver-runs-list" class="runs-list"></div>
          <div id="ver-run-detail" class="result-box"></div>
          <h4 style="margin-top:12px">Linha do Tempo do Ledger</h4>
          <div id="ver-ledger-list" class="ledger-list"></div>
        </section>
      </div>`;

    this.verifyEl.querySelector('#ver-btn-run')?.addEventListener('click', () => {
      const destino = this.verifyEl.querySelector('#ver-destino')?.value || '';
      const checks = [...this.verifyEl.querySelectorAll('[data-ver-only]:checked')].map((c) => c.dataset.verOnly);
      this._execVerify(destino, checks.join(','));
    });
    this.verifyEl.querySelector('#ver-btn-refresh-hist')?.addEventListener('click', () => this.refreshHistory());
    this._renderHistoryLists();
  }

  async _execVerify(destino, only) {
    const box = this.verifyEl?.querySelector('#ver-result-box');
    const badge = this.verifyEl?.querySelector('#ver-badge');
    if (badge) { badge.className = 'badge badge-info'; badge.textContent = 'Verificando...'; }
    if (box) box.innerHTML = '<p class="muted">Recalculando SHA-256 e reexecutando gates contra manifestos...</p>';
    const res = await api.verify(destino, only);
    const ok = Boolean(res.ok && res.exit === 0);
    if (badge) {
      badge.className = `badge ${ok ? 'badge-ok' : 'badge-err'}`;
      badge.textContent = ok ? 'ÍNTEGRO (exit=0)' : `FALHOU (exit=${res.exit ?? 3})`;
    }
    if (box) {
      box.innerHTML = `<div class="alert ${ok ? 'alert-ok' : 'alert-error'}"><b>Destino:</b> <code>${esc(destino)}</code> · Status: <b>${ok ? 'Aprovado' : esc(res.mensagem || 'Divergência detectada')}</b></div><pre class="json-viewer">${esc(JSON.stringify(res.resultado || res, null, 2))}</pre>`;
    }
  }

  async refreshHistory() {
    const [rRuns, rLedger] = await Promise.all([api.runs(40), api.ledger(80)]);
    if (rRuns.ok) this.runs = rRuns.runs || rRuns.itens || [];
    if (rLedger.ok) this.ledger = rLedger.eventos || [];
    this._renderHistoryLists();
  }

  _renderHistoryLists() {
    if (!this.verifyEl) return;
    const runsBox = this.verifyEl.querySelector('#ver-runs-list');
    const ledBox = this.verifyEl.querySelector('#ver-ledger-list');
    if (runsBox) {
      runsBox.innerHTML = this.runs.length
        ? `<table class="data-table"><thead><tr><th>Run ID</th><th>Projeto</th><th>Perfil</th><th>Exit</th><th>Ação</th></tr></thead><tbody>${this.runs.map((r) => {
          const id = r.run_id || r.id || '';
          const ex = r.exit ?? r.relatorio?.exit ?? 0;
          return `<tr><td><code>${esc(id)}</code></td><td>${esc(r.projeto || '—')}</td><td><code>${esc(r.perfil || '—')}</code></td><td><span class="badge ${ex === 0 ? 'badge-ok' : 'badge-err'}">exit=${esc(ex)}</span></td><td><button class="btn btn-xs btn-sec" data-run-id="${esc(id)}">Inspecionar JSON</button></td></tr>`;
        }).join('')}</tbody></table>`
        : '<p class="muted">Nenhuma execução registrada em runs/.</p>';
      runsBox.querySelectorAll('[data-run-id]').forEach((b) => b.addEventListener('click', async () => {
        const dRes = await api.runDetail(b.dataset.runId);
        const detBox = this.verifyEl.querySelector('#ver-run-detail');
        if (detBox) detBox.innerHTML = `<pre class="json-viewer">${esc(JSON.stringify(dRes, null, 2))}</pre>`;
      }));
    }
    if (ledBox) {
      ledBox.innerHTML = this.ledger.length
        ? `<table class="data-table"><thead><tr><th>Evento</th><th>Run / ID</th><th>Projeto</th><th>Detalhe</th></tr></thead><tbody>${this.ledger.slice(0, 40).map((ev) => `<tr><td><span class="badge">${esc(ev.evento || 'evento')}</span></td><td><code>${esc(ev.run_id || ev.id || ev.asset_id || '—')}</code></td><td>${esc(ev.projeto || '—')}</td><td><code class="code-wrap">${esc(JSON.stringify(ev.resumo || ev))}</code></td></tr>`).join('')}</tbody></table>`
        : '<p class="muted">Ledger vazio.</p>';
    }
  }

  renderEnvTab() {
    if (!this.envEl) return;
    const doc = this.doctor || {};
    const checks = doc.checks || [];
    const ia = doc.conectores_ia || {};
    const modelos = doc.modelos_aptos || [];
    const allow = this.destinations.allowlist || [];

    this.envEl.innerHTML = `
      <div class="ops-grid-2">
        <section class="card">
          <div class="card-header">
            <h3>Preflight do Ambiente (<code>forge3d doctor</code>)</h3>
            <button class="btn btn-xs btn-sec" id="env-btn-doctor">↻ Reexecutar Doctor</button>
          </div>
          <div class="checks-grid">
            ${checks.map((c) => `
              <div class="check-card ${c.ok ? 'check-ok' : c.critico ? 'check-err' : 'check-warn'}">
                <div class="check-top"><strong>${esc(c.nome)}</strong><span class="badge ${c.ok ? 'badge-ok' : c.critico ? 'badge-err' : 'badge-warn'}">${c.ok ? 'OK' : c.critico ? 'CRÍTICO' : 'AVISO'}</span></div>
                <div class="check-detail">${esc(c.detalhe)}</div>
              </div>`).join('')}
          </div>
          <h4 style="margin-top:12px">Conectores de IA &amp; Providers 3D</h4>
          <div class="checks-grid">
            ${Object.entries(ia).map(([nome, info]) => `
              <div class="check-card ${info.pronto || info.ok ? 'check-ok' : 'check-warn'}">
                <div class="check-top"><strong><code>${esc(nome)}</code></strong><span class="badge ${info.pronto || info.ok ? 'badge-ok' : 'badge-warn'}">${esc(info.status || (info.pronto ? 'pronto' : 'indisponível'))}</span></div>
                <div class="check-detail">${esc(info.detalhe || '')}</div>
              </div>`).join('')}
          </div>
          <h4 style="margin-top:12px">Modelos Aptos p/ Uso Comercial (Gate I7 · ${modelos.length})</h4>
          <div class="chips-wrap">${modelos.map((m) => `<span class="badge badge-ok">${esc(typeof m === 'string' ? m : m.nome || m.id || JSON.stringify(m))}</span>`).join('') || '<span class="muted">Nenhum modelo listado</span>'}</div>
        </section>

        <section class="card">
          <div class="card-header">
            <h3>Governança de Destinos (Allowlist I13) &amp; Coleta de Lixo (<code>gc</code>)</h3>
          </div>
          <p class="muted">Sandbox padrão (sempre autorizado): <code>${esc(this.destinations.sandbox || doc.estado || '~/.local/state/forge3d/saida')}</code></p>
          <div class="upload-row" style="margin:8px 0">
            <input type="text" id="env-allow-input" placeholder="Nova raiz ext4 p/ allowlist (ex: ~/projetos/meu_jogo/assets)" style="flex:1" />
            <button class="btn btn-sm btn-pri" id="env-allow-add">+ Autorizar Raiz</button>
          </div>
          <table class="data-table">
            <thead><tr><th>Raiz Autorizada</th><th>Ação</th></tr></thead>
            <tbody>
              ${allow.map((a) => `<tr><td><code>${esc(a)}</code></td><td><button class="btn btn-xs btn-danger" data-allow-rem="${esc(a)}">Remover</button></td></tr>`).join('')}
            </tbody>
          </table>

          <hr class="sep" />
          <h4>Coleta de Lixo de Estado (<code>forge3d gc</code>)</h4>
          <div class="form-grid-2" style="margin-top:8px">
            <label><span>Manter Runs/Cache dos Últimos (dias)</span><input type="number" id="env-gc-dias" value="30" min="0" /></label>
            <label class="chk-label" style="margin-top:18px"><input type="checkbox" id="env-gc-aplicar" /> Aplicar exclusão real (desmarcado = Dry-Run)</label>
          </div>
          <button class="btn btn-sec" id="env-gc-run" style="margin-top:8px">🧹 Executar Coleta de Lixo (GC)</button>
          <div id="env-gc-result" class="result-box"></div>
        </section>
      </div>`;

    const q = (s) => this.envEl.querySelector(s);
    q('#env-btn-doctor')?.addEventListener('click', async () => {
      const res = await api.doctor();
      if (res.ok) { this.doctor = res.doctor || res; this.renderEnvTab(); toast('Diagnóstico atualizado', 'ok'); }
    });
    q('#env-allow-add')?.addEventListener('click', async () => {
      const cam = q('#env-allow-input')?.value?.trim();
      if (!cam) return;
      const res = await api.allowlist('add', cam);
      if (!res.ok) return toast(`Erro allowlist: ${res.mensagem}`, 'error');
      toast('Raiz adicionada à allowlist', 'ok');
      await this._reloadDestinations();
    });
    this.envEl.querySelectorAll('[data-allow-rem]').forEach((b) => b.addEventListener('click', async () => {
      const res = await api.allowlist('remove', b.dataset.allowRem);
      if (!res.ok) return toast(`Erro ao remover: ${res.mensagem}`, 'error');
      toast('Raiz removida da allowlist', 'ok');
      await this._reloadDestinations();
    }));
    q('#env-gc-run')?.addEventListener('click', async () => {
      const dias = Number(q('#env-gc-dias')?.value ?? 30);
      const aplicar = Boolean(q('#env-gc-aplicar')?.checked);
      const res = await api.gc(dias, aplicar);
      const box = q('#env-gc-result');
      if (!res.ok) {
        if (box) box.innerHTML = `<div class="alert alert-error">${esc(res.mensagem)}</div>`;
        return;
      }
      if (box) box.innerHTML = `<pre class="json-viewer">${esc(JSON.stringify(res.relatorio || res, null, 2))}</pre>`;
    });
  }

  async _reloadDestinations() {
    const d = await api.destinations();
    if (d.ok) {
      this.destinations = d;
      this.renderEnvTab();
      this.renderExportTab();
      this.renderVerifyTab();
      this.onRefreshDestinations?.(d);
    }
  }
}
