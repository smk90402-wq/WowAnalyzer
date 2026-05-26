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
  const aggUrl = `/api/talent-tree-aggregate?cls=${encodeURIComponent(row.class)}&spec=${encodeURIComponent(row.spec)}&encounter_id=${row.encounter_id}&difficulty=${state.difficulty}`;
  $('#build-body').innerHTML = `
    <div class="bp-header">
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
      ${renderPrepull(d.prepull)}
    </div>
    <div class="bp-tabs">
      <button class="bp-tab active" data-bp-tab="cycle">딜사이클</button>
      <button class="bp-tab" data-bp-tab="gear">아이템 / 특성 / 스탯</button>
    </div>
    <div class="bp-pane active" data-bp-pane="cycle">
      <iframe class="tl-frame" src="${tlUrl}" title="타임라인"></iframe>
    </div>
    <div class="bp-pane" data-bp-pane="gear">
      <h3>특성 트리
        <span class="tree-toggle">
          <button class="tree-mode active" data-mode="self">본인 픽</button>
          <button class="tree-mode" data-mode="agg">Top100 픽률</button>
        </span>
      </h3>
      <iframe class="tree-frame" id="tree-frame" src="${treeUrl}" title="특성 트리"
        data-self-url="${treeUrl}"
        data-agg-url="${aggUrl}"></iframe>
      <h3>장비 (${gear.length} 슬롯)</h3>
      <ul class="gear-list">
        ${gear.map(g => gearItemHtml(g)).join('')}
      </ul>
      <h3>스탯</h3>
      ${renderStats(statsKr)}
    </div>
  `;
}

// prepull = [{spell_id, ts, name_ko, icon}] — 음식/영약/오일/숫돌 등 전투 직전 5초 안에 적용된 버프.
// 백엔드가 spell_db 로 name_ko + icon 채워 보냄. 빈 배열이면 섹션 숨김.
function renderPrepull(prepull) {
  if (!Array.isArray(prepull) || prepull.length === 0) return '';
  return `
    <h3>전투 직전 버프 (${prepull.length})</h3>
    <ul class="prepull-list">
      ${prepull.map(p => {
        const iconUrl = p.icon
          ? `https://wow.zamimg.com/images/wow/icons/medium/${p.icon}`
          : 'https://wow.zamimg.com/images/wow/icons/medium/inv_misc_questionmark.jpg';
        return `
          <li class="prepull-item">
            <img class="picon" src="${iconUrl}" alt="">
            <a class="pname" href="https://www.wowhead.com/spell=${p.spell_id}"
               target="_blank" rel="noopener">${esc(p.name_ko)}</a>
          </li>`;
      }).join('')}
    </ul>
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

  // 우클릭 → 비교에 추가
  $('#ranking-body').addEventListener('contextmenu', e => {
    const tr = e.target.closest('tr');
    if (!tr) return;
    e.preventDefault();
    const idx = parseInt(tr.dataset.idx, 10);
    const r = filteredRows()[idx];
    if (!r) return;
    showContextMenu(e.clientX, e.clientY, [
      { label: `비교 좌측 추가 (${r.character})`,
        onClick: () => compLoadInto('left', r.report_id, r.fight_id, r.character) },
      { label: `비교 우측 추가 (${r.character})`,
        onClick: () => compLoadInto('right', r.report_id, r.fight_id, r.character) },
    ]);
  });

  // 빌드 패널 위임 — 매 row 클릭마다 재렌더 → 위임 패턴 필수
  function bindBuildPanel(rootSel) {
    document.querySelector(rootSel).addEventListener('click', e => {
      // 1) 트리 본인 vs Top100 토글
      const tBtn = e.target.closest('.tree-mode');
      if (tBtn) {
        const iframe = document.querySelector(rootSel + ' .tree-frame');
        if (!iframe) return;
        const url = tBtn.dataset.mode === 'agg'
          ? iframe.dataset.aggUrl : iframe.dataset.selfUrl;
        if (url) iframe.src = url;
        document.querySelectorAll(rootSel + ' .tree-mode')
          .forEach(b => b.classList.remove('active'));
        tBtn.classList.add('active');
        return;
      }
      // 2) 딜사이클 ↔ 아이템/특성/스탯 탭 전환
      const pBtn = e.target.closest('.bp-tab');
      if (pBtn) {
        const root = document.querySelector(rootSel);
        root.querySelectorAll('.bp-tab').forEach(b => b.classList.remove('active'));
        pBtn.classList.add('active');
        root.querySelectorAll('.bp-pane').forEach(p => p.classList.toggle(
          'active', p.dataset.bpPane === pBtn.dataset.bpTab));
        return;
      }
    });
  }
  bindBuildPanel('#build-body');
  bindBuildPanel('#arb-build-body');
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
    // class/spec 은 백엔드가 talent_trees.json 5스펙 중 매칭되는 거 추론해서 보냄
    const fakeRow = {
      character: char,
      class: d.inferred_class || '',
      spec: d.inferred_spec || '',
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
  // ranking 의 renderBuild 와 동일 구조 — target selector 만 다름. 탭으로 분리.
  const gear = d.gear || [];
  const statsKr = d.stats_kr || [];
  const tlUrl = `/api/timeline/${encodeURIComponent(row.report_id)}/${row.fight_id}/${encodeURIComponent(row.character)}`;
  const hasTree = row.class && row.spec;
  const treeUrl = hasTree
    ? `/api/talent-tree/${encodeURIComponent(row.report_id)}/${row.fight_id}/${encodeURIComponent(row.character)}?cls=${encodeURIComponent(row.class)}&spec=${encodeURIComponent(row.spec)}`
    : '';
  const treeHtml = hasTree
    ? `<h3>특성 트리 (${esc(row.class)} ${esc(row.spec)})</h3>
       <iframe class="tree-frame" src="${treeUrl}" title="특성 트리"></iframe>`
    : '<p style="color:var(--text-mute);font-size:11px">특성 트리: talent_trees.json 미등록 스펙 (5 타깃 외 클래스)</p>';
  document.querySelector(selector).innerHTML = `
    <div class="bp-header">
      <div class="build-section">
        <div class="build-row">
          <span class="k">캐릭</span>
          <span class="v">${esc(row.character)}${hasTree ? ` · ${esc(row.class)} ${esc(row.spec)}` : ''}</span>
        </div>
        <div class="build-row">
          <span class="k">보스</span>
          <span class="v">${esc(d.encounter_name || row.encounter_name || '?')}</span>
        </div>
      </div>
      ${renderPrepull(d.prepull)}
    </div>
    <div class="bp-tabs">
      <button class="bp-tab active" data-bp-tab="cycle">딜사이클</button>
      <button class="bp-tab" data-bp-tab="gear">아이템 / 특성 / 스탯</button>
    </div>
    <div class="bp-pane active" data-bp-pane="cycle">
      <iframe class="tl-frame" src="${tlUrl}" title="타임라인"></iframe>
    </div>
    <div class="bp-pane" data-bp-pane="gear">
      ${treeHtml}
      <h3>장비 (${gear.length} 슬롯)</h3>
      <ul class="gear-list">
        ${gear.map(g => gearItemHtml(g)).join('')}
      </ul>
      <h3>스탯</h3>
      ${renderStats(statsKr)}
    </div>
  `;
}

// ── 비교 분석 탭 ────────────────────────────────────────────────────────
const compState = {
  left:  { rid: null, meta: null, fid: null, char: null, data: null },
  right: { rid: null, meta: null, fid: null, char: null, data: null },
};

function compSel(side, attr) {
  return document.querySelector(`[data-side-${attr}="${side}"]`);
}

async function compFetch(side) {
  const urlInput = compSel(side, 'url');
  const stat = compSel(side, 'stat');
  const parsed = parseWclUrl(urlInput.value.trim());
  if (!parsed) { stat.textContent = 'URL 파싱 실패'; return; }
  stat.textContent = '리포트 페치 중…';
  try {
    const r = await fetch(`/api/report/${encodeURIComponent(parsed.rid)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const meta = await r.json();
    compState[side].rid = parsed.rid;
    compState[side].meta = meta;
    populateCompFights(side, parsed.fid);
    stat.textContent = `${parsed.rid} · ${(meta.fights||[]).length} fights`;
  } catch (e) {
    stat.textContent = `실패: ${e.message}`;
  }
}

function populateCompFights(side, preferFid) {
  const meta = compState[side].meta || {};
  const DIFF_KR = {1: 'LFR', 2: 'N', 3: 'H', 4: 'M', 5: 'M'};
  const sel = compSel(side, 'fight');
  sel.innerHTML = (meta.fights || []).map(f => {
    const dur = ((f.endTime || 0) - (f.startTime || 0)) / 1000;
    const diff = DIFF_KR[f.difficulty] || `d${f.difficulty}`;
    const kill = f.kill ? '✓' : '✗';
    return `<option value="${f.id}">fight ${f.id} · ${diff} · ${kill} ${esc(f.name || '?')} (${dur.toFixed(0)}s)</option>`;
  }).join('');
  if (preferFid) {
    const opt = sel.querySelector(`option[value="${preferFid}"]`);
    if (opt) sel.value = String(preferFid);
  }
  compFightChange(side);
}

function compFightChange(side) {
  const sel = compSel(side, 'fight');
  if (!sel.value) return;
  compState[side].fid = parseInt(sel.value, 10);
  const meta = compState[side].meta || {};
  const actors = meta.actors || {};
  const names = Object.keys(actors).sort((a, b) => a.localeCompare(b, 'ko'));
  const tbody = compSel(side, 'pbody');
  tbody.innerHTML = names.map(nm => `
    <tr data-name="${esc(nm)}"><td>${esc(nm)}</td><td class="mute">#${actors[nm]}</td></tr>
  `).join('');
  // 빌드 패널 + 하단 iframe 초기화 (선택 캐릭이 바뀌었으니)
  compState[side].char = null;
  compState[side].data = null;
  const build = compSel(side, 'build');
  build.className = 'comp-build empty';
  build.textContent = '캐릭 클릭';
  const tl = document.getElementById(`comp-tl-${side}`);
  tl.removeAttribute('src');
  applyCompDiff();
}

async function compPlayerClick(side, tr) {
  document.querySelectorAll(`[data-side-pbody="${side}"] tr.selected`)
    .forEach(t => t.classList.remove('selected'));
  tr.classList.add('selected');
  const char = tr.dataset.name;
  const rid = compState[side].rid;
  const fid = compState[side].fid;
  if (!rid || !fid || !char) return;
  compState[side].char = char;

  const build = compSel(side, 'build');
  build.className = 'comp-build';
  build.innerHTML = `<p style="color:var(--text-mute)">${esc(char)} 데이터 로드 중…</p>`;

  // 하단 iframe 도 같이 띄움
  const tl = document.getElementById(`comp-tl-${side}`);
  tl.src = `/api/timeline/${encodeURIComponent(rid)}/${fid}/${encodeURIComponent(char)}`;
  // 버프 토글 상태 iframe load 후 적용
  tl.onload = () => applyBuffVisibility();

  try {
    const r = await fetch(`/api/character/${encodeURIComponent(rid)}/${fid}/${encodeURIComponent(char)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    compState[side].data = d;
    renderCompBuild(side, d);
    applyCompDiff();
  } catch (e) {
    build.innerHTML = `<p style="color:#d97757">로드 실패: ${esc(e.message)}</p>`;
  }
}

function renderCompBuild(side, d) {
  const gear = d.gear || [];
  const statsKr = d.stats_kr || [];
  const build = compSel(side, 'build');
  build.innerHTML = `
    <div class="build-section">
      <div class="build-row"><span class="k">캐릭</span><span class="v">${esc(d.char || '?')}</span></div>
      <div class="build-row"><span class="k">보스</span><span class="v">${esc(d.encounter_name || '?')}</span></div>
    </div>
    <h3>장비 (${gear.length})</h3>
    <ul class="gear-list">${gear.map(g => gearItemHtml(g)).join('')}</ul>
    <h3>스탯</h3>${renderStats(statsKr)}
  `;
}

function applyCompDiff() {
  // 양쪽 다 data 있어야 diff 계산. 한쪽만이면 모든 highlight 제거.
  const ld = compState.left.data, rd = compState.right.data;
  // 기존 diff 클래스 다 떼기
  document.querySelectorAll('[data-side-build] .gear-item').forEach(li => li.classList.remove('diff'));
  if (!ld || !rd) return;
  const leftBySlot = {}, rightBySlot = {};
  (ld.gear || []).forEach(g => { leftBySlot[g.slot] = g.id; });
  (rd.gear || []).forEach(g => { rightBySlot[g.slot] = g.id; });
  // 양쪽 gear list 의 li 들을 순서대로 매칭 — gear list 가 슬롯 순으로 정렬돼있음
  const leftLis = document.querySelectorAll('[data-side-build="left"] .gear-item');
  const rightLis = document.querySelectorAll('[data-side-build="right"] .gear-item');
  let diffCount = 0;
  (ld.gear || []).forEach((g, i) => {
    const otherId = rightBySlot[g.slot];
    if (otherId !== g.id) {
      diffCount++;
      if (leftLis[i]) leftLis[i].classList.add('diff');
    }
  });
  (rd.gear || []).forEach((g, i) => {
    const otherId = leftBySlot[g.slot];
    if (otherId !== g.id) {
      if (rightLis[i]) rightLis[i].classList.add('diff');
    }
  });
  // stat 라벨에 diff 카운트 표시
  document.querySelector('[data-side-stat="left"]').textContent =
    `장비 차이 ${diffCount} 슬롯`;
  document.querySelector('[data-side-stat="right"]').textContent =
    `장비 차이 ${diffCount} 슬롯`;
}

function applyBuffVisibility() {
  const show = document.getElementById('comp-buff-chk').checked;
  ['left', 'right'].forEach(side => {
    const tl = document.getElementById(`comp-tl-${side}`);
    try {
      const doc = tl.contentDocument;
      if (doc && doc.body) {
        doc.body.classList.toggle('hide-buffs', !show);
      }
    } catch (_) { /* cross-origin or not loaded */ }
  });
}

// 우클릭 → 비교에 자동 로드. 양쪽 사이드 chained promises.
async function compLoadInto(side, rid, fid, char) {
  switchTab('comparison');
  const urlInput = compSel(side, 'url');
  urlInput.value = `https://www.warcraftlogs.com/reports/${rid}?fight=${fid}`;
  await compFetch(side);  // populateCompFights → compFightChange 자동 호출됨
  // fid 가 preferFid 와 일치하면 그 fight 가 selected. 플레이어 row 찾아 클릭.
  const tbody = compSel(side, 'pbody');
  const tr = tbody.querySelector(`tr[data-name="${CSS.escape(char)}"]`);
  if (tr) {
    await compPlayerClick(side, tr);
    tr.scrollIntoView({ block: 'center' });
  }
}

// 컨텍스트 메뉴 — 단일 floating div, 외부 클릭 시 닫힘
function showContextMenu(x, y, items) {
  closeContextMenu();
  const menu = document.createElement('div');
  menu.id = 'ctx-menu';
  menu.style.left = `${x}px`;
  menu.style.top = `${y}px`;
  menu.innerHTML = items.map((it, i) =>
    `<div class="ctx-item" data-idx="${i}">${esc(it.label)}</div>`
  ).join('');
  menu.addEventListener('click', e => {
    const item = e.target.closest('.ctx-item');
    if (!item) return;
    const idx = parseInt(item.dataset.idx, 10);
    closeContextMenu();
    if (items[idx]) items[idx].onClick();
  });
  document.body.appendChild(menu);
  // 다음 tick 에 외부 클릭 닫기 바인딩 (이번 클릭 이벤트 안 잡히게)
  setTimeout(() => document.addEventListener('click', closeContextMenu, { once: true }), 0);
}

function closeContextMenu() {
  const m = document.getElementById('ctx-menu');
  if (m) m.remove();
}

function bindComparison() {
  // URL 입력 + 분석 버튼
  document.querySelectorAll('[data-side-fetch]').forEach(btn => {
    btn.addEventListener('click', () => compFetch(btn.dataset.sideFetch));
  });
  document.querySelectorAll('[data-side-url]').forEach(inp => {
    inp.addEventListener('keydown', e => {
      if (e.key === 'Enter') compFetch(inp.dataset.sideUrl);
    });
  });
  // fight 변경
  document.querySelectorAll('[data-side-fight]').forEach(sel => {
    sel.addEventListener('change', () => compFightChange(sel.dataset.sideFight));
  });
  // 플레이어 클릭 (이벤트 위임)
  document.querySelectorAll('[data-side-pbody]').forEach(tbody => {
    tbody.addEventListener('click', e => {
      const tr = e.target.closest('tr');
      if (tr) compPlayerClick(tbody.dataset.sidePbody, tr);
    });
  });
  // 버프 토글
  document.getElementById('comp-buff-chk').addEventListener('change', applyBuffVisibility);
}

// ── 부트 ────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  bind();
  bindComparison();
  loadRankings('heroic');
});
