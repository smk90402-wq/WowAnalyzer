// 분노 전사 딜사이클 우선순위 트레이너 (미니게임 — 랜덤 문제 + 5초 타이머)
// 매 문제: 완전 랜덤한 버프/자원 상태 → '쓸 수 있는(빛나는)' 스킬 중 최우선을 5초 안에 클릭.
// 정답=다음 문제, 오답/시간초과=즉시 실패 팝업(이유)+다음/다시하기/종료.
// 우선순위 = 검증된 rotation_data 기반(산왕/학살자 × 무모한 희생 OFF/ON). window.openRotGame(cls,spec,build).
'use strict';
(function () {
  const IMG = (ic) => `https://wow.zamimg.com/images/wow/icons/large/${ic}.jpg`;
  const AB = {
    rampage: { nm: '광란', ic: 'ability_warrior_rampage' },
    bt: { nm: '피의 갈증', ic: 'spell_nature_bloodlust', rNm: '피범벅', rIc: 'ability_warrior_bloodbath' },
    rblow: { nm: '분노의 강타', ic: 'warrior_wild_strike', rNm: '분쇄의 타격', rIc: 'ability_hunter_swiftstrike' },
    execute: { nm: '마무리 일격', ic: 'inv_sword_48' },
    odyn: { nm: '오딘의 격노', ic: 'inv_sword_1h_artifactvigfus_d_01' },
    bstorm: { nm: '칼날폭풍', ic: 'ability_warrior_bladestorm' },
    ww: { nm: '소용돌이', ic: 'ability_whirlwind' },
    tblast: { nm: '우레 작렬', ic: 'warrior_talent_icon_bloodandthunder' },
    tclap: { nm: '천둥벼락', ic: 'spell_nature_thunderclap' },
  };
  const disp = (k, reck) => (reck && AB[k].rNm) ? { nm: AB[k].rNm, ic: AB[k].rIc } : { nm: AB[k].nm, ic: AB[k].ic };

  const R = {
    슬레이어OFF: [
      { k: 'rampage', c: s => (!s.enraged || s.rage > 100) && s.rage >= 80, w: '비격노/분노캡 — 자원 1규칙(최우선)' },
      { k: 'odyn', c: s => s.odynCd <= 0, w: '오딘의 격노 쿨마다(4세트 엔진)' },
      { k: 'execute', c: s => s.sd || s.exec, w: '급살 프록/처형 구간' },
      { k: 'bt', c: s => s.btCd <= 0, w: '피의 갈증 쿨마다' },
      { k: 'rampage', c: s => s.rage >= 80, w: '분노 차면 광란(일반)' },
      { k: 'rblow', c: s => s.rbCharges > 0, w: '분노의 강타 필러' },
      { k: 'ww', c: () => true, w: '최하위 필러 (개선된 회전베기로 분쇄 자동 전파)' },
    ],
    슬레이어ON: [
      { k: 'rampage', c: s => (!s.enraged || s.rage > 100) && s.rage >= 80, w: '비격노/분노캡 — 자원 1규칙' },
      { k: 'bstorm', c: s => s.bsCd <= 0, w: '무모한 희생 창엔 칼날폭풍' },
      { k: 'odyn', c: s => s.odynCd <= 0, w: '오딘의 격노 쿨마다' },
      { k: 'bt', c: s => s.btCd <= 0, w: '피범벅(피의 갈증 변형)' },
      { k: 'rampage', c: s => s.rage >= 80, w: '광란(일반)' },
      { k: 'execute', c: s => s.sd || s.exec, w: '마무리 일격' },
      { k: 'rblow', c: s => s.rbCharges > 0, w: '분쇄의 타격(분노의 강타 변형)' },
      { k: 'ww', c: () => true, w: '필러' },
    ],
    산왕OFF: [
      { k: 'rampage', c: s => (!s.enraged || s.rage > 100) && s.rage >= 80, w: '비격노/분노캡 — 자원 1규칙' },
      { k: 'tblast', c: s => s.tbCharges >= 2, w: '우레 작렬 2충전(오버캡 방지, 처형보다 위)' },
      { k: 'bt', c: s => s.btCd <= 0, w: '피의 갈증 쿨마다(엔진)' },
      { k: 'execute', c: s => s.sd || s.exec, w: '급살 프록/처형' },
      { k: 'tblast', c: s => s.tbCharges >= 1, w: '우레 작렬(1충전)' },
      { k: 'rampage', c: s => s.rage >= 80, w: '광란(일반)' },
      { k: 'rblow', c: s => s.rbCharges > 0, w: '분노의 강타 필러' },
      { k: 'tclap', c: () => true, w: '천둥벼락 필러' },
    ],
    산왕ON: [
      { k: 'odyn', c: s => s.odynCd <= 0, w: '버스트 진입 — 오딘의 격노' },
      { k: 'rampage', c: s => (!s.enraged || s.rage > 100) && s.rage >= 80, w: '비격노/분노캡 — 자원 1규칙' },
      { k: 'tblast', c: s => s.tbCharges >= 2, w: '우레 작렬 2충전' },
      { k: 'bt', c: s => s.btCd <= 0, w: '피범벅(피의 갈증 변형)' },
      { k: 'rampage', c: s => s.rage >= 80, w: '광란(일반)' },
      { k: 'tblast', c: s => s.tbCharges >= 1, w: '우레 작렬(1충전)' },
      { k: 'execute', c: s => s.sd || s.exec, w: '마무리 일격' },
      { k: 'rblow', c: s => s.rbCharges > 0, w: '분쇄의 타격(분노의 강타 변형)' },
      { k: 'tclap', c: () => true, w: '천둥벼락 필러' },
    ],
  };
  const BAR = {
    학살자: ['rampage', 'bt', 'execute', 'rblow', 'odyn', 'bstorm', 'ww'],
    산왕: ['rampage', 'tblast', 'bt', 'execute', 'rblow', 'odyn', 'tclap'],
  };
  const rulesFor = (build, reck) =>
    build === '산왕' ? (reck ? R.산왕ON : R.산왕OFF) : (reck ? R.슬레이어ON : R.슬레이어OFF);

  function actionable(s, k) {
    switch (k) {
      case 'rampage': return s.rage >= 80;
      case 'bt': return s.btCd <= 0;
      case 'execute': return s.sd || s.exec;
      case 'rblow': return s.rbCharges > 0;
      case 'odyn': return s.odynCd <= 0;
      case 'bstorm': return s.bsCd <= 0 && s.reck; // 칼날폭풍은 무모한 희생 중에만
      case 'tblast': return s.tbCharges > 0;
      default: return true; // ww / tclap 필러
    }
  }
  const NA = {
    rampage: '분노 부족(80 필요)', bt: '쿨다운 중', execute: '급살 프록도 처형 구간도 아님',
    rblow: '충전 없음', odyn: '쿨다운 중', tblast: '충전 없음',
  };
  function correctRule(s) {
    const rules = rulesFor(s.build, s.reck);
    for (const r of rules) if (r.c(s)) return r;
    return rules[rules.length - 1];
  }
  function tierOf(s, k) {
    const rules = rulesFor(s.build, s.reck);
    for (let i = 0; i < rules.length; i++) if (rules[i].k === k) return i + 1;
    return rules.length;
  }
  const rb = (p) => Math.random() < p;
  // 완전 랜덤 문제 상태 (버프/자원/쿨 무작위)
  function randomProblem(build) {
    return {
      build,
      reck: rb(0.4),
      exec: rb(0.2),
      rage: Math.floor(Math.random() * 13) * 10,   // 0~120
      enraged: rb(0.55),
      sd: rb(0.4),
      btCd: rb(0.5) ? 0 : 3,
      odynCd: rb(0.4) ? 0 : 6,
      bsCd: 0,                                       // 칼날폭풍은 reck일 때만 빛남
      rbCharges: Math.floor(Math.random() * 3),      // 0~2
      tbCharges: Math.floor(Math.random() * 3),      // 0~2 (산왕)
    };
  }
  function activeBuffs(s) {
    const out = [];
    if (s.reck) out.push('🔥 무모한 희생 ON (버스트)');
    if (s.sd) out.push('⚡ 급살 프록');
    if (s.exec) out.push('💀 처형 구간');
    if (s.build === '산왕' && s.tbCharges > 0) out.push(`⚡ 우레 작렬 ${s.tbCharges}충전`);
    return out;
  }

  const STEPS = 50, LIMIT = 5000;
  let _styled = false;
  function injectStyle() {
    if (_styled) return; _styled = true;
    const css = `
.rg-ov{position:fixed;inset:0;z-index:9999;background:rgba(10,10,14,.92);display:flex;align-items:center;justify-content:center;font-family:inherit}
.rg-box{position:relative;width:min(760px,94vw);max-height:94vh;overflow:auto;background:#16161c;border:1px solid #33333f;border-radius:14px;padding:20px 22px;color:#e8e8ee}
.rg-top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px}
.rg-title{font-size:17px;font-weight:600}
.rg-badge{font-size:12px;font-weight:600;padding:3px 10px;border-radius:20px}
.rg-off{background:#2a2a33;color:#cfcfe0}.rg-on{background:#9a6b16;color:#ffe9b8}
.rg-x{margin-left:auto;cursor:pointer;background:none;border:none;color:#999;font-size:22px;line-height:1}
.rg-state{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:8px;font-size:12px;color:#b9b9c6}
.rg-ragebar{flex:1;min-width:120px;height:14px;background:#26262f;border-radius:7px;overflow:hidden}
.rg-ragefill{height:100%;background:#c0392b}
.rg-chip{padding:2px 9px;border-radius:12px;font-weight:600}
.rg-en{background:#7a3b16;color:#ffcf9e}.rg-noen{background:#33333f;color:#9a9aa8}
.rg-ex{background:#5a1f1f;color:#ffb3b3}
.rg-pop{margin:0 0 8px;padding:8px 12px;background:#3a2a0a;border:1px solid #b6831f;border-radius:8px;color:#ffe9b8;font-size:13px;font-weight:600;display:flex;gap:14px;flex-wrap:wrap}
.rg-timer{height:8px;background:#26262f;border-radius:5px;overflow:hidden;margin:4px 0 12px}
.rg-timerfill{height:100%;background:#5dade2;width:100%;animation:rgtimer 5s linear forwards}
@keyframes rgtimer{from{width:100%}to{width:0}}
.rg-hint{font-size:13px;color:#cfcfd8;margin:0 0 8px}
.rg-prog{font-size:12px;color:#9a9aa8}
.rg-bar{display:flex;gap:10px;flex-wrap:wrap;justify-content:center;padding:14px;background:#0e0e13;border-radius:10px}
.rg-tile{width:70px;text-align:center;cursor:pointer;user-select:none}
.rg-ic{width:54px;height:54px;border-radius:9px;margin:0 auto;background-size:cover;border:2px solid #2c2c36;position:relative}
.rg-tile.live .rg-ic{border-color:#f4c542;box-shadow:0 0 9px 1px rgba(244,197,66,.55)}
.rg-tile.dim{cursor:not-allowed}.rg-tile.dim .rg-ic{filter:grayscale(1) brightness(.45);border-color:#22222a}
.rg-nm{font-size:11px;margin-top:4px;color:#d4d4de;line-height:1.15}
.rg-tile.dim .rg-nm{color:#6a6a76}
.rg-mk{position:absolute;top:-7px;right:-7px;min-width:18px;height:18px;padding:0 4px;border-radius:9px;background:#f4c542;color:#1a1a1a;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;border:1px solid #16161c}
.rg-msg{text-align:center;font-size:14px;font-weight:600;min-height:22px;margin-top:12px}
.rg-ok{color:#5fd38a}
.rg-fail{position:absolute;inset:0;background:rgba(12,8,8,.93);border-radius:14px;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:26px;text-align:center;animation:rgpop .25s ease}
@keyframes rgpop{from{opacity:0;transform:scale(.97)}to{opacity:1;transform:none}}
.rg-failh{font-size:20px;font-weight:700;color:#ff7a7a;margin-bottom:10px}
.rg-failw{font-size:14px;color:#e8e8ee;line-height:1.6;max-width:560px;margin-bottom:6px}
.rg-failsub{font-size:12px;color:#9a9aa8;margin-bottom:18px}
.rg-btns{display:flex;gap:10px;flex-wrap:wrap;justify-content:center}
.rg-btn{cursor:pointer;background:#2a2a33;border:1px solid #44444f;color:#e8e8ee;border-radius:8px;padding:9px 18px;font-size:13px;font-weight:600}
.rg-btn.pri{background:#9a6b16;border-color:#b6831f;color:#ffe9b8}
.rg-res h3{font-size:18px;margin:0 0 4px}.rg-grade{font-size:13px;color:#c9c9d4;margin-bottom:12px}
.rg-miss{max-height:42vh;overflow:auto;border-top:1px solid #2c2c36;padding-top:10px;margin-bottom:14px}
.rg-row{display:flex;gap:8px;font-size:12.5px;padding:6px 0;border-bottom:1px solid #22222a;line-height:1.4}
.rg-step{color:#8a8a96;min-width:34px}`;
    const st = document.createElement('style'); st.id = 'rg-style'; st.textContent = css;
    document.head.appendChild(st);
  }
  const el = (h) => { const d = document.createElement('div'); d.innerHTML = h.trim(); return d.firstChild; };

  window.openRotGame = function (cls, spec, build) {
    if (cls !== 'Warrior' || spec !== 'Fury' || !BAR[build]) {
      alert('이 미니게임은 전사 분노(산왕/학살자) 전용입니다.'); return;
    }
    injectStyle();
    let s, cr, no, correct, miss, timer, resolved;
    const ov = el('<div class="rg-ov"></div>'), box = el('<div class="rg-box"></div>');
    ov.appendChild(box); document.body.appendChild(ov);
    ov.addEventListener('click', (e) => { if (e.target === ov) close(); });
    function close() { clearTimeout(timer); ov.remove(); }
    function restart() { no = 0; correct = 0; miss = []; next(); }
    function next() {
      clearTimeout(timer); resolved = false;
      if (no >= STEPS) { renderResult(); return; }
      no++; s = randomProblem(build); cr = correctRule(s);
      renderPlay();
      timer = setTimeout(onTimeout, LIMIT);
    }

    function renderPlay() {
      const buffs = activeBuffs(s);
      const tiles = BAR[build].map(k => {
        const d = disp(k, s.reck), live = actionable(s, k);
        let mk = '';
        if (k === 'execute' && (s.sd || s.exec)) mk = '<span class="rg-mk">!</span>';
        else if (k === 'tblast' && s.tbCharges > 0) mk = `<span class="rg-mk">${s.tbCharges}</span>`;
        else if (k === 'rampage' && live && (!s.enraged || s.rage > 100)) mk = '<span class="rg-mk">★</span>';
        return `<div class="rg-tile ${live ? 'live' : 'dim'}" data-k="${k}">
          <div class="rg-ic" style="background-image:url('${IMG(d.ic)}')">${mk}</div>
          <div class="rg-nm">${d.nm}</div></div>`;
      }).join('');
      box.innerHTML = `
        <div class="rg-top">
          <span class="rg-title">⚔ ${build} 딜사이클 연습</span>
          <span class="rg-badge ${s.reck ? 'rg-on' : 'rg-off'}">${s.reck ? '무모한 희생 ON' : '평상시'}</span>
          <span class="rg-prog">${no} / ${STEPS} · 정답 ${correct}</span>
          <button class="rg-x" title="종료">×</button>
        </div>
        ${buffs.length ? `<div class="rg-pop">${buffs.map(b => `<span>${b}</span>`).join('')}</div>` : ''}
        <div class="rg-state">
          <span>분노</span>
          <div class="rg-ragebar"><div class="rg-ragefill" style="width:${Math.min(100, s.rage / 1.2)}%"></div></div>
          <span>${s.rage}</span>
          <span class="rg-chip ${s.enraged ? 'rg-en' : 'rg-noen'}">${s.enraged ? '격노 O' : '격노 X'}</span>
        </div>
        <div class="rg-timer"><div class="rg-timerfill"></div></div>
        <div class="rg-hint">5초 안에 <b>지금 1순위</b>를 클릭 (노란 테두리 = 사용 가능)</div>
        <div class="rg-bar">${tiles}</div>
        <div class="rg-msg" id="rg-msg"></div>`;
      box.querySelector('.rg-x').onclick = close;
      box.querySelectorAll('.rg-tile').forEach(t => {
        t.onclick = () => { if (!resolved) pick(t.getAttribute('data-k')); };
      });
    }

    function wrongWhy(k) {
      const want = disp(cr.k, s.reck).nm, pressed = disp(k, s.reck).nm;
      if (!actionable(s, k)) {
        let na = NA[k] || '필러(언제나 가능)';
        if (k === 'bstorm' && !s.reck) na = '무모한 희생 중에만 사용 — 아껴두세요';
        return `${pressed}은(는) 지금 사용 불가 (${na}). 정답은 ${want} — ${cr.w}`;
      }
      return `${want}이(가) 더 우선 — ${cr.w}. (누른 ${pressed}은 ${tierOf(s, k)}순위)`;
    }

    function pick(k) {
      resolved = true; clearTimeout(timer);
      const want = disp(cr.k, s.reck).nm;
      if (k === cr.k) {
        correct++;
        const m = box.querySelector('#rg-msg'); if (m) { m.className = 'rg-msg rg-ok'; m.textContent = `✓ 정답 — ${want}`; }
        box.querySelectorAll('.rg-tile').forEach(t => t.onclick = null);
        setTimeout(next, 480);
      } else {
        const why = wrongWhy(k);
        miss.push({ no, reck: s.reck, why });
        showFail('✗ 오답', why);
      }
    }
    function onTimeout() {
      if (resolved) return; resolved = true;
      const want = disp(cr.k, s.reck).nm;
      const why = `정답은 ${want} — ${cr.w}`;
      miss.push({ no, reck: s.reck, why: `(시간초과) ${why}` });
      showFail('⏱ 시간 초과', why);
    }

    function showFail(head, why) {
      const fail = el(`<div class="rg-fail">
        <div class="rg-failh">${head}</div>
        <div class="rg-failw">${why}</div>
        <div class="rg-failsub">${no} / ${STEPS} · 정답 ${correct}</div>
        <div class="rg-btns">
          <button class="rg-btn pri" id="rg-nx">다음 문제 ▶</button>
          <button class="rg-btn" id="rg-rs">다시하기</button>
          <button class="rg-btn" id="rg-cl">종료</button>
        </div></div>`);
      box.appendChild(fail);
      fail.querySelector('#rg-nx').onclick = next;
      fail.querySelector('#rg-rs').onclick = restart;
      fail.querySelector('#rg-cl').onclick = close;
    }

    function renderResult() {
      const pct = Math.round(correct / STEPS * 100);
      const grade = pct >= 95 ? 'S — 거의 완벽' : pct >= 85 ? 'A — 숙련' : pct >= 70 ? 'B — 무난' : pct >= 50 ? 'C — 연습 필요' : 'D — 우선순위 재숙지';
      const rows = miss.length ? miss.map(m =>
        `<div class="rg-row"><span class="rg-step">#${m.no}</span><span>${m.reck ? '🔥 ' : ''}${m.why}</span></div>`).join('')
        : '<div class="rg-row" style="color:#5fd38a">틀린 곳 없음 — 완벽합니다! 🎉</div>';
      box.innerHTML = `
        <div class="rg-top"><span class="rg-title">⚔ ${build} 결과</span><button class="rg-x">×</button></div>
        <div class="rg-res">
          <h3>${correct} / ${STEPS} 정답 (${pct}%)</h3>
          <div class="rg-grade">등급 ${grade} · 🔥=무모한 희생 창</div>
          <div class="rg-miss">${rows}</div>
          <div class="rg-btns">
            <button class="rg-btn pri" id="rg-rs2">다시하기</button>
            <button class="rg-btn" id="rg-cl2">종료</button>
          </div>
        </div>`;
      box.querySelector('.rg-x').onclick = close;
      box.querySelector('#rg-rs2').onclick = restart;
      box.querySelector('#rg-cl2').onclick = close;
    }

    restart();
  };
})();
