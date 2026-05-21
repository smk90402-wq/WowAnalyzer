// WowAnalyzer SPA — Week 2 foundation.
// 상태 관리: 단일 객체 + 명시적 render 함수. 프레임워크 X.

'use strict';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  difficulty: 'heroic',
  rows: [],           // 현재 difficulty 의 모든 랭킹 row
  bossFilter: '',     // encounter_id (string)
  classFilter: '',
  specFilter: '',
  selectedRowIdx: -1, // filtered rows 안의 인덱스
};

// ── 데이터 로드 ──────────────────────────────────────────────────────────
async function loadRankings(difficulty) {
  $('#meta').textContent = `${difficulty} 로딩 중…`;
  try {
    const r = await fetch(`/api/rankings/${difficulty}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();
    state.difficulty = difficulty;
    state.rows = j.rows;
    state.classFilter = '';
    state.specFilter = '';
    state.selectedRowIdx = -1;
    populateFilters();
    // 보스 자동 선택: 첫 보스. 24300 rows 전체 보단 보스별 ~2700 rows 가 더 유의미.
    const bossSel = $('#boss-select');
    if (bossSel.options.length > 1) {
      bossSel.selectedIndex = 1;
      state.bossFilter = bossSel.value;
    } else {
      state.bossFilter = '';
    }
    renderTable();
    $('#meta').textContent =
      `${j.row_count.toLocaleString()} rows · ${difficulty}`;
  } catch (e) {
    $('#meta').textContent = `로드 실패: ${e.message}`;
    console.error(e);
  }
}

// ── 필터 selector 채우기 (보스/클래스/스펙) ────────────────────────────
function populateFilters() {
  // 보스 — encounter_id → name 매핑, name 순
  const bosses = new Map();
  for (const r of state.rows) {
    if (r.encounter_id != null && !bosses.has(r.encounter_id)) {
      bosses.set(r.encounter_id, r.encounter_name);
    }
  }
  const bossSel = $('#boss-select');
  bossSel.innerHTML = '<option value="">(전체)</option>'
    + [...bosses.entries()]
        .map(([id, nm]) => `<option value="${id}">${esc(nm)}</option>`)
        .join('');

  // 클래스 — 중복 제거 + 정렬
  const classes = [...new Set(state.rows.map(r => r.class).filter(Boolean))].sort();
  $('#class-select').innerHTML = '<option value="">(전체)</option>'
    + classes.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('');

  // 스펙은 클래스 선택에 따라 갱신
  updateSpecOptions();
}

function updateSpecOptions() {
  const cls = state.classFilter;
  const specs = [...new Set(
    state.rows
      .filter(r => !cls || r.class === cls)
      .map(r => r.spec).filter(Boolean)
  )].sort();
  $('#spec-select').innerHTML = '<option value="">(전체)</option>'
    + specs.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
}

// ── 필터 적용 + 테이블 렌더 ─────────────────────────────────────────────
function filteredRows() {
  return state.rows.filter(r => {
    if (state.bossFilter && String(r.encounter_id) !== state.bossFilter) return false;
    if (state.classFilter && r.class !== state.classFilter) return false;
    if (state.specFilter && r.spec !== state.specFilter) return false;
    return true;
  });
}

function renderTable() {
  const rows = filteredRows();
  const tbody = $('#ranking-body');
  // 보스+클래스 필터 적용 시 보통 100명 미만. 무필터 + 영웅 전체 = 24300 → cap 1500 으로 부드럽게.
  const max = 1500;
  const slice = rows.slice(0, max);
  tbody.innerHTML = slice.map((r, i) => `
    <tr data-idx="${i}">
      <td class="mute num">${r.rank ?? ''}</td>
      <td>${esc(r.character ?? '')}</td>
      <td class="mute">${esc(r.guild ?? '')}</td>
      <td class="mute">${esc(r.server ?? '')}</td>
      <td class="right num">${r.dps != null ? Math.round(r.dps).toLocaleString() : ''}</td>
      <td class="right mute num">${r.item_level ?? ''}</td>
    </tr>
  `).join('');
  $('#count').textContent =
    `${rows.length.toLocaleString()} / ${state.rows.length.toLocaleString()} rows`
    + (rows.length > max ? ` (상위 ${max}개 표시 — 필터 좁혀서 좁히기)` : '');
}

// ── 행 클릭 → 캐릭터 빌드 페치 ──────────────────────────────────────────
async function onRowClick(rowEl) {
  const idx = parseInt(rowEl.dataset.idx, 10);
  if (Number.isNaN(idx)) return;
  $$('#ranking-body tr.selected').forEach(t => t.classList.remove('selected'));
  rowEl.classList.add('selected');
  const r = filteredRows()[idx];
  if (!r) return;
  state.selectedRowIdx = idx;

  const rid = r.report_id, fid = r.fight_id, char = r.character;
  $('#build-title').textContent = `캐릭터 빌드 — ${char}`;
  $('#build-body').className = '';
  $('#build-body').innerHTML =
    `<p style="color:var(--text-mute)">${esc(char)} 데이터 로드 중…</p>`;

  try {
    const resp = await fetch(`/api/character/${encodeURIComponent(rid)}/${fid}/${encodeURIComponent(char)}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
    const d = await resp.json();
    renderBuild(d, r);
  } catch (e) {
    $('#build-body').innerHTML =
      `<p style="color:#d97757">로드 실패: ${esc(e.message)}</p>`
      + `<p style="color:var(--text-mute);font-size:11px">백필 안 된 캐릭이면 V2 페치에 수~십초 걸림. 잠시 후 재시도.</p>`;
  }
}

function renderBuild(d, row) {
  const gear = d.gear || [];
  const statsKr = d.stats_kr || [];
  const tlUrl = `/api/timeline/${encodeURIComponent(row.report_id)}/${row.fight_id}/${encodeURIComponent(row.character)}`;
  const treeUrl = `/api/talent-tree/${encodeURIComponent(row.report_id)}/${row.fight_id}/${encodeURIComponent(row.character)}?cls=${encodeURIComponent(row.class)}&spec=${encodeURIComponent(row.spec)}`;
  $('#build-body').innerHTML = `
    <div class="build-section">
      <div class="build-row">
        <span class="k">캐릭</span>
        <span class="v">${esc(row.character)} · ${esc(row.class)} ${esc(row.spec)} · ilvl ${row.item_level ?? '?'}</span>
      </div>
      <div class="build-row">
        <span class="k">DPS</span>
        <span class="v">${row.dps != null ? Math.round(row.dps).toLocaleString() : '?'} · #${row.rank}</span>
      </div>
      <div class="build-row">
        <span class="k">보스</span>
        <span class="v">${esc(d.encounter_name || row.encounter_name)}</span>
      </div>
    </div>
    <h3>딜사이클</h3>
    <iframe class="tl-frame" src="${tlUrl}" title="타임라인"></iframe>
    <h3>특성 트리
      <span class="tree-toggle">
        <button class="tree-mode active" data-mode="self">본인 픽</button>
        <button class="tree-mode" data-mode="agg">Top100 픽률</button>
      </span>
    </h3>
    <iframe class="tree-frame" id="tree-frame" src="${treeUrl}" title="특성 트리"
      data-self-url="${treeUrl}"
      data-agg-url="/api/talent-tree-aggregate?cls=${encodeURIComponent(row.class)}&spec=${encodeURIComponent(row.spec)}&encounter_id=${row.encounter_id}&difficulty=${state.difficulty}"></iframe>
    <h3>장비 (${gear.length} 슬롯)</h3>
    <ul class="gear-list">
      ${gear.map(g => gearItemHtml(g)).join('')}
    </ul>
    <h3>스탯</h3>
    ${renderStats(statsKr)}
  `;
}

const QUALITY_COLOR = {
  POOR: '#9d9d9d', COMMON: '#ffffff', UNCOMMON: '#1eff00',
  RARE: '#0070dd', EPIC: '#a335ee', LEGENDARY: '#ff8000',
  ARTIFACT: '#e6cc80', HEIRLOOM: '#00ccff',
};

function gearItemHtml(g) {
  const name = g.name_ko || `#${g.id ?? '?'}`;
  const color = QUALITY_COLOR[(g.quality || '').toUpperCase()] || 'var(--text)';
  const iconUrl = g.icon
    ? `https://wow.zamimg.com/images/wow/icons/medium/${g.icon}`
    : '';
  // wowhead 링크 — 호버 시 wowhead 가 native 툴팁 띄움 (외부 인터넷 필요)
  const wh = g.id
    ? `https://www.wowhead.com/item=${g.id}?ilvl=${g.ilvl ?? ''}`
    : '';
  return `
    <li class="gear-item">
      ${iconUrl ? `<img class="gicon" src="${iconUrl}" alt="">` : '<span class="gicon-empty"></span>'}
      <div class="ginfo">
        <a class="gname" href="${wh}" target="_blank" rel="noopener" style="color:${color}">${esc(name)}</a>
        <span class="gmeta">${esc(g.slot_kr || '')} · ilvl ${g.ilvl ?? '?'}</span>
      </div>
    </li>
  `;
}

function renderStats(stats) {
  if (!stats.length) return '<p style="color:var(--text-mute)">캐시 없음</p>';
  return `
    <table class="stats-table">
      <tbody>
        ${stats.map(s => `
          <tr>
            <td class="sk">${esc(s.label_kr)}</td>
            <td class="sv">${s.rating != null ? s.rating.toLocaleString() : '?'}</td>
            <td class="sp">${s.pct != null ? `${s.pct.toFixed(2)}%` : ''}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

// ── 유틸 ────────────────────────────────────────────────────────────────
function esc(s) {
  if (s == null) return '';
  return String(s)
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

// ── 이벤트 바인딩 ───────────────────────────────────────────────────────
function switchTab(tab) {
  $$('#tabs .tab').forEach(t => t.classList.remove('active'));
  $$('.tab-pane').forEach(p => p.classList.remove('active'));
  const btn = document.querySelector(`#tabs .tab[data-tab="${tab}"]`);
  if (btn) btn.classList.add('active');
  // ranking pane: heroic/mythic 공용. arbitrary: 별도 pane.
  const paneId = (tab === 'arbitrary') ? 'arbitrary' : 'ranking';
  document.querySelector(`#pane-${paneId}`).classList.add('active');
}

function bind() {
  $('#tabs').addEventListener('click', e => {
    const btn = e.target.closest('.tab');
    if (!btn || btn.classList.contains('disabled')) return;
    const tab = btn.dataset.tab;
    switchTab(tab);
    if (tab === 'heroic' || tab === 'mythic') {
      loadRankings(tab);
    }
  });

  // 임의 로그
  $('#arb-fetch').addEventListener('click', onArbitraryFetch);
  $('#arb-url').addEventListener('keydown', e => {
    if (e.key === 'Enter') onArbitraryFetch();
  });
  $('#arb-fight').addEventListener('change', onArbitraryFightChange);
  $('#arb-player-body').addEventListener('click', e => {
    const tr = e.target.closest('tr');
    if (tr) onArbitraryPlayerClick(tr);
  });

  $('#boss-select').addEventListener('change', e => {
    state.bossFilter = e.target.value;
    renderTable();
  });
  $('#class-select').addEventListener('change', e => {
    state.classFilter = e.target.value;
    state.specFilter = '';
    updateSpecOptions();
    renderTable();
  });
  $('#spec-select').addEventListener('change', e => {
    state.specFilter = e.target.value;
    renderTable();
  });

  $('#ranking-body').addEventListener('click', e => {
    const tr = e.target.closest('tr');
    if (tr) onRowClick(tr);
  });

  // 트리 본인/Top100 토글 — 빌드 패널이 매번 재렌더되므로 위임 핸들러
  $('#build-body').addEventListener('click', e => {
    const btn = e.target.closest('.tree-mode');
    if (!btn) return;
    const iframe = $('#tree-frame');
    if (!iframe) return;
    const mode = btn.dataset.mode;
    const url = mode === 'agg' ? iframe.dataset.aggUrl : iframe.dataset.selfUrl;
    iframe.src = url;
    document.querySelectorAll('.tree-mode').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  });
}

// ── 임의 로그 탭 ────────────────────────────────────────────────────────
const arbState = {
  rid: null,
  meta: null,        // /api/report response
  fights: [],
  fid: null,
  players: [],
  selectedChar: null,
};

function parseWclUrl(url) {
  // https://www.warcraftlogs.com/reports/{rid}?fight={fid} (한국 도메인 ko. 도)
  const m = url.match(/reports\/([A-Za-z0-9]+)(?:.*?fight=([0-9]+))?/);
  return m ? { rid: m[1], fid: m[2] ? parseInt(m[2], 10) : null } : null;
}

async function onArbitraryFetch() {
  const url = $('#arb-url').value.trim();
  const parsed = parseWclUrl(url);
  if (!parsed) {
    $('#arb-status').textContent = 'URL 파싱 실패 — warcraftlogs.com/reports/... 형식';
    return;
  }
  $('#arb-status').textContent = '리포트 페치 중…';
  try {
    const r = await fetch(`/api/report/${encodeURIComponent(parsed.rid)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
    const meta = await r.json();
    arbState.rid = parsed.rid;
    arbState.meta = meta;
    arbState.fights = meta.fights || [];
    if (arbState.fights.length === 0) {
      $('#arb-status').textContent = 'fight 0개 (private 이거나 잘못된 ID)';
      return;
    }
    populateArbFights(parsed.fid);
    $('#arb-status').textContent = `${parsed.rid} · fights ${arbState.fights.length}개`;
  } catch (e) {
    $('#arb-status').textContent = `실패: ${e.message}`;
    console.error(e);
  }
}

function populateArbFights(preferFid) {
  const DIFF_KR = {1: 'LFR', 2: 'Normal', 3: 'Heroic', 4: 'Mythic', 5: 'Mythic'};
  const sel = $('#arb-fight');
  sel.innerHTML = arbState.fights.map(f => {
    const dur = ((f.endTime || 0) - (f.startTime || 0)) / 1000;
    const diff = DIFF_KR[f.difficulty] || `diff${f.difficulty}`;
    const kill = f.kill ? '✓' : '✗';
    const nm = f.name || `enc ${f.encounterID}`;
    return `<option value="${f.id}">fight ${f.id} · ${diff} · ${kill} ${esc(nm)} (${dur.toFixed(0)}s)</option>`;
  }).join('');
  if (preferFid) {
    const opt = sel.querySelector(`option[value="${preferFid}"]`);
    if (opt) sel.value = String(preferFid);
  }
  onArbitraryFightChange();
}

function onArbitraryFightChange() {
  const fidStr = $('#arb-fight').value;
  if (!fidStr) return;
  arbState.fid = parseInt(fidStr, 10);
  // V2Data.report_meta 의 actors 는 {name: sourceID} dict. report 전체 (per-fight 아님).
  // 클릭 시 pfight 가 None 이면 "이 fight 미참가" 표시.
  const actorsObj = arbState.meta?.actors || {};
  const names = Object.keys(actorsObj).sort((a, b) => a.localeCompare(b, 'ko'));
  arbState.players = names;
  const tbody = $('#arb-player-body');
  tbody.innerHTML = names.map(nm => `
    <tr data-name="${esc(nm)}">
      <td>${esc(nm)}</td>
      <td class="mute">source #${actorsObj[nm]}</td>
      <td class="mute">${esc('—')}</td>
    </tr>
  `).join('');
  $('#arb-build-body').className = 'empty';
  $('#arb-build-body').textContent = '플레이어 클릭';
}

async function onArbitraryPlayerClick(tr) {
  $$('#arb-player-body tr.selected').forEach(t => t.classList.remove('selected'));
  tr.classList.add('selected');
  const char = tr.dataset.name;
  arbState.selectedChar = char;
  const rid = arbState.rid;
  const fid = arbState.fid;
  if (!rid || !fid || !char) return;

  $('#arb-build-title').textContent = `캐릭터 빌드 — ${char}`;
  $('#arb-build-body').className = '';
  $('#arb-build-body').innerHTML =
    `<p style="color:var(--text-mute)">${esc(char)} 데이터 로드 중… (V2 페치 + events, 수~십초 가능)</p>`;
  try {
    const r = await fetch(`/api/character/${encodeURIComponent(rid)}/${fid}/${encodeURIComponent(char)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
    const d = await r.json();
    // ranking row 형태로 emulate (renderBuild 재사용)
    const fakeRow = {
      character: char,
      class: '',  // V2 player_fight 응답에 직접 없음
      spec: '',
      item_level: null,
      dps: null,
      rank: null,
      report_id: rid,
      fight_id: fid,
      encounter_id: d.encounter_id,
      encounter_name: d.encounter_name,
    };
    renderBuildInto('#arb-build-body', d, fakeRow);
  } catch (e) {
    $('#arb-build-body').innerHTML =
      `<p style="color:#d97757">로드 실패: ${esc(e.message)}</p>`;
  }
}

function renderBuildInto(selector, d, row) {
  // ranking 의 renderBuild 와 동일 — 단지 target selector 만 다름
  const gear = d.gear || [];
  const statsKr = d.stats_kr || [];
  const tlUrl = `/api/timeline/${encodeURIComponent(row.report_id)}/${row.fight_id}/${encodeURIComponent(row.character)}`;
  document.querySelector(selector).innerHTML = `
    <div class="build-section">
      <div class="build-row">
        <span class="k">캐릭</span>
        <span class="v">${esc(row.character)}</span>
      </div>
      <div class="build-row">
        <span class="k">보스</span>
        <span class="v">${esc(d.encounter_name || row.encounter_name || '?')}</span>
      </div>
    </div>
    <h3>딜사이클</h3>
    <iframe class="tl-frame" src="${tlUrl}" title="타임라인"></iframe>
    <h3>장비 (${gear.length} 슬롯)</h3>
    <ul class="gear-list">
      ${gear.map(g => gearItemHtml(g)).join('')}
    </ul>
    <h3>스탯</h3>
    ${renderStats(statsKr)}
  `;
}

// ── 부트 ────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  bind();
  loadRankings('heroic');
});
