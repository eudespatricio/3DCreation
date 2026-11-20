/**
 * Forge3D Studio Web — Cliente REST (/api/*), Serializador spec@6 e Utilitários UI.
 * Puro ES2022, zero dependências externas, zero caminhos pessoais fixos (I15).
 */

export const STATIC_ENUMS = {
  tipos: [
    'prop_estatico', 'prop_equipavel', 'personagem_humanoide', 'criatura',
    'criatura_quadrupede', 'criatura_alada', 'montaria', 'modulo_cenario',
    'textura', 'mapa_setor',
  ],
  rotas: [
    'blocky', 'import', 'mesh', 'modular',
    'i23d', 'template', 'procedural', 'extrude_2d',
  ],
  estilos: ['blocky_voxel', 'lowpoly_lit', 'stylized_pbr'],
  pivots: ['base', 'centro', 'origem', 'empunhadura', 'topo'],
  materiais: ['opaque', 'alpha_clip', 'transparent', 'pbr'],
  materiais_procedurais: [
    'pele_humana', 'escamas_dragao', 'aco_forjado', 'ouro_ornamentado',
    'couro_gasto', 'cristal_arcano', 'pedra_musgo', 'tecido_nobre',
    'madeira_ancestral', 'energia_espectral',
  ],
  providers_conceito: ['auto', 'sd15', 'gemini', 'higgsfield'],
  colisoes: ['none', 'box', 'convex', 'ucx'],
  qualidades: ['standard', 'hero', 'ultra'],
  esqueletos: [
    'godot-humanoid@1', 'godot-humanoid-aa@1', 'r15@1',
    'quadruped@1', 'winged_mount@1',
  ],
  rig_modos: ['none', 'skinned', 'motor6d'],
  clipes: [
    'idle', 'walk', 'run', 'jump', 'attack', 'slash_combo', 'cast',
    'block', 'hit', 'death', 'ride_idle', 'ride_fly', 'gallop',
    'wing_flap', 'glide', 'bite', 'roar',
  ],
  sockets: [
    'Hand.R', 'Hand.L', 'Back', 'Head', 'Shoulder.L', 'Shoulder.R', 'MountSeat',
  ],
  partes_r15: [
    'LowerTorso', 'UpperTorso', 'Head',
    'LeftUpperArm', 'LeftLowerArm', 'LeftHand',
    'RightUpperArm', 'RightLowerArm', 'RightHand',
    'LeftUpperLeg', 'LeftLowerLeg', 'LeftFoot',
    'RightUpperLeg', 'RightLowerLeg', 'RightFoot',
  ],
  partes_kit: [
    'corpo', 'capa', 'arma', 'cabelo', 'elmo', 'ombreiras', 'peitoral',
    'luvas', 'calcas', 'botas', 'escudo', 'mochila', 'orbe', 'sela', 'asas',
  ],
};

export function createDefaultSpec() {
  return {
    schema: 'forge3d/spec@6',
    projeto: 'estudio_demo',
    perfil: 'godot4',
    destino_exportacao: '~/.local/state/forge3d/saida/estudio_demo',
    estilo_global: 'blocky_voxel',
    paleta: ['#3b82f6', '#1e293b', '#94a3b8', '#f59e0b'],
    politica: { falha: 'continuar', custo_max_min: 30, seed_base: 42 },
    requisicao: { id: 'req-studio-01', isolamento: 'padrao', limpar_destino: false },
    orcamento_cena: { triangulos_max: 400000, draw_calls_max: 400, vram_mb_max: 200 },
    roblox_render: {
      lighting_technology: 'Future',
      render_fidelity_padrao: 'Precise',
      surface_appearance: true,
      strip_embedded_textures_glb: true,
    },
    lote: [
      {
        id: 'prop.bau.madeira.01',
        tipo: 'prop_estatico',
        rota: 'blocky',
        altura_metros: 0.9,
        pivot: 'base',
        limite_triangulos: 1200,
        material: 'opaque',
        colisao: 'box',
        lod: [100, 50],
        quantidade_cena: 2,
        tags: ['bau', 'madeira'],
      },
    ],
  };
}

export function esc(val) {
  if (val === null || val === undefined) return '';
  return String(val)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function fmtBytes(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) return '0 B';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

export function fmtNum(val, digits = 0) {
  const n = Number(val);
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString('pt-BR', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function toast(mensagem, tipo = 'info', duracaoMs = 4000) {
  const box = document.getElementById('toast-container');
  if (!box) return;
  const el = document.createElement('div');
  el.className = `toast toast-${esc(tipo)}`;
  el.textContent = String(mensagem || '');
  box.appendChild(el);
  setTimeout(() => {
    el.classList.add('toast-fade');
    setTimeout(() => el.remove(), 260);
  }, duracaoMs);
}

function cleanParams(obj = {}) {
  const out = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v !== undefined && v !== null && v !== '') out[k] = String(v);
  }
  return out;
}

async function request(method, url, body = undefined) {
  const opts = {
    method,
    headers: { Accept: 'application/json' },
  };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  try {
    const res = await fetch(url, opts);
    const contentType = res.headers.get('content-type') || '';
    let data = {};
    if (contentType.includes('application/json')) {
      data = await res.json();
    } else {
      const txt = await res.text();
      try {
        data = JSON.parse(txt);
      } catch {
        data = { ok: res.ok, mensagem: txt || res.statusText };
      }
    }
    const ok = Boolean(res.ok && data.ok !== false);
    return {
      ...data,
      ok,
      httpStatus: res.status,
      codigo: data.codigo || (ok ? null : `HTTP-${res.status}`),
      mensagem: data.mensagem || data.erro?.mensagem || (ok ? '' : res.statusText),
    };
  } catch (err) {
    return {
      ok: false,
      httpStatus: 0,
      codigo: 'FORGE-E-REDE',
      mensagem: err instanceof Error ? err.message : String(err),
      detalhes: {},
    };
  }
}

export function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || '');
      const comma = result.indexOf(',');
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(reader.error || new Error('Falha ao ler arquivo'));
    reader.readAsDataURL(file);
  });
}

export const api = {
  health: () => request('GET', '/api/health'),
  doctor: () => request('GET', '/api/doctor'),
  meta: () => request('GET', '/api/meta'),
  example: (name) => request('GET', `/api/examples/${encodeURIComponent(name)}`),
  destinations: () => request('GET', '/api/destinations'),
  assets: (params = {}) => {
    const qs = new URLSearchParams(cleanParams(params)).toString();
    return request('GET', qs ? `/api/assets?${qs}` : '/api/assets');
  },
  asset: (destino, id) => {
    const qs = new URLSearchParams({ destino: destino || '', id: id || '' }).toString();
    return request('GET', `/api/asset?${qs}`);
  },
  bundleZipUrl: (destino, id) => {
    const qs = new URLSearchParams({ destino: destino || '', id: id || '' }).toString();
    return `/api/asset/bundle.zip?${qs}`;
  },
  fileUrl: (path, download = false) => {
    const params = { path: path || '' };
    if (download) params.download = '1';
    return `/api/file?${new URLSearchParams(params).toString()}`;
  },
  runs: (limit = 50) => request('GET', `/api/runs?limit=${encodeURIComponent(limit)}`),
  runDetail: (runId) => request('GET', `/api/runs/${encodeURIComponent(runId)}`),
  ledger: (limit = 100) => request('GET', `/api/ledger?limit=${encodeURIComponent(limit)}`),
  jobs: () => request('GET', '/api/jobs'),
  job: (jobId) => request('GET', `/api/jobs/${encodeURIComponent(jobId)}`),
  uploadInput: (nome, conteudo_b64, categoria = 'origem') =>
    request('POST', '/api/upload-input', { nome, conteudo_b64, categoria }),
  uploadFile: async (file, categoria = 'origem') => {
    const b64 = await fileToBase64(file);
    return request('POST', '/api/upload-input', {
      nome: file.name,
      conteudo_b64: b64,
      categoria,
    });
  },
  saveSpec: (nome, yaml) => request('POST', '/api/spec/save', { nome, yaml }),
  validate: (yaml) => request('POST', '/api/validate', { yaml }),
  plan: (yaml, { no_cache = false, scene_budget = true } = {}) =>
    request('POST', '/api/plan', { yaml, no_cache, scene_budget }),
  run: (yaml, { nao_publicar = false, no_cache = false, clean_dest = false } = {}) =>
    request('POST', '/api/run', { yaml, nao_publicar, no_cache, clean_dest }),
  cancelJob: (jobId) => request('POST', `/api/jobs/${encodeURIComponent(jobId)}/cancel`, {}),
  verify: (destino, only = '') => {
    const payload = { destino };
    if (only) payload.only = only;
    return request('POST', '/api/verify', payload);
  },
  migrate: (yaml) => request('POST', '/api/migrate', { yaml }),
  exportAsset: (payload) => request('POST', '/api/export', payload),
  sync: (payload) => request('POST', '/api/sync', payload),
  uploadCloud: (payload) => request('POST', '/api/upload-cloud', payload),
  allowlist: (acao, caminho = '') => request('POST', '/api/allowlist', { acao, caminho }),
  gc: (manter_dias = 30, aplicar = false) =>
    request('POST', '/api/gc', { manter_dias: Number(manter_dias), aplicar: Boolean(aplicar) }),
};

/**
 * Serializador YAML determinístico para documentos spec@6.
 */
function yamlScalar(v) {
  if (v === null || v === undefined) return 'null';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'number') return Number.isFinite(v) ? String(v) : '0';
  const s = String(v);
  if (
    s === '' ||
    /^[\d.-]/.test(s) ||
    /[:#[\]{},&*!|>'"%@`]/.test(s) ||
    /\s/.test(s) ||
    ['true', 'false', 'null', 'yes', 'no', 'on', 'off'].includes(s.toLowerCase())
  ) {
    return JSON.stringify(s);
  }
  return s;
}

function isEmptyVal(v) {
  if (v === undefined || v === null || v === '') return true;
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === 'object') return Object.keys(v).length === 0;
  return false;
}

function dumpYamlNode(node, indent = 0) {
  const pad = ' '.repeat(indent);
  const lines = [];
  if (Array.isArray(node)) {
    for (const item of node) {
      if (item !== null && typeof item === 'object' && !Array.isArray(item)) {
        const entries = Object.entries(item).filter(([, val]) => !isEmptyVal(val));
        if (entries.length === 0) {
          lines.push(`${pad}- {}`);
          continue;
        }
        const [firstK, firstV] = entries[0];
        if (typeof firstV !== 'object' || firstV === null) {
          lines.push(`${pad}- ${firstK}: ${yamlScalar(firstV)}`);
        } else {
          lines.push(`${pad}- ${firstK}:`);
          lines.push(...dumpYamlNode(firstV, indent + 4));
        }
        for (let i = 1; i < entries.length; i += 1) {
          const [k, v] = entries[i];
          lines.push(...dumpKeyVal(k, v, indent + 2));
        }
      } else {
        lines.push(`${pad}- ${yamlScalar(item)}`);
      }
    }
    return lines;
  }
  if (node && typeof node === 'object') {
    for (const [k, v] of Object.entries(node)) {
      if (isEmptyVal(v)) continue;
      lines.push(...dumpKeyVal(k, v, indent));
    }
  }
  return lines;
}

function dumpKeyVal(k, v, indent) {
  const pad = ' '.repeat(indent);
  if (Array.isArray(v)) {
    if (v.length > 0 && v.every((x) => typeof x !== 'object' || x === null)) {
      return [`${pad}${k}: [${v.map(yamlScalar).join(', ')}]`];
    }
    return [`${pad}${k}:`, ...dumpYamlNode(v, indent + 2)];
  }
  if (v && typeof v === 'object') {
    const cleaned = Object.fromEntries(
      Object.entries(v).filter(([, sub]) => !isEmptyVal(sub)),
    );
    if (Object.keys(cleaned).length === 0) return [];
    return [`${pad}${k}:`, ...dumpYamlNode(cleaned, indent + 2)];
  }
  return [`${pad}${k}: ${yamlScalar(v)}`];
}

export function specToYaml(doc) {
  const ordered = {
    schema: doc.schema || 'forge3d/spec@6',
    projeto: doc.projeto || 'estudio_demo',
    perfil: doc.perfil || 'godot4',
    destino_exportacao: doc.destino_exportacao || '~/.local/state/forge3d/saida/estudio_demo',
  };
  const optKeys = [
    'estilo_global', 'paleta', 'politica', 'requisicao',
    'orcamento_cena', 'roblox_render', 'lote',
  ];
  for (const k of optKeys) {
    if (!isEmptyVal(doc[k])) ordered[k] = doc[k];
  }
  for (const [k, v] of Object.entries(doc)) {
    if (!(k in ordered) && !k.startsWith('_') && !isEmptyVal(v)) {
      ordered[k] = v;
    }
  }
  return `${dumpYamlNode(ordered, 0).join('\n')}\n`;
}
