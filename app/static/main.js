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

// ── 메타 분석 (4차원 종합 표) ────────────────────────────────────────────
let _metaLoaded = false;
let _metaRows = [];   // 팝업용 행 데이터 보관
async function loadSpecMeta(force) {
  if (_metaLoaded && !force) return;
  const body = $('#meta-body');
  body.innerHTML = '<tr><td colspan="18" class="empty">로딩…</td></tr>';
  try {
    const r = await fetch('/api/spec-meta');
    if (!r.ok) throw new Error(`HTTP ${r.status} — run_full_analysis.py 필요할 수 있음`);
    const j = await r.json();
    renderSpecMeta(j.rows || []);
    _metaLoaded = true;
  } catch (e) {
    body.innerHTML = `<tr><td colspan="19" class="empty">로드 실패: ${esc(e.message)}</td></tr>`;
  }
}

function renderSpecMeta(rows) {
  const fmt = (v, d = 2) => (v == null || Number.isNaN(v)) ? '-' : Number(v).toFixed(d);
  const body = $('#meta-body');
  _metaRows = rows;
  body.innerHTML = rows.map((r, i) => {
    const piHi = r.pi_indep != null && r.pi_indep >= 0.9;
    const upDep = r.uplift_pct != null && r.uplift_pct >= 3;
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
      <td class="right num strong" title="${r.score_parse != null ? `파스력 ${fmt(r.score_parse,3)} × 0.65 + 막공환영 ${r.pug || '-'}/5 × 0.35` : ''}">${fmt(r.score, 3)}</td>
      <td class="right num">${fmt(r.ease)}</td>
      <td class="right mute num">${r.rot_rank != null ? Math.round(r.rot_rank) : '-'}</td>
      <td class="right num ${piHi ? 'good' : ''}">${fmt(r.pi_indep)}</td>
      <td class="right num ${upDep ? 'bad' : 'mute'}">${r.uplift_pct != null ? (r.uplift_pct >= 0 ? '+' : '') + fmt(r.uplift_pct) + '%' : '-'}</td>
      <td class="right num">${fmt(r.consistency)}</td>
      ${tierCell(r.raid_tier)}
      ${tierCell(r.mplus_tier)}
      <td class="right num ${tuneCls(r.tuning)}" title="${esc(r.tuning_note || '')}">${r.tuning || '-'}</td>
      <td class="right num ${r.pop_favor >= 70 ? 'good' : (r.pop_favor != null && r.pop_favor < 35 ? 'bad' : 'mute')}" title="실제 모집단 ~${r.pop_avg != null ? Number(r.pop_avg).toLocaleString() : '?'}명">${r.pop_favor != null ? Math.round(r.pop_favor) : '-'}</td>
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
  const sc = r.score;
  const pt = sc >= 0.85 ? '막공 종합 최상' : (sc >= 0.70 ? '막공 종합 우수'
    : (sc >= 0.50 ? '막공 종합 보통' : '막공 종합 낮음'));
  const sp = r.score_parse;
  const brk = sp != null
    ? ` <span class="sm-muted">= 파스력 ${_fmtN(sp, 3)}×0.65 + 막공환영 ${r.pug || '-'}/5×0.35 (구인난 가중)</span>`
    : '';
  out.push({ tone: sc >= 0.70 ? 'good' : (sc < 0.50 ? 'bad' : ''),
    text: `<b>${pt}</b> (종합 ${_fmtN(sc, 3)} · ${r.rank}위)${brk}` });
  if (r.pi_indep != null) {
    const dep = r.uplift_pct != null && r.uplift_pct >= 3;
    out.push({ tone: dep ? 'bad' : 'good', text: dep
      ? `마력주입(PI) <b>의존</b> — uplift +${_fmtN(r.uplift_pct, 1)}% (사제 버프 있어야 고파스)`
      : `마력주입(PI) <b>독립</b> — 버프 없이도 OK (uplift ${r.uplift_pct >= 0 ? '+' : ''}${_fmtN(r.uplift_pct, 1)}%)` });
  }
  if (r.consistency != null)
    out.push({ tone: r.consistency >= 0.85 ? 'good' : (r.consistency < 0.60 ? 'bad' : ''),
      text: r.consistency >= 0.85 ? '기믹/RNG에 <b>안정적</b> (일관성↑)'
        : (r.consistency < 0.60 ? '기믹/RNG에 <b>흔들림</b> (일관성↓)' : '일관성 보통') });
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
      text: `인구 <b>~${r.pop_avg != null ? Number(r.pop_avg).toLocaleString() : '?'}명</b> ${many ? '(많음 — median 파스엔 유리)' : (few ? '(적음 — 고인물풀)' : '(중간)')} <span class="sm-muted">점수 미반영·1%추구자엔 무의미</span>` });
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
      text: `특임/유틸 부담 <b>${r.burden}/5</b> ${hi ? '(높음 — 강제 기믹에 딜 끊김, 파스 불리)' : (lo ? '(낮음 — 순수딜 집중 가능, 파스 유리)' : '(중간)')} — ${esc(r.burden_note || '')}` });
  }
  if (r.aoe_ratio != null)
    out.push({ tone: '', text: r.aoe_ratio >= 1.4 ? `<b>다타겟·쫄파이 특화</b> (광딜비 ${_fmtN(r.aoe_ratio)})`
      : (r.aoe_ratio < 1.1 ? `<b>단일 위주</b> (광딜비 ${_fmtN(r.aoe_ratio)})` : `광/단일 균형 (${_fmtN(r.aoe_ratio)})`) });
  if (r.skill_ceiling >= 4)
    out.push({ tone: 'bad', text: `최적화 <b>스킬천장 높음</b> (${r.skill_label}) — ${esc(r.skill_reason || '')}` });
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
    cell('PI 독립', _fmtN(r.pi_indep)),
    cell('PI uplift', r.uplift_pct != null ? (r.uplift_pct >= 0 ? '+' : '') + _fmtN(r.uplift_pct, 1) + '%' : '-'),
    cell('일관성', _fmtN(r.consistency)),
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
    <div class="sm-foot">난이도·스킬천장·꿀팁 = 유튜브(12.0.5)/가이드 큐레이션 · 레이드/쐐기 티어 = 순수 성능(파스 무관) · PI독립·일관성·광딜·인구 = 로그 데이터</div>`;
  $('#spec-modal').classList.add('show');
  whEnsure();  // 스킬명 마우스오버 툴팁
}
function closeSpecModal() { $('#spec-modal').classList.remove('show'); }

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
    $('#rot-body').innerHTML = '<div class="empty">이 전문화는 보스별 실측 데이터 없음 (top100 캐시 부족)</div>';
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
  $('#rot-body').innerHTML = `<div class="bc-note">⚠ top100 실측 역산. 블러드는 펫블러드(야수)외엔 외부주술사라 받은판만 집계(커버리지 표기). 물약 추적 희박=참고.</div><div class="bc-grid">${cards}</div>`;
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
  if (box.count_median != null) parts.push(`중앙 ${box.count_median}회`);
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
    <div class="sm-foot">아이템에 마우스 = wowhead 툴팁(풀스탯·마부·보석명). 클릭 = wowhead. 보석 아이콘=호버시 이름.</div>`;
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
  $('#rot-body').innerHTML = `
    <div class="rot-meta">
      <div class="rot-summary">${wsify(esc(spec.summary || ''))}</div>
      ${spec.stat ? `<div class="rot-stat"><b>스탯</b> ${wsify(esc(spec.stat))}</div>` : ''}
      ${build.hero_note ? `<div class="rot-hero"><b>${esc(_rotSel.build)}</b> ${wsify(esc(build.hero_note))}</div>` : ''}
      ${hasGame ? `<button id="rot-game-btn" class="rot-game-btn" style="margin-top:10px">딜사이클 문제풀이 — ${esc(_rotSel.build)} (단일특/광특 50문제)</button>` : ''}
    </div>
    <div class="rot-cols">
      <div class="rot-col"><div class="rot-col-h single">단일 우선순위</div>${list(build.single)}</div>
      <div class="rot-col"><div class="rot-col-h aoe">광역 우선순위</div>${list(build.aoe)}</div>
      <div class="rot-col"><div class="rot-col-h opener">오프너</div>${list(build.opener)}</div>
      ${build.util && build.util.length ? `<div class="rot-col"><div class="rot-col-h util">유틸·생존 (눌러야 할 것)</div>${list(build.util)}</div>` : ''}
    </div>`;
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
function switchTab(tab) {
  $$('#tabs .tab').forEach(t => t.classList.remove('active'));
  $$('.tab-pane').forEach(p => p.classList.remove('active'));
  const btn = document.querySelector(`#tabs .tab[data-tab="${tab}"]`);
  if (btn) btn.classList.add('active');
  // 탭 → pane 매핑: heroic/mythic 은 공용 ranking, 나머지는 각자 pane.
  const paneId = (tab === 'arbitrary') ? 'arbitrary'
              : (tab === 'comparison') ? 'comparison'
              : (tab === 'meta') ? 'meta'
              : (tab === 'rotation') ? 'rotation'
              : (tab === 'stats') ? 'stats'
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
    } else if (tab === 'rotation') {
      $('#meta').textContent = '표본: 신화 top100';
      loadRotation();
    } else if (tab === 'stats') {
      $('#meta').textContent = '표본: 신화 top100';
      loadStats();
    }
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
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeSpecModal(); $('#gear-modal')?.classList.remove('show'); }
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
