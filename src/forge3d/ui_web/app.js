/**
 * Forge3D Studio Web — Controlador Principal SPA (5 Workspaces, Status Bar, Lightbox e Sincronização).
 */

import { api, esc, toast } from './api.js';
import { OpsView } from './ops_view.js';
import { OutputsView } from './outputs_view.js';
import { SpecBuilderView } from './spec_builder.js';

class Forge3DStudioApp {
  constructor() {
    this.activeTab = 'studio';
    this.specBuilder = null;
    this.outputsView = null;
    this.opsView = null;
    this.lastJobStatus = null;
  }

  async start() {
    this._bindNavigation();
    this._bindLightbox();

    const studioEl = document.getElementById('tab-studio');
    const outputsEl = document.getElementById('tab-outputs');
    const exportEl = document.getElementById('tab-export');
    const verifyEl = document.getElementById('tab-verify');
    const envEl = document.getElementById('tab-env');

    this.specBuilder = new SpecBuilderView(studioEl, {
      onOpenAsset: (destino, assetId) => {
        this.switchTab('outputs');
        this.outputsView?.openAsset(destino, assetId);
      },
      onJobUpdate: (job) => this._handleJobUpdate(job),
    });

    this.outputsView = new OutputsView(outputsEl, {
      onJumpVerify: (destino) => {
        this.switchTab('verify');
        this.opsView?.runVerifyForDestination(destino);
      },
      onJumpExport: (assetDetail) => {
        this.switchTab('export');
        this.opsView?.prefillExportFromAsset(assetDetail);
      },
      onOpenLightbox: (url, title) => this.openLightbox(url, title),
    });

    this.opsView = new OpsView({
      exportEl,
      verifyEl,
      envEl,
      onRefreshDestinations: (dests) => {
        this.specBuilder?.init(null, dests);
        this.outputsView?.init(dests);
      },
      onJobUpdate: (job) => this._handleJobUpdate(job),
    });

    // Renderiza estado inicial imediatamente mesmo antes da rede responder
    this.specBuilder.init(null, null);

    const [health, doctorRes, meta, destinations, jobsRes] = await Promise.all([
      api.health(),
      api.doctor(),
      api.meta(),
      api.destinations(),
      api.jobs(),
    ]);

    this._updateHeaderStatus(health, doctorRes, jobsRes);
    this.specBuilder.init(meta, destinations);
    await this.outputsView.init(destinations);
    await this.opsView.init(meta, destinations, doctorRes);
  }

  switchTab(tabId) {
    this.activeTab = tabId;
    window.scrollTo(0, 0);
    document.querySelectorAll('.nav-tab').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.tab === tabId);
    });
    document.querySelectorAll('.workspace-pane').forEach((pane) => {
      pane.classList.toggle('hidden', pane.id !== `tab-${tabId}`);
    });
    if (tabId === 'outputs') {
      this.outputsView?.viewer?.resize();
    } else if (tabId === 'verify') {
      this.opsView?.refreshHistory();
    }
  }

  _bindNavigation() {
    document.querySelectorAll('.nav-tab').forEach((btn) => {
      btn.addEventListener('click', () => this.switchTab(btn.dataset.tab));
    });
    document.getElementById('pill-job')?.addEventListener('click', () => {
      this.switchTab('studio');
      document.getElementById('sb-output-drawer')?.scrollIntoView({ behavior: 'smooth' });
    });
    document.getElementById('btn-header-refresh')?.addEventListener('click', async () => {
      const [health, doctorRes, destinations, jobsRes] = await Promise.all([
        api.health(),
        api.doctor(),
        api.destinations(),
        api.jobs(),
      ]);
      this._updateHeaderStatus(health, doctorRes, jobsRes);
      await this.outputsView?.refreshAssets();
      await this.opsView?.init(null, destinations, doctorRes);
      toast('Estado do Studio sincronizado', 'ok');
    });
  }

  _updateHeaderStatus(health, doctorRes, jobsRes) {
    const vBadge = document.getElementById('badge-versao');
    if (vBadge && health?.ok) {
      vBadge.textContent = `v${health.versao || '0.9.5'} · pipe ${health.pipeline_version || '0.9.5'} · spec@6`;
    }

    const doc = doctorRes?.doctor || doctorRes || {};
    const checks = doc.checks || [];
    const findCheck = (name) => checks.find((c) => c.nome === name);

    const setPill = (id, label, checkObj, warnIfFalse = false) => {
      const el = document.getElementById(id);
      if (!el) return;
      const ok = checkObj ? Boolean(checkObj.ok) : true;
      el.className = `status-pill ${ok ? 'pill-ok' : warnIfFalse ? 'pill-warn' : 'pill-err'}`;
      el.textContent = `${label}: ${ok ? 'OK' : 'Atenção'}`;
      if (checkObj?.detalhe) el.title = checkObj.detalhe;
    };

    setPill('pill-blender', 'Blender 4.2', findCheck('blender'));
    setPill('pill-gpu', 'GPU', findCheck('gpu'), true);
    setPill('pill-estado', 'Estado ext4', findCheck('estado'));

    const iaEl = document.getElementById('pill-ia');
    if (iaEl) {
      const entries = Object.values(doc.conectores_ia || {});
      const ready = entries.filter((x) => x.pronto || x.ok).length;
      iaEl.className = `status-pill ${ready > 0 ? 'pill-ok' : 'pill-warn'}`;
      iaEl.textContent = `IA: ${ready}/${entries.length || 7}`;
      iaEl.title = 'Conectores de IA prontos (veja Ambiente & Governança)';
    }

    const jobs = jobsRes?.jobs || [];
    const running = jobs.find((j) => j.status === 'running');
    if (running) this._handleJobUpdate(running);
  }

  async _handleJobUpdate(job) {
    const pill = document.getElementById('pill-job');
    if (!pill || !job) return;
    if (job.status === 'running') {
      pill.className = 'status-pill pill-running';
      pill.textContent = `⟳ Job ${job.job_id} em execução`;
    } else if (job.status === 'done' && (job.exit_code === 0 || job.exit_code === undefined)) {
      pill.className = 'status-pill pill-ok';
      pill.textContent = `✔ Job ${job.job_id} concluído`;
    } else {
      pill.className = 'status-pill pill-err';
      pill.textContent = `✖ Job ${job.job_id} (${job.status})`;
    }

    if (this.lastJobStatus === 'running' && job.status !== 'running') {
      const dests = await api.destinations();
      await this.outputsView?.init(dests);
      await this.opsView?.refreshHistory();
    }
    this.lastJobStatus = job.status;
  }

  _bindLightbox() {
    const modal = document.getElementById('lightbox-modal');
    modal?.addEventListener('click', (e) => {
      if (e.target === modal || e.target.id === 'lightbox-close') {
        modal.classList.add('hidden');
      }
    });
  }

  openLightbox(url, title = '') {
    const modal = document.getElementById('lightbox-modal');
    const img = document.getElementById('lightbox-img');
    const cap = document.getElementById('lightbox-caption');
    if (!modal || !img) return;
    img.src = url;
    if (cap) cap.innerHTML = `${esc(title)} · <a href="${esc(url)}" target="_blank" rel="noopener">Abrir original</a>`;
    modal.classList.remove('hidden');
  }
}

window.addEventListener('DOMContentLoaded', () => {
  const app = new Forge3DStudioApp();
  app.start();
});
