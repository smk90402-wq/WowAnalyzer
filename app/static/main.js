// WowAnalyzer SPA — Week 2 foundation.
// 상태 관리: 단일 객체 + 명시적 render 함수. 프레임워크 X.

'use strict';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function wowIconUrl(icon, size = 'medium') {
  const raw = String(icon || '').trim().toLowerCase();
  if (!raw) return '';
  const file = /\.(jpg|png|gif)$/i.test(raw) ? raw : `${raw}.jpg`;
  return `https://wow.zamimg.com/images/wow/icons/${size}/${encodeURIComponent(file)}`;
}

// 인증 비활성화 — 401 redirect 핸들러 제거. (사용자 요청: 일단 롤백)

// ── 프론트엔드 로그 → 백엔드 (사용자 디버깅용) ──────────────────────────
function logToBackend(level, msg, src='fe', url=null, line=null) {
  try {
    fetch('/api/log', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({level, msg: String(msg).substring(0, 2000), src, url, line}),
    }).catch(() => {});
  } catch (_) {}
}
window.addEventListener('error', (e) => {
  logToBackend('error',
    `${e.message} (${e.filename || '?'}:${e.lineno || '?'}:${e.colno || '?'})`,
    'window.onerror', e.filename, e.lineno);
});
window.addEventListener('unhandledrejection', (e) => {
  logToBackend('error',
    `unhandledrejection: ${(e.reason && e.reason.message) || e.reason}`,
    'window.onunhandled');
});
// console.error / console.warn 도 백엔드에 mirror
['error', 'warn'].forEach(lvl => {
  const orig = console[lvl].bind(console);
  console[lvl] = function(...args) {
    orig(...args);
    logToBackend(lvl === 'warn' ? 'warning' : 'error',
                 args.map(a => typeof a === 'string' ? a : JSON.stringify(a)).join(' '),
                 `console.${lvl}`);
  };
});

const state = {
  difficulty: 'heroic',
  rows: [],           // 현재 difficulty 의 모든 랭킹 row
  bossFilter: '',     // encounter_id (string)
  classFilter: '',
  specFilter: '',
  selectedRowIdx: -1, // filtered rows 안의 인덱스
};

const replayState = {
  loaded: false,
  rows: [],
  selectedId: null,
  detail: null,
};

// ── 메타 분석 (5차원 종합 표) ────────────────────────────────────────────
let _metaLoaded = false;
let _metaRows = [];   // 팝업용 행 데이터 보관
async function loadSpecMeta(force) {
  if (_metaLoaded && !force) return;
  const body = $('#meta-body');
  body.innerHTML = '<tr><td colspan="21" class="empty">로딩…</td></tr>';
  try {
    const r = await fetch('/api/spec-meta');
    if (!r.ok) throw new Error(`HTTP ${r.status} — run_full_analysis.py 필요할 수 있음`);
    const j = await r.json();
    renderSpecMeta(j.rows || []);
    _metaLoaded = true;
  } catch (e) {
    body.innerHTML = `<tr><td colspan="21" class="empty">로드 실패: ${esc(e.message)}</td></tr>`;
  }
}

function renderSpecMeta(rows) {
  const fmt = (v, d = 2) => (v == null || Number.isNaN(v)) ? '-' : Number(v).toFixed(d);
  const body = $('#meta-body');
  _metaRows = rows;
  body.innerHTML = rows.map((r, i) => {
    const piHi = r.pi_indep != null && r.pi_indep >= 0.9;
    const upVal = r.uplift_top_pct != null ? r.uplift_top_pct : r.uplift_pct;
    const upDep = upVal != null && upVal >= 3;
    // 광딜 프로필 강조: >1.4 다타겟 특화(초록), <1.1 단일형(흐림)
    const aoeHi = r.aoe_ratio != null && r.aoe_ratio >= 1.4;
    // 스킬천장: 1~2 쉬움(초록), 4~5 어려움(빨강), 셀 tooltip=근거
    const sc = r.skill_ceiling || 0;
    const scCls = sc >= 4 ? 'bad' : (sc >= 1 && sc <= 2 ? 'good' : 'mute');
    const scTxt = sc ? `${sc} ${r.skill_label || ''}` : '-';
    // 메타 티어 색: S/A 초록, B 기본, C/D 빨강. note 있으면 ※ 표시 + title
    const tierCls = (t) => t === 'S' || t === 'A' ? 'good' : (t === 'C' || t === 'D' ? 'bad' : 'mute');
    const tuneCls = (t) => (t === '↑↑' || t === '↑') ? 'good' : ((t === '↓↓' || t === '↓') ? 'bad' : 'mute');
    const note = r.meta_note || '';
    const tierCell = (t) => `<td class="right num ${tierCls(t)}" title="${esc(note)}">${t || '-'}${note ? '<span class="note-mark">※</span>' : ''}</td>`;
    return `
    <tr class="meta-row" data-idx="${i}" title="클릭 = 특징 팝업">
      <td class="mute num">${r.rank}</td>
      <td>${esc(r.kr || (r.class_kr + ' ' + r.spec_kr))}</td>
      <td class="right num strong" title="${r.score_parse != null ? `로그점수 잘나옴 ${fmt(r.score_parse,3)} × 0.65 + 막공환영 ${r.pug || '-'}/5 × 0.35` : ''}">${fmt(r.score, 3)}</td>
      <td class="right num">${fmt(r.ease)}</td>
      <td class="right mute num">${r.rot_rank != null ? Math.round(r.rot_rank) : '-'}</td>
      <td class="right num ${r.reactive_stability >= 0.7 ? 'good' : (r.reactive_stability != null && r.reactive_stability < 0.4 ? 'bad' : '')}">${fmt(r.reactive_stability)}</td>
      <td class="right num ${piHi ? 'good' : ''}">${fmt(r.pi_indep)}</td>
      <td class="right num ${upDep ? 'bad' : 'mute'}" title="${r.pi_rate_top10_pct != null ? `최상위(top10) 파스 중 PI 받은 비율 ${Math.round(r.pi_rate_top10_pct)}%` : ''}${r.uplift_pct != null ? ` · 중앙값 기준 ${r.uplift_pct >= 0 ? '+' : ''}${fmt(r.uplift_pct)}%` : ''}">${upVal != null ? (upVal >= 0 ? '+' : '') + fmt(upVal) + '%' : '-'}</td>
      <td class="right num">${fmt(r.consistency)}</td>
      <td class="right num ${r.p99_ease >= 0.75 ? 'good' : (r.p99_ease != null && r.p99_ease < 0.55 ? 'bad' : '')}">${fmt(r.p99_ease)}</td>
      ${tierCell(r.raid_tier)}
      ${tierCell(r.mplus_tier)}
      <td class="right num ${tuneCls(r.tuning)}" title="${esc(r.tuning_note || '')}">${r.tuning || '-'}</td>
      <td class="right num ${r.pop_favor >= 70 ? 'good' : (r.pop_favor != null && r.pop_favor < 35 ? 'bad' : 'mute')}" title="집계된 실제 인원 ~${r.pop_avg != null ? Number(r.pop_avg).toLocaleString() : '?'}명">${r.pop_favor != null ? Math.round(r.pop_favor) : '-'}</td>
      <td class="right num ${r.pug >= 4 ? 'good' : (r.pug && r.pug <= 2 ? 'bad' : 'mute')}" title="${esc(r.pug_note || '')}${r.pug_to != null ? ` (참고·정공로스터: 공대당 ${r.pug_to}자리·채용 ${r.pug_present}%)` : ''}">${r.pug || '-'}</td>
      <td class="right num ${r.burden >= 4 ? 'bad' : (r.burden && r.burden <= 2 ? 'good' : 'mute')}" title="${esc(r.burden_note || '')}">${r.burden || '-'}</td>
      <td class="right num ${aoeHi ? 'good' : 'mute'}">${r.aoe_ratio != null ? fmt(r.aoe_ratio) : '-'}</td>
      <td class="right num ${scCls}" title="${esc(r.skill_reason || '')}">${scTxt}</td>
      <td class="right mute num">${r.unique_spells != null ? Math.round(r.unique_spells) : '-'}</td>
      <td class="right mute num">${r.apm != null ? Math.round(r.apm) : '-'}</td>
      <td class="right mute num">${r.cleave_med != null ? Math.round(r.cleave_med).toLocaleString() : '-'}</td>
    </tr>`;
  }).join('');
  updateSortIndicators();
}

// ── 메타 표 정렬 (헤더 클릭) ───────────────────────────────────────────
const _TIER_ORD = { S: 5, A: 4, B: 3, C: 2, D: 1 };
const _TUNE_ORD = { '↑↑': 2, '↑': 1, '→': 0, '↓': -1, '↓↓': -2 };
let _metaSort = { field: 'score', dir: -1 };
function _metaSortVal(r, field) {
  if (field === 'kr') return r.kr || ((r.class_kr || '') + ' ' + (r.spec_kr || ''));
  if (field === 'raid_tier' || field === 'mplus_tier') return _TIER_ORD[r[field]] || 0;
  if (field === 'tuning') return (r.tuning in _TUNE_ORD) ? _TUNE_ORD[r.tuning] : -99;
  const v = r[field];
  return (v == null || Number.isNaN(Number(v))) ? -Infinity : Number(v);
}
function sortMetaRows(field) {
  if (_metaSort.field === field) _metaSort.dir *= -1;       // 같은 컬럼=방향 토글
  else _metaSort = { field, dir: field === 'kr' ? 1 : -1 }; // 새 컬럼=숫자 내림/문자 오름
  const dir = _metaSort.dir;
  const sorted = _metaRows.slice().sort((a, b) => {
    const va = _metaSortVal(a, field), vb = _metaSortVal(b, field);
    if (typeof va === 'string') return dir * va.localeCompare(vb, 'ko');
    if (va === vb) return a.rank - b.rank;  // 동점은 종합순위로 안정 정렬
    return dir * (va - vb);
  });
  renderSpecMeta(sorted);
}
function updateSortIndicators() {
  $$('#meta-table thead th[data-sort]').forEach(th => {
    const active = th.dataset.sort === _metaSort.field;
    th.classList.toggle('sorted', active);
    let arrow = th.querySelector('.sort-arrow');
    if (active) {
      if (!arrow) { arrow = document.createElement('span'); arrow.className = 'sort-arrow'; th.appendChild(arrow); }
      arrow.textContent = _metaSort.dir < 0 ? ' ▼' : ' ▲';
    } else if (arrow) { arrow.remove(); }
  });
}

// ── 스펙 특징 팝업 ─────────────────────────────────────────────────────
const _fmtN = (v, d = 2) => (v == null || Number.isNaN(Number(v))) ? '-' : Number(v).toFixed(d);
const _diffLabel = (rank) => {
  if (rank == null) return '?';
  if (rank <= 5) return '매우 쉬움'; if (rank <= 11) return '쉬움';
  if (rank <= 17) return '중간'; if (rank <= 22) return '어려움';
  return '매우 어려움';
};

function specTraits(r) {
  const out = [];
  const rank = r.rot_rank;
  out.push({ tone: rank <= 11 ? 'good' : (rank >= 18 ? 'bad' : ''),
    text: `딜사이클 <b>${_diffLabel(rank)}</b> (난이도 #${rank != null ? Math.round(rank) : '?'}/27)` });
  if (r.reactive_stability != null) {
    const stable = r.reactive_stability >= 0.7;
    const swingy = r.reactive_stability < 0.4;
    const note = r.reactive_note ? ` <span class="sm-muted">- ${esc(r.reactive_note)}</span>` : '';
    out.push({ tone: stable ? 'good' : (swingy ? 'bad' : ''),
      text: stable ? `우선순위/프록 분기에 <b>덜 흔들림</b> (반응 안정 ${_fmtN(r.reactive_stability)})${note}`
        : (swingy ? `상황/프록 반응형에 <b>많이 흔들림</b> (반응 안정 ${_fmtN(r.reactive_stability)})${note}`
          : `반응 안정성 보통 (${_fmtN(r.reactive_stability)})${note}`) });
  }
  const sc = r.score;
  const pt = sc >= 0.85 ? '막공 종합 최상' : (sc >= 0.70 ? '막공 종합 우수'
    : (sc >= 0.50 ? '막공 종합 보통' : '막공 종합 낮음'));
  const sp = r.score_parse;
  const brk = sp != null
    ? ` <span class="sm-muted">= 로그점수 잘나옴 ${_fmtN(sp, 3)}×0.65 + 막공환영 ${r.pug || '-'}/5×0.35 (구인난 가중, 로그점수 잘나옴 안에 반응 안정 15%)</span>`
    : '';
  out.push({ tone: sc >= 0.70 ? 'good' : (sc < 0.50 ? 'bad' : ''),
    text: `<b>${pt}</b> (종합 ${_fmtN(sc, 3)} · ${r.rank}위)${brk}` });
  if (r.pi_indep != null) {
    const upv = r.uplift_top_pct != null ? r.uplift_top_pct : r.uplift_pct;
    const t10 = r.pi_rate_top10_pct != null ? ` · 최상위 파스 중 PI ${Math.round(r.pi_rate_top10_pct)}%` : '';
    const dep = upv != null && upv >= 3;
    out.push({ tone: dep ? 'bad' : 'good', text: dep
      ? `마력주입(PI) <b>의존</b> — 상위권 기준 받으면 딜 +${_fmtN(upv, 1)}%${t10} (사제 버프 있어야 최고점)`
      : `마력주입(PI) <b>독립</b> — 버프 없이도 최고점 경쟁 가능 (상위권 기준 받아도 ${upv >= 0 ? '+' : ''}${_fmtN(upv, 1)}%${t10})` });
  }
  if (r.consistency != null)
    out.push({ tone: r.consistency >= 0.85 ? 'good' : (r.consistency < 0.60 ? 'bad' : ''),
      text: r.consistency >= 0.85 ? '기믹·운에 <b>안정적</b> — 매번 딜이 비슷하게 나옴 (일관성↑)'
        : (r.consistency < 0.60 ? '기믹·운에 <b>흔들림</b> — 킬마다 딜 편차 큼 (일관성↓)' : '일관성 보통') });
  out.push({ tone: 'info',
    text: `실전 성능 — 레이드 <b>${r.raid_tier || '?'}</b> · 쐐기 <b>${r.mplus_tier || '?'}</b> <span class="sm-muted">(순수 성능, 파스 무관)</span>` });
  if (r.meta_note) out.push({ tone: 'warn', text: `⚠ ${esc(r.meta_note)}` });
  if (r.tuning) {
    const up = r.tuning.includes('↑'), down = r.tuning.includes('↓');
    out.push({ tone: up ? 'good' : (down ? 'bad' : ''),
      text: `최근 튜닝 <b>${r.tuning}</b> ${up ? '(버프받는 중·상승세)' : (down ? '(너프 중·하락세)' : '(유지)')} — ${esc(r.tuning_note || '')}` });
  }
  if (r.pop_favor != null) {
    const many = r.pop_favor >= 70, few = r.pop_favor < 35;
    out.push({ tone: '',
      text: `인구 <b>~${r.pop_avg != null ? Number(r.pop_avg).toLocaleString() : '?'}명</b> ${many ? '(많음 — 50~80점대 파스 따긴 유리)' : (few ? '(적음 — 잘하는 사람만 남아 경쟁 빡셈)' : '(중간)')} <span class="sm-muted">점수 미반영·99파스 노리면 무의미</span>` });
  }
  if (r.pug) {
    const PUG_LBL = { 5: '최우선 모심', 4: '환영', 3: '무난', 2: '찬밥', 1: '기피' };
    const ref = r.pug_to != null
      ? ` <span class="sm-muted">(참고·정공로스터: 공대당 ${r.pug_to}자리·채용 ${r.pug_present}% — 정공 누적이라 신규진입과 다를 수 있음)</span>`
      : '';
    out.push({ tone: r.pug >= 4 ? 'good' : (r.pug <= 2 ? 'bad' : ''),
      text: `막공 환영도 <b>${r.pug}/5 ${PUG_LBL[r.pug] || ''}</b> <span class="sm-muted">(구인 시장 기반: 인벤 공격대_구인 본문 138개 정독)</span> — ${esc(r.pug_note || '')}${ref}` });
  }
  if (r.burden) {
    const hi = r.burden >= 4, lo = r.burden <= 2;
    out.push({ tone: lo ? 'good' : (hi ? 'bad' : ''),
      text: `특임/유틸 부담 <b>${r.burden}/5</b> ${hi ? '(높음 — 딜 말고 시켜지는 일이 많아 신경 분산)' : (lo ? '(낮음 — 내 딜에만 집중하기 쉬움)' : '(중간)')} <span class="sm-muted">점수 미반영</span> — ${esc(r.burden_note || '')}` });
  }
  if (r.aoe_ratio != null)
    out.push({ tone: '', text: r.aoe_ratio >= 1.4 ? `<b>다타겟·쫄파이 특화</b> (광딜비 ${_fmtN(r.aoe_ratio)})`
      : (r.aoe_ratio < 1.1 ? `<b>단일 위주</b> (광딜비 ${_fmtN(r.aoe_ratio)})` : `광/단일 균형 (${_fmtN(r.aoe_ratio)})`) });
  if (r.skill_ceiling >= 4)
    out.push({ tone: 'bad', text: `딜 최적화 <b>스킬천장 높음</b> (${r.skill_label}) — ${esc(r.skill_reason || '')}` });
  return out;
}

function openSpecModal(idx) {
  const r = _metaRows[idx];
  if (!r) return;
  const traits = specTraits(r).map(t =>
    `<div class="sm-trait ${t.tone}">${t.text}</div>`).join('');
  const cell = (label, val) => `<div class="sm-cell"><span>${label}</span><b>${val}</b></div>`;
  const grid = [
    cell('로테 쉬움', _fmtN(r.ease)),
    cell('난이도 순위', r.rot_rank != null ? '#' + Math.round(r.rot_rank) : '-'),
    cell('반응 안정', _fmtN(r.reactive_stability)),
    cell('PI 독립', _fmtN(r.pi_indep)),
    cell('PI 딜상승(상위)', r.uplift_top_pct != null ? (r.uplift_top_pct >= 0 ? '+' : '') + _fmtN(r.uplift_top_pct, 1) + '%'
      : (r.uplift_pct != null ? (r.uplift_pct >= 0 ? '+' : '') + _fmtN(r.uplift_pct, 1) + '%' : '-')),
    cell('top10 PI율', r.pi_rate_top10_pct != null ? Math.round(r.pi_rate_top10_pct) + '%' : '-'),
    cell('일관성', _fmtN(r.consistency)),
    cell('99파스 쉬움', _fmtN(r.p99_ease)),
    cell('레이드 티어', r.raid_tier || '-'),
    cell('쐐기 티어', r.mplus_tier || '-'),
    cell('최근 튜닝', r.tuning || '-'),
    cell('인구', r.pop_avg != null ? '~' + Number(r.pop_avg).toLocaleString() : '-'),
    cell('막공 환영', r.pug ? r.pug + '/5' : '-'),
    cell('특임 부담', r.burden ? r.burden + '/5' : '-'),
    cell('광딜 프로필', _fmtN(r.aoe_ratio)),
    cell('스킬천장', r.skill_ceiling ? r.skill_ceiling + ' ' + (r.skill_label || '') : '-'),
    cell('APM', r.apm != null ? Math.round(r.apm) : '-'),
    cell('스킬 수', r.unique_spells != null ? Math.round(r.unique_spells) : '-'),
    cell('쫄파이 DPS', r.cleave_med != null ? Math.round(r.cleave_med).toLocaleString() : '-'),
  ].join('');
  // ── 우측 패널: 스펙 설명 / 로테이션 / 꿀팁 ──
  const tips = Array.isArray(r.guide_tips) ? r.guide_tips : [];
  const tipsHtml = tips.length ? tips.map(tp => {
    const body = wsify(esc(tp.d || '')).replace(/\n/g, '<br>');
    const src = tp.src ? `<div class="sm-tip-src">— ${esc(tp.src)}</div>` : '';
    const sc = tp.scope || '공용';
    const scCls = sc === '쐐기' ? 'mplus' : (sc === '레이드' ? 'raid' : 'both');
    const badge = `<span class="sm-tip-scope ${scCls}">${esc(sc)}</span>`;
    return `<div class="sm-tip"><div class="sm-tip-t">💡 ${esc(tp.t || '')} ${badge}</div><div class="sm-tip-d">${body}</div>${src}</div>`;
  }).join('') : `<div class="sm-empty">아직 꿀팁 없음 — 영상/가이드 찾으면 추가됨</div>`;
  const rightHtml = `
    <div class="sm-sec-label">스펙 설명</div>
    <div class="sm-guide-desc">${r.guide_desc ? wsify(esc(r.guide_desc)) : '<span class="sm-empty">설명 미작성</span>'}</div>
    <div class="sm-sec-label">로테이션</div>
    <div class="sm-guide-rot">${r.guide_rotation ? wsify(esc(r.guide_rotation)) : '<span class="sm-empty">로테 미작성</span>'}</div>
    <div class="sm-sec-label">꿀팁 ${tips.length ? '(' + tips.length + ')' : ''}</div>
    <div class="sm-tips">${tipsHtml}</div>`;

  $('#spec-modal-body').innerHTML = `
    <div class="sm-head">
      <span class="sm-rank">#${r.rank}</span>
      <span class="sm-title">${esc(r.kr || (r.class_kr + ' ' + r.spec_kr))}</span>
      <span class="sm-score">종합 ${_fmtN(r.score, 3)}</span>
    </div>
    <div class="sm-cols">
      <div class="sm-col-left">
        <div class="sm-sec-label">특징 요약</div>
        <div class="sm-traits">${traits}</div>
        <div class="sm-sec-label">지표 상세</div>
        <div class="sm-grid">${grid}</div>
      </div>
      <div class="sm-col-right">${rightHtml}</div>
    </div>
    <div class="sm-foot">난이도·딜 스킬천장·꿀팁 = 유튜브(12.0.5)/가이드를 보고 직접 정리 · 특임/유틸 부담 = 점수 미반영 참고 · 레이드/쐐기 티어 = 순수 성능(파스 무관) · PI독립·일관성·광딜·인구 = 로그 데이터</div>`;
  $('#spec-modal').classList.add('show');
  whEnsure();  // 스킬명 마우스오버 툴팁
}
function closeSpecModal() { $('#spec-modal').classList.remove('show'); }

// ── 재미 분석 탭 ──────────────────────────────────────────────────────
let _funRows = [];
let _funLoaded = false;
let _funSort = { field: 'yt_score', dir: -1 };

async function loadSpecFun() {
  if (_funLoaded) return;
  const body = $('#fun-body');
  body.innerHTML = '<tr><td colspan="11" class="empty">로딩…</td></tr>';
  try {
    const r = await fetch('/api/spec-fun');
    if (!r.ok) throw new Error(`HTTP ${r.status} — analyze_spec_fun.py 필요할 수 있음`);
    const j = await r.json();
    _funRows = j.rows || [];
    _funMeta = j._meta || {};
    renderSpecFun();
    _funLoaded = true;
  } catch (e) {
    body.innerHTML = `<tr><td colspan="11" class="empty">로드 실패: ${esc(e.message)}</td></tr>`;
  }
}
let _funMeta = {};

function _verifyMark(v) {
  if (!v) return '-';
  if (v.startsWith('✓')) return '<span class="good">✓ 일치</span>';
  if (v.startsWith('✗')) return '<span class="bad">✗ 불일치</span>';
  return '<span style="color:#ffd166">△ 갈림/부분</span>';
}

function renderSpecFun() {
  const fmt1 = v => (v == null ? '-' : Number(v).toFixed(1));
  const dir = _funSort.dir, f = _funSort.field;
  const rows = _funRows.slice().sort((a, b) => {
    const va = a[f], vb = b[f];
    if (typeof va === 'string' || typeof vb === 'string')
      return String(va).localeCompare(String(vb), 'ko') * dir;
    return (((va == null) ? -Infinity : va) - ((vb == null) ? -Infinity : vb)) * dir;
  });
  $('#fun-body').innerHTML = rows.map(r => {
    const i = _funRows.indexOf(r);
    const scoreCls = r.yt_score >= 4 ? 'good' : (r.yt_score < 2.5 ? 'bad' : '');
    const split = r.split_note ? '<span class="note-mark" style="color:#ffd166">※</span>' : '';
    const axis = v => `<td class="right num ${v >= 4.5 ? 'good' : (v <= 2 ? 'bad' : '')}">${fmt1(v)}</td>`;
    return `
    <tr class="fun-row" data-idx="${i}" title="클릭 = 영상별 평가와 데이터 확인">
      <td class="mute num">${r.rank}</td>
      <td>${esc(r.kr)}</td>
      <td class="right num strong ${scoreCls}" title="${esc(r.split_note || '')}">${fmt1(r.yt_score)}${split}</td>
      <td class="right mute num">${r.yt_n}</td>
      ${axis(r.impact)}${axis(r.proc)}${axis(r.burst)}${axis(r.flow)}${axis(r.fantasy)}
      <td class="right num ${r.mobility >= 4 ? 'good' : (r.mobility != null && r.mobility < 1.5 ? 'bad' : 'mute')}">${fmt1(r.mobility)}</td>
      <td>${_verifyMark(r.verify)}</td>
    </tr>`;
  }).join('');
  // 헤더 정렬 표시
  $$('#fun-table th').forEach(th => {
    th.classList.toggle('sorted', th.dataset.fsort === f);
  });
}

function showFunDetail(idx) {
  const r = _funRows[idx];
  if (!r) return;
  const box = $('#fun-detail');
  const srcMap = {};
  (_funMeta.sources || []).forEach(s => { srcMap[s.id] = s; });
  const notes = (r.yt_notes || []).map(n => {
    const s = srcMap[n.src] || {};
    const link = s.url ? `<a href="${s.url}" target="_blank" rel="noopener">${esc(s.channel || n.src)}</a>` : esc(n.src);
    return `<div class="fd-note"><b>[${esc(n.tier)}]</b> ${esc(n.text)}<span class="fd-src">— ${link}</span></div>`;
  }).join('');
  const log = r.log || {};
  box.innerHTML = `
    <div class="fd-title">${esc(r.kr)} — 재미 ${Number(r.yt_score).toFixed(1)}/5 (${r.yt_n}개 영상) · ${esc(r.note)}</div>
    ${r.split_note ? `<div class="fd-split">※ 평가 갈림: ${esc(r.split_note)}</div>` : ''}
    <div class="fd-verify">데이터로 확인: ${esc(r.verify)}</div>
    ${notes}
    <div class="fd-log">실제 로그에서 잰 값 — 1분에 스킬 ${log.apm ?? '-'}번 · 쓰는 버튼 ${log.unique_spells ?? '-'}개 · 누르는 순서 다양함 ${log.bigram_entropy ?? '-'} (높을수록 다채로움) · 킬마다 딜 출렁임 ${log.avg_cv ?? '-'} (높을수록 운빨) · 움직일 때 딜 손해 ${log.move_pen != null ? Number(log.move_pen).toFixed(2) : '-'} (높을수록 무빙에 약함)</div>`;
  $('#fun-modal').classList.add('show');
}
function closeFunModal() { $('#fun-modal')?.classList.remove('show'); }

// ── 시즌2 전망 탭 (예측·추측 자료집 — 수시 갱신) ─────────────────────────
let _s2Data = null;
const _S2_TIER_ORD = { S: 8, '상': 7, A: 6, B: 5, '중': 4, C: 3, '하': 2, D: 1, '?': 0 };

let _s2Mode = 'raid';   // raid | mplus

async function loadS2Meta() {
  // 수시 갱신 자료라 캐시 안 함 — 탭 열 때마다 재요청
  const board = $('#s2-board');
  board.innerHTML = '<div class="empty">로딩…</div>';
  try {
    const r = await fetch('/api/s2-meta');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    _s2Data = await r.json();
    renderS2();
  } catch (e) {
    board.innerHTML = `<div class="empty">로드 실패: ${esc(e.message)}</div>`;
  }
}

// 티어표 행 정의 — outlook 값을 행으로 묶음 (S~D 자료가 들어와도 수용)
const _S2_ROWS = [
  { label: '상', match: ['S', '상', 'A'], cls: 'top', desc: '강할 거라는 예측' },
  { label: '중', match: ['B', '중'], cls: 'mid', desc: '무난 예측' },
  { label: '하', match: ['C', '하', 'D'], cls: 'low', desc: '약할 거라는 예측' },
  { label: '?', match: ['?'], cls: 'unk', desc: '자료 부족' },
];
const _S2_ROLE = { '혈기': '탱', '보호': '탱', '수호': '탱', '양조': '탱', '복수': '탱',
  '신성': '힐', '수양': '힐', '회복': '힐', '운무': '힐', '보존': '힐', '복원': '힐' };
// 전문화 아이콘 (wowhead 표준 아이콘명 — 스킬 아이콘과 같은 CDN 사용)
const _S2_SPEC_ICON = {
  'Warrior|Arms': 'ability_warrior_savageblow', 'Warrior|Fury': 'ability_warrior_innerrage', 'Warrior|Protection': 'ability_warrior_defensivestance',
  'Paladin|Holy': 'spell_holy_holybolt', 'Paladin|Protection': 'ability_paladin_shieldofthetemplar', 'Paladin|Retribution': 'spell_holy_auraoflight',
  'Hunter|Beast Mastery': 'ability_hunter_bestialdiscipline', 'Hunter|Marksmanship': 'ability_hunter_focusedaim', 'Hunter|Survival': 'ability_hunter_camouflage',
  'Rogue|Assassination': 'ability_rogue_deadlybrew', 'Rogue|Outlaw': 'ability_rogue_waylay', 'Rogue|Subtlety': 'ability_stealth',
  'Priest|Discipline': 'spell_holy_powerwordshield', 'Priest|Holy': 'spell_holy_guardianspirit', 'Priest|Shadow': 'spell_shadow_shadowwordpain',
  'Death Knight|Blood': 'spell_deathknight_bloodpresence', 'Death Knight|Frost': 'spell_deathknight_frostpresence', 'Death Knight|Unholy': 'spell_deathknight_unholypresence',
  'Shaman|Elemental': 'spell_nature_lightning', 'Shaman|Enhancement': 'spell_shaman_improvedstormstrike', 'Shaman|Restoration': 'spell_nature_magicimmunity',
  'Mage|Arcane': 'spell_holy_magicalsentry', 'Mage|Fire': 'spell_fire_firebolt02', 'Mage|Frost': 'spell_frost_frostbolt02',
  'Warlock|Affliction': 'spell_shadow_deathcoil', 'Warlock|Demonology': 'spell_shadow_metamorphosis', 'Warlock|Destruction': 'spell_shadow_rainoffire',
  'Monk|Brewmaster': 'monk_stance_drunkenox', 'Monk|Mistweaver': 'monk_stance_wiseserpent', 'Monk|Windwalker': 'monk_stance_whitetiger',
  'Druid|Balance': 'spell_nature_starfall', 'Druid|Feral': 'ability_druid_catform', 'Druid|Guardian': 'ability_racial_bearform', 'Druid|Restoration': 'spell_nature_healingtouch',
  'Demon Hunter|Havoc': 'ability_demonhunter_specdps', 'Demon Hunter|Vengeance': 'ability_demonhunter_spectank', 'Demon Hunter|Devourer': 'classicon_demonhunter',
  'Evoker|Devastation': 'classicon_evoker_devastation', 'Evoker|Preservation': 'classicon_evoker_preservation', 'Evoker|Augmentation': 'classicon_evoker_augmentation',
};

function renderS2() {
  const specs = Object.entries(_s2Data.specs || {});
  const meta = _s2Data._meta || {};
  $('#meta').textContent = `시즌2(${meta.patch || '12.1'}) 예측 — 자료 ${(meta.sources || []).length}건 · ${meta.updated || ''} 갱신 · 전부 추측입니다`;
  if (!specs.length) {
    $('#s2-board').innerHTML = '<div class="empty">아직 자료 없음 — 영상/PTR 자료를 주시면 정리해서 채웁니다</div>';
    return;
  }
  $$('.s2-mode-btn').forEach(b => b.classList.toggle('active', b.dataset.s2mode === _s2Mode));
  const boardRows = _S2_ROWS.map(row => {
    const chips = specs
      .filter(([, v]) => row.match.includes(((v[_s2Mode] || {}).outlook) || '?'))
      .sort((a, b) => (a[1].kr || a[0]).localeCompare(b[1].kr || b[0], 'ko'))
      .map(([key, v]) => {
        const spec = (v.kr || key).split(' ').pop();
        const role = _S2_ROLE[spec] || '';
        const nRefs = ((v.raid || {}).notes || []).length + ((v.mplus || {}).notes || []).length + (v.changes || []).length;
        const ico = _S2_SPEC_ICON[key]
          ? `<img class="s2-ico" src="https://wow.zamimg.com/images/wow/icons/medium/${_S2_SPEC_ICON[key]}.jpg" onerror="this.remove()">`
          : '';
        return `<div class="s2-chip ${role ? 'role-' + (role === '탱' ? 'tank' : 'heal') : ''}" data-key="${esc(key)}"
          title="${esc(v.summary || '')}">
          ${ico}${esc(v.kr || key)}${role ? `<span class="s2-role">${role}</span>` : ''}<span class="s2-nrefs">${nRefs}</span>
        </div>`;
      }).join('');
    if (!chips) return '';
    return `
    <div class="s2-tier-row ${row.cls}">
      <div class="s2-tier-label" title="${esc(row.desc)}">${row.label}</div>
      <div class="s2-tier-cell">${chips}</div>
    </div>`;
  }).join('');
  $('#s2-board').innerHTML = boardRows || '<div class="empty">표시할 스펙 없음</div>';
}

function showS2Detail(key) {
  const v = (_s2Data.specs || {})[key];
  if (!v) return;
  const srcMap = {};
  ((_s2Data._meta || {}).sources || []).forEach(s => { srcMap[s.id] = s; });
  const noteList = (arr) => (arr || []).map(n => {
    const s = srcMap[n.src] || {};
    return `<div class="fd-note">${esc(n.note)}<span class="fd-src">— ${esc(s.channel || n.src)}${n.date ? ' · ' + esc(n.date) : ''}</span></div>`;
  }).join('') || '<div class="sm-empty">자료 없음</div>';
  $('#s2-detail').innerHTML = `
    <div class="fd-title">${esc(v.kr || key)} — 시즌2 전망 <span class="sm-muted">(예측 — 자료 들어오면 갱신)</span></div>
    ${v.summary ? `<div class="fd-verify">${esc(v.summary)}</div>` : ''}
    <div class="fl-track-h">레이드 (전망 ${esc((v.raid || {}).outlook || '?')})</div>
    ${noteList((v.raid || {}).notes)}
    <div class="fl-track-h" style="margin-top:10px">쐐기 (전망 ${esc((v.mplus || {}).outlook || '?')})</div>
    ${noteList((v.mplus || {}).notes)}
    ${(v.changes || []).length ? `<div class="fl-track-h" style="margin-top:10px">변경 사항</div>${noteList(v.changes)}` : ''}`;
  $('#s2-modal').classList.add('show');
}
function closeS2Modal() { $('#s2-modal')?.classList.remove('show'); }

// ── 스킬명 → 아이콘 + wowhead 마우스오버 툴팁 ──────────────────────────
let _spellMap = null, _spellNames = null;
async function ensureSpellMap() {
  if (_spellMap) return;
  try {
    const r = await fetch('/api/spell-map');
    _spellMap = (await r.json()).map || {};
    _spellNames = Object.keys(_spellMap).sort((a, b) => b.length - a.length); // 긴 이름 우선
  } catch (e) { _spellMap = {}; _spellNames = []; }
}
function whEnsure() {
  // wowhead 파워 툴팁 스크립트 1회 로드 / 동적 추가 링크 재스캔
  if (!window.$WowheadPower) {
    if (document.getElementById('wh-power-js')) return;
    const s = document.createElement('script');
    s.id = 'wh-power-js';
    s.src = 'https://wow.zamimg.com/widgets/power.js';
    document.head.appendChild(s);
  } else if (window.$WowheadPower.refreshLinks) window.$WowheadPower.refreshLinks();
}
// 산문과 충돌하는 일반 단어 — 스펠DB에 단독 이름으로 존재해도 링크 금지
// (전체 스킬명은 긴 이름 우선 매칭이라 영향 없음. '속사포' 같은 합성어는 한글 경계 규칙이 막음)
const WS_BLOCK = new Set(['사격', '강화', '폭발', '질주', '회복', '재생', '어둠', '격노', '집중', '표식']);
const _wsHangul = (c) => c >= '가' && c <= '힣';
const WS_PARTICLES = [
  '으로부터', '이라면', '에서는', '에서', '으로', '부터', '까지', '처럼',
  '마다', '보다', '조차', '라도', '이면', '이고', '은', '는', '이', '가',
  '을', '를', '에', '와', '과', '도', '만', '로',
];
function _wsParticleLen(text, idx) {
  for (const p of WS_PARTICLES) {
    if (text.startsWith(p, idx)) {
      const next = text[idx + p.length] || '';
      if (!_wsHangul(next)) return p.length;
    }
  }
  return 0;
}
function wsify(escText) {
  // esc() 처리된 평문에서 스킬명을 아이콘+툴팁 링크로 치환.
  // 토큰 치환(긴 이름 우선) 후 일괄 전개 — 짧은 이름이 긴 이름 내부를 재치환하는 것 방지.
  // 한글 경계: 매칭 앞뒤가 한글 음절이면 단어 일부라 치환 안 함 (정규식 대신 수동 스캔 — 이스케이프 불필요).
  if (!_spellNames || !_spellNames.length || !escText) return escText;
  const toks = [];
  let out = escText;
  for (const n of _spellNames) {
    if (WS_BLOCK.has(n) || out.indexOf(n) === -1) continue;
    let res = '', pos = 0, hit = false;
    for (let k = out.indexOf(n, pos); k !== -1; k = out.indexOf(n, pos)) {
      const pre = k > 0 ? out[k - 1] : '';
      const post = k + n.length < out.length ? out[k + n.length] : '';
      const postOk = !_wsHangul(post) || _wsParticleLen(out, k + n.length);
      if (!_wsHangul(pre) && postOk) {
        res += out.slice(pos, k) + '' + toks.length + '';
        hit = true;
      } else {
        res += out.slice(pos, k + n.length);
      }
      pos = k + n.length;
    }
    res += out.slice(pos);
    if (hit) { toks.push(n); out = res; }
  }
  return out.replace(/(\d+)/g, (_, i) => {
    const n = toks[+i], s = _spellMap[n];
    const ic = s.icon ? `<img class="ws-ic" src="https://wow.zamimg.com/images/wow/icons/small/${s.icon}.jpg" onerror="this.remove()">` : '';
    return `<a class="ws" href="https://www.wowhead.com/ko/spell=${s.id}" target="_blank" rel="noopener" data-wowhead="spell=${s.id}&domain=ko">${ic}${n}</a>`;
  });
}

// ── 딜사이클 (로테이션 베이스) ─────────────────────────────────────────
let _rotData = null, _bossCycle = null;
const _rotSel = { cls: null, spec: null, build: null, mode: 'general' };
async function loadRotation() {
  if (_rotData) { renderRotControls(); return; }
  $('#rot-body').innerHTML = '<div class="empty">로딩…</div>';
  try {
    const [r, b] = await Promise.all([fetch('/api/rotation'), fetch('/api/boss-dealcycle')]);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    _rotData = await r.json();
    _bossCycle = b.ok ? (await b.json()).data : {};
    renderRotControls();
  } catch (e) {
    $('#rot-body').innerHTML = `<div class="empty">로드 실패: ${esc(e.message)}</div>`;
  }
}
function _rotClasses() { return Object.keys(_rotData).filter(k => !k.startsWith('_')); }
function rotGameSupported() {
  return typeof window.openRotGame === 'function'
    && typeof window.rotGameSupports === 'function'
    && window.rotGameSupports(_rotSel.cls, _rotSel.spec, _rotSel.build);
}
function updateRotGameButton() {
  const btn = $('#rot-game-control-btn');
  if (!btn) return;
  const supported = rotGameSupported();
  btn.style.display = supported ? '' : 'none';
  btn.textContent = supported
    ? `딜사이클 문제풀이 — ${_rotSel.build}`
    : '딜사이클 문제풀이';
  btn.onclick = supported
    ? () => openRotGame(_rotSel.cls, _rotSel.spec, _rotSel.build)
    : null;
}
function renderRotControls() {
  const classes = _rotClasses();
  if (!_rotSel.cls || !classes.includes(_rotSel.cls)) _rotSel.cls = classes[0];
  const clsObj = _rotData[_rotSel.cls];
  const specs = Object.keys(clsObj.specs || {});
  if (!_rotSel.spec || !specs.includes(_rotSel.spec)) _rotSel.spec = specs[0];
  const builds = Object.keys(clsObj.specs[_rotSel.spec].builds || {});
  if (!_rotSel.build || !builds.includes(_rotSel.build)) _rotSel.build = builds[0];
  // 콤보박스 채우기
  const opt = (v, label, sel) => `<option value="${esc(v)}" ${v === sel ? 'selected' : ''}>${esc(label)}</option>`;
  $('#rot-class').innerHTML = classes.map(c => opt(c, _rotData[c].kr || c, _rotSel.cls)).join('');
  $('#rot-spec').innerHTML = specs.map(s => opt(s, clsObj.specs[s].kr || s, _rotSel.spec)).join('');
  $('#rot-build').innerHTML = builds.map(b => opt(b, b, _rotSel.build)).join('');
  updateRotGameButton();
  if (_rotSel.mode === 'boss') renderRotBoss(); else renderRotBody();
}

function renderRotBoss() {
  const key = `${_rotSel.cls}|${_rotSel.spec}`;
  const bosses = _bossCycle && _bossCycle[key];
  if (!bosses || !Object.keys(bosses).length) {
    $('#rot-body').innerHTML = '<div class="empty">이 전문화는 보스별 기록 없음 (상위 100명 데이터 부족)</div>';
    return;
  }
  // 킬타임 순 정렬
  const cards = Object.entries(bosses).sort((a, b) => a[1].kill_s - b[1].kill_s).map(([eid, d]) => {
    const opener = (d.opener || []).map(o => `<span class="bc-skill">${wsify(esc(o.skill))}</span>`).join('<span class="bc-arrow">→</span>');
    const cds = (d.cooldowns || []).map(c => `${wsify(esc(c.skill))} <b>${c.first_s}s</b>·${c.count}회`).join(' / ');
    let boxHtml = '';
    if (d.box) {
      const b = d.box;
      if (b.opener_pct >= 70) boxHtml = `오프닝 사용 (${b.opener_pct}%)`;
      else if (b.delayed_first_s != null) boxHtml = `<b>오프닝 X → 첫 사용 ~${b.delayed_first_s}s</b> <span class="bc-mute">(오프닝 ${b.opener_pct}%, 지연 ${b.delayed_n}판)</span>`;
      else boxHtml = `혼재 (오프닝 ${b.opener_pct}%)`;
    }
    const lust = d.lust ? `블러드 ${d.lust.cover} @${d.lust.first_s}s` : '블러드 데이터없음';
    const pot = d.potion ? `물약 ${d.potion.cover}` : '';
    const ups = (d.buff_uptime || []).map(u => `${esc(u.buff)} ${u.pct}%`).join(' · ');
    const build = d.build ? `<span class="bc-build ${d.build.pick.includes('광') || d.build.pick.includes('난타') ? 'aoe' : 'st'}">${esc(d.build.pick)} (광 ${d.build.aoe_pct}%)</span>` : '';
    return `<div class="bc-card">
      <div class="bc-head"><span class="bc-boss">${esc(d.boss_kr)}</span>
        <span class="bc-kill">킬 ${d.kill_s}s · n=${d.n}</span>${build}</div>
      <div class="bc-row"><span class="bc-label">오프너${d.opener_match != null ? ` <span class="bc-match">대표 ${d.opener_match}%</span>` : ''}</span><div class="bc-opener">${opener}</div></div>
      ${cds ? `<div class="bc-row"><span class="bc-label">쿨기</span><div>${cds}</div></div>` : ''}
      ${boxHtml ? `<div class="bc-row"><span class="bc-label">상자</span><div>${boxHtml}</div></div>` : ''}
      <div class="bc-row"><span class="bc-label">타이밍</span><div class="bc-mute">${lust}${pot ? ' · ' + pot : ''}</div></div>
      ${ups ? `<div class="bc-row"><span class="bc-label">버프업타임</span><div class="bc-mute">${ups}</div></div>` : ''}
    </div>`;
  }).join('');
  $('#rot-body').innerHTML = `<div class="bc-note">⚠ 상위 100명이 실제로 쓴 순서에서 뽑아낸 값. 블러드는 펫블러드(야수) 말고는 남이 걸어주는 거라 받은 판만 집계(비율 표기). 물약은 기록이 드물어 참고만.</div><div class="bc-grid">${cards}</div>`;
  whEnsure();
}
// ── 스탯 (보스별 스탯 분포) ─────────────────────────────────────────
let _statData = null;
let _statMeta = null;
const _statSel = { cls: null, spec: null, boss: null };
async function loadStats() {
  if (_statData) { renderStatControls(); return; }
  $('#stat-body').innerHTML = '<div class="empty">로딩…</div>';
  try {
    const r = await fetch('/api/boss-stats');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const payload = await r.json();
    _statData = payload.data || {};
    _statMeta = payload.meta || {};
    renderStatControls();
  } catch (e) {
    $('#stat-body').innerHTML = `<div class="empty">로드 실패: ${esc(e.message)}</div>`;
  }
}
function renderStatControls() {
  // 키 'Class|Spec' → 클래스/전문화 목록
  const keys = Object.keys(_statData);
  const classes = [...new Set(keys.map(k => k.split('|')[0]))];
  const clsKrMap = { Hunter: '사냥꾼', Warrior: '전사', Mage: '마법사', Rogue: '도적', Priest: '사제',
    Warlock: '흑마법사', Druid: '드루이드', Paladin: '성기사', 'Death Knight': '죽음의 기사',
    'Demon Hunter': '악마사냥꾼', Monk: '수도사', Shaman: '주술사', Evoker: '기원사' };
  if (!_statSel.cls || !classes.includes(_statSel.cls)) _statSel.cls = classes[0];
  const specs = keys.filter(k => k.startsWith(_statSel.cls + '|')).map(k => k.split('|')[1]);
  if (!_statSel.spec || !specs.includes(_statSel.spec)) _statSel.spec = specs[0];
  const bosses = _statData[`${_statSel.cls}|${_statSel.spec}`] || {};
  const bossIds = Object.keys(bosses);
  if (!_statSel.boss || !bossIds.includes(_statSel.boss)) _statSel.boss = bossIds[0];
  const opt = (v, label, sel) => `<option value="${esc(v)}" ${v === sel ? 'selected' : ''}>${esc(label)}</option>`;
  $('#stat-class').innerHTML = classes.map(c => opt(c, clsKrMap[c] || c, _statSel.cls)).join('');
  $('#stat-spec').innerHTML = specs.map(s => opt(s, _specKrStat(s) || s, _statSel.spec)).join('');
  $('#stat-boss').innerHTML = bossIds.map(b => opt(b, bosses[b].boss_kr, _statSel.boss)).join('');
  renderStatBody();
}
function _specKrStat(spec) {
  const m = {
    'Beast Mastery': '야수', 'Marksmanship': '사격', 'Survival': '생존',
    'Arms': '무기', 'Fury': '분노', 'Frost': '냉기', 'Unholy': '부정',
    'Feral': '야성', 'Balance': '조화', 'Havoc': '파멸', 'Devourer': '포식',
    'Windwalker': '풍운', 'Retribution': '징벌', 'Shadow': '암흑',
    'Assassination': '암살', 'Outlaw': '무법', 'Subtlety': '잠행',
    'Elemental': '정기', 'Enhancement': '고양', 'Affliction': '고통',
    'Demonology': '악마', 'Destruction': '파괴', 'Fire': '화염', 'Arcane': '비전',
    'Devastation': '황폐', 'Augmentation': '증강',
  };
  return m[spec] || spec;
}
function _statCorrText(corr) {
  const fmt = (v) => v == null || Number.isNaN(Number(v)) ? '-' : `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}`;
  corr = corr || {};
  return `치명 ${fmt(corr.crit)} · 가속 ${fmt(corr.haste)} · 특화 ${fmt(corr.mastery)}`;
}
function renderBossStatRecommendationTable() {
  const bosses = _statData[`${_statSel.cls}|${_statSel.spec}`] || {};
  const rows = Object.entries(bosses)
    .filter(([, b]) => b.recommendation)
    .map(([eid, b]) => {
      const r = b.recommendation || {};
      const m = r.mean || {};
      return `<tr>
        <td>${esc(b.boss_kr || eid)}</td>
        <td>${esc(r.shape || '-')}</td>
        <td>${esc(r.plume || '-')}</td>
        <td class="num">${r.crit_mastery_pct != null ? r.crit_mastery_pct + '%' : '-'}</td>
        <td class="num">${m.mastery || '-'} / ${m.crit || '-'} / ${m.haste || '-'}</td>
        <td>${esc(_statCorrText(r.adjusted_corr))}</td>
        <td>${esc(r.profile || '-')}</td>
      </tr>`;
    }).join('');
  if (!rows) return '';
  return `<div class="st-section-label">보스별 권장 스탯 형태 <span class="bc-mute">— BM 무리 인도자, ilvl·전투시간 보정 포함</span></div>
    <div class="table-wrap st-rec-wrap">
      <table class="st-table st-rec-table">
        <thead><tr><th>보스</th><th>권장 형태</th><th>꽁지깃</th><th>치/특</th><th>특/치/가 평균</th><th>보정 후 상관</th><th>성격</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}
function renderSelectedStatRecommendation(d) {
  const r = d.recommendation;
  if (!r) return '';
  return `<div class="st-rec-card">
    <div class="st-rec-head">
      <span>${esc(d.boss_kr)} 권장</span>
      <span class="st-rec-conf">신뢰도 ${esc(r.confidence || '보통')} · n=${r.sample_n || '-'}</span>
    </div>
    <div class="st-rec-grid">
      <div><span class="bc-mute">스탯 형태</span><b>${esc(r.shape || '-')}</b></div>
      <div><span class="bc-mute">꽁지깃</span><b>${esc(r.plume || '-')}</b></div>
      <div><span class="bc-mute">보스 성격</span><b>${esc(r.profile || '-')}</b></div>
      <div><span class="bc-mute">동일 ilvl 보정</span><b>${esc(_statCorrText(r.adjusted_corr))}</b></div>
    </div>
    <div class="st-rec-note">${esc(r.basis || '')}</div>
    <div class="st-rec-note bc-mute">${esc(r.adjustment || '')}</div>
  </div>`;
}
function _trinketComboText(combos) {
  return (combos || []).slice(0, 2).map(c => `${c.combo} ${c.pct}%`).join(' / ') || '-';
}
function _boxEventText(box) {
  if (!box) return '-';
  const parts = [];
  if (box.event_coverage_pct != null) parts.push(`확인 ${box.event_coverage_pct}%`);
  if (box.used_pct_checked != null) parts.push(`사용 ${box.used_pct_checked}%`);
  if (box.opener_pct != null) parts.push(`오프닝 ${box.opener_pct}%`);
  if (box.first_s_median != null) parts.push(`첫사용 ${box.first_s_median}s`);
  if (box.count_median != null) parts.push(`보통 ${box.count_median}회`);
  return parts.join(' · ') || '-';
}
function renderBossTrinketRecommendationTable() {
  const bosses = _statData[`${_statSel.cls}|${_statSel.spec}`] || {};
  const rows = Object.entries(bosses)
    .filter(([, b]) => b.trinket_recommendation)
    .map(([eid, b]) => {
      const t = b.trinket_recommendation || {};
      const r = t.recommendation || {};
      return `<tr>
        <td>${esc(b.boss_kr || t.boss || eid)}</td>
        <td>${esc(r.pick || '-')}</td>
        <td>${esc(_trinketComboText(t.top_combos))}</td>
        <td class="num">${t.pack_leader_n || '-'}/${t.rankings_n || '-'}</td>
        <td>${esc(_boxEventText(t.box_events))}</td>
        <td>${esc(r.risk_profile || '-')}</td>
      </tr>`;
    }).join('');
  if (!rows) return '';
  return `<div class="st-section-label">보스별 장신구 추천 <span class="bc-mute">BM 무리의 인도자 · WCL 최신 파티션 top 표본</span></div>
    <div class="table-wrap st-rec-wrap">
      <table class="st-table st-rec-table st-trinket-table">
        <thead><tr><th>보스</th><th>추천</th><th>상위 조합</th><th>무리 표본</th><th>상자 로그</th><th>판단</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}
function renderSelectedTrinketRecommendation(d) {
  const t = d.trinket_recommendation;
  if (!t) return '';
  const r = t.recommendation || {};
  const g = t.groups || {};
  const box = g.box || {};
  const mastery = g.mastery_plume || {};
  const crit = g.crit_plume || {};
  return `<div class="st-rec-card st-trinket-card">
    <div class="st-rec-head">
      <span>${esc(d.boss_kr || t.boss)} 장신구 추천</span>
      <span class="st-rec-conf">${esc(r.risk_profile || '판단 보류')} · n=${t.pack_leader_n || '-'}</span>
    </div>
    <div class="st-rec-grid">
      <div><span class="bc-mute">추천 세팅</span><b>${esc(r.pick || '-')}</b></div>
      <div><span class="bc-mute">상위 조합</span><b>${esc(_trinketComboText(t.top_combos))}</b></div>
      <div><span class="bc-mute">상자 채택</span><b>${box.pct != null ? box.pct + '%' : '-'}</b></div>
      <div><span class="bc-mute">상자 사용</span><b>${esc(_boxEventText(t.box_events))}</b></div>
      <div><span class="bc-mute">특화 꽁지깃</span><b>${mastery.pct != null ? mastery.pct + '%' : '-'}</b></div>
      <div><span class="bc-mute">치명 꽁지깃</span><b>${crit.pct != null ? crit.pct + '%' : '-'}</b></div>
      <div><span class="bc-mute">상위 킬타임</span><b>${t.top_kill_s != null ? t.top_kill_s + 's' : '-'}</b></div>
      <div><span class="bc-mute">상위 ilvl</span><b>${t.top_ilvl != null ? t.top_ilvl : '-'}</b></div>
    </div>
    <div class="st-rec-note">${esc(r.reason || '')}</div>
  </div>`;
}
function renderOfficialSourceBrief() {
  const meta = _statMeta || {};
  const tr = meta.trinket_recommendations || {};
  const sources = meta.official_sources || [];
  if (!sources.length && !tr.partition_name) return '';
  const srcHtml = sources.map(s => {
    const takeaways = (s.takeaways || []).map(t => `<li>${esc(t)}</li>`).join('');
    const transcript = s.transcript_chars
      ? `자막 ${Number(s.transcript_chars).toLocaleString()}자 확보`
      : esc(s.transcript_status || '자막 없음');
    return `<div class="st-source-item">
      <div class="st-source-title">
        <a href="${esc(s.url || '#')}" target="_blank" rel="noreferrer">${esc(s.title || s.key || '공식 출처')}</a>
        <span>${esc(s.author_name || '')}</span>
      </div>
      <div class="st-source-meta">${esc(s.patch || tr.partition_name || '')} · ${transcript}</div>
      ${takeaways ? `<ul>${takeaways}</ul>` : ''}
    </div>`;
  }).join('');
  const notes = (tr.notes || []).slice(0, 3).map(n => `<li>${esc(n)}</li>`).join('');
  return `<section class="st-source-card">
    <div class="st-source-head">
      <span>12.0.7 공식 근거 반영</span>
      <b>${esc(tr.partition_name || '최신 파티션')}</b>
    </div>
    <div class="st-source-grid">
      ${srcHtml || '<div class="st-source-item"><div class="st-source-meta">공식 출처 메타 없음</div></div>'}
      <div class="st-source-item">
        <div class="st-source-title"><span>분석 적용 방식</span></div>
        <ul>
          <li>WCL 최신 파티션 표본을 기준으로 보스별 스탯/장신구 추천을 계산합니다.</li>
          <li>신규 298 장비가 로그에 섞이므로 ilvl·킬타임 보정값을 함께 봅니다.</li>
          ${notes}
        </ul>
      </div>
    </div>
  </section>`;
}
function renderStatBody() {
  const d = (_statData[`${_statSel.cls}|${_statSel.spec}`] || {})[_statSel.boss];
  if (!d) { $('#stat-body').innerHTML = '<div class="empty">데이터 없음</div>'; return; }
  const STATS = ['특화', '치명', '가속', '유연'];
  // 비중 막대 (% 기준 너비)
  const bar = (p) => `<div class="st-bar">${STATS.map(s =>
    `<span class="st-seg seg-${s}" style="width:${p[s] || 0}%" title="${s} ${p[s] || 0}%">${(p[s] || 0) >= 10 ? p[s] + '%' : ''}</span>`).join('')}</div>`;
  // 스탯 셀: raw 수치 + 실효%(DR) 병기
  const statCell = (raw, eff) => raw == null ? '<td class="num">-</td>'
    : `<td class="num st-cell" title="실효 ${eff != null ? eff + '%' : '?'} (점감 적용)">${raw}<span class="st-eff">${eff != null ? eff + '%' : ''}</span></td>`;
  const buildBadge = (b) => b ? `<span class="bc-build ${b === '광' ? 'aoe' : 'st'}">${esc(b)}</span>` : '';
  const eff = (r) => r.eff || {};
  const topRows = (d.top || []).map(r => {
    const E = eff(r);
    return `<tr class="st-row" data-ref='${JSON.stringify(r.ref)}' title="클릭 = 장비창">
      <td class="mute num">${r.rank}</td>
      <td class="num">${r.dps.toLocaleString()}</td>
      <td>${buildBadge(r.build)}</td>
      ${statCell(r.stats['특화'], E['특화'])}
      ${statCell(r.stats['치명'], E['치명'])}
      ${statCell(r.stats['가속'], E['가속'])}
      ${statCell(r.stats['유연'], E['유연'])}
      <td class="st-bar-cell">${bar(r.pct)}</td>
    </tr>`;
  }).join('');
  // 평균 카드 렌더 (top_avg / rest_avg 공용)
  const avgCards = (blocks) => (blocks || []).map(b => {
    const E = b.eff || {};
    const num = (s) => `${s} <b>${b.stats[s]}</b><span class="st-eff">${E[s] != null ? E[s] + '%' : ''}</span>`;
    return `<div class="st-avg-card">
      <div class="st-avg-head">${buildBadge(d.has_build ? b.label : null)} ${esc(b.label)} 평균 <span class="bc-mute">(${b.n}명, ilvl ${b.ilvl})</span></div>
      <div class="st-avg-nums">${STATS.map(num).join(' · ')}</div>
      ${bar(b.pct)}
    </div>`;
  }).join('');
  const topAvg = avgCards(d.top_avg);
  const restAvg = avgCards(d.rest_avg);
  $('#stat-body').innerHTML = `
    ${renderOfficialSourceBrief()}
    ${renderBossTrinketRecommendationTable()}
    ${renderSelectedTrinketRecommendation(d)}
    ${renderBossStatRecommendationTable()}
    ${renderSelectedStatRecommendation(d)}
    <div class="st-section-label">🎯 1~20등 평균 = 목표 스탯 ${d.has_build ? '(빌드별 광/단일)' : ''} <span class="bc-mute">— 풀버프 기준, 인게임 음식·영약 켜고 맞추면 됨</span></div>
    <div class="st-avg-grid">${topAvg || '<div class="sm-empty">데이터 없음</div>'}</div>
    <div class="st-section-label">1~20등 개별 <span class="bc-mute">— 수치 + 실효%(점감반영). 행 클릭=장비창</span></div>
    <div class="table-wrap st-table-wrap">
      <table class="st-table">
        <thead><tr><th>#</th><th>DPS</th><th>빌드</th><th>특화</th><th>치명</th><th>가속</th><th>유연</th><th>비중</th></tr></thead>
        <tbody>${topRows}</tbody>
      </table>
    </div>
    <div class="st-section-label">21~100등 평균</div>
    <div class="st-avg-grid">${restAvg || '<div class="sm-empty">평균 데이터 없음</div>'}</div>`;
}

// 장비창 모달 — 기존 /api/character (gear enrichment 재사용)
const _SLOT_ORDER = ['머리','목','어깨','등','가슴','손목','손','허리','다리','발','반지','반지','장신구','장신구','주무기','보조장비'];
async function openGearModal(ref) {
  const m = $('#gear-modal');
  m.classList.add('show');
  $('#gear-modal-body').innerHTML = '<div class="empty">장비 로딩…</div>';
  // 경량 gear 엔드포인트 (player_fight 캐시에서 gear 만 — events 안 건드려 즉시)
  const gearUrl = `/api/gear/${encodeURIComponent(ref.rid)}/${ref.fid}/${encodeURIComponent(ref.char)}`;
  try {
    const r = await fetch(gearUrl);
    if (r.ok) { renderGear(await r.json(), ref.char); return; }
    if (r.status !== 404) throw new Error(`HTTP ${r.status}`);
    // 캐시 미스 → character_detail 로 WCL 페치 (느림)
    const fullUrl = `/api/character/${encodeURIComponent(ref.rid)}/${ref.fid}/${encodeURIComponent(ref.char)}`;
    $('#gear-modal-body').innerHTML =
      `<div class="empty">이 캐릭 장비는 캐시에 없습니다.<br>
       <button class="gm-fetch-btn">WCL에서 불러오기 (~8초)</button></div>`;
    $('#gear-modal-body .gm-fetch-btn').addEventListener('click', async () => {
      $('#gear-modal-body').innerHTML = '<div class="empty">WCL 페치 중… (~8초)</div>';
      try {
        const r2 = await fetch(fullUrl);
        if (!r2.ok) throw new Error(`HTTP ${r2.status}`);
        renderGear(await r2.json(), ref.char);
      } catch (e) {
        $('#gear-modal-body').innerHTML = `<div class="empty">페치 실패: ${esc(e.message)}</div>`;
      }
    });
  } catch (e) {
    $('#gear-modal-body').innerHTML = `<div class="empty">로드 실패: ${esc(e.message)}</div>`;
  }
}
function renderGear(data, charName) {
  const gear = (data.gear || []).filter(g => g.id && g.id !== 0);  // 빈 슬롯 제외
  const qcls = (q) => 'q' + (q || 'common');
  const items = gear.map(g => {
    // wowhead 툴팁 — 아이템 풀스탯 + 마부 + 보석 (data-wowhead 속성)
    const wh = `item=${g.id}&domain=ko`
      + (g.ench ? `&ench=${g.ench}` : '')
      + ((g.gems || []).length ? `&gems=${g.gems.map(x => x.id).join(':')}` : '');
    // 보석: 아이콘 + 이름
    const gems = (g.gems || []).map(gm =>
      gm.icon ? `<img class="gm-gem-icon" src="${wowIconUrl(gm.icon)}" title="${esc(gm.name_ko || gm.id)}" onerror="this.style.display='none'">`
              : `<span class="gm-gem" title="보석 ${gm.id}"></span>`).join('');
    // 마부: ID 표기 (wowhead 툴팁에서 이름 확인)
    const ench = g.ench ? `<span class="gm-ench" title="마부 (툴팁 참고)">마부</span>` : '';
    return `<a class="gm-item ${qcls(g.quality)}" href="https://www.wowhead.com/ko/item=${g.id}" target="_blank" data-wowhead="${wh}" rel="noopener">
      ${wowIconUrl(g.icon) ? `<img class="gm-icon" src="${wowIconUrl(g.icon)}" onerror="this.style.visibility='hidden'">` : '<span class="gm-icon gm-noicon"></span>'}
      <div class="gm-info">
        <div class="gm-slot">${esc(g.slot_kr || '')}</div>
        <div class="gm-name">${esc(g.name_ko || g.name_wcl || ('#' + (g.id || '')))} <span class="gm-ilvl">${g.ilvl || ''}</span></div>
        <div class="gm-extra">${ench}${gems}</div>
      </div>
    </a>`;
  }).join('');
  $('#gear-modal-body').innerHTML = `
    <div class="gm-head">${esc(charName)} <span class="bc-mute">장비 (${gear.length}부위)</span></div>
    <div class="gm-grid">${items || '<div class="empty">장비 데이터 없음</div>'}</div>
    <div class="sm-foot">아이템에 마우스 = wowhead 툴팁(풀스탯·마부·보석명). 클릭 = wowhead. 보석 아이콘에 마우스 올리면 이름.</div>`;
  // wowhead 파워 툴팁 스크립트 (없으면 1회 로드)
  if (!window.$WowheadPower) {
    const s = document.createElement('script');
    s.src = 'https://wow.zamimg.com/widgets/power.js';
    document.head.appendChild(s);
  } else if (window.$WowheadPower.refreshLinks) {
    window.$WowheadPower.refreshLinks();
  }
}

function renderRotBody() {
  const spec = _rotData[_rotSel.cls].specs[_rotSel.spec];
  const build = spec.builds[_rotSel.build];
  if (!build) { $('#rot-body').innerHTML = '<div class="empty">빌드 없음</div>'; return; }
  const hasGame = rotGameSupported();
  const list = (arr) => arr && arr.length
    ? `<ol class="rot-list">${arr.map(x => `<li>${wsify(esc(x))}</li>`).join('')}</ol>`
    : '<div class="sm-empty">데이터 없음</div>';
  const gameBtn = hasGame ? `<button id="rot-game-btn" class="rot-game-btn" style="margin-top:10px">딜사이클 문제풀이 — ${esc(_rotSel.build)} (단일특/광특 50문제)</button>` : '';
  const head = `
    <div class="rot-meta">
      <div class="rot-summary">${wsify(esc(spec.summary || ''))}</div>
      ${spec.stat ? `<div class="rot-stat"><b>스탯</b> ${wsify(esc(spec.stat))}</div>` : ''}
      ${build.hero_note ? `<div class="rot-hero"><b>${esc(_rotSel.build)}</b> ${wsify(esc(build.hero_note))}</div>` : ''}
      ${gameBtn}
    </div>`;

  if (build.flow) {
    // ── 플로우형 레이아웃: 체크리스트(뭘 누를까) + 오프너 타임라인 + 용어 ──
    const f = build.flow;
    const TONE_LBL = { proc: '프록', cd: '쿨기', hold: '아끼기', spend: '소모', filler: '기본기' };
    const rows = (f.checklist || []).map((c, i) => {
      const tone = TONE_LBL[c.tone] ? c.tone : '';   // 화이트리스트 — class 속성 주입 방지
      // 답(아이콘+스킬)을 왼쪽에 — 설명과 붙여서 시선 이동 없이 읽히게 (2026-07-11 사용자 요청)
      return `
      <div class="fl-row ${tone}">
        <div class="fl-num">${i + 1}</div>
        <div class="fl-a">${wsify(esc(c.a))}${tone ? `<span class="fl-tone ${tone}">${TONE_LBL[tone]}</span>` : ''}</div>
        <div class="fl-q">${wsify(esc(c.q))}<div class="fl-why">${wsify(esc(c.why || ''))}</div></div>
      </div>`;
    }).join('');
    const openerStrip = (steps) => (steps || []).map((o, i) => `
      <div class="fl-op-step">
        <div class="fl-op-num">${i + 1}</div>
        <div class="fl-op-icon">${wsify(esc(o.s))}</div>
        <div class="fl-op-cap">${esc(o.t || '')}</div>
      </div>`).join('<div class="fl-op-arrow">→</div>');
    // 오프너: 단일/광역 분리(opener_single/opener_aoe) 지원, 없으면 공용(opener)
    const openerBlocks = [];
    if (f.opener_single) openerBlocks.push(['오프너 (단일 보스)', f.opener_single]);
    if (f.opener_aoe) openerBlocks.push(['오프너 (쫄 나오는 보스)', f.opener_aoe]);
    if (!openerBlocks.length && f.opener) openerBlocks.push(['오프너 — 전투 시작 순서 그대로', f.opener]);
    const openerHtml = openerBlocks.map(([title, steps]) => `
      <div class="fl-sec">
        <div class="fl-h">${esc(title)}</div>
        <div class="fl-opener">${openerStrip(steps)}</div>
      </div>`).join('');
    const gloss = (f.glossary || []).map(g =>
      `<div class="fl-gloss-item"><b>${esc(g.w)}</b> ${wsify(esc(g.m))}</div>`).join('');
    const tipItem = (t) => `<div class="fl-track-item"><span class="fl-track-s">${wsify(esc(t.s))}</span>${wsify(esc(t.n))}${t.macro ? `<pre class="fl-macro">${esc(t.macro)}</pre>` : ''}</div>`;
    // 프록·변신 맵 (proc_map): 프록이 뜨면 뭘 누르나 / 특성으로 버튼 자체가 바뀌는 것
    const procRow = (p) => `
      <div class="fl-proc-row">
        <div class="fl-proc-s">${wsify(esc(p.s))}</div>
        <div class="fl-proc-from">${wsify(esc(p.from || ''))}</div>
        <div class="fl-arrow">→</div>
        <div class="fl-proc-act">${wsify(esc(p.act || ''))}</div>
      </div>`;
    const procHtml = f.proc_map ? `
      <div class="fl-sec">
        <div class="fl-h">프록이 뜨면 — 무엇이 바뀌고 뭘 누르나</div>
        ${f.proc_map.note ? `<div class="fl-note">${esc(f.proc_map.note)}</div>` : ''}
        <div class="fl-proc-head"><div>버프/프록</div><div>언제 뜨나</div><div></div><div>그래서 뭘 누르나</div></div>
        ${(f.proc_map.items || []).map(procRow).join('')}
        ${(f.proc_map.transforms || []).length ? `
        <div class="fl-track-h" style="margin-top:12px">특성으로 버튼 자체가 바뀌는 것</div>
        ${f.proc_map.transforms.map(procRow).join('')}` : ''}
      </div>` : '';
    $('#rot-body').innerHTML = `
      ${head}
      <div class="fl-sec">
        <div class="fl-h">다음에 뭘 누르지? — 위에서부터 우선순위</div>
        <div class="fl-note">${esc(f.note || '')}</div>
        <div class="fl-list">${rows}</div>
        ${f.aoe_diff && f.aoe_diff.length ? `
        <div class="fl-aoe"><div class="fl-aoe-h">여러 마리일 때 (광역)</div>
          ${f.aoe_diff.map(x => `<div class="fl-aoe-line">${wsify(esc(x))}</div>`).join('')}</div>` : ''}
      </div>
      ${procHtml}
      ${openerHtml}
      ${f.opener_note ? `<div class="fl-note" style="margin:-6px 4px 10px">${wsify(esc(f.opener_note))}</div>` : ''}
      ${f.tracking ? `
      <div class="fl-sec">
        <div class="fl-h">화면에서 볼 것 — 추적할 버프·스택</div>
        <div class="fl-note">${esc(f.tracking.note || '')}</div>
        <div class="fl-track-grid">
          <div>
            <div class="fl-track-h">항상 보이게 (딜 버튼 옆)</div>
            ${(f.tracking.always || []).map(t => `<div class="fl-track-item"><span class="fl-track-s">${wsify(esc(t.s))}</span>${wsify(esc(t.n))}</div>`).join('')}
          </div>
          <div>
            <div class="fl-track-h">상황 확인용</div>
            ${(f.tracking.sometimes || []).map(t => `<div class="fl-track-item"><span class="fl-track-s">${wsify(esc(t.s))}</span>${wsify(esc(t.n))}</div>`).join('')}
          </div>
        </div>
      </div>` : ''}
      ${f.util_tips && (f.util_tips.items || []).length ? `
      <div class="fl-sec">
        <div class="fl-h">${esc(f.util_tips.title || '유틸 꿀팁')}</div>
        ${f.util_tips.items.map(tipItem).join('')}
      </div>` : ''}
      ${gloss ? `<div class="fl-sec"><div class="fl-h">용어 설명</div><div class="fl-gloss">${gloss}</div></div>` : ''}
      <details class="fl-details">
        <summary>자세한 설명 전문 (조건별 원문)</summary>
        <div class="rot-cols">
          <div class="rot-col"><div class="rot-col-h single">단일 우선순위</div>${list(build.single)}</div>
          <div class="rot-col"><div class="rot-col-h aoe">광역 우선순위</div>${list(build.aoe)}</div>
          <div class="rot-col"><div class="rot-col-h opener">오프너</div>${list(build.opener)}</div>
          ${build.util && build.util.length ? `<div class="rot-col"><div class="rot-col-h util">유틸·생존 (눌러야 할 것)</div>${list(build.util)}</div>` : ''}
        </div>
      </details>`;
  } else {
    $('#rot-body').innerHTML = `
      ${head}
      <div class="rot-cols">
        <div class="rot-col"><div class="rot-col-h single">단일 우선순위</div>${list(build.single)}</div>
        <div class="rot-col"><div class="rot-col-h aoe">광역 우선순위</div>${list(build.aoe)}</div>
        <div class="rot-col"><div class="rot-col-h opener">오프너</div>${list(build.opener)}</div>
        ${build.util && build.util.length ? `<div class="rot-col"><div class="rot-col-h util">유틸·생존 (눌러야 할 것)</div>${list(build.util)}</div>` : ''}
      </div>`;
  }
  const gb = $('#rot-game-btn');
  if (gb) gb.onclick = () => openRotGame(_rotSel.cls, _rotSel.spec, _rotSel.build);
  whEnsure();
}

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

  // 영문 class/spec → 한글 매핑 (백엔드가 행마다 class_kr/spec_kr 동봉)
  state.clsKr = {}; state.specKr = {};
  for (const r of state.rows) {
    if (r.class && r.class_kr) state.clsKr[r.class] = r.class_kr;
    if (r.spec && r.spec_kr) state.specKr[r.spec] = r.spec_kr;
  }

  // 클래스 — 한글 표시, value 는 영문(필터/트리 API 용). 한글 가나다순.
  const classes = [...new Set(state.rows.map(r => r.class).filter(Boolean))]
    .sort((a, b) => (state.clsKr[a]||a).localeCompare(state.clsKr[b]||b, 'ko'));
  $('#class-select').innerHTML = '<option value="">(전체)</option>'
    + classes.map(c => `<option value="${esc(c)}">${esc(state.clsKr[c]||c)}</option>`).join('');

  // 스펙은 클래스 선택에 따라 갱신
  updateSpecOptions();
}

function updateSpecOptions() {
  const cls = state.classFilter;
  const specs = [...new Set(
    state.rows
      .filter(r => !cls || r.class === cls)
      .map(r => r.spec).filter(Boolean)
  )].sort((a, b) => (state.specKr[a]||a).localeCompare(state.specKr[b]||b, 'ko'));
  $('#spec-select').innerHTML = '<option value="">(전체)</option>'
    + specs.map(s => `<option value="${esc(s)}">${esc(state.specKr[s]||s)}</option>`).join('');
}

// 영문 class/spec → 한글 (state 매핑, 없으면 영문 그대로)
function clsKr(en) { return (state.clsKr && state.clsKr[en]) || en; }
function specKr(en) { return (state.specKr && state.specKr[en]) || en; }

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
          <span class="v">${esc(row.character)} · ${esc(clsKr(row.class))} ${esc(specKr(row.spec))} · ilvl ${row.item_level ?? '?'}</span>
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
        const iconUrl = wowIconUrl(p.icon) || 'https://wow.zamimg.com/images/wow/icons/medium/inv_misc_questionmark.jpg';
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
  const name = g.name_ko || g.name_wcl || `#${g.id ?? '?'}`;
  const color = QUALITY_COLOR[(g.quality || '').toUpperCase()] || 'var(--text)';
  const iconUrl = wowIconUrl(g.icon);
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
// 로컬 전투로그 리플레이
function _replayTime(sec) {
  const v = Math.max(0, Number(sec) || 0);
  const m = Math.floor(v / 60);
  const s = Math.floor(v % 60);
  const ms = Math.floor((v - Math.floor(v)) * 10);
  return `${m}:${String(s).padStart(2, '0')}.${ms}`;
}

function _replayResult(row) {
  if (row.result) return '<span class="rp-ok">킬</span>';
  const pct = row.boss_percent != null ? ` · ${esc(row.boss_percent)}%` : '';
  return `<span class="rp-wipe">전멸${pct}</span>`;
}

function _analysisCauseText(rows, max = 3) {
  return (rows || []).slice(0, max)
    .map(row => `${esc(row.name || '?')}×${Number(row.deaths) || 0}`).join(' · ');
}

function _analysisCluster(analysis) {
  const clusters = analysis?.death_clusters || [];
  if (!clusters.length) return null;
  const key = analysis?.flags?.[0]?.key || '';
  const wanted = {
    radiance: 'Radiance', dissonance: 'Dissonance', interrupt: 'Terminate',
  }[key];
  let candidates = clusters;
  if (key === 'p3_transition') {
    const p3 = clusters.filter(row => Number(row.start_t) >= 330);
    if (p3.length) candidates = p3;
  } else if (wanted) {
    const matched = clusters.filter(row =>
      (row.causes || []).some(cause => cause.name === wanted));
    if (matched.length) candidates = matched;
  }
  return [...candidates].sort((a, b) => Number(b.events || 0) - Number(a.events || 0))[0];
}

function _analysisJump(t, label, canReplay) {
  const shown = _replayTime(t || 0);
  return canReplay
    ? `<button class="ra-jump" type="button" data-analysis-jump="${Number(t) || 0}" title="리플레이에서 이 시각으로 이동">${shown}</button> ${label}`
    : `${shown} ${label}`;
}

function _replayAnalysisCard(analysis, canReplay) {
  if (!analysis) return '';
  const flag = analysis.flags?.[0];
  const first = analysis.first_death || null;
  const cluster = _analysisCluster(analysis);
  const terminate = analysis.terminate || {};
  const finalCauses = _analysisCauseText(analysis.final_wipe_causes);
  const clusterCauses = _analysisCauseText(cluster?.causes);
  const sourceLabel = canReplay ? '2D/3D 재생 가능' : 'WCL 분석만 · 로컬 원본 없음';
  const firstText = first
    ? _analysisJump(first.t, `첫 기록 사망 · ${esc(first.cause || '?')}`, canReplay)
    : '첫 기록 사망 없음';
  const clusterText = cluster
    ? `${_analysisJump(cluster.start_t, '붕괴 연쇄', canReplay)} · ${Number(cluster.events) || 0}건/${Number(cluster.unique_players) || 0}명${clusterCauses ? ` · ${clusterCauses}` : ''}`
    : '뚜렷한 집단 사망 연쇄 없음';
  const bestDelta = analysis.compare_best?.boss_remaining_delta_pp;
  const compare = Number(bestDelta) > 0
    ? `최고 풀보다 ${Number(bestDelta).toFixed(2)}%p 더 남음`
    : '세션 최고 진행';
  return `
    <section class="replay-analysis-card">
      <div class="ra-title">
        <span class="ra-flag s-${esc(flag?.severity || 'info')}">${esc(flag?.label || '풀 분석')}</span>
        <span>${sourceLabel}</span>
        <a href="${esc(analysis.fight_url || analysis.report_url || '#')}" target="_blank" rel="noopener">WCL fight ${Number(analysis.fight_id) || '?'}</a>
      </div>
      <div class="ra-grid">
        <div><small>진행도</small><b>${esc(analysis.phase || '')} · ${Number(analysis.boss_remaining_pct).toFixed(2)}% 남음 · 세션 ${Number(analysis.progress_rank) || '?'}위</b><span>${compare}</span></div>
        <div><small>첫 사망 / 붕괴</small><b>${firstText}</b><span>${clusterText}</span></div>
        <div><small>사망 이벤트</small><b>${Number(analysis.deaths) || 0}건 · 고유 ${Number(analysis.unique_dead_players) || 0}명 · 재사망 ${Number(analysis.repeat_deaths) || 0}</b><span>종료 ${Number(analysis.early_cutoff_seconds) || 8}초 이전 ${Number(analysis.early_deaths) || 0}건</span></div>
        <div><small>Terminate / 블러드</small><b>시작 ${Number(terminate.begun) || 0} · 차단 ${Number(terminate.interrupted) || 0} · 완료 ${Number(terminate.completed) || 0}${Number(terminate.other) ? ` · 기타 ${Number(terminate.other)}` : ''}</b><span>이 풀 ${Number(analysis.bloodlust_casts) || 0}회 · 세션 ${Number(analysis.session_bloodlust_casts) || 0}회</span></div>
      </div>
      ${finalCauses ? `<div class="ra-final" title="직접 결정타 집계이며 붕괴를 시작한 원인은 더 앞선 타임라인에 있을 수 있습니다.">마지막 8초 직접 결정타 · ${finalCauses}</div>` : ''}
      <div class="ra-caveat">사망 원인은 직접 결정타입니다. 조기 사망은 종료 ${Number(analysis.early_cutoff_seconds) || 8}초 이전이라는 임의 분석 기준입니다.</div>
    </section>`;
}

const REPLAY_FOCUS_DEFS = [
  { key: 'p1_rune_quasar', phase: 'P1', label: '문양 후 집결·레이저', note: '문양 종료 뒤 집결선과 Dark Quasar 피격 확인' },
  { key: 'intermission_crystal', phase: '사이페', label: '수정·별빛파열 간섭', note: '수정 담당과 동시 특임의 배치·동선 확인' },
  { key: 'p2_crystal_spread', phase: 'P2', label: '수정→산개→복귀', note: '두 차례 수정 조작과 임계점 산개·복귀 확인' },
  { key: 'p3_knockback_spread', phase: 'P3 진입', label: '진입 전 튕김 산개', note: '어둠의 용해 전후 산개와 양쪽 분리 확인' },
];

function _rfShortName(value) {
  return String(value || '').split('-')[0];
}

function _rfNameList(values, limit = 4) {
  const names = [...new Set((values || []).map(_rfShortName).filter(Boolean))];
  if (!names.length) return '';
  return `${names.slice(0, limit).join(', ')}${names.length > limit ? ` 외 ${names.length - limit}명` : ''}`;
}

function _rfWaveSummary(item, wave) {
  const observed = wave.observed || {};
  if (item.key === 'p1_rune_quasar') {
    const hits = Number(observed.quasar_hit_players) || 0;
    const mismatch = Number(observed.rune_mismatch_players) || 0;
    const hitNames = _rfNameList(observed.quasar_targets);
    const mismatchNames = _rfNameList(observed.rune_mismatch_targets);
    return {
      text: `준항성 피격 ${hits}명${hitNames ? ` · ${hitNames}` : ''} · 문양 불화 ${mismatch}명${observed.window_complete === false ? ' · 레이저 전 종료' : ''}`,
      title: mismatchNames ? `문양 불화: ${mismatchNames}` : '',
    };
  }
  if (item.key === 'intermission_crystal') {
    const handlers = _rfNameList(observed.simultaneous_handlers, 6);
    const clips = _rfNameList(observed.quasar_targets);
    return {
      text: `수정 사전 ${Number(observed.pre_crystal_operations) || 0}+사이페 ${Number(observed.crystal_operations) || 0}회 · 별빛파열 중 조작 ${Number(observed.simultaneous_operations) || 0}회 · 준항성 ${Number(observed.quasar_hit_players) || 0}명`,
      title: `${handlers ? `동시 특임: ${handlers}` : '동시 특임 없음'}${clips ? ` · 준항성: ${clips}` : ''}`,
    };
  }
  if (item.key === 'p2_crystal_spread') {
    const formation = observed.formation || {};
    const pairs = (formation.closest_pairs || []).map(pair =>
      `${_rfShortName(pair.left_name)}↔${_rfShortName(pair.right_name)} ${Number(pair.distance_yards).toFixed(1)}m`).join(', ');
    const coverage = `${Number(formation.tracked_players) || 0}/${Number(formation.roster_players) || 0}`;
    return {
      text: `수정 ${Number(observed.first_crystal_operations) || 0}+${Number(observed.second_crystal_operations) || 0}회 · 5.5m 미만 후보 ${Number(formation.near_pairs_5_5y) || 0}쌍 · 좌표 ${coverage}`,
      title: pairs || '5.5m 미만 근접 후보 없음',
    };
  }
  const snapshots = observed.snapshots || [];
  if (snapshots.length) {
    const pairFlow = snapshots.map(s => `${s.label} ${Number(s.near_pairs_5_5y) || 0}쌍`).join(' → ');
    const radiusFlow = snapshots.map(s => Number(s.raid_radius_yards?.r90 || 0).toFixed(1)).join('→');
    const pairNames = snapshots.map(s => {
      const pairs = (s.closest_pairs || []).map(pair =>
        `${_rfShortName(pair.left_name)}↔${_rfShortName(pair.right_name)} ${Number(pair.distance_yards).toFixed(1)}m`).join(', ');
      return pairs ? `${s.label}: ${pairs}` : '';
    }).filter(Boolean).join(' · ');
    return { text: `${pairFlow} · r90 ${radiusFlow}m`, title: pairNames || '5.5m 미만 근접 후보 없음' };
  }
  return { text: '', title: '' };
}

function _replayFocusCard(focus, canReplay, loading = false) {
  let items = focus?.items || [];
  if (!items.length) {
    items = REPLAY_FOCUS_DEFS.map(row => ({
      ...row, status: canReplay ? (loading ? 'loading' : 'event_missing') : 'no_positions', windows: [],
    }));
  }
  const statusText = {
    loading: '체크포인트 계산 중…',
    not_reached: '이 풀은 해당 구간 미도달',
    event_missing: '구간 시각 도달 · 기준 이벤트 없음',
    no_positions: '위치 없음 · WCL에서 확인',
  };
  return `
    <section class="replay-focus-card">
      <div class="rf-title"><b>집중 관찰</b><span>좌표·피격 기록만 표시 · 배치 정오답은 리플레이에서 확인</span></div>
      <div class="rf-grid">
        ${items.map(item => {
          const windows = item.windows || [];
          return `<article class="rf-item k-${esc(item.key || '')} s-${esc(item.status || '')}" title="${esc(item.note || '')}">
            <div class="rf-item-head"><span>${esc(item.phase || '')}</span><b>${esc(item.label || '')}</b></div>
            <p>${esc(item.note || '')}</p>
            ${windows.length ? windows.map(wave => {
              const summary = _rfWaveSummary(item, wave);
              const segments = wave.segments || [{ label: `${Number(wave.occurrence) || 1}차`, t: wave.seek_t ?? wave.start_t }];
              return `<div class="rf-wave">
                <b>${Number(wave.occurrence) || 1}차</b>
                <span class="rf-jumps">${segments.map(segment => canReplay
                  ? `<button type="button" data-focus-jump="${Number(segment.t) || 0}" title="${esc(segment.label || '')} 시각으로 이동">${esc(segment.label || '')} ${rcClock(segment.t || 0)}</button>`
                  : `<i>${esc(segment.label || '')} ${rcClock(segment.t || 0)}</i>`).join('')}</span>
                <small title="${esc(summary.title)}">${esc(summary.text)}</small>
              </div>`;
            }).join('') : `<div class="rf-unavailable">${esc(statusText[item.status] || '확인 구간 없음')}</div>`}
          </article>`;
        }).join('')}
      </div>
      <div class="rf-caveat">${esc(focus?.distance_note || 'WCL 전용 풀은 원본 좌표가 없어 대형·동선을 판정할 수 없습니다.')}</div>
    </section>`;
}

function renderReplayFocus(focus, canReplay = true) {
  const host = $('#replay-review-focus');
  if (!host) return;
  host.innerHTML = _replayFocusCard(focus, canReplay);
  host.querySelectorAll('[data-focus-jump]').forEach(button => {
    button.addEventListener('click', () => rcSeek(Number(button.dataset.focusJump) || 0));
  });
}

async function loadLocalReplays(force = false) {
  if (replayState.loaded && !force) return;
  const body = $('#replay-list-body');
  const status = $('#replay-status');
  if (!body) return;
  body.innerHTML = '<tr><td colspan="4" class="empty">로딩…</td></tr>';
  if (status) status.textContent = '전투로그/CCTV 스캔 중…';
  try {
    const r = await fetch(`/api/local-replay/list${force ? '?refresh=1' : ''}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();
    replayState.rows = j.rows || [];
    replayState.loaded = true;
    renderLocalReplayList(replayState.rows);
    const src = j.sources || {};
    const session = src.wcl_session || {};
    if (status) {
      status.textContent = session.pulls
        ? `${session.pulls}풀 · 좌표 리플레이 ${src.analysis_replay ?? 0} · 좌표 없음 숨김 ${src.coordinates_hidden ?? src.wcl_only ?? 0} · 최고 ${session.best_boss_remaining_pct}% · 블러드 ${session.bloodlust_casts ?? 0}회`
        : `${replayState.rows.length}개 리플레이 · 로그 전용 ${src.log_only ?? 0}개`;
    }
    if (replayState.rows.length && !replayState.selectedId) {
      const firstPlayable = replayState.rows.find(row => row.capabilities?.frames !== false);
      selectLocalReplay((firstPlayable || replayState.rows[0]).id);
    }
    rcStartTerrainPrefetch();
  } catch (e) {
    body.innerHTML = `<tr><td colspan="4" class="empty">로드 실패: ${esc(e.message)}</td></tr>`;
    if (status) status.textContent = '로드 실패';
  }
}

// ── 지형 프리페치 ────────────────────────────────────────────────────────
// 목록 로드 후 3초 쉬었다가 최근 10개 리플레이의 지형을 하나씩 미리 요청.
// 서버가 디스크(data/maps/terrain_*.json)에 저장하므로 다음 3D 열람이 즉시 뜬다.
// 실패는 무시, 리플레이 탭을 떠나면 중단, 보고 있는 리플레이는 건너뜀.
const rcPrefetch = { timer: 0, on: false, abort: null };

function rcStartTerrainPrefetch() {
  rcStopTerrainPrefetch();
  // 받은 대용량 로그는 선택했을 때 frames와 함께 한 번만 읽는다.
  // 백그라운드 프리페치는 기존 CCTV 캡처에만 유지한다.
  const ids = replayState.rows
    .filter(r => !r.log_only && r.capabilities?.terrain !== false)
    .slice(0, 10).map(r => r.id);
  if (!ids.length) return;
  rcPrefetch.timer = setTimeout(async () => {
    rcPrefetch.timer = 0;
    rcPrefetch.on = true;
    for (const id of ids) {
      if (!rcPrefetch.on) return;                 // 탭 이탈 등으로 중단됨
      if (id === replayState.selectedId) continue; // 보고 있는 리플레이는 3D 진입이 알아서
      rcPrefetch.abort = new AbortController();
      try {
        await fetch(`/api/replay/${encodeURIComponent(id)}/terrain`,
                    { signal: rcPrefetch.abort.signal });
      } catch (_) {}
      rcPrefetch.abort = null;
    }
    rcPrefetch.on = false;
  }, 3000);
}

function rcStopTerrainPrefetch() {
  if (rcPrefetch.timer) clearTimeout(rcPrefetch.timer);
  rcPrefetch.timer = 0;
  rcPrefetch.on = false;
  if (rcPrefetch.abort) { try { rcPrefetch.abort.abort(); } catch (_) {} rcPrefetch.abort = null; }
}

function renderLocalReplayList(rows) {
  const body = $('#replay-list-body');
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="4" class="empty">표시할 전투로그/CCTV 없음</td></tr>';
    return;
  }
  body.innerHTML = rows.map(row => {
    const matched = row.analysis_only
      ? 'rp-analysis-only'
      : (row.log_match ? 'rp-matched' : 'rp-unmatched');
    const active = row.id === replayState.selectedId ? 'selected' : '';
    const analysis = row.analysis || null;
    const flag = analysis?.flags?.[0];
    const secondary = analysis
      ? `#${analysis.pull} · fight ${analysis.fight_id} · ${analysis.phase} · ${row.analysis_only ? 'WCL만' : '2D/3D'}`
      : (row.player || '');
    return `
      <tr class="replay-row ${matched} ${active}" data-replay-id="${esc(row.id)}">
        <td>${esc((row.start_local || '').slice(5, 16))}</td>
        <td>
          <b>${flag ? `<i class="rp-flag s-${esc(flag.severity || 'info')}">${esc(flag.label)}</i>` : ''}${esc(row.encounter)}</b>
          <span>${esc(secondary)}</span>
        </td>
        <td>${_replayResult(row)}</td>
        <td class="right">${_replayTime(row.duration || 0)}</td>
      </tr>
    `;
  }).join('');
}

async function selectLocalReplay(id) {
  if (!id) return;
  replayState.selectedId = id;
  renderLocalReplayList(replayState.rows);
  const root = $('#replay-detail');
  if (root) root.innerHTML = '<div class="empty">상세 파싱 중…</div>';
  const selected = replayState.rows.find(row => row.id === id);
  if (selected?.capabilities?.frames === false) {
    const detail = {
      capture: selected,
      analysis: selected.analysis || null,
      analysis_only: true,
      duration: selected.duration || 0,
      events: [], positions: [], actors: [], counts: {},
      video: { available: false },
    };
    replayState.detail = detail;
    renderLocalReplayDetail(detail);
    return;
  }
  try {
    const r = await fetch(`/api/local-replay/${encodeURIComponent(id)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const detail = await r.json();
    if (!detail.analysis && selected?.analysis) detail.analysis = selected.analysis;
    replayState.detail = detail;
    renderLocalReplayDetail(detail);
  } catch (e) {
    if (root) root.innerHTML = `<div class="empty">상세 로드 실패: ${esc(e.message)}</div>`;
  }
}

// 이벤트 목록 한 줄 (전투로그 상세 이벤트 — t 는 캡처 시작 기준)
function _replayEventRow(ev) {
  return `
    <button class="replay-event ${esc(ev.kind || '')}" type="button" data-replay-jump="${Number(ev.t || 0)}">
      <span class="rt">${_replayTime(ev.t)}</span>
      <span class="rk">${esc(ev.kind || ev.event || '')}</span>
      <span class="rs">${esc(ev.source || '')}</span>
      <span class="ra">${esc(ev.spell || ev.event || '')}</span>
      <span class="rtg">${esc(ev.target || '')}</span>
      ${ev.amount ? `<span class="rd">${Number(ev.amount).toLocaleString()}</span>` : ''}
    </button>
  `;
}

// ── 통합 이벤트 피드 (보스 기믹 + 죽음 + 플레이어 이벤트) ────────────────
// 종류 정의 — 체크박스·색점 공용. 물약/쿨기류는 양이 많아 기본 꺼짐.
const RC_FEED_KINDS = [
  { key: 'boss',      label: '보스 기믹' },
  { key: 'death',     label: '죽음' },
  { key: 'bloodlust', label: '블러드' },
  { key: 'battleres', label: '전투부활' },
  { key: 'potion',    label: '물약' },
  { key: 'healthpot', label: '치유석·생명력 물약' },
  { key: 'offensive', label: '공격 쿨기' },
  { key: 'defensive', label: '생존기' },
  { key: 'utility',   label: '유틸기' },
];
const rcFeedOn = {
  boss: true, death: true, bloodlust: true, battleres: true,
  potion: false, healthpot: false, offensive: false, defensive: false, utility: false,
};
const RC_FEED_MAX_ROWS = 2000;   // 전부 켰을 때 DOM 폭주 방지

// 피드 한 줄 — [시간] [종류 색점] [짧은 텍스트] (t 는 전투 기준 → 영상 기준으로 변환)
// 툴팁 재료는 data-* 로 (sid=스킬 id, bk=보스 이벤트 종류, dur=지속 초, dest/src=대상/시전자)
function _feedRow(it) {
  const vt = Number(it.t || 0) + rc.videoOffset;
  return `
    <button class="replay-event feed k-${esc(it.kind)}" type="button" data-replay-jump="${vt}"
      data-k="${esc(it.kind)}" data-sid="${Number(it.sid) || 0}" data-spell="${esc(it.spell || '')}"
      data-mkey="${esc(it.mkey || '')}"
      data-bk="${esc(it.bk || '')}" data-dur="${Number(it.dur) || 0}"
      data-shape="${esc(it.geometry?.shape || '')}" data-radius="${Number(it.geometry?.radius || it.geometry?.length) || 0}"
      data-max-stacks="${Number(it.maxStacks) || 0}"
      data-dest="${esc(it.dest || '')}" data-src="${esc(it.src || '')}">
      <span class="rt">${rcClock(vt)}</span><i class="dot"></i><span class="tx">${esc(it.text)}</span>
    </button>
  `;
}

// 연결된 기믹 단위 표시 필터. 캐스트/디버프/피해 파생 ID를 함께 켜고 끈다.
const rcMechanicOff = new Set();
const rcMechanicShown = (ev) => !ev.mechanic_key || !rcMechanicOff.has(ev.mechanic_key);

function rcMechanicMeta(key) {
  return (key && rc.mechanicByKey[key]) || null;
}

function rcPlaceMechanicPop(btn, pop) {
  pop.hidden = false;
  pop.style.maxHeight = `${Math.max(220, Math.min(440, window.innerHeight - 16))}px`;
  const br = btn.getBoundingClientRect();
  const w = pop.offsetWidth, h = pop.offsetHeight;
  const x = Math.max(8, Math.min(br.right - w, window.innerWidth - w - 8));
  let y = br.bottom + 6;
  if (y + h > window.innerHeight - 8) y = Math.max(8, br.top - h - 6);
  pop.style.left = `${Math.round(x)}px`;
  pop.style.top = `${Math.round(y)}px`;
}

// 필터 변경을 모든 표시 경로(피드·타임라인 트랙·링·유닛 패널)에 반영
function rcApplyMechanicFilter() {
  renderReplayEventRows();
  document.querySelectorAll('#rc-bossevents i[data-mkey]').forEach(el => {
    el.classList.toggle('off', rcMechanicOff.has(el.dataset.mkey));
  });
  rcPanelKey = '';
  rcDraw();
}

// frames 데이터 → 피드 재료 (t 오름차순, 종류 무관 전체)
function rcBuildFeed() {
  const items = [];
  const nameOf = {};
  for (const u of (rc.meta?.units || [])) nameOf[u.id] = String(u.name || u.id).split('-')[0];
  for (const ev of rc.bossEvents || []) {
    if (!rcMechanicShown(ev)) continue;
    const mechanic = rcMechanicMeta(ev.mechanic_key);
    const dest = ev.dest_name ? String(ev.dest_name).split('-')[0] : '';
    const who = dest ? ` → ${dest}` : '';
    // 기간형 디버프(end 있음)는 걸려 있던 시간을 같이 표기 — "(8초)"
    const durS = ev.end != null ? Math.round(Number(ev.end) - Number(ev.t)) : 0;
    const dur = ev.end != null ? ` (${durS}초)` : '';
    const shownName = mechanic?.name || ev.spell || '';
    items.push({ t: Number(ev.t) || 0, kind: 'boss', text: `${shownName}${who}${dur}`,
                 sid: mechanic?.spell_id || ev.root_spell_id || ev.spell_id,
                 spell: shownName, mkey: ev.mechanic_key, bk: ev.kind, dur: durS,
                 geometry: ev.geometry, maxStacks: ev.max_stacks,
                 dest, src: ev.src_name ? String(ev.src_name).split('-')[0] : '' });
  }
  for (const d of rc.meta?.deaths || []) {
    // 쫄몹 죽음은 제외 — 웨이브형 보스에선 수십 건이라 플레이어 죽음이 묻힌다
    if (String(d.id).startsWith('n')) continue;
    items.push({ t: Number(d.t) || 0, kind: 'death', text: `${nameOf[d.id] || d.id} 사망`,
                 spell: `${nameOf[d.id] || d.id} 사망` });
  }
  for (const pe of rc.playerEvents || []) {
    if (!(pe.kind in rcFeedOn)) continue;
    const who = pe.unit_id ? (nameOf[pe.unit_id] || '') : '';   // 펫 시전은 이름 없이
    items.push({ t: Number(pe.t) || 0, kind: pe.kind,
                 text: who ? `${who} ${pe.spell || ''}` : String(pe.spell || ''),
                 sid: pe.spell_id, spell: pe.spell, src: who });
  }
  items.sort((a, b) => a.t - b.t);
  return items;
}

// 통합 피드 렌더 — 체크된 종류만, 종류별 건수는 체크박스 라벨 옆에 표시
function renderReplayEventRows() {
  const evRoot = $('#replay-events');
  if (!evRoot) return;
  evRoot.classList.remove('raw');
  const feed = rc.meta ? rcBuildFeed() : [];
  const counts = {};
  for (const k of RC_FEED_KINDS) counts[k.key] = 0;
  for (const it of feed) counts[it.kind]++;
  for (const k of RC_FEED_KINDS) {
    const n = document.querySelector(`#replay-ev-kinds [data-evn="${k.key}"]`);
    if (n) n.textContent = counts[k.key] ? String(counts[k.key]) : '';
  }
  const shown = feed.filter(it => rcFeedOn[it.kind]);
  const cut = shown.length - RC_FEED_MAX_ROWS;
  evRoot.innerHTML = (shown.slice(0, RC_FEED_MAX_ROWS).map(_feedRow).join('')
    + (cut > 0 ? `<div class="empty">…${cut.toLocaleString()}개 생략 (종류를 줄여 보세요)</div>` : ''))
    || '<div class="empty">표시할 이벤트 없음 (위 체크박스로 종류 선택)</div>';
  rcRebuildEvCache();
}

// frames(좌표) 없는 풀 폴백 — 기존 상세 이벤트 원본 목록 (종류 필터 불가)
function renderReplayEventRowsRaw() {
  const evRoot = $('#replay-events');
  if (!evRoot) return;
  evRoot.classList.add('raw');
  const events = replayState.detail?.events || [];
  evRoot.innerHTML = events.slice(0, 900).map(_replayEventRow).join('')
    || '<div class="empty">표시할 이벤트 없음</div>';
  rcRebuildEvCache();
}

// 이벤트 종류 체크박스 활성/비활성 (frames 로딩 성공 후에만 켜짐)
function rcSetFeedEnabled(on, why) {
  const root = $('#replay-ev-kinds');
  if (!root) return;
  root.title = why || '';
  root.querySelectorAll('input[data-evkind]').forEach(cb => { cb.disabled = !on; });
}

function renderReplayAnalysisOnly(detail) {
  const root = $('#replay-detail');
  if (!root) return;
  const cap = detail.capture || {};
  const analysis = detail.analysis || cap.analysis || {};
  const isLura = Number(cap.encounter_id) === 3183 || String(cap.encounter || '').includes('한밤의 도래');
  root.classList.remove('empty', 'view-max');
  root.classList.add('analysis-only');
  root.innerHTML = `
    <div class="replay-head">
      <div>
        <h2>${esc(cap.encounter || '르우라')} — #${Number(analysis.pull) || '?'}풀</h2>
        <div class="replay-sub">${esc(cap.start_local || '')} · WCL fight ${Number(analysis.fight_id) || '?'}</div>
      </div>
      <div class="replay-kpis">
        <span>잔여 HP <b>${Number(analysis.boss_remaining_pct).toFixed(2)}%</b></span>
        <span>도달 <b>${esc(analysis.phase || '')}</b></span>
        <span>길이 <b>${_replayTime(analysis.duration_s || cap.duration || 0)}</b></span>
      </div>
    </div>
    ${_replayAnalysisCard(analysis, false)}
    ${isLura ? `<div id="replay-review-focus">${_replayFocusCard(null, false)}</div>` : ''}
    <div class="replay-analysis-empty">
      <b>WCL 분석 전용 — 지도·2D/3D 리플레이 없음</b>
      <p>로컬 전투로그가 23:02:15에 끝난 뒤의 풀입니다. 위치·이동 경로를 재생하려면 이 시간대가 포함된 원본 전투로그가 필요합니다.</p>
      <a href="${esc(analysis.fight_url || analysis.report_url || '#')}" target="_blank" rel="noopener">Warcraft Logs에서 이 풀 열기</a>
    </div>`;
}

// 우측 분석 패널 접힘 상태 — 풀을 전환해도 유지
let rcSideOpen = true;

function renderLocalReplayDetail(detail) {
  const root = $('#replay-detail');
  if (!root) return;
  const cap = detail.capture || {};
  const analysis = detail.analysis || cap.analysis || null;
  if (detail.analysis_only || cap.capabilities?.frames === false) {
    renderReplayAnalysisOnly({ ...detail, analysis });
    return;
  }
  const counts = detail.counts || {};
  const events = detail.events || [];
  const hasVideo = !!detail.video?.available;
  const isLura = Number(cap.encounter_id) === 3183 || String(cap.encounter || '').includes('한밤의 도래');
  // 분석·리뷰 카드는 지도 위가 아니라 우측 접이식 패널에 — 지도가 주인공
  const analysisCardHtml = _replayAnalysisCard(analysis, true);
  const focusHtml = isLura ? `<div id="replay-review-focus">${_replayFocusCard(null, true, true)}</div>` : '';
  const hasSide = !!(analysisCardHtml || focusHtml);
  root.classList.remove('empty');
  root.classList.remove('analysis-only');
  root.classList.toggle('view-max', !hasVideo);
  root.innerHTML = `
    <div class="replay-head">
      <div>
        <h2>${esc(cap.encounter || '리플레이')}${analysis ? ` — #${Number(analysis.pull) || '?'}풀` : ''}</h2>
        <div class="replay-sub">${esc(cap.start_local || '')} · ${esc(cap.difficulty || '')} · ${_replayResult(cap)}${analysis ? ` · WCL fight ${Number(analysis.fight_id) || '?'}` : ''}</div>
      </div>
      <div class="replay-kpis">
        ${analysis ? `<span>잔여 HP <b>${Number(analysis.boss_remaining_pct).toFixed(2)}%</b></span><span>도달 <b>${esc(analysis.phase || '')}</b></span>` : ''}
        <span>이벤트 <b id="rc-kpi-events">${events.length.toLocaleString()}</b></span>
        <span>좌표 <b id="rc-kpi-positions">${Number(counts.positions ?? (detail.positions || []).length).toLocaleString()}</b></span>
        <span>전투원 <b id="rc-kpi-units">${(detail.actors || []).length.toLocaleString()}</b></span>
      </div>
    </div>
    <div class="replay-mid">
    <div class="replay-main ${hasVideo ? '' : 'view-map'}">
      <div class="replay-video-wrap">
        ${hasVideo
          ? `<video id="replay-video" class="replay-video" preload="metadata" src="${esc(detail.video.url)}"></video>`
          : '<div class="empty replay-no-video">전투로그 전용 리플레이</div>'}
      </div>
      <div class="replay-canvas-wrap">
        <div class="rc-stage">
          <canvas id="rc-canvas" width="1000" height="660"></canvas>
          <div id="rc-banner" class="rc-banner"></div>
          <div id="rc-space" class="rc-space"></div>
          <div id="rc-panel" class="rc-panel" style="display:none"></div>
          <div id="rc-msg" class="rc-msg">이동 경로 데이터 로딩…</div>
        </div>
        <div id="rc-units" class="rc-units"></div>
        <div id="rc-note" class="rc-note"></div>
      </div>
    </div>
    ${hasSide ? `<aside id="replay-side" class="${rcSideOpen ? '' : 'collapsed'}">
      <button id="rc-side-toggle" type="button" title="분석 패널 접기/펴기 — 접으면 지도가 화면 전체를 씁니다">${rcSideOpen ? '분석 접기 ▸' : '◂ 분석'}</button>
      <div class="rc-side-body">
        ${analysisCardHtml}
        ${focusHtml}
      </div>
    </aside>` : ''}
    </div>
    <!-- 타임라인 하나 — 영상·리플레이 둘 다 이 줄로 조작 (두 화면 아래 전체 폭) -->
    <div class="rc-controls">
      <button id="rc-play" type="button">재생</button>
      <button id="rc-speed" type="button" title="재생 속도">1x</button>
      <button id="rc-3d" type="button" title="지형 위에서 입체로 보기">3D 보기</button>
      ${hasVideo ? '<button id="rc-view-video" class="rc-viewbtn" type="button" title="영상만 크게 — 아래 이벤트 목록과 같이 보기 (다시 누르면 기본)">영상 크게</button>\n      <button id="rc-view-map" class="rc-viewbtn" type="button" title="지도만 크게 — 아래 이벤트 목록과 같이 보기 (다시 누르면 기본)">지도 크게</button>\n      <button id="rc-mute" type="button" title="영상 소리 켜고 끄기">소리 끄기</button>' : ''}
      <div class="rc-scrub-wrap">
        <input id="rc-scrub" type="range" min="0" max="0" step="0.1" value="0">
        <div id="rc-bossevents" title=""></div>
        <div id="rc-deaths"></div>
      </div>
      <span id="rc-clock">0:00 / 0:00</span>
    </div>
    <div class="replay-belt">
      <div class="replay-ev-kinds" id="replay-ev-kinds" title="이동 경로 데이터 로딩 후 사용 가능">
        ${RC_FEED_KINDS.map(k => `
          <label class="k-${k.key}">
            <input type="checkbox" data-evkind="${k.key}" ${rcFeedOn[k.key] ? 'checked' : ''} disabled>
            <i class="dot"></i>${k.label}<span class="n" data-evn="${k.key}"></span>
          </label>`).join('')}
        <button id="rc-mechanic-btn" type="button" title="이 판의 보스 기믹을 캐스트·디버프·피해까지 함께 켜고 끄기">기믹 필터 ▾</button>
        <div id="rc-mechanic-pop" hidden></div>
      </div>
      <div class="replay-counts">
        <span>캐스트 <b id="rc-count-casts">${Number(counts.casts || 0).toLocaleString()}</b></span>
        <span>디버프 <b id="rc-count-debuffs">${Number(counts.debuffs || 0).toLocaleString()}</b></span>
        <span>큰 피해 <b id="rc-count-damage">${Number(counts.damage || 0).toLocaleString()}</b></span>
        <span>사망 <b id="rc-count-deaths">${Number(cap.deaths || counts.deaths || 0).toLocaleString()}</b></span>
        ${counts.skipped ? `<span>목록 생략 ${Number(counts.skipped).toLocaleString()}</span>` : ''}
      </div>
    </div>
    <div id="replay-events" class="replay-events">
      <div class="empty">이벤트 목록 로딩…</div>
    </div>
  `;

  const video = $('#replay-video');
  root.querySelectorAll('[data-analysis-jump]').forEach(button => {
    button.addEventListener('click', () => {
      const t = Number(button.dataset.analysisJump) || 0;
      if (video) video.currentTime = Math.max(0, t + Number(rc.videoOffset || 0));
      rcSeek(t);
    });
  });
  // 보기 모드 — 영상만/지도만 크게 (다시 누르면 기본 2분할)
  {
    const mainEl = root.querySelector('.replay-main');
    const vv = $('#rc-view-video');
    const vm = $('#rc-view-map');
    const setView = (mode) => {
      root.classList.toggle('view-max', !!mode);
      mainEl.classList.toggle('view-video', mode === 'video');
      mainEl.classList.toggle('view-map', mode === 'map');
      vv.classList.toggle('active', mode === 'video');
      vm.classList.toggle('active', mode === 'map');
      vv.textContent = mode === 'video' ? '기본 보기' : '영상 크게';
      vm.textContent = mode === 'map' ? '기본 보기' : '지도 크게';
      window.dispatchEvent(new Event('resize'));   // 2D/3D 캔버스 크기 재계산
    };
    if (vv && vm) {
      vv.addEventListener('click', () => setView(mainEl.classList.contains('view-video') ? '' : 'video'));
      vm.addEventListener('click', () => setView(mainEl.classList.contains('view-map') ? '' : 'map'));
    }
  }
  // 우측 분석 패널 접기/펴기 — 접으면 지도가 가로 전체를 쓴다
  {
    const side = $('#replay-side');
    const sideToggle = $('#rc-side-toggle');
    if (side && sideToggle) {
      sideToggle.addEventListener('click', () => {
        rcSideOpen = !rcSideOpen;
        side.classList.toggle('collapsed', !rcSideOpen);
        sideToggle.textContent = rcSideOpen ? '분석 접기 ▸' : '◂ 분석';
        window.dispatchEvent(new Event('resize'));   // 2D/3D 캔버스 크기 재계산
      });
    }
  }
  // 소리 켜기/끄기 — video.muted 토글 (동사형: 누르면 할 일을 표시)
  const muteBtn = $('#rc-mute');
  if (muteBtn && video) {
    muteBtn.addEventListener('click', () => {
      video.muted = !video.muted;
      muteBtn.textContent = video.muted ? '소리 켜기' : '소리 끄기';
    });
  }
  const evRoot = $('#replay-events');
  if (evRoot) {
    evRoot.addEventListener('click', e => {
      const btn = e.target.closest('[data-replay-jump]');
      if (!btn) return;
      rcHideTip();
      const t = Number(btn.dataset.replayJump || 0);
      if (video) video.currentTime = t;
      // 이벤트/영상 t 는 캡처 시작 기준, 캔버스는 전투 시작 기준 → 오프셋 보정
      rcSeek(Math.max(0, t - Number(rc.meta?.video_offset_s || 0)));
    });
    // 피드 행에 마우스를 올리면 스킬 툴팁 (터치 클릭은 방해하지 않음)
    evRoot.addEventListener('mouseover', e => {
      const row = e.target.closest('.replay-event.feed');
      if (!row || row === rcTip.anchor) return;
      rcShowTip(rcTipInfoFromRow(row), row);
    });
    evRoot.addEventListener('mouseout', e => {
      const row = e.target.closest('.replay-event.feed');
      if (row && !row.contains(e.relatedTarget)) rcHideTip();
    });
    // 재생 중 자동 스크롤 등으로 행이 움직이면 툴팁이 어긋나니 바로 치움
    evRoot.addEventListener('scroll', rcHideTip, { passive: true });
  }
  const evKinds = $('#replay-ev-kinds');
  if (evKinds) {
    evKinds.addEventListener('change', e => {
      const cb = e.target.closest('input[data-evkind]');
      if (!cb) return;
      rcFeedOn[cb.dataset.evkind] = cb.checked;
      renderReplayEventRows();
    });
    const dbtn = evKinds.querySelector('#rc-mechanic-btn');
    const dpop = evKinds.querySelector('#rc-mechanic-pop');
    if (dbtn && dpop) {
      dbtn.addEventListener('click', () => {
        if (!dpop.hidden) { dpop.hidden = true; return; }
        let mechanics = rc.bossMechanics || [];
        if (!mechanics.length) {
          const fallback = new Map();
          for (const ev of rc.bossEvents || []) {
            const key = ev.mechanic_key || `spell:${Number(ev.spell_id) || 0}`;
            const cur = fallback.get(key) || {
              key, spell_id: ev.root_spell_id || ev.spell_id,
              name: ev.spell || String(ev.spell_id), count: 0,
              kinds: [], geometry: ev.geometry || null,
            };
            cur.count++;
            if (!cur.kinds.includes(ev.kind)) cur.kinds.push(ev.kind);
            fallback.set(key, cur);
          }
          mechanics = [...fallback.values()].sort((a, b) => b.count - a.count);
        }
        dpop._mechanics = mechanics;
        const shapeLabel = { circle: '원형', donut: '도넛형', cone: '부채꼴', line: '직선', target: '대상', global: '전장 전체' };
        dpop.innerHTML = mechanics.length
          ? `<div class="rc-mechanic-all">
              <button type="button" data-mall="on">전체 켜기</button>
              <button type="button" data-mall="off">전체 끄기</button>
            </div>` + mechanics.map((v, i) => {
              const g = v.geometry || {};
              const size = Number(g.radius || g.length) || 0;
              const geo = shapeLabel[g.shape] ? ` · ${shapeLabel[g.shape]}${size ? ` ${size}m` : ''}` : '';
              const type = v.guide?.type || (v.types || []).join(' · ') || (v.kinds || []).join('/');
              const guide = v.guide?.url
                ? `<a href="${esc(v.guide.url)}" target="_blank" rel="noopener" title="Mythic Trap 신화 공략 열기">공략</a>` : '';
              return `<label class="rc-mechanic-row" data-mi="${i}">
                <input type="checkbox" data-mkey="${esc(v.key)}" ${rcMechanicOff.has(v.key) ? '' : 'checked'}>
                <img src="/api/spell-icon/${Number(v.spell_id) || 0}.png" alt="" loading="lazy" onerror="this.classList.add('missing')">
                <span class="rc-mechanic-copy"><b>${esc(v.name)}</b><small>${esc(type)}${geo}</small></span>
                ${guide}<span class="n">${Number(v.count) || 0}</span>
              </label>`;
            }).join('')
          : '<div class="empty">추적할 보스 기믹 없음</div>';
        rcPlaceMechanicPop(dbtn, dpop);
        dpop.querySelectorAll('input[data-mkey]').forEach(cb => cb.addEventListener('change', () => {
          const key = cb.dataset.mkey;
          if (cb.checked) rcMechanicOff.delete(key); else rcMechanicOff.add(key);
          dbtn.classList.toggle('filtered', rcMechanicOff.size > 0);
          rcApplyMechanicFilter();
        }));
        dpop.querySelectorAll('button[data-mall]').forEach(btn => btn.addEventListener('click', () => {
          const on = btn.dataset.mall === 'on';
          rcMechanicOff.clear();
          if (!on) for (const v of mechanics) rcMechanicOff.add(v.key);
          dpop.querySelectorAll('input[data-mkey]').forEach(cb => { cb.checked = on; });
          dbtn.classList.toggle('filtered', rcMechanicOff.size > 0);
          rcApplyMechanicFilter();
        }));
        dpop.querySelectorAll('a').forEach(a => a.addEventListener('click', e => {
          e.preventDefault(); e.stopPropagation();
          window.open(a.href, '_blank', 'noopener');
        }));
      });
      dpop.addEventListener('mouseover', e => {
        const row = e.target.closest('.rc-mechanic-row[data-mi]');
        if (!row || row === rcTip.anchor) return;
        const mechanic = dpop._mechanics?.[Number(row.dataset.mi)];
        if (mechanic) rcShowTip(rcTipInfoFromMechanic(mechanic), row);
      });
      dpop.addEventListener('mouseout', e => {
        const row = e.target.closest('.rc-mechanic-row[data-mi]');
        if (row && !row.contains(e.relatedTarget)) rcHideTip();
      });
      document.addEventListener('click', e => {
        if (!dpop.hidden && !dpop.contains(e.target) && !dbtn.contains(e.target)) dpop.hidden = true;
      });
    }
  }
  // initReplayCanvas 가 rc 상태(t·meta)를 리셋한 뒤에 캐시를 만들어야
  // 직전 리플레이 시각 기준의 엉뚱한 하이라이트/스크롤이 안 생긴다
  initReplayCanvas(cap.id || replayState.selectedId);
  rcRebuildEvCache();
}

// ── 캔버스 리플레이 (전투로그 좌표 재생: /api/replay/{id}/frames) ────────
const CLASS_COLORS = {
  deathknight: '#C41E3A', demonhunter: '#A330C9', druid: '#FF7C0A',
  evoker: '#33937F', hunter: '#AAD372', mage: '#3FC7EB', monk: '#00FF98',
  paladin: '#F48CBA', priest: '#FFFFFF', rogue: '#FFF468', shaman: '#0070DD',
  warlock: '#8788EE', warrior: '#C69B6D',
};
const RC_TRAIL_S = 3;      // 궤적 잔상 길이(초)
const RC_STALE_S = 15;     // 이 시간 넘게 샘플 없으면 점 숨김
const RC_RING_S = 3;       // 보스 기믹: 순간형(end 없음) 대상 링 표시 시간(초)
const RC_BANNER_S = 4;     // 보스 기믹: 상단 자막 유지 시간(초)
const RC_RING_MAX = 40;    // 대상 링 동시 표시 상한 — 기간형(end 있음) 우선
                           // (20인 디버프 웨이브가 겹치는 구간까지 커버 — 16이면 일부 잘림)
const RC_RING_FADE_S = 0.5; // 기간형 링: 풀리기 직전 페이드아웃 시간(초)
const RC_EV_WINDOW_S = 120; // 기간형 검색 창(초) 기본값 — 실제 창은 rc.evWindow
                            // (최장 지속 기믹에 맞춰 로드 시 확장 — 장기 디버프가
                            //  120초 지나며 뚝 끊기는 것 방지)

const rc = {
  token: 0,       // 리플레이 재선택 시 이전 비동기 로드 무효화
  raf: 0,
  playing: false,
  speed: 1,
  t: 0,
  lastTs: 0,
  duration: 0,
  meta: null,     // frames 응답 meta
  tracks: {},     // unitId → [[t, wx, wy, facing, hp], ...] (t 오름차순, hp 는 %/null)
  deathsBy: {},   // unitId → [t, ...]
  mapImg: null,
  mode: {},       // unitId → 0 보통 / 1 강조 / 2 숨김
  bossEvents: [], // frames 응답 boss_events (t 오름차순, 전투 시작 기준)
  bossMechanics: [], // 대표 기술별 이름·설명·아이콘·공략 메타
  mechanicByKey: {}, // mechanic_key → bossMechanics 항목
  playerEvents: [], // frames 응답 player_events (t 오름차순 — 블러드/물약/쿨기류)
  peByUnit: {},   // unitId → player_events 배열 (t 오름차순, 패널 강조용)
  casts: {},      // frames 응답 casts — unitId → [[t, 스킬이름], ...] (t 오름차순)
  crystalHolds: [], // frames 응답 crystal_holds — [{u, s, e}] 여명의 수정 보유 구간
  selectedUnit: null, // 3D 에서 클릭으로 선택한 unitId (정보 패널 대상)
  video: null,    // 영상 있는 풀이면 <video> — 재생/탐색/배속 동기화 대상
  videoOffset: 0, // meta.video_offset_s (영상 t − 이 값 = 캔버스 t)
  is3d: false,    // 3D 보기 모드 — rcDraw 가 replay3d.js 로 위임 (시계·재생은 공유)
  replayId: null, // 현재 리플레이 id — 3D 지형 요청(/terrain)에 사용
};

function rcClock(sec) {
  const v = Math.max(0, Number(sec) || 0);
  return `${Math.floor(v / 60)}:${String(Math.floor(v % 60)).padStart(2, '0')}`;
}

function rcSpaceAt(sec = rc.t) {
  const spaces = rc.meta?.map?.spaces || [];
  const t = Math.max(0, Number(sec) || 0);
  return spaces.find((space, index) => {
    const start = Number(space.start_t) || 0;
    const end = Number(space.end_t) || 0;
    return t >= start && (t < end || (index === spaces.length - 1 && t <= end));
  }) || null;
}

function rcUpdateSpace() {
  const node = $('#rc-space');
  if (!node) return;
  const space = rcSpaceAt();
  node.textContent = space?.label || '';
  node.dataset.space = space?.key || '';
  node.title = space ? (rc.meta?.map?.space_note || space.label) : '';
}

function rcUnitColor(u) {
  if (u.kind === 'boss') return '#e06c6c';
  if (u.kind === 'npc') return '#8a93a3';
  return CLASS_COLORS[u.cls] || '#7db7ff';
}

async function initReplayCanvas(replayId) {
  const token = ++rc.token;
  rc.video = null;  // 이전 풀 영상 참조 해제 (rcPause 가 옛 영상 건드리지 않게)
  rcPause();
  rc.meta = null; rc.tracks = {}; rc.deathsBy = {}; rc.mapImg = null;
  rc.mode = {}; rc.t = 0; rc.speed = 1; rc.duration = 0;
  rc.bossEvents = []; rc.bossMechanics = []; rc.mechanicByKey = {}; rc.videoOffset = 0;
  rc.playerEvents = []; rc.peByUnit = {};
  rc.casts = {}; rc.crystalHolds = []; rc.selectedUnit = null;
  rc.is3d = false; rc.replayId = replayId;   // 리플레이 바꾸면 2D 부터 (3D 씬은 폐기)
  if (window.Replay3D) window.Replay3D.reset();
  rcHideTip();   // 직전 리플레이 목록에 떠 있던 툴팁 제거
  const msg = $('#rc-msg');
  if (!msg || !replayId) return;
  msg.style.display = '';
  msg.textContent = '이동 경로 데이터 로딩…';
  let j = null;
  try {
    const r = await fetch(`/api/replay/${encodeURIComponent(replayId)}/frames`);
    if (!r.ok) {
      let why = `HTTP ${r.status}`;
      try { const e = await r.json(); if (e.detail) why = e.detail; } catch (_) {}
      throw new Error(why);
    }
    j = await r.json();
  } catch (e) {
    if (token === rc.token && $('#rc-msg')) {
      // textContent 라 HTML 이스케이프 불필요
      $('#rc-msg').textContent = `이동 경로를 불러오지 못했습니다 — ${e.message || e}`;
      // 통합 피드 재료(frames)가 없으니 원본 이벤트 목록으로 폴백
      rcSetFeedEnabled(false, '이동 경로 데이터가 없어 종류별 목록을 쓸 수 없습니다');
      renderReplayEventRowsRaw();
      rcRestoreVideoControls();   // 통합 조작줄이 못 움직이니 영상 기본 조작 복원
      renderReplayFocus(null, false);
    }
    return;
  }
  if (token !== rc.token) return;

  const meta = j.meta || {};
  const frames = j.frames || [];
  const frameCounts = j.counts || {};
  for (const key of ['casts', 'debuffs', 'damage', 'deaths']) {
    const node = $(`#rc-count-${key}`);
    if (node) node.textContent = Number(frameCounts[key] || 0).toLocaleString();
  }
  if (!frames.length) {
    renderReplayFocus(j.review_focus, false);
    msg.textContent = '이 전투에는 좌표 데이터가 없습니다 (고급 전투 정보 로그 필요)';
    rcSetFeedEnabled(false, '좌표 데이터가 없어 종류별 목록을 쓸 수 없습니다');
    renderReplayEventRowsRaw();
    rcRestoreVideoControls();   // 통합 조작줄이 못 움직이니 영상 기본 조작 복원
    return;
  }
  let pointCount = 0;
  for (const fr of frames) {
    const ft = Number(fr.t || 0);
    for (const [uid, p] of Object.entries(fr.p || {})) {
      pointCount++;
      (rc.tracks[uid] ??= []).push([ft, p[0], p[1], p[2], p[3] ?? null]);
    }
  }
  for (const d of meta.deaths || []) (rc.deathsBy[d.id] ??= []).push(d.t);
  rc.meta = meta;
  renderReplayFocus(j.review_focus, true);
  rc.duration = Math.max(Number(meta.duration_s) || 0, frames[frames.length - 1].t);
  rc.bossEvents = j.boss_events || [];
  rc.bossMechanics = j.boss_mechanics || [];
  rc.mechanicByKey = Object.fromEntries(rc.bossMechanics.map(v => [v.key, v]));
  rcMechanicOff.clear();
  document.getElementById('rc-mechanic-btn')?.classList.remove('filtered');
  // 기간형 검색 창 = 최장 지속 기믹 + 여유 — 장기 디버프도 끝까지 링·패널 유지
  let maxDur = 0;
  for (const ev of rc.bossEvents) {
    if (ev.end != null) maxDur = Math.max(maxDur, Number(ev.end) - Number(ev.t));
  }
  rc.evWindow = Math.max(RC_EV_WINDOW_S, maxDur + RC_BANNER_S);
  rc.playerEvents = j.player_events || [];
  rc.peByUnit = {};
  for (const pe of rc.playerEvents) {
    if (pe.unit_id) (rc.peByUnit[pe.unit_id] ??= []).push(pe);
  }
  rc.casts = j.casts || {};
  rc.crystalHolds = j.crystal_holds || [];
  rc.videoOffset = Number(meta.video_offset_s) || 0;
  rc.video = $('#replay-video');  // 영상 없는 풀(아카이브 등)은 null → 자립 시계
  const eventCount = rc.bossEvents.length + rc.playerEvents.length + (meta.deaths || []).length;
  const kpiEvents = $('#rc-kpi-events');
  const kpiPositions = $('#rc-kpi-positions');
  const kpiUnits = $('#rc-kpi-units');
  if (kpiEvents) kpiEvents.textContent = eventCount.toLocaleString();
  if (kpiPositions) kpiPositions.textContent = pointCount.toLocaleString();
  if (kpiUnits) kpiUnits.textContent = (meta.units || []).length.toLocaleString();

  const map = meta.map || {};
  const cv = $('#rc-canvas');
  if (cv) { cv.width = map.px_w || 1000; cv.height = map.px_h || 660; }

  // 맵 이미지 (실패해도 어두운 배경 위에 점만 표시)
  const notes = [];
  if (map.space_note) notes.push(map.space_note);
  if (map.error) {
    // 서버가 실패 사유를 줬으면 PNG 요청 자체를 생략 (네거티브 캐시와 짝)
    notes.push(`맵 이미지를 못 받아 임시 좌표계로 표시 (${map.error})`);
  } else {
    await new Promise(resolve => {
      const img = new Image();
      img.onload = () => { if (token === rc.token) rc.mapImg = img; resolve(); };
      img.onerror = () => {
        notes.push('맵 이미지를 불러오지 못해 배경 없이 표시합니다');
        resolve();
      };
      img.src = `/api/replay/map/${Number(map.ui_map_id) || 0}.png`;
    });
  }
  if (token !== rc.token) return;

  // 실반경 원·수정 보유 범례 — 해당 데이터가 있는 전투에서만
  const circleSpells = [...new Set(rc.bossEvents
    .filter(e => e.geometry?.shape === 'circle' && Number(e.geometry.radius))
    .map(e => `${e.spell} ${e.geometry.radius}m${e.geometry.confidence === 'estimated' ? '(추정)' : ''}`))];
  if (circleSpells.length) notes.push(`실반경 원: ${circleSpells.slice(0, 4).join(', ')} — 겹치면 빨강`);
  if (rc.crystalHolds.length) notes.push('◆ 금색 이름 = 여명의 수정 보유');

  msg.style.display = 'none';
  const note = $('#rc-note');
  if (note) note.textContent = notes.join(' · ');
  rcBuildControls();
  rcBindVideo();
  rcSetFeedEnabled(true);
  renderReplayEventRows();
  rcSyncControls();
  rcDraw();
  // 기본은 3D — 실패하면(three.js 로드 불가 등) 그대로 2D 유지.
  // '2D 보기'를 누르면 이 리플레이에선 다시 자동 전환하지 않음 (자동 진입은 로드 때 한 번뿐).
  if (window.Replay3D) rcToggle3D();
}

// frames(좌표) 없는 풀 폴백 — 통합 조작줄은 rc.meta 가 없으면 못 움직이므로
// 영상이 있으면 브라우저 기본 컨트롤을 되살려 재생·소리를 잃지 않게 한다.
function rcRestoreVideoControls() {
  const v = $('#replay-video');
  if (v) v.controls = true;
  // 통합 조작줄은 frames 가 있어야 동작 — 죽은 버튼·스크럽을 노출하지 않는다
  const controls = document.querySelector('.rc-controls');
  if (controls) controls.style.display = 'none';
}

// 영상 ↔ 캔버스 재생 동기화 (영상이 시계 역할, 캔버스가 따라감)
function rcBindVideo() {
  const v = rc.video;
  if (!v) return;
  rc.speed = v.playbackRate || 1;
  const speedBtn = $('#rc-speed');
  if (speedBtn) speedBtn.textContent = `${rc.speed}x`;
  v.addEventListener('play', () => { if (!rc.playing) rcPlay(); });
  v.addEventListener('pause', () => { if (rc.playing) rcPause(); });
  v.addEventListener('seeked', rcSetFromVideo);
  v.addEventListener('ratechange', () => {
    rc.speed = v.playbackRate || 1;
    if (speedBtn) speedBtn.textContent = `${rc.speed}x`;
  });
  if (v.readyState >= 1) rcExtendTimelineToVideo();
  else v.addEventListener('loadedmetadata', rcExtendTimelineToVideo, { once: true });
  rcSetFromVideo();
  if (!v.paused) rcPlay();  // 프레임 로딩 전에 이미 재생 중이면 이어붙기
}

// 영상이 전투보다 길면 타임라인을 영상 끝까지 확장 — 유일한 타임라인이 된 만큼
// 전투 종료 후(킬 장면 등) 영상 구간도 탐색·시계 표시가 가능해야 한다
function rcExtendTimelineToVideo() {
  const v = rc.video;
  if (!v || !rc.meta) return;
  const vd = Number(v.duration);
  if (!isFinite(vd) || vd <= 0) return;
  const full = vd - rc.videoOffset;
  if (full <= rc.duration + 0.5) return;
  rc.duration = full;
  const scrub = $('#rc-scrub');
  if (scrub) scrub.max = String(full);
  const dur = Math.max(1, full);
  document.querySelectorAll('#rc-deaths i').forEach(el => {
    el.style.left = `${(Number(el.dataset.t) / dur * 100).toFixed(2)}%`;
  });
  document.querySelectorAll('#rc-bossevents i[data-bi]').forEach(el => {
    const ev = rc.bossEvents[Number(el.dataset.bi)];
    if (ev) el.style.left = `${(Number(ev.t) / dur * 100).toFixed(2)}%`;
  });
  rcSyncControls();
}

// 영상 현재 시각 → 캔버스 시각 (영상 쪽 탐색/재생 반영, 영상은 안 건드림)
function rcSetFromVideo() {
  if (!rc.video || !rc.meta) return;
  rc.t = Math.min(Math.max(0, rc.video.currentTime - rc.videoOffset), rc.duration);
  rcSyncControls();
  rcDraw();
}

function rcBuildControls() {
  const scrub = $('#rc-scrub');
  if (scrub) {
    scrub.max = String(rc.duration);
    scrub.value = '0';
    scrub.addEventListener('input', () => rcSeek(scrub.value));
  }
  const deaths = $('#rc-deaths');
  if (deaths) {
    // 스크럽 마커도 쫄몹 죽음 제외 (플레이어·보스만). data-t 는 타임라인 확장 시 재배치용
    deaths.innerHTML = (rc.meta.deaths || []).filter(d => !String(d.id).startsWith('n')).map(d =>
      `<i data-t="${Number(d.t) || 0}" style="left:${(Number(d.t) / Math.max(1, rc.duration) * 100).toFixed(2)}%" title="${rcClock(d.t)} 사망"></i>`
    ).join('');
  }
  // 보스 기믹 트랙 — 캐스트/디버프/실제 적중을 색으로 구분한다.
  const bossTrack = $('#rc-bossevents');
  if (bossTrack) {
    const dur = Math.max(1, rc.duration);
    bossTrack.innerHTML = rc.bossEvents.map((ev, i) => {
      const cls = `${ev.kind || 'cast'}${ev.priority ? ' prio' : ''}`;
      return `<i class="${cls}" data-bi="${i}" data-sid="${Number(ev.root_spell_id || ev.spell_id) || 0}" data-mkey="${esc(ev.mechanic_key || '')}" style="left:${(Number(ev.t) / dur * 100).toFixed(2)}%"></i>`;
    }).join('');
    bossTrack.addEventListener('click', e => {
      const el = e.target.closest('i[data-bi]');
      if (!el) return;
      const ev = rc.bossEvents[Number(el.dataset.bi)];
      if (ev) rcSeek(ev.t);
    });
    // 눈금에 마우스 올리면 스킬 툴팁 (피드 행과 같은 모양)
    bossTrack.addEventListener('mouseover', e => {
      const el = e.target.closest('i[data-bi]');
      if (!el || el === rcTip.anchor) return;
      const ev = rc.bossEvents[Number(el.dataset.bi)];
      if (!ev) return;
      const mechanic = rcMechanicMeta(ev.mechanic_key) || {};
      rcShowTip({
        sid: Number(mechanic.spell_id || ev.root_spell_id || ev.spell_id) || 0,
        name: mechanic.name || ev.spell || '', mkey: ev.mechanic_key || '',
        kind: rcTipKindLabel('boss', ev.kind),
        dur: ev.end != null ? Math.round(Number(ev.end) - Number(ev.t)) : 0,
        shape: ev.geometry?.shape || '', radius: Number(ev.geometry?.radius || ev.geometry?.length) || 0,
        maxStacks: Number(ev.max_stacks) || 0,
        dest: ev.dest_name ? String(ev.dest_name).split('-')[0] : '',
        src: ev.src_name ? String(ev.src_name).split('-')[0] : '',
        desc: mechanic.desc || '', roleNotes: mechanic.role_notes || [],
        roles: mechanic.roles || [], guide: mechanic.guide || {},
        sources: mechanic.sources || [],
      }, el);
    });
    bossTrack.addEventListener('mouseout', e => {
      const el = e.target.closest('i[data-bi]');
      if (el && el !== e.relatedTarget) rcHideTip();
    });
  }
  const play = $('#rc-play');
  if (play) play.addEventListener('click', () => { rc.playing ? rcPause() : rcPlay(); });
  const speed = $('#rc-speed');
  if (speed) {
    speed.addEventListener('click', () => {
      rc.speed = rc.speed >= 4 ? 1 : rc.speed * 2;
      speed.textContent = `${rc.speed}x`;
      if (rc.video) rc.video.playbackRate = rc.speed;  // 배속도 영상과 동기
    });
  }
  const btn3d = $('#rc-3d');
  if (btn3d) {
    btn3d.disabled = !window.Replay3D;   // replay3d.js 로드 실패 시 비활성
    btn3d.addEventListener('click', rcToggle3D);
  }
  const unitsRoot = $('#rc-units');
  if (unitsRoot) {
    const chip = u => {
      const label = u.kind === 'boss' ? `★ ${u.name}` : (String(u.name || u.id).split('-')[0] || u.id);
      return `<button type="button" class="rc-unit rc-${esc(u.kind)}" data-uid="${esc(u.id)}"
        style="--uc:${rcUnitColor(u)}" title="클릭: 강조 → 숨김 → 해제"><i></i>${esc(label)}</button>`;
    };
    // 쫄몹(npc)은 수십 개 늘어설 수 있어 '쫄몹 N' 칩 하나로 접어두고 클릭 시 펼침
    const allUnits = rc.meta.units || [];
    const npcs = allUnits.filter(u => u.kind === 'npc');
    unitsRoot.classList.remove('npc-open');
    unitsRoot.innerHTML = allUnits.filter(u => u.kind !== 'npc').map(chip).join('')
      + (npcs.length
        ? `<button type="button" class="rc-unit rc-npc-toggle" title="쫄몹 목록 펴기/접기">쫄몹 ${npcs.length} ▸</button>`
          + npcs.map(chip).join('')
        : '');
    // 접힌 그룹 칩에 강조·숨김 중인 쫄 수 표시 — 접어도 상태 단서가 남게
    const npcToggleLabel = (open) => {
      const hl = npcs.filter(u => rc.mode[u.id] === 1).length;
      const off = npcs.filter(u => rc.mode[u.id] === 2).length;
      const badge = (hl ? ` · 강조 ${hl}` : '') + (off ? ` · 숨김 ${off}` : '');
      return `쫄몹 ${npcs.length}${badge} ${open ? '▾' : '▸'}`;
    };
    unitsRoot.addEventListener('click', e => {
      const tg = e.target.closest('.rc-npc-toggle');
      if (tg) {
        const open = unitsRoot.classList.toggle('npc-open');
        tg.textContent = npcToggleLabel(open);
        return;
      }
      const btn = e.target.closest('.rc-unit');
      if (!btn) return;
      const uid = btn.dataset.uid;
      rc.mode[uid] = ((rc.mode[uid] || 0) + 1) % 3;
      btn.classList.toggle('hl', rc.mode[uid] === 1);
      btn.classList.toggle('off', rc.mode[uid] === 2);
      const ntg = unitsRoot.querySelector('.rc-npc-toggle');
      if (ntg) ntg.textContent = npcToggleLabel(unitsRoot.classList.contains('npc-open'));
      rcDraw();
    });
  }
}

function rcPlay() {
  if (!rc.meta || rc.playing) return;
  if (!rc.video && rc.t >= rc.duration - 0.05) rc.t = 0;   // 끝에서 재생 → 처음부터
  rc.playing = true;
  rc.lastTs = 0;
  const btn = $('#rc-play');
  if (btn) btn.textContent = '일시정지';
  // 영상 있는 풀은 영상도 같이 재생 (이미 재생 중이면 no-op → 루프 없음)
  if (rc.video && rc.video.paused) rc.video.play().catch(() => {});
  rc.raf = requestAnimationFrame(rcStep);
}

function rcPause() {
  rc.playing = false;
  if (rc.raf) cancelAnimationFrame(rc.raf);
  rc.raf = 0;
  const btn = $('#rc-play');
  if (btn) btn.textContent = '재생';
  if (rc.video && !rc.video.paused) rc.video.pause();
}

function rcStep(ts) {
  if (!rc.playing) return;
  if (rc.video) {
    // 영상이 시계 — 탐색/배속/버퍼링이 전부 자동 반영
    rc.t = Math.min(Math.max(0, rc.video.currentTime - rc.videoOffset), rc.duration);
  } else {
    if (rc.lastTs) rc.t = Math.min(rc.duration, rc.t + (ts - rc.lastTs) / 1000 * rc.speed);
    rc.lastTs = ts;
  }
  rcSyncControls();
  rcDraw();
  // 자립 시계만 끝에서 정지 — 영상은 영상 pause/ended 이벤트가 처리
  if (!rc.video && rc.t >= rc.duration) { rcPause(); return; }
  rc.raf = requestAnimationFrame(rcStep);
}

function rcSeek(t) {
  if (!rc.meta) return;
  rc.t = Math.min(Math.max(0, Number(t) || 0), rc.duration);
  if (rc.video) {
    // 캔버스 쪽 탐색 → 영상도 이동 (같은 값이면 건너뜀 → seeked 루프 방지)
    const vt = rc.t + rc.videoOffset;
    if (Math.abs(rc.video.currentTime - vt) > 0.2) rc.video.currentTime = vt;
  }
  rcSyncControls();
  rcDraw();
}

function rcSyncControls() {
  const scrub = $('#rc-scrub');
  if (scrub) scrub.value = String(rc.t);
  const clock = $('#rc-clock');
  if (clock) clock.textContent = `${rcClock(rc.t)} / ${rcClock(rc.duration)}`;
  rcUpdateSpace();
  rcUpdateEvNow();
  rcUpdatePanel();
}

// 2D/3D 전환 — 3D 는 replay3d.js(three.js)가 그림. 시계·재생·스크럽·기믹은 공유.
async function rcToggle3D() {
  const btn = $('#rc-3d');
  if (!btn || !rc.meta || !window.Replay3D) return;
  const cv = $('#rc-canvas');
  if (rc.is3d) {
    rc.is3d = false;
    btn.textContent = '3D 보기';
    window.Replay3D.hide();
    if (cv) cv.style.display = '';
    rcUpdatePanel();   // 정보 패널은 3D 전용 — 2D 로 오면 숨김
    rcDraw();
    return;
  }
  const token = rc.token;
  const msg = $('#rc-msg');
  btn.disabled = true;
  if (msg) { msg.style.display = ''; msg.textContent = '3D 화면 준비 중… (처음엔 지형을 내려받아서 잠깐 걸려요)'; }
  let ok = false;
  try { ok = await window.Replay3D.enter(); } catch (_) { ok = false; }
  if (token !== rc.token) return;   // 기다리는 동안 다른 리플레이 선택됨
  btn.disabled = false;
  if (msg) msg.style.display = 'none';
  if (!ok) return;                  // 실패 사유는 rc-note 에 표시됨
  rc.is3d = true;
  btn.textContent = '2D 보기';
  if (cv) cv.style.display = 'none';
  rcUpdatePanel();   // 선택이 남아 있으면 패널 다시 표시
  rcDraw();
}

// track 에서 시각 t 의 보간 위치 — {x, y, facing, age, srcT} | null
function rcTrackAt(track, t) {
  if (!track || !track.length || track[0][0] > t) return null;
  let lo = 0, hi = track.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (track[mid][0] <= t) lo = mid; else hi = mid - 1;
  }
  const prev = track[lo];
  const next = track[lo + 1];
  let x = prev[1], y = prev[2];
  if (next && next[0] > prev[0] && next[0] - prev[0] <= 2.5) {
    const u = Math.min(1, (t - prev[0]) / (next[0] - prev[0]));
    x += (next[1] - x) * u;
    y += (next[2] - y) * u;
  }
  return { x, y, facing: prev[3], age: t - prev[0], srcT: prev[0], idx: lo };
}

// 정렬 배열에서 "t 이하 마지막" 인덱스 (이진탐색, 없으면 -1)
function rcUpperIdx(arr, t, getT) {
  let lo = -1, hi = arr.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (getT(arr[mid]) <= t) lo = mid; else hi = mid - 1;
  }
  return lo;
}

// 시각 t 에 죽어 있는지 — 마지막 죽음 이후 새 좌표 샘플 없음 = 사망 (rcDraw 와 같은 판정)
function rcDeadAt(uid, t) {
  let last = -1;
  for (const dt of rc.deathsBy[uid] || []) if (dt <= t && dt > last) last = dt;
  if (last < 0) return false;
  const cur = rcTrackAt(rc.tracks[uid], t);
  return !cur || cur.srcT <= last;
}

// 시각 t 의 체력% — 트랙 s[4] 보간, 근처 샘플에 값이 없으면 null (체력 정보 없음)
function rcHpAt(track, t) {
  const cur = rcTrackAt(track, t);
  if (!cur) return null;
  let i = cur.idx;
  for (let n = 0; i >= 0 && track[i][4] == null && n < 30; n++) i--;
  if (i < 0 || track[i][4] == null) return null;
  const prev = track[i];
  let hp = Number(prev[4]);
  const next = track[i + 1];
  if (next && next[4] != null && next[0] > prev[0] && next[0] - prev[0] <= 2.5) {
    hp += (Number(next[4]) - hp) * Math.min(1, Math.max(0, (t - prev[0]) / (next[0] - prev[0])));
  }
  return Math.round(Math.min(100, Math.max(0, hp)));
}

// ── 이벤트 목록: 현재 시각 근처 행 자동 하이라이트 ──────────────────────
// 목록이 다시 그려질 때 행/시각 캐시를 만들어 두고, t 이동 때는 이진탐색만 한다.
let rcEvCache = { els: [], ts: [], idx: -1 };

function rcRebuildEvCache() {
  rcEvCache = { els: [], ts: [], idx: -1 };
  const box = $('#replay-events');
  if (!box) return;
  for (const el of box.querySelectorAll('[data-replay-jump]')) {
    rcEvCache.els.push(el);
    rcEvCache.ts.push(Number(el.dataset.replayJump || 0));   // 캡처(영상) 시각 기준
  }
  rcUpdateEvNow(true);
}

function rcUpdateEvNow(force) {
  const c = rcEvCache;
  if (!c.els.length || !rc.meta) return;
  const idx = rcUpperIdx(c.ts, rc.t + rc.videoOffset, v => v);
  if (idx === c.idx && !force) return;
  if (c.idx >= 0 && c.els[c.idx]) c.els[c.idx].classList.remove('now');
  c.idx = idx;
  if (idx < 0) return;
  const el = c.els[idx];
  el.classList.add('now');
  const box = $('#replay-events');
  if (box) {   // 목록 내부 스크롤만 살짝 — 페이지 스크롤은 안 건드림
    if (el.offsetTop < box.scrollTop + 6) box.scrollTop = el.offsetTop - 6;
    else if (el.offsetTop + el.offsetHeight > box.scrollTop + box.clientHeight - 6) {
      box.scrollTop = el.offsetTop + el.offsetHeight - box.clientHeight + 6;
    }
  }
}

// ── 스킬 툴팁 (피드 행·기믹 눈금에 마우스 올리면) ────────────────────────
// 아이콘/이름/종류/기간/대상·시전자는 바로, 설명(desc)은 150ms 뒤 lazy fetch.
const rcTip = { anchor: null, rect: null, key: '', timer: 0 };
const rcTipCache = new Map();   // spell_id → Promise<{name, desc}> (실패도 캐시 → 재요청 안 함)

// 피드 종류 → 쉬운 이름. 보스 이벤트는 세부 종류(bk)로 디버프/시전 구분.
function rcTipKindLabel(kind, bk) {
  if (kind === 'boss') return {
    hit: '보스 디버프', impact: '실제 적중', summon: '소환', cast: '보스 시전',
  }[bk] || '보스 기믹';
  const k = RC_FEED_KINDS.find(v => v.key === kind);
  return k ? k.label : '';
}

function rcTipInfoFromRow(row) {
  const d = row.dataset;
  const mechanic = rcMechanicMeta(d.mkey) || {};
  return {
    sid: Number(mechanic.spell_id || d.sid) || 0,
    name: mechanic.name || d.spell || '', mkey: d.mkey || '',
    kind: rcTipKindLabel(d.k, d.bk), dur: Number(d.dur) || 0,
    shape: d.shape || '', radius: Number(d.radius) || 0,
    maxStacks: Number(d.maxStacks) || 0,
    dest: d.dest || '', src: d.src || '',
    desc: mechanic.desc || '', roleNotes: mechanic.role_notes || [],
    roles: mechanic.roles || [], guide: mechanic.guide || {},
    sources: mechanic.sources || [],
  };
}

function rcTipInfoFromMechanic(mechanic) {
  const g = mechanic.geometry || {};
  return {
    sid: Number(mechanic.spell_id) || 0, name: mechanic.name || '',
    mkey: mechanic.key || '', kind: '보스 기믹',
    shape: g.shape || '', radius: Number(g.radius || g.length) || 0,
    desc: mechanic.desc || '', roleNotes: mechanic.role_notes || [],
    roles: mechanic.roles || [], guide: mechanic.guide || {},
    sources: mechanic.sources || [],
  };
}

function rcTipFetch(sid, name) {
  const encounterId = Number(rc.meta?.encounter_id) || 0;
  const cacheKey = `${sid}|${encounterId}`;
  let p = rcTipCache.get(cacheKey);
  if (!p) {
    const qs = new URLSearchParams();
    if (encounterId) qs.set('encounter_id', String(encounterId));
    if (name) qs.set('name', name);
    p = fetch(`/api/spell-tip/${sid}${qs.size ? `?${qs}` : ''}`)
      .then(r => (r.ok ? r.json() : {}))
      .catch(() => ({}));
    rcTipCache.set(cacheKey, p);
  }
  return p;
}

// 앵커(행/눈금) 근처에 고정 — 화면 밖으로 안 나가게. 마우스는 안 따라다님.
function rcPlaceTip() {
  const el = document.getElementById('rc-tip');
  const r = rcTip.rect;
  if (!el || !r) return;
  const w = el.offsetWidth, h = el.offsetHeight;
  const x = Math.min(Math.max(8, r.left), window.innerWidth - w - 8);
  let y = r.top - h - 8;
  if (y < 8) y = Math.min(r.bottom + 8, window.innerHeight - h - 8);
  y = Math.max(8, Math.min(y, window.innerHeight - h - 8));
  el.style.left = `${Math.round(x)}px`;
  el.style.top = `${Math.round(y)}px`;
}

function rcTipDetailsHtml(info) {
  const roleLabel = { tank: '방어 담당', healer: '치유 담당', damage: '공격 담당' };
  const roles = (info.roles || []).map(v => roleLabel[v] || v).filter(Boolean);
  const notes = (info.roleNotes || info.role_notes || []).filter(Boolean);
  const guide = info.guide || {};
  const sources = (info.sources || []).filter(Boolean);
  return `
    ${info.desc ? `<div class="rc-tip-desc">${esc(info.desc)}</div>` : ''}
    ${notes.length ? `<div class="rc-tip-note"><span>도감 주의</span>${notes.slice(0, 3).map(v => `<p>${esc(v)}</p>`).join('')}</div>` : ''}
    ${(guide.type || roles.length) ? `<div class="rc-tip-badges">${guide.type ? `<i>${esc(guide.type)}</i>` : ''}${roles.map(v => `<i>${esc(v)}</i>`).join('')}</div>` : ''}
    ${guide.url ? `<div class="rc-tip-guide">Mythic Trap 신화 공략에서 세부 처리 확인</div>` : ''}
    ${sources.length ? `<div class="rc-tip-sources">${esc(sources.join(' · '))}</div>` : ''}`;
}

function rcShowTip(info, anchorEl) {
  if (rcTip.timer) clearTimeout(rcTip.timer);
  rcTip.timer = 0;
  let el = document.getElementById('rc-tip');
  if (!el) {
    el = document.createElement('div');
    el.id = 'rc-tip';
    document.body.appendChild(el);
  }
  const key = `${info.sid}|${info.name}|${info.kind}`;
  rcTip.anchor = anchorEl;
  rcTip.rect = anchorEl.getBoundingClientRect();
  rcTip.key = key;
  const sub = [
    info.dur ? `${info.dur}초 동안` : '',
    info.shape ? `${({circle: '원형', donut: '도넛형', cone: '부채꼴', line: '직선', target: '대상', global: '전장 전체'}[info.shape] || info.shape)}${info.radius ? ` ${info.radius}m` : ''}` : '',
    info.maxStacks ? `최대 ${info.maxStacks}중첩` : '',
    info.dest ? `대상 ${info.dest}` : '',
    info.src ? `시전자 ${info.src}` : '',
  ].filter(Boolean).join(' · ');
  el.innerHTML = `
    <div class="rc-tip-head">
      <b>${esc(info.name)}</b><span class="k">${esc(info.kind)}</span>
    </div>
    ${sub ? `<div class="rc-tip-sub">${esc(sub)}</div>` : ''}
    <div class="rc-tip-body">${rcTipDetailsHtml(info)}</div>`;
  el.style.display = 'block';
  rcPlaceTip();
  if (info.sid) {
    // 아이콘도 설명처럼 150ms 뒤에 요청 — 피드를 마우스로 훑을 때
    // 미캐시 스펠 수만큼 요청이 쏟아지는 것 방지
    rcTip.timer = setTimeout(async () => {
      if (rcTip.key !== key) return;
      const head = el.querySelector('.rc-tip-head');
      if (head && !head.querySelector('img')) {
        const img = document.createElement('img');
        img.src = `/api/spell-icon/${info.sid}.png`;
        img.alt = '';
        img.onerror = () => { img.style.display = 'none'; };
        head.prepend(img);
      }
      const j = await rcTipFetch(info.sid, info.name);
      if (rcTip.key !== key) return;   // 기다리는 동안 다른 행으로 이동함
      const merged = {
        ...info,
        name: j.name || info.name,
        desc: info.desc || j.desc || '',
        roleNotes: (info.roleNotes || []).length ? info.roleNotes : (j.role_notes || []),
        roles: (info.roles || []).length ? info.roles : (j.roles || []),
        guide: Object.keys(info.guide || {}).length ? info.guide : (j.guide || {}),
        sources: (info.sources || []).length ? info.sources : (j.sources || []),
      };
      const title = el.querySelector('.rc-tip-head b');
      if (title) title.textContent = merged.name;
      const box = el.querySelector('.rc-tip-body');
      if (box) { box.innerHTML = rcTipDetailsHtml(merged); rcPlaceTip(); }
    }, 150);
  }
}

function rcHideTip() {
  if (rcTip.timer) clearTimeout(rcTip.timer);
  rcTip.timer = 0;
  rcTip.anchor = null; rcTip.rect = null; rcTip.key = '';
  const el = document.getElementById('rc-tip');
  if (el) { el.style.display = 'none'; el.innerHTML = ''; }
}

// ── 3D 선택 유닛 정보 패널 (이름·직업·체력·걸린 기믹·쓴 스킬) ────────────
const RC_CLASS_KR = {
  deathknight: '죽음의 기사', demonhunter: '악마사냥꾼', druid: '드루이드',
  evoker: '기원사', hunter: '사냥꾼', mage: '마법사', monk: '수도사',
  paladin: '성기사', priest: '사제', rogue: '도적', shaman: '주술사',
  warlock: '흑마법사', warrior: '전사',
};
const RC_PANEL_CASTS = 10;   // 쓴 스킬: 최근 10개

let rcPanelKey = '';   // 마지막으로 그린 패널 내용 키 — 같으면 DOM 재구성 생략

// '쓴 스킬' 한 줄이 player_events(쿨기/물약 등)에 잡힌 시전인지 — 종류 반환 (없으면 '')
// casts 와 player_events 는 같은 시전에서 나오므로 스킬명 + 시각(±1초)으로 짝을 찾는다.
// 외부생존기는 player_events 쪽 spell 에 "→대상"이 붙어 있어 prefix 비교.
function rcCastEventKind(uid, t, spell) {
  const arr = rc.peByUnit[uid];
  if (!arr || !spell) return '';
  let i = rcUpperIdx(arr, t + 1.0, pe => Number(pe.t));
  for (; i >= 0 && t - Number(arr[i].t) <= 1.0; i--) {
    const s = String(arr[i].spell || '');
    if (s === spell || s.startsWith(spell + '→')) return arr[i].kind || '';
  }
  return '';
}

function rcStacksAt(ev, t) {
  let stacks = 1;
  for (const update of ev.stack_events || []) {
    if (Number(update.t) > t) break;
    stacks = Math.max(1, Number(update.stacks) || stacks);
  }
  return stacks;
}

// '지금 걸린 보스 기믹' — uid 대상 중 시각 t 에 표시할 것 (오래된 것 위).
// 기간형(end 있음)은 활성(시작<=t<end)인 동안, 순간형은 발생 후 3초만.
// bossEvents 는 t 오름차순 → 이진탐색 + 최근 120초 창만 역방향 스캔 (전체 스캔 금지).
function rcActiveHitsFor(uid, t) {
  const evs = rc.bossEvents || [];
  const out = [];
  for (let i = rcUpperIdx(evs, t, e => Number(e.t)); i >= 0; i--) {
    const ev = evs[i];
    const age = t - Number(ev.t);
    if (age > (rc.evWindow || RC_EV_WINDOW_S)) break;
    if (ev.dest_id !== uid) continue;
    if (!rcMechanicShown(ev)) continue;
    if (ev.end != null) {
      if (t < Number(ev.end)) out.push({ ev, i, end: Number(ev.end) });
    } else if (age <= RC_RING_S) {
      out.push({ ev, i, end: null });
    }
  }
  out.reverse();
  return out;
}

// replay3d.js 픽킹이 부른다 — uid=null 이면 선택 해제
function rcSelectUnit(uid) {
  if (!rc.meta) return;
  rc.selectedUnit = uid || null;
  rcPanelKey = '';
  rcUpdatePanel();
  rcDraw();
}

function rcUpdatePanel() {
  const panel = $('#rc-panel');
  if (!panel) return;
  const uid = rc.selectedUnit;
  const u = (uid && rc.meta) ? (rc.meta.units || []).find(v => v.id === uid) : null;
  if (!u || !rc.is3d) {
    if (panel.style.display !== 'none') { panel.style.display = 'none'; panel.innerHTML = ''; }
    rcPanelKey = '';
    return;
  }
  panel.style.display = '';
  const t = rc.t;
  const dead = rcDeadAt(uid, t);
  const hp = dead ? 0 : rcHpAt(rc.tracks[uid], t);

  // 지금 걸린 기믹: 기간형은 활성인 것만, 순간형은 3초 (남은 시간은 아래에서 값만 갱신)
  const hits = rcActiveHitsFor(uid, t);
  // 쓴 스킬: t 이전 최근 10개 (오래된 것 위, 최신 아래) + 사망 시각을 빨간 줄로 삽입
  const castArr = rc.casts[uid] || [];
  const castEnd = rcUpperIdx(castArr, t, c => Number(c[0]));
  const castRows = castArr.slice(Math.max(0, castEnd - RC_PANEL_CASTS + 1), castEnd + 1)
    .map(c => ({ t: Number(c[0]), spell: String(c[1] || '') }));
  let deathCnt = 0;
  for (const dt of rc.deathsBy[uid] || []) {
    if (dt <= t) { castRows.push({ t: dt, death: true }); deathCnt++; }
  }
  castRows.sort((a, b) => a.t - b.t);
  const castList = castRows.slice(-RC_PANEL_CASTS);

  const key = [uid, dead ? 1 : 0,
    hits.map(h => `${h.i}:${rcStacksAt(h.ev, t)}`).join(','), castEnd, deathCnt].join('|');
  if (key !== rcPanelKey) {
    rcPanelKey = key;
    const name = String(u.name || u.id).split('-')[0];
    const clsKr = u.kind === 'boss' ? '보스'
      : (u.kind === 'npc' ? '몬스터' : (RC_CLASS_KR[u.cls] || ''));
    panel.innerHTML = `
      <div class="rc-panel-head">
        <span class="rc-panel-name" style="color:${rcUnitColor(u)}">${esc(name)}</span>
        <span class="rc-panel-cls">${esc(clsKr)}</span>
        <span class="rc-panel-state ${dead ? 'dead' : 'alive'}">${dead ? '사망' : '생존'}</span>
        <button type="button" class="rc-panel-close" title="선택 해제">×</button>
      </div>
      <div class="rc-panel-hpbar"><i></i></div>
      <div class="rc-panel-hptxt"></div>
      <div class="rc-panel-lists">
        <div class="rc-panel-sec">지금 걸린 보스 기믹</div>
        ${hits.map(h => {
            const stacks = rcStacksAt(h.ev, t);
            return `<div class="rc-panel-row ${h.ev.kind || ''}"><span class="s">${esc(h.ev.spell || '')}${h.ev.max_stacks ? ` ×${stacks}` : ''}</span>${h.end != null ? `<span class="rem" data-end="${h.end}"></span>` : ''}</div>`;
          }).join('')
          || '<div class="rc-panel-none">없음</div>'}
        <div class="rc-panel-sec">쓴 스킬 (최근 ${RC_PANEL_CASTS}개)</div>
        ${castList.map(c => {
          if (c.death) {
            return `<div class="rc-panel-row death"><span class="t">${rcClock(c.t)}</span><span class="s">💀 사망</span></div>`;
          }
          const pk = rcCastEventKind(uid, c.t, c.spell);
          return `<div class="rc-panel-row"><span class="t">${rcClock(c.t)}</span><span class="s${pk ? ` pk-${pk}` : ''}">${esc(c.spell)}</span></div>`;
        }).join('')
          || '<div class="rc-panel-none">없음</div>'}
      </div>`;
    const lists = panel.querySelector('.rc-panel-lists');
    if (lists) lists.scrollTop = lists.scrollHeight;   // 최신(아래)이 보이게
    const closeBtn = panel.querySelector('.rc-panel-close');
    if (closeBtn) closeBtn.addEventListener('click', () => rcSelectUnit(null));
  }
  // 체력바 — 값만 매번 갱신 (DOM 재구성 없이 폭/색/문구)
  const bar = panel.querySelector('.rc-panel-hpbar i');
  const txt = panel.querySelector('.rc-panel-hptxt');
  if (bar && txt) {
    if (hp == null && !dead) {
      bar.style.width = '0%';
      txt.textContent = '체력 정보 없음';
    } else {
      const v = dead ? 0 : hp;
      bar.style.width = `${v}%`;
      bar.style.background = v > 50 ? '#6fcf7f' : (v > 25 ? '#e2c14e' : '#e06c6c');
      txt.textContent = `체력 ${v}%`;
    }
  }
  // 기간형 기믹 남은 시간 — 체력바처럼 매 틱 값만 갱신 (DOM 재구성 없음)
  for (const el of panel.querySelectorAll('.rc-panel-row .rem')) {
    const s = `· ${Math.max(0, Math.ceil(Number(el.dataset.end) - t))}초 남음`;
    if (el.textContent !== s) el.textContent = s;
  }
}

// 시각 t 에 대상 링을 그릴 보스 기믹 목록 — 2D(rcDraw)/3D(replay3d.js) 공용 규칙.
// bossEvents 는 t 오름차순이지만 end 는 아님 → 이진탐색으로 t 이하 끝을 찾고
// 최근 RC_EV_WINDOW_S 창만 역방향 스캔해 비용 제한 (매 프레임 전체 스캔 금지).
// 기간형(end 있음): 걸린 동안 유지, 마지막 0.5초 페이드아웃 / 순간형: 기존 3초 페이드.
// 상한 RC_RING_MAX — 기간형 먼저 채움. fade 는 0~1 (그리는 쪽에서 투명도에 곱함).
function rcRingEventsAt(t) {
  const evs = rc.bossEvents || [];
  const durable = [], instant = [];
  for (let i = rcUpperIdx(evs, t, e => Number(e.t)); i >= 0; i--) {
    const ev = evs[i];
    const age = t - Number(ev.t);
    if (age > (rc.evWindow || RC_EV_WINDOW_S) || durable.length >= RC_RING_MAX) break;
    if (ev.geometry?.shape === 'global') continue;
    const anchorId = ev.geometry?.anchor === 'source' ? ev.src_id
      : (ev.geometry?.anchor === 'target' ? ev.dest_id : (ev.dest_id || ev.src_id));
    if (!anchorId || rc.mode[anchorId] === 2) continue;
    if (!rcMechanicShown(ev)) continue;
    if (ev.end != null) {
      const end = Number(ev.end);
      if (t < end) durable.push({ ev, anchorId, age, durable: true, fade: Math.min(1, (end - t) / RC_RING_FADE_S) });
    } else if (age <= RC_RING_S && instant.length < RC_RING_MAX) {
      instant.push({ ev, anchorId, age, durable: false, fade: 1 - age / RC_RING_S });
    }
  }
  const out = durable.concat(instant).slice(0, RC_RING_MAX);
  out.sort((a, b) => Number(a.ev.t) - Number(b.ev.t));   // 그리는 순서는 기존처럼 t 오름차순
  // 실반경 원 겹침 판정 (2D/3D 공용): 같은 기믹의 다른 대상이 서로의 폭발
  // 반경 안에 있으면 양쪽 다 danger — 그리는 쪽에서 빨강으로 강조한다.
  const circles = [];
  for (const it of out) {
    const g = it.ev.geometry;
    if (!it.durable || g?.shape !== 'circle' || !Number(g.radius)) continue;
    const pos = rcTrackAt(rc.tracks[it.anchorId], t);
    if (!pos || pos.age > RC_STALE_S) continue;
    circles.push([it, pos, Number(g.radius)]);
  }
  for (let a = 0; a < circles.length; a++) {
    for (let b = a + 1; b < circles.length; b++) {
      const [A, pa, ra] = circles[a], [B, pb, rb] = circles[b];
      if (A.ev.mechanic_key !== B.ev.mechanic_key || A.anchorId === B.anchorId) continue;
      if (Math.hypot(pa.x - pb.x, pa.y - pb.y) < Math.max(ra, rb)) A.danger = B.danger = true;
    }
  }
  return out;
}

// 시각 t 의 자막 대상 기믹 — 마지막 이벤트가 자막 창(4초) 안이면 그것 (이진탐색)
function rcBannerEventAt(t) {
  const evs = rc.bossEvents || [];
  for (let i = rcUpperIdx(evs, t, e => Number(e.t)); i >= 0; i--) {
    if (t - Number(evs[i].t) > RC_BANNER_S) break;
    if (rcMechanicShown(evs[i])) return evs[i];
  }
  return null;
}

// 상단 자막 1줄 — 최근 기믹 (textContent 라 esc 불필요)
function rcUpdateBanner(bannerEv) {
  const banner = $('#rc-banner');
  if (!banner) return;
  const txt = bannerEv
    ? `${rcClock(bannerEv.t)} ${bannerEv.spell || ''}${bannerEv.dest_name ? ' → ' + String(bannerEv.dest_name).split('-')[0] : ''}`
    : '';
  if (banner.textContent !== txt) banner.textContent = txt;
}

function rcDraw() {
  if (!rc.meta) return;
  // 3D 모드면 렌더러만 교체 — 유닛/기믹 로직은 replay3d.js 가 rc 를 읽어 처리
  if (rc.is3d && window.Replay3D && window.Replay3D.isReady()) {
    window.Replay3D.draw();
    rcUpdateBanner(rcBannerEventAt(rc.t));
    return;
  }
  const cv = $('#rc-canvas');
  if (!cv) return;
  const ctx = cv.getContext('2d');
  ctx.clearRect(0, 0, cv.width, cv.height);
  if (rc.mapImg) ctx.drawImage(rc.mapImg, 0, 0, cv.width, cv.height);
  else { ctx.fillStyle = '#10141a'; ctx.fillRect(0, 0, cv.width, cv.height); }
  if (rcSpaceAt()?.key === 'p2') {
    ctx.fillStyle = 'rgba(62, 34, 105, .20)';
    ctx.fillRect(0, 0, cv.width, cv.height);
  }

  const M = rc.meta.map.world_to_px;
  const toPx = (wx, wy) => [M.a * wx + M.b * wy + M.c, M.d * wx + M.e * wy + M.f];
  const t = rc.t;
  const anyHl = Object.values(rc.mode).includes(1);

  // 죽음 해골 마커 (죽은 자리에 고정) — 쫄몹은 제외 (지도가 해골로 뒤덮이지 않게)
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (const d of rc.meta.deaths || []) {
    if (String(d.id).startsWith('n')) continue;
    if (Number(d.t) > t || rc.mode[d.id] === 2) continue;
    const pos = rcTrackAt(rc.tracks[d.id], Number(d.t));
    if (!pos) continue;
    const [x, y] = toPx(pos.x, pos.y);
    ctx.globalAlpha = 0.92;
    ctx.font = 'bold 16px sans-serif';
    ctx.lineWidth = 3;
    ctx.strokeStyle = '#000';
    ctx.strokeText('☠', x, y);
    ctx.fillStyle = '#f0f0f0';
    ctx.fillText('☠', x, y);
  }

  for (const u of rc.meta.units || []) {
    if (rc.mode[u.id] === 2) continue;
    const track = rc.tracks[u.id];
    const cur = track ? rcTrackAt(track, t) : null;
    if (!cur) continue;
    // 샘플 끊김: 네임드는 마지막 위치에 계속 표시(살짝 흐리게), 나머지는 숨김
    const stale = cur.age > RC_STALE_S;
    if (stale && u.kind !== 'boss') continue;
    // 마지막 죽음 이후 새 샘플이 없으면 = 지금 죽어 있음 → 점 생략 (해골만)
    const dts = rc.deathsBy[u.id] || [];
    let lastDeath = -1;
    for (const dt of dts) if (dt <= t && dt > lastDeath) lastDeath = dt;
    if (lastDeath >= 0 && cur.srcT <= lastDeath) continue;

    const color = rcUnitColor(u);
    const hl = rc.mode[u.id] === 1;
    const baseA = (anyHl && !hl ? 0.25 : 1) * (stale ? 0.55 : 1);
    const [x, y] = toPx(cur.x, cur.y);

    // 궤적 잔상 (최근 3초 페이드)
    ctx.lineWidth = u.kind === 'boss' ? 3 : 2;
    ctx.strokeStyle = color;
    let prevPt = null;
    for (let i = Math.max(0, cur.idx - Math.ceil(RC_TRAIL_S * 2) - 1); i <= cur.idx; i++) {
      const s = track[i];
      if (s[0] < t - RC_TRAIL_S) continue;
      const p = toPx(s[1], s[2]);
      if (prevPt) {
        ctx.globalAlpha = baseA * 0.45 * Math.max(0, 1 - (t - s[0]) / RC_TRAIL_S);
        ctx.beginPath(); ctx.moveTo(prevPt[0], prevPt[1]); ctx.lineTo(p[0], p[1]); ctx.stroke();
      }
      prevPt = p;
    }
    if (prevPt && (prevPt[0] !== x || prevPt[1] !== y)) {
      ctx.globalAlpha = baseA * 0.45;
      ctx.beginPath(); ctx.moveTo(prevPt[0], prevPt[1]); ctx.lineTo(x, y); ctx.stroke();
    }

    const r = u.kind === 'boss' ? 11 : (u.kind === 'npc' ? 4 : 6.5);
    // 시선(facing) 짧은 선 — 월드 방향(cosθ, sinθ)을 같은 행렬로 회전
    ctx.globalAlpha = baseA;
    if (cur.facing != null) {
      const vx = M.a * Math.cos(cur.facing) + M.b * Math.sin(cur.facing);
      const vy = M.d * Math.cos(cur.facing) + M.e * Math.sin(cur.facing);
      const n = Math.hypot(vx, vy) || 1;
      const L = r + 9;
      ctx.lineWidth = 2;
      ctx.strokeStyle = color;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + vx / n * L, y + vy / n * L); ctx.stroke();
    }
    // 유닛 점
    ctx.beginPath();
    ctx.arc(x, y, hl ? r + 2 : r, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.lineWidth = hl ? 2.5 : 1.2;
    ctx.strokeStyle = hl ? '#ffffff' : 'rgba(255,255,255,.55)';
    ctx.stroke();
    // 여명의 수정 보유 — ◆ 배지 + 이름 금색 (보유 구간 내내)
    const holding = rc.crystalHolds.length > 0
      && rc.crystalHolds.some(h => h.u === u.id && t >= h.s && t < h.e);
    if (holding) {
      // 금색 이중 링 — 직업색 점과 확실히 구분되게 점 둘레를 감싼다
      ctx.beginPath();
      ctx.arc(x, y, r + 5, 0, Math.PI * 2);
      ctx.lineWidth = 3;
      ctx.strokeStyle = '#f5d76e';
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(x, y, r + 9, 0, Math.PI * 2);
      ctx.lineWidth = 1.2;
      ctx.strokeStyle = 'rgba(245, 215, 110, .55)';
      ctx.stroke();
      ctx.font = 'bold 13px sans-serif';
      ctx.lineWidth = 3;
      ctx.strokeStyle = '#10141a';
      ctx.strokeText('◆', x, y - r - 12);
      ctx.fillStyle = '#f5d76e';
      ctx.fillText('◆', x, y - r - 12);
    }
    // 이름: 보스는 항상, 강조 유닛·수정 보유자도
    if (u.kind === 'boss' || hl || holding) {
      const label = String(u.name || '').split('-')[0];
      const ly = y - r - (holding ? 26 : 10);
      ctx.font = 'bold 15px sans-serif';
      ctx.lineWidth = 3;
      ctx.strokeStyle = '#10141a';
      ctx.strokeText(label, x, ly);
      ctx.fillStyle = holding ? '#f5d76e' : '#f0f0f0';
      ctx.fillText(label, x, ly);
    }
  }

  // 보스 기믹: 대상 링 + 스킬명 라벨 — 기간형(end)은 걸린 동안 유지(은은한 맥동)
  // 후 0.5초 페이드아웃, 순간형은 기존 3초 페이드 (rcRingEventsAt 이 공용 규칙)
  const unitNameById = {};
  for (const u of rc.meta.units || []) unitNameById[u.id] = String(u.name || '').split('-')[0];
  for (const it of rcRingEventsAt(t)) {
    const ev = it.ev;
    const age = it.age;
    const pos = rcTrackAt(rc.tracks[it.anchorId], t);
    if (!pos || pos.age > RC_STALE_S) continue;
    const [x, y] = toPx(pos.x, pos.y);
    const color = it.danger ? '#ff5b5b'
      : ({ hit: '#b18cf0', impact: '#ef6b62', summon: '#4fc9b0' }[ev.kind] || '#e8a34c');
    const rr = it.durable
      ? 13 + 1.5 * Math.sin(age * Math.PI * 2 / 1.6)   // 은은한 맥동
      : 11 + age * 5;                                  // 링이 천천히 퍼지며 사라짐
    const geometry = ev.geometry || {};
    const shape = geometry.shape || 'target';
    const radius = Number(geometry.radius) || 0;
    const appendWorldPath = (points) => {
      points.forEach((point, i) => {
        const p = toPx(point[0], point[1]);
        if (i) ctx.lineTo(p[0], p[1]); else ctx.moveTo(p[0], p[1]);
      });
      ctx.closePath();
    };
    const worldPath = (points) => { ctx.beginPath(); appendWorldPath(points); };
    let drewArea = false;
    let fillRule = 'nonzero';
    if (shape === 'circle' && radius) {
      const points = [];
      for (let i = 0; i < 32; i++) {
        const a = i / 32 * Math.PI * 2;
        points.push([pos.x + Math.cos(a) * radius, pos.y + Math.sin(a) * radius]);
      }
      worldPath(points);
      drewArea = true;
    } else if (shape === 'donut' && radius && Number(geometry.inner_radius)) {
      const outer = [], inner = [];
      for (let i = 0; i < 32; i++) {
        const a = i / 32 * Math.PI * 2;
        outer.push([pos.x + Math.cos(a) * radius, pos.y + Math.sin(a) * radius]);
        inner.unshift([pos.x + Math.cos(a) * Number(geometry.inner_radius),
                      pos.y + Math.sin(a) * Number(geometry.inner_radius)]);
      }
      ctx.beginPath();
      appendWorldPath(outer);
      appendWorldPath(inner);
      fillRule = 'evenodd';
      drewArea = true;
    } else if (shape === 'cone' && radius) {
      let facing = pos.facing;
      const dest = ev.dest_id ? rcTrackAt(rc.tracks[ev.dest_id], t) : null;
      if (facing == null && dest) facing = Math.atan2(dest.y - pos.y, dest.x - pos.x);
      facing = facing == null ? 0 : facing;
      const half = (Number(geometry.angle) || 90) * Math.PI / 360;
      const points = [[pos.x, pos.y]];
      for (let i = 0; i <= 18; i++) {
        const a = facing - half + (half * 2 * i / 18);
        points.push([pos.x + Math.cos(a) * radius, pos.y + Math.sin(a) * radius]);
      }
      worldPath(points);
      drewArea = true;
    } else if (shape === 'line' && Number(geometry.length)) {
      const length = Number(geometry.length);
      const width = Number(geometry.width) || 4;
      let facing = pos.facing;
      const dest = ev.dest_id ? rcTrackAt(rc.tracks[ev.dest_id], t) : null;
      if (facing == null && dest) facing = Math.atan2(dest.y - pos.y, dest.x - pos.x);
      facing = facing == null ? 0 : facing;
      const fx = Math.cos(facing), fy = Math.sin(facing);
      const sx = -fy * width / 2, sy = fx * width / 2;
      worldPath([
        [pos.x + sx, pos.y + sy], [pos.x - sx, pos.y - sy],
        [pos.x + fx * length - sx, pos.y + fy * length - sy],
        [pos.x + fx * length + sx, pos.y + fy * length + sy],
      ]);
      drewArea = true;
    }
    ctx.lineWidth = it.danger ? 3.5 : (ev.priority ? 3 : 2);
    ctx.strokeStyle = color;
    if (drewArea) {
      ctx.globalAlpha = (it.danger ? 0.32 : 0.16) * it.fade;
      ctx.fillStyle = color;
      ctx.fill(fillRule);
      ctx.globalAlpha = 0.9 * it.fade;
    } else {
      ctx.globalAlpha = 0.9 * it.fade;
      ctx.beginPath();
      ctx.arc(x, y, rr, 0, Math.PI * 2);
    }
    ctx.stroke();
    const stacks = ev.max_stacks ? rcStacksAt(ev, t) : 0;
    const label = `${String(ev.spell || '')}${stacks ? ` ×${stacks}` : ''}`
      + (it.danger ? ` 겹침! ${unitNameById[it.anchorId] || ''}` : '');
    if (label) {
      ctx.font = 'bold 12px sans-serif';
      ctx.lineWidth = 3;
      ctx.strokeStyle = '#10141a';
      ctx.strokeText(label, x, y + (drewArea ? 20 : rr + 11));
      ctx.fillStyle = color;
      ctx.fillText(label, x, y + (drewArea ? 20 : rr + 11));
    }
  }
  ctx.globalAlpha = 1;

  rcUpdateBanner(rcBannerEventAt(t));
}

function switchTab(tab) {
  if (tab !== 'replay') {
    rcPause();                  // 리플레이 탭 이탈 시 캔버스 재생 정지
    rcStopTerrainPrefetch();    // 지형 미리받기도 중단
    rcHideTip();
  }
  $$('#tabs .tab').forEach(t => t.classList.remove('active'));
  $$('.tab-pane').forEach(p => p.classList.remove('active'));
  const btn = document.querySelector(`#tabs .tab[data-tab="${tab}"]`);
  if (btn) btn.classList.add('active');
  // 탭 → pane 매핑: heroic/mythic 은 공용 ranking, 나머지는 각자 pane.
  const paneId = (tab === 'arbitrary') ? 'arbitrary'
              : (tab === 'comparison') ? 'comparison'
              : (tab === 'meta') ? 'meta'
              : (tab === 'fun') ? 'fun'
              : (tab === 's2') ? 's2'
              : (tab === 'rotation') ? 'rotation'
              : (tab === 'stats') ? 'stats'
              : (tab === 'replay') ? 'replay'
              : 'ranking';
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
    } else if (tab === 'meta') {
      $('#meta').textContent = '표본: 신화 top100 (PI·로테·일관성 전부 mythic)';
      loadSpecMeta();
    } else if (tab === 'fun') {
      $('#meta').textContent = '유튜브 재미 영상 10개 종합 + 실제 로그로 확인';
      loadSpecFun();
    } else if (tab === 's2') {
      $('#meta').textContent = '시즌2(12.1) 예측 자료집 — 실측 아님, 수시 갱신';
      loadS2Meta();
    } else if (tab === 'rotation') {
      $('#meta').textContent = '표본: 신화 top100';
      loadRotation();
    } else if (tab === 'stats') {
      $('#meta').textContent = '표본: 신화 top100';
      loadStats();
    } else if (tab === 'replay') {
      $('#meta').textContent = '로컬 전투로그 · CCTV 선택 사항';
      loadLocalReplays();
    }
  });

  const replayRefresh = $('#replay-refresh');
  if (replayRefresh) {
    replayRefresh.addEventListener('click', () => {
      replayState.loaded = false;
      replayState.selectedId = null;
      replayState.detail = null;
      loadLocalReplays(true);
    });
  }
  // 캡처 목록 접기/펴기 — 영상+리플레이 두 화면이라 공간 확보용
  const replayListToggle = $('#replay-list-toggle');
  if (replayListToggle) {
    replayListToggle.addEventListener('click', () => {
      const grid = document.querySelector('.replay-grid');
      if (!grid) return;
      const collapsed = grid.classList.toggle('list-collapsed');
      replayListToggle.textContent = collapsed ? '▶ 목록 펴기' : '◀ 목록 접기';
      // 스테이지 폭이 바뀌므로 한 번 다시 그려 3D 버퍼 크기를 맞춤 (일시정지 중 왜곡 방지)
      if (rc.meta) rcDraw();
    });
  }
  const replayList = $('#replay-list-body');
  if (replayList) {
    replayList.addEventListener('click', e => {
      const tr = e.target.closest('tr[data-replay-id]');
      if (tr) selectLocalReplay(tr.dataset.replayId);
    });
  }
  // 브라우저 탭 이탈 시 캔버스 리플레이 정지
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) rcPause();
  });

  // 딜사이클 콤보박스
  $('#rot-class').addEventListener('change', e => {
    _rotSel.cls = e.target.value; _rotSel.spec = null; _rotSel.build = null; renderRotControls();
  });
  $('#rot-spec').addEventListener('change', e => {
    _rotSel.spec = e.target.value; _rotSel.build = null; renderRotControls();
  });
  $('#rot-build').addEventListener('change', e => {
    _rotSel.build = e.target.value;
    updateRotGameButton();
    if (_rotSel.mode === 'boss') renderRotBoss(); else renderRotBody();
  });
  // 스탯 탭 콤보박스
  $('#stat-class').addEventListener('change', e => {
    _statSel.cls = e.target.value; _statSel.spec = null; _statSel.boss = null; renderStatControls();
  });
  $('#stat-spec').addEventListener('change', e => {
    _statSel.spec = e.target.value; _statSel.boss = null; renderStatControls();
  });
  $('#stat-boss').addEventListener('change', e => {
    _statSel.boss = e.target.value; renderStatBody();
  });
  // 스탯 행 클릭 → 장비창
  $('#stat-body').addEventListener('click', e => {
    const tr = e.target.closest('tr.st-row');
    if (!tr || !tr.dataset.ref) return;
    try { openGearModal(JSON.parse(tr.dataset.ref)); } catch (_) {}
  });
  // 장비창 닫기
  const gm = $('#gear-modal');
  if (gm) gm.addEventListener('click', e => {
    if (e.target === gm || e.target.closest('.gm-close')) gm.classList.remove('show');
  });
  // 일반/보스별 모드 토글
  document.querySelector('.rot-mode')?.addEventListener('click', e => {
    const btn = e.target.closest('.rot-mode-btn');
    if (!btn) return;
    _rotSel.mode = btn.dataset.mode;
    $$('.rot-mode-btn').forEach(b => b.classList.toggle('active', b === btn));
    updateRotGameButton();
    if (_rotSel.mode === 'boss') renderRotBoss(); else renderRotBody();
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
      { label: `▲ 비교 위 row 추가 (${r.character})`,
        onClick: () => compLoadInto('top', r.report_id, r.fight_id, r.character) },
      { label: `▼ 비교 아래 row 추가 (${r.character})`,
        onClick: () => compLoadInto('bottom', r.report_id, r.fight_id, r.character) },
    ]);
  });

  // 메타 표 헤더 클릭 → 정렬 (내림/오름 토글)
  const _mthead = document.querySelector('#meta-table thead');
  if (_mthead) _mthead.addEventListener('click', e => {
    const th = e.target.closest('th[data-sort]');
    if (th) sortMetaRows(th.dataset.sort);
  });
  // 재미 표 헤더 클릭 → 정렬 / row 클릭 → 상세
  const _fthead = document.querySelector('#fun-table thead');
  if (_fthead) _fthead.addEventListener('click', e => {
    const th = e.target.closest('th[data-fsort]');
    if (!th) return;
    const field = th.dataset.fsort;
    if (_funSort.field === field) _funSort.dir *= -1;
    else _funSort = { field, dir: (field === 'kr' || field === 'rank') ? 1 : -1 };
    renderSpecFun();
  });
  const _fbody = $('#fun-body');
  if (_fbody) _fbody.addEventListener('click', e => {
    const tr = e.target.closest('tr.fun-row');
    if (tr) showFunDetail(Number(tr.dataset.idx));
  });
  // 메타 표 row 클릭 → 특징 팝업
  $('#meta-body').addEventListener('click', e => {
    const tr = e.target.closest('tr.meta-row');
    if (!tr) return;
    openSpecModal(parseInt(tr.dataset.idx, 10));
  });
  // 팝업 닫기: 배경 클릭 / X / Esc
  const sm = $('#spec-modal');
  if (sm) sm.addEventListener('click', e => {
    if (e.target === sm || e.target.closest('.sm-close')) closeSpecModal();
  });
  const fm = $('#fun-modal');
  if (fm) fm.addEventListener('click', e => {
    if (e.target === fm || e.target.closest('.sm-close')) closeFunModal();
  });
  const s2m = $('#s2-modal');
  if (s2m) s2m.addEventListener('click', e => {
    if (e.target === s2m || e.target.closest('.sm-close')) closeS2Modal();
  });
  const s2b = $('#s2-board');
  if (s2b) s2b.addEventListener('click', e => {
    const chip = e.target.closest('.s2-chip');
    if (chip) showS2Detail(chip.dataset.key);
  });
  $$('.s2-mode-btn').forEach(b => b.addEventListener('click', () => {
    _s2Mode = b.dataset.s2mode;
    if (_s2Data) renderS2();
  }));
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeSpecModal(); closeFunModal(); closeS2Modal(); $('#gear-modal')?.classList.remove('show'); }
    // 스페이스바 = 리플레이 재생/일시정지 (리플레이 탭 + 입력창 포커스 아닐 때)
    if ((e.code === 'Space' || e.key === ' ') && rc.meta
        && document.querySelector('#pane-replay')?.classList.contains('active')
        && !e.target.closest?.('input, textarea, select, [contenteditable]')) {
      e.preventDefault();   // 페이지 스크롤·포커스된 버튼 재클릭 방지
      rc.playing ? rcPause() : rcPlay();
    }
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
  // 추론된 spec 한글 (백엔드 inferred_*_kr, 없으면 매핑 fallback)
  const clsK = d.inferred_class_kr || clsKr(row.class);
  const specK = d.inferred_spec_kr || specKr(row.spec);
  const treeHtml = hasTree
    ? `<h3>특성 트리 (${esc(clsK)} ${esc(specK)})</h3>
       <iframe class="tree-frame" src="${treeUrl}" title="특성 트리"></iframe>`
    : '<p style="color:var(--text-mute);font-size:11px">특성 트리: talent_trees.json 미등록 스펙 (5 타깃 외 클래스)</p>';
  document.querySelector(selector).innerHTML = `
    <div class="bp-header">
      <div class="build-section">
        <div class="build-row">
          <span class="k">캐릭</span>
          <span class="v">${esc(row.character)}${hasTree ? ` · ${esc(clsK)} ${esc(specK)}` : ''}</span>
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
// row-based 비교 분석 — side 식별자 = 'top' | 'bottom'
const compState = {
  top:    { rid: null, meta: null, fid: null, char: null },
  bottom: { rid: null, meta: null, fid: null, char: null },
  selectedChar: null,  // 사이드바에서 active 캐릭 (등록 캐릭) — recent reports lookup 용
};

function compSel(row, attr) {
  return document.querySelector(`[data-row-${attr}="${row}"]`);
}

async function compFetch(row) {
  const urlInput = compSel(row, 'url');
  const meta = compSel(row, 'meta');
  const parsed = parseWclUrl(urlInput.value.trim());
  if (!parsed) { meta.textContent = 'URL 파싱 실패'; return; }
  meta.textContent = '리포트 페치 중…';
  try {
    const r = await fetch(`/api/report/${encodeURIComponent(parsed.rid)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const m = await r.json();
    compState[row].rid = parsed.rid;
    compState[row].meta = m;
    populateCompFights(row, parsed.fid);
    meta.textContent = `${parsed.rid} · ${(m.fights||[]).length} fights`;
  } catch (e) {
    meta.textContent = `실패: ${e.message}`;
  }
}

function populateCompFights(row, preferFid) {
  const m = compState[row].meta || {};
  const DIFF_KR = {1: 'LFR', 2: 'N', 3: 'H', 4: 'M', 5: 'M'};
  const sel = compSel(row, 'fight');
  sel.innerHTML = (m.fights || []).map(f => {
    const dur = ((f.endTime || 0) - (f.startTime || 0)) / 1000;
    const diff = DIFF_KR[f.difficulty] || `d${f.difficulty}`;
    const kill = f.kill ? '✓' : '✗';
    return `<option value="${f.id}">fight ${f.id} · ${diff} · ${kill} ${esc(f.name || '?')} (${dur.toFixed(0)}s)</option>`;
  }).join('');
  if (preferFid) {
    const opt = sel.querySelector(`option[value="${preferFid}"]`);
    if (opt) sel.value = String(preferFid);
  }
  compFightChange(row);
}

function compFightChange(row) {
  const sel = compSel(row, 'fight');
  if (!sel.value) return;
  const fid = parseInt(sel.value, 10);
  compState[row].fid = fid;
  const m = compState[row].meta || {};
  const actors = m.actors || {};
  const f = (m.fights || []).find(x => x.id === fid);
  const fp = new Set(f && f.friendlyPlayers ? f.friendlyPlayers : []);
  let names = Object.keys(actors);
  if (fp.size) names = names.filter(nm => fp.has(actors[nm]));  // 그 fight 참가자만 (신화 20인)
  names.sort((a, b) => a.localeCompare(b, 'ko'));
  const tbody = compSel(row, 'pbody');
  tbody.innerHTML = names.map(nm => `
    <tr data-name="${esc(nm)}"><td>${esc(nm)}</td></tr>
  `).join('');
  compState[row].char = null;
  const tl = document.getElementById(`row-tl-${row}`);
  tl.removeAttribute('src');
}

async function compPlayerClick(row, tr) {
  document.querySelectorAll(`[data-row-pbody="${row}"] tr.selected`)
    .forEach(t => t.classList.remove('selected'));
  tr.classList.add('selected');
  const char = tr.dataset.name;
  const rid = compState[row].rid;
  const fid = compState[row].fid;
  if (!rid || !fid || !char) return;
  compState[row].char = char;

  const tl = document.getElementById(`row-tl-${row}`);
  tl.src = `/api/timeline/${encodeURIComponent(rid)}/${fid}/${encodeURIComponent(char)}`;
  tl.onload = () => applyBuffVisibility();
  loadAugFeedback(row, rid, fid, char);
}

// ── 증강 피드백 패널 (비교탭 row 별) ──────────────────────────────────────
async function loadAugFeedback(row, rid, fid, char) {
  const box = document.querySelector(`[data-row-fb="${row}"]`);
  if (!box) return;
  box.style.display = '';
  box.innerHTML = '<span class="fb-load">피드백 분석 중…</span>';
  try {
    const r = await fetch(`/api/aug-feedback/${encodeURIComponent(rid)}/${fid}/${encodeURIComponent(char)}`);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    if (!d.is_aug) { box.style.display = 'none'; box.innerHTML = ''; return; }  // 증강 아니면 패널 숨김
    box.innerHTML = renderAugFeedback(d);
  } catch (e) {
    box.innerHTML = `<span class="fb-err">피드백 실패: ${esc(e.message)}</span>`;
  }
}

function renderAugFeedback(d) {
  const k = d.kpis || {};
  const upTone = k.ebon_uptime_pct >= 90 ? 'good' : (k.ebon_uptime_pct >= 80 ? 'warn' : 'bad');
  const brTone = k.breath_casts ? (k.breath_after_ebon === k.breath_casts ? 'good' : 'bad') : '';
  const kpis = [
    `<span class="fb-kpi ${upTone}">칠흑 유지율 <b>${k.ebon_uptime_pct}%</b><i>목표 90%+</i></span>`,
    `<span class="fb-kpi">칠흑 시전 <b>${k.ebon_casts}</b></span>`,
    `<span class="fb-kpi">예지 <b>${k.prescience_casts}</b><i>${k.prescience_per_min}/분</i></span>`,
    `<span class="fb-kpi ${brTone}">영겁 칠흑직후 <b>${k.breath_after_ebon}/${k.breath_casts}</b></span>`,
    `<span class="fb-kpi">필러 <b>${Math.round((k.filler_ratio || 0) * 100)}%</b></span>`,
    `<span class="fb-kpi">부양 <b>${k.hover_casts}</b><i>유지 ${k.hover_uptime_pct}%</i></span>`,
  ].join('');
  const vs = d.violations || [];
  const viol = vs.length
    ? `<div class="fb-viol"><b>개선점 ${vs.length}건</b>` + vs.map(v =>
        `<div class="fb-v ${esc(v.kind)}"><span class="fb-vt">${v.ts_rel}s · ${esc(v.label)}</span> ${esc(v.why)} <a href="${esc(v.ref)}" target="_blank" rel="noopener">영상</a></div>`).join('') + '</div>'
    : '<div class="fb-viol ok">자동 점검 위반 없음 ✓</div>';
  const notes = (d.notes || []).map(n =>
    `<details class="fb-note"><summary>${esc(n.title)}</summary><div>${esc(n.body)}</div></details>`).join('');
  const noteHdr = notes ? '<div class="fb-note-hdr" style="margin-top:5px;color:var(--text-mute);font-size:10px;opacity:.85">📘 알아둘 점 — 자동 판정 불가(칠흑 유지와 무관한 참고 개념)</div>' : '';
  return `<div class="fb-kpis">${kpis}</div>${viol}${noteHdr}<div class="fb-notes">${notes}</div>`;
}

// ── 비교 화면 단독 HTML 내보내기 (줌/툴팁 유지, 오프라인 전송용) ──────────
function exportComparison() {
  const t = compState.top || {}, b = compState.bottom || {};
  if (!t.rid || !t.fid || !t.char) { alert('위 row 에 캐릭터를 먼저 선택하세요.'); return; }
  const p = new URLSearchParams({ top_rid: t.rid, top_fid: t.fid, top_char: t.char });
  if (b.rid && b.fid && b.char) { p.set('bot_rid', b.rid); p.set('bot_fid', b.fid); p.set('bot_char', b.char); }
  window.open('/api/export/comparison?' + p.toString(), '_blank');
}

function applyBuffVisibility() {
  const chk = document.getElementById('comp-buff-chk');
  if (!chk) return;
  const show = chk.checked;
  ['top', 'bottom'].forEach(row => {
    const tl = document.getElementById(`row-tl-${row}`);
    try {
      const doc = tl && tl.contentDocument;
      if (doc && doc.body) doc.body.classList.toggle('hide-buffs', !show);
    } catch (_) { /* not loaded */ }
  });
}

// 우클릭 / report 클릭 → 비교 row 로드 (chained promises).
async function compLoadInto(row, rid, fid, char) {
  switchTab('comparison');
  const urlInput = compSel(row, 'url');
  urlInput.value = `https://www.warcraftlogs.com/reports/${rid}?fight=${fid}`;
  await compFetch(row);
  const tbody = compSel(row, 'pbody');
  const tr = tbody.querySelector(`tr[data-name="${CSS.escape(char)}"]`);
  if (tr) {
    await compPlayerClick(row, tr);
    tr.scrollIntoView({ block: 'center' });
  }
}

// ── 사이드바: 등록 캐릭터 + 최근 로그 ───────────────────────────────────
async function loadCharList() {
  const ul = document.getElementById('char-list');
  if (!ul) return;
  try {
    const chars = await (await fetch('/api/characters')).json();
    if (!chars.length) {
      ul.innerHTML = '<li class="empty">+ 버튼으로 등록</li>';
      return;
    }
    ul.innerHTML = chars.map(c => `
      <li data-cname="${esc(c.name)}" data-cserver="${esc(c.server)}" data-cregion="${esc(c.region)}">
        <div>${esc(c.name)}</div>
        <div class="ch-meta">${esc(c.server)} · ${esc(c.region)}</div>
        <button class="ch-del" title="삭제">×</button>
      </li>
    `).join('');
  } catch (e) {
    ul.innerHTML = `<li class="empty">로드 실패: ${esc(e.message)}</li>`;
  }
}

// + 버튼 → form 토글. submit → POST.
function toggleCharForm(show) {
  const form = document.getElementById('char-add-form');
  if (!form) return;
  const visible = (show !== undefined) ? show : (form.style.display === 'none');
  form.style.display = visible ? 'flex' : 'none';
  if (visible) {
    document.getElementById('cf-name').focus();
    document.getElementById('cf-error').textContent = '';
  }
}

async function submitCharForm(e) {
  e.preventDefault();
  const name = document.getElementById('cf-name').value.trim();
  const server = document.getElementById('cf-server').value.trim().toLowerCase();
  const region = document.getElementById('cf-region').value;
  const err = document.getElementById('cf-error');
  if (!name || !server) {
    err.textContent = '이름 + 서버 필수';
    return;
  }
  err.textContent = '등록 중…';
  try {
    const r = await fetch('/api/characters', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name, server, region}),
    });
    if (!r.ok) {
      err.textContent = `실패 (${r.status}): ${(await r.text()).substring(0, 80)}`;
      return;
    }
    // 성공 → 폼 초기화 + 닫고 list 갱신
    document.getElementById('cf-name').value = '';
    document.getElementById('cf-server').value = '';
    document.getElementById('cf-error').textContent = '';
    toggleCharForm(false);
    await loadCharList();
  } catch (e2) {
    err.textContent = `에러: ${e2.message}`;
  }
}

async function deleteChar(name, server, region) {
  // confirm() 도 pywebview 에서 안 동작할 수 있어 직접 진행. ×버튼은 실수가
  // 드무니 (hover 만 보임) 즉시 삭제.
  try {
    await fetch(`/api/characters/${encodeURIComponent(name)}?server=${encodeURIComponent(server)}&region=${encodeURIComponent(region)}`,
                {method: 'DELETE'});
    await loadCharList();
    if (compState.selectedChar &&
        compState.selectedChar.name === name &&
        compState.selectedChar.server === server) {
      compState.selectedChar = null;
      document.getElementById('reports-list').innerHTML =
        '<li class="empty">캐릭 클릭</li>';
      document.getElementById('reports-head').textContent = '최근 로그';
    }
  } catch (e) {
    alert(`삭제 실패: ${e.message}`);
  }
}

async function selectChar(name, server, region) {
  // active 표시
  document.querySelectorAll('#char-list li').forEach(li => li.classList.remove('active'));
  const li = document.querySelector(
    `#char-list li[data-cname="${CSS.escape(name)}"]`);
  if (li) li.classList.add('active');
  compState.selectedChar = {name, server, region};

  const ul = document.getElementById('reports-list');
  const head = document.getElementById('reports-head');
  head.textContent = `최근 로그 — ${name}`;
  ul.innerHTML = '<li class="empty">WCL 페치 중…</li>';
  try {
    const url = `/api/character-reports?name=${encodeURIComponent(name)}`
              + `&server=${encodeURIComponent(server)}&region=${encodeURIComponent(region)}&limit=15`;
    const r = await fetch(url);
    if (!r.ok) {
      const t = await r.text();
      ul.innerHTML = `<li class="empty">실패: ${esc(t.substring(0, 80))}</li>`;
      return;
    }
    const d = await r.json();
    if (!d.reports.length) {
      ul.innerHTML = '<li class="empty">최근 로그 없음</li>';
      return;
    }
    ul.innerHTML = d.reports.map(rp => {
      const dt = rp.startTime ? new Date(rp.startTime) : null;
      const dstr = dt ? `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}` : '?';
      return `
        <li data-rid="${esc(rp.code)}" data-char="${esc(name)}">
          <div class="rp-title">${esc(rp.title || rp.zone_name || rp.code)}</div>
          <div class="rp-meta">${esc(rp.zone_name)} · ${dstr}</div>
        </li>
      `;
    }).join('');
  } catch (e) {
    ul.innerHTML = `<li class="empty">에러: ${esc(e.message)}</li>`;
  }
}

// report 클릭 → 빈 row (또는 우클릭 → 명시적 row 선택) 로 자동 로드
async function loadReportIntoRow(rid, char, preferRow) {
  // 빈 row 자동 선택: top → bottom 순. 둘 다 차있으면 top 덮어쓰기.
  let row = preferRow;
  if (!row) {
    if (!compState.top.rid) row = 'top';
    else if (!compState.bottom.rid) row = 'bottom';
    else row = 'top';
  }
  // 해당 캐릭이 가장 최근에 한 fight 자동 선택
  const urlInput = compSel(row, 'url');
  urlInput.value = `https://www.warcraftlogs.com/reports/${rid}`;
  await compFetch(row);
  const tbody = compSel(row, 'pbody');
  const tr = tbody.querySelector(`tr[data-name="${CSS.escape(char)}"]`);
  if (tr) {
    await compPlayerClick(row, tr);
    tr.scrollIntoView({ block: 'center' });
  } else {
    compSel(row, 'meta').textContent =
      `${char} 이 fight 미참가 — 다른 fight 선택`;
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

// 비교 탭 timeline sync — top ↔ bottom iframe 사이에서 wheel/drag 동기화.
// 각 iframe 의 ZOOM_JS 가 상태 변경 시 parent.postMessage({type:'tlsync',...}).
// parent 가 받아서 OTHER iframe 에 {type:'tlapply',...} 로 forward.
function bindTimelineSync() {
  window.addEventListener('message', (e) => {
    const d = e.data;
    if (!d || d.type !== 'tlsync') return;
    const topTl = document.getElementById('row-tl-top');
    const botTl = document.getElementById('row-tl-bottom');
    if (!topTl || !botTl) return;
    let target = null;
    if (topTl.contentWindow === e.source) target = botTl;
    else if (botTl.contentWindow === e.source) target = topTl;
    if (!target || !target.contentWindow) return;
    target.contentWindow.postMessage(
      {type: 'tlapply', pps: d.pps, panX: d.panX, panY: d.panY}, '*');
  });
}

function bindComparison() {
  // URL 입력 + 분석 버튼
  document.querySelectorAll('[data-row-fetch]').forEach(btn => {
    btn.addEventListener('click', () => compFetch(btn.dataset.rowFetch));
  });
  document.querySelectorAll('[data-row-url]').forEach(inp => {
    inp.addEventListener('keydown', e => {
      if (e.key === 'Enter') compFetch(inp.dataset.rowUrl);
    });
  });
  // fight 변경
  document.querySelectorAll('[data-row-fight]').forEach(sel => {
    sel.addEventListener('change', () => compFightChange(sel.dataset.rowFight));
  });
  // 플레이어 클릭 (이벤트 위임)
  document.querySelectorAll('[data-row-pbody]').forEach(tbody => {
    tbody.addEventListener('click', e => {
      const tr = e.target.closest('tr');
      if (tr) compPlayerClick(tbody.dataset.rowPbody, tr);
    });
  });
  // 버프 토글
  const buffChk = document.getElementById('comp-buff-chk');
  if (buffChk) buffChk.addEventListener('change', applyBuffVisibility);

  // 사이드바: + 버튼 → form 토글
  const addBtn = document.getElementById('char-add');
  if (addBtn) addBtn.addEventListener('click', () => toggleCharForm());
  const addForm = document.getElementById('char-add-form');
  if (addForm) {
    addForm.addEventListener('submit', submitCharForm);
    addForm.querySelector('.cf-cancel').addEventListener('click', () => toggleCharForm(false));
  }

  // 사이드바: 캐릭 클릭 (위임)
  const charUl = document.getElementById('char-list');
  if (charUl) {
    charUl.addEventListener('click', e => {
      const delBtn = e.target.closest('.ch-del');
      const li = e.target.closest('li[data-cname]');
      if (delBtn && li) {
        e.stopPropagation();
        deleteChar(li.dataset.cname, li.dataset.cserver, li.dataset.cregion);
        return;
      }
      if (li) {
        selectChar(li.dataset.cname, li.dataset.cserver, li.dataset.cregion);
      }
    });
  }

  // 사이드바: 리포트 클릭 → 빈 row 자동 로드
  const repUl = document.getElementById('reports-list');
  if (repUl) {
    repUl.addEventListener('click', e => {
      const li = e.target.closest('li[data-rid]');
      if (!li) return;
      loadReportIntoRow(li.dataset.rid, li.dataset.char);
    });
    repUl.addEventListener('contextmenu', e => {
      const li = e.target.closest('li[data-rid]');
      if (!li) return;
      e.preventDefault();
      const rid = li.dataset.rid, char = li.dataset.char;
      showContextMenu(e.clientX, e.clientY, [
        { label: `▲ 위 row 로 (${char})`,
          onClick: () => loadReportIntoRow(rid, char, 'top') },
        { label: `▼ 아래 row 로 (${char})`,
          onClick: () => loadReportIntoRow(rid, char, 'bottom') },
      ]);
    });
  }
}

// 인증 비활성 — auth-info topbar 숨김
function loadAuthInfo() {
  const el = document.getElementById('auth-info');
  if (el) el.style.display = 'none';
}

// ── 부트 ────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  bind();
  ensureSpellMap();  // 스킬명 아이콘+툴팁 매핑 선로딩
  bindComparison();
  bindTimelineSync();
  loadAuthInfo();
  loadRankings('heroic');
  loadCharList();
});
