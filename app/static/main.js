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
    state.bossFilter = '';
    state.classFilter = '';
    state.specFilter = '';
    state.selectedRowIdx = -1;
    populateFilters();
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
  // top 200개만 우선 렌더 (전체 24300 은 DOM 무거움 — 가상화는 Week 3)
  const max = 200;
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
    + (rows.length > max ? ` (위 ${max}개 표시)` : '');
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
  const talents = d.talents || [];
  const stats = d.stats;
  const tlUrl = `/api/timeline/${encodeURIComponent(row.report_id)}/${row.fight_id}/${encodeURIComponent(row.character)}`;
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
    <h3>장비 (${gear.length} 슬롯)</h3>
    <ul class="gear-list">
      ${gear.map(g => `
        <li>
          <span class="slot">slot ${g.slot ?? '?'}</span>
          <span class="iid">item ${g.id ?? '?'}</span>
          <span class="ilvl">ilvl ${g.ilvl ?? '?'}</span>
        </li>
      `).join('')}
    </ul>
    <h3>특성 (${talents.length} 노드)</h3>
    <p style="color:var(--text-mute);font-size:11px">트리 시각화는 다음 단계 작업 예정.</p>
    <h3>스탯</h3>
    ${stats ? `<pre style="color:var(--text-mute);font-size:11px">${esc(JSON.stringify(stats, null, 2))}</pre>` : '<p style="color:var(--text-mute)">캐시 없음</p>'}
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
function bind() {
  $('#tabs').addEventListener('click', e => {
    const btn = e.target.closest('.tab');
    if (!btn || btn.classList.contains('disabled')) return;
    $$('#tabs .tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    const tab = btn.dataset.tab;
    if (tab === 'heroic' || tab === 'mythic') {
      loadRankings(tab);
    }
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
}

// ── 부트 ────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  bind();
  loadRankings('heroic');
});
