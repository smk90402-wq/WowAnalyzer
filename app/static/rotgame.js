// Rotation priority trainer.
// Practice mode has no timer; timed test mode adds a 5 second limit per question.
'use strict';
(function () {
  const IMG = (ic) => `https://wow.zamimg.com/images/wow/icons/large/${ic}.jpg`;
  const SMALL = (ic) => `https://wow.zamimg.com/images/wow/icons/small/${ic}.jpg`;
  const STEPS = 50;
  const LIMIT = 5000;
  const rb = (p) => Math.random() < p;
  const ri = (max) => Math.floor(Math.random() * max);
  const PROFILE = { single: '단일특', aoe: '광특' };
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));
  const tip = (v) => `data-tip="${esc(v).replace(/\n/g, '&#10;')}" aria-label="${esc(v)}"`;
  const wowAttr = (d) => d?.id ? `data-spell-id="${d.id}" data-wowhead="spell=${d.id}&domain=ko"` : '';
  const tipAttrs = (d, text) =>
    `${tip(text)} data-tip-title="${esc(d?.nm || '')}" data-tip-icon="${esc(d?.ic || '')}" ${wowAttr(d)}`;

  const W = {
    rampage: { nm: '광란', ic: 'ability_warrior_rampage', id: 184367 },
    bt: { nm: '피의 갈증', ic: 'spell_nature_bloodlust', id: 23881, rNm: '피범벅', rIc: 'ability_warrior_bloodbath' },
    rblow: { nm: '분노의 강타', ic: 'warrior_wild_strike', id: 85288, rNm: '분쇄의 타격', rIc: 'ability_hunter_swiftstrike' },
    execute: { nm: '마무리 일격', ic: 'inv_sword_48', id: 5308 },
    odyn: { nm: '오딘의 격노', ic: 'inv_sword_1h_artifactvigfus_d_01', id: 385059 },
    bstorm: { nm: '칼날폭풍', ic: 'ability_warrior_bladestorm', id: 46924 },
    ww: { nm: '소용돌이', ic: 'ability_whirlwind', id: 190411 },
    tblast: { nm: '우레 작렬', ic: 'warrior_talent_icon_bloodandthunder' },
    tclap: { nm: '천둥벼락', ic: 'spell_nature_thunderclap', id: 6343 },
  };
  const M = {
    flurry: { nm: '진눈깨비', ic: 'ability_deathknight_chillstreak', id: 44614 },
    iceLance: { nm: '얼음창', ic: 'spell_frost_frostblast', id: 30455 },
    frozenOrb: { nm: '얼어붙은 구슬', ic: 'spell_frost_frozenorb', id: 84714 },
    glacialSpike: { nm: '혹한의 쐐기', ic: 'ability_mage_glacialspike', id: 199786 },
    ray: { nm: '서리 광선', ic: 'ability_mage_rayoffrost', id: 205021 },
    frostbolt: { nm: '얼음 화살', ic: 'spell_frost_frostbolt02', id: 116 },
    blizzard: { nm: '눈보라', ic: 'spell_frost_icestorm', id: 190356 },
  };
  const AURA = {
    enrage: { nm: '격노', ic: 'spell_shadow_unholyfrenzy', id: 184362 },
    reck: { nm: '무모한 희생', ic: 'warrior_talent_icon_innerrage', id: 1719 },
    suddenDeath: { nm: '급살', ic: 'ability_warrior_improveddisciplines', id: 280776 },
    execute: { nm: '처형 구간', ic: 'inv_sword_48' },
    thunder: { nm: '우레 작렬', ic: 'warrior_talent_icon_bloodandthunder' },
    brainFreeze: { nm: '두뇌 빙결', ic: 'ability_mage_brainfreeze', id: 190446 },
    fingers: { nm: '서리의 손가락', ic: 'ability_mage_wintersgrasp', id: 44544 },
    thermal: { nm: '열기 동공', ic: 'spell_mage_thermalvoid', id: 1247730 },
    freezing: { nm: '빙결', ic: 'spell_frost_frostblast' },
    freezingRain: { nm: '빙결의 비', ic: 'spell_frost_icestorm', id: 270233 },
    aoe: { nm: '광역 상황', ic: 'spell_frost_icestorm' },
    targets: { nm: '타겟 수', ic: 'ability_hunter_snipershot' },
  };

  const warriorRules = {
    학살자OFF: [
      { k: 'rampage', c: s => (!s.enraged || s.rage > 100) && s.rage >= 80, w: '비격노 또는 분노캡이면 광란이 최우선입니다.' },
      { k: 'odyn', c: s => s.odynCd <= 0, w: '오딘의 격노는 쿨마다 돌립니다.' },
      { k: 'execute', c: s => s.sd || s.exec, w: '급살 프록 또는 처형 구간입니다.' },
      { k: 'bt', c: s => s.btCd <= 0, w: '피의 갈증 쿨을 놀리지 않습니다.' },
      { k: 'rampage', c: s => s.rage >= 80, w: '분노가 충분하면 광란으로 소모합니다.' },
      { k: 'rblow', c: s => s.rbCharges > 0, w: '분노의 강타 필러입니다.' },
      { k: 'ww', c: () => true, w: '남는 글쿨은 소용돌이입니다.' },
    ],
    학살자ON: [
      { k: 'rampage', c: s => (!s.enraged || s.rage > 100) && s.rage >= 80, w: '버스트 중에도 비격노/분노캡 광란은 최우선입니다.' },
      { k: 'bstorm', c: s => s.bsCd <= 0, w: '무모한 희생 창에는 칼날폭풍을 먼저 씁니다.' },
      { k: 'odyn', c: s => s.odynCd <= 0, w: '오딘의 격노를 버스트 창에 넣습니다.' },
      { k: 'bt', c: s => s.btCd <= 0, w: '피범벅으로 바뀐 피의 갈증을 씁니다.' },
      { k: 'rampage', c: s => s.rage >= 80, w: '분노가 충분하면 광란입니다.' },
      { k: 'execute', c: s => s.sd || s.exec, w: '마무리 일격은 그 다음입니다.' },
      { k: 'rblow', c: s => s.rbCharges > 0, w: '분쇄의 타격 필러입니다.' },
      { k: 'ww', c: () => true, w: '남는 글쿨은 소용돌이입니다.' },
    ],
    학살자AOEOFF: [
      { k: 'odyn', c: s => s.odynCd <= 0, w: '광특 학살자는 오딘의 격노를 쿨마다 굴려 광역 엔진을 시작합니다.' },
      { k: 'tclap', c: s => s.targets >= 6, w: '6타겟 이상 광특에서는 천둥벼락이 단일 자원 규칙보다 앞섭니다.' },
      { k: 'tblast', c: s => s.tbCharges > 0, w: '광특 학살자는 우레 작렬 프록/충전을 광역 우선순위에 넣습니다.' },
      { k: 'bstorm', c: s => s.bsCd <= 0, w: '칼날폭풍은 학살자 광특의 핵심 광역 버튼입니다.' },
      { k: 'rampage', c: s => (!s.enraged || s.rage > 100) && s.rage >= 80, w: '비격노 또는 분노캡이면 광특에서도 광란으로 정리합니다.' },
      { k: 'execute', c: s => s.sd || s.exec, w: '급살 프록 또는 처형 구간입니다.' },
      { k: 'bt', c: s => s.btCd <= 0, w: '피의 갈증 쿨을 놀리지 않습니다.' },
      { k: 'rampage', c: s => s.rage >= 80, w: '분노가 충분하면 광란입니다.' },
      { k: 'rblow', c: s => s.rbCharges > 0, w: '분노의 강타 필러입니다.' },
      { k: 'ww', c: () => true, w: '남는 글쿨은 소용돌이입니다.' },
    ],
    학살자AOEON: [
      { k: 'bstorm', c: s => s.bsCd <= 0, w: '무모한 희생 광역 창에는 칼날폭풍을 먼저 씁니다.' },
      { k: 'odyn', c: s => s.odynCd <= 0, w: '오딘의 격노를 광역 버스트 창에 넣습니다.' },
      { k: 'tclap', c: s => s.targets >= 6, w: '6타겟 이상에서는 천둥벼락이 광역 우선순위로 올라옵니다.' },
      { k: 'tblast', c: s => s.tbCharges > 0, w: '우레 작렬 프록/충전을 소모합니다.' },
      { k: 'rampage', c: s => (!s.enraged || s.rage > 100) && s.rage >= 80, w: '비격노 또는 분노캡이면 광란입니다.' },
      { k: 'execute', c: s => s.sd || s.exec, w: '마무리 일격은 그 다음입니다.' },
      { k: 'bt', c: s => s.btCd <= 0, w: '피범벅으로 바뀐 피의 갈증을 씁니다.' },
      { k: 'rampage', c: s => s.rage >= 80, w: '분노가 충분하면 광란입니다.' },
      { k: 'rblow', c: s => s.rbCharges > 0, w: '분쇄의 타격 필러입니다.' },
      { k: 'ww', c: () => true, w: '남는 글쿨은 소용돌이입니다.' },
    ],
    산왕OFF: [
      { k: 'rampage', c: s => (!s.enraged || s.rage > 100) && s.rage >= 80, w: '비격노 또는 분노캡이면 광란입니다.' },
      { k: 'tblast', c: s => s.tbCharges >= 2, w: '우레 작렬 2충전은 오버캡 방지로 최우선권입니다.' },
      { k: 'bt', c: s => s.btCd <= 0, w: '산왕은 피의 갈증이 엔진입니다.' },
      { k: 'execute', c: s => s.sd || s.exec, w: '급살 프록 또는 처형 구간입니다.' },
      { k: 'tblast', c: s => s.tbCharges >= 1, w: '우레 작렬 1충전을 소모합니다.' },
      { k: 'rampage', c: s => s.rage >= 80, w: '분노가 충분하면 광란입니다.' },
      { k: 'rblow', c: s => s.rbCharges > 0, w: '분노의 강타 필러입니다.' },
      { k: 'tclap', c: () => true, w: '남는 글쿨은 천둥벼락입니다.' },
    ],
    산왕ON: [
      { k: 'odyn', c: s => s.odynCd <= 0, w: '버스트 진입은 오딘의 격노부터 정렬합니다.' },
      { k: 'rampage', c: s => (!s.enraged || s.rage > 100) && s.rage >= 80, w: '비격노 또는 분노캡이면 광란입니다.' },
      { k: 'tblast', c: s => s.tbCharges >= 2, w: '우레 작렬 2충전은 즉시 소모합니다.' },
      { k: 'bt', c: s => s.btCd <= 0, w: '피범벅을 소모합니다.' },
      { k: 'rampage', c: s => s.rage >= 80, w: '분노가 충분하면 광란입니다.' },
      { k: 'tblast', c: s => s.tbCharges >= 1, w: '우레 작렬 1충전을 소모합니다.' },
      { k: 'execute', c: s => s.sd || s.exec, w: '마무리 일격은 뒤쪽입니다.' },
      { k: 'rblow', c: s => s.rbCharges > 0, w: '분쇄의 타격 필러입니다.' },
      { k: 'tclap', c: () => true, w: '남는 글쿨은 천둥벼락입니다.' },
    ],
    산왕AOEOFF: [
      { k: 'tclap', c: s => s.targets >= 6, w: '6타겟 이상 산왕 광특은 천둥벼락을 가장 먼저 누르는 예외 구간입니다.' },
      { k: 'tblast', c: s => s.tbCharges > 0, w: '광특 산왕은 우레 작렬을 광역 엔진으로 빠르게 소모합니다.' },
      { k: 'rampage', c: s => (!s.enraged || s.rage > 100) && s.rage >= 80, w: '비격노 또는 분노캡이면 광특에서도 광란입니다.' },
      { k: 'bt', c: s => s.btCd <= 0, w: '피의 갈증으로 우레 작렬 프록과 산왕 엔진을 굴립니다.' },
      { k: 'execute', c: s => s.sd || s.exec, w: '급살 프록 또는 처형 구간입니다.' },
      { k: 'rampage', c: s => s.rage >= 80, w: '분노가 충분하면 광란입니다.' },
      { k: 'rblow', c: s => s.rbCharges > 0, w: '분노의 강타 필러입니다.' },
      { k: 'tclap', c: () => true, w: '남는 광역 글쿨은 천둥벼락입니다.' },
    ],
    산왕AOEON: [
      { k: 'tclap', c: s => s.targets >= 6, w: '투신/광역 창에서 6타겟 이상이면 천둥벼락이 가장 앞섭니다.' },
      { k: 'odyn', c: s => s.odynCd <= 0, w: '버스트 진입은 오딘의 격노부터 정렬합니다.' },
      { k: 'tblast', c: s => s.tbCharges > 0, w: '우레 작렬 충전을 소모합니다.' },
      { k: 'rampage', c: s => (!s.enraged || s.rage > 100) && s.rage >= 80, w: '비격노 또는 분노캡이면 광란입니다.' },
      { k: 'bt', c: s => s.btCd <= 0, w: '피범벅을 소모합니다.' },
      { k: 'execute', c: s => s.sd || s.exec, w: '마무리 일격은 뒤쪽입니다.' },
      { k: 'rampage', c: s => s.rage >= 80, w: '분노가 충분하면 광란입니다.' },
      { k: 'rblow', c: s => s.rbCharges > 0, w: '분쇄의 타격 필러입니다.' },
      { k: 'tclap', c: () => true, w: '남는 광역 글쿨은 천둥벼락입니다.' },
    ],
  };

  const frostSingleRules = [
    { k: 'iceLance', c: s => s.fingers >= 2, w: '서리의 손가락 2중첩이면 얼음창으로 1개 먼저 털어야 합니다.' },
    { k: 'flurry', c: s => s.brainFreeze && !s.thermalVoid && s.freezing >= 12 && s.flurryCd <= 0, w: '진눈깨비를 쓸 때입니다: 두뇌 빙결 있음, 열기 동공 없음, 빙결 12중첩 이상.' },
    { k: 'frozenOrb', c: s => s.orbCd <= 0, w: '얼어붙은 구슬은 조건이 맞으면 바로바로 털어줍니다.' },
    { k: 'glacialSpike', c: s => s.spikeCd <= 0 && s.fingers < 2, w: '혹한의 쐐기는 서리의 손가락이 2중첩이 아닐 때 씁니다. 2중첩이면 얼음창 1회가 먼저입니다.' },
    { k: 'iceLance', c: s => s.fingers > 0, w: '서리의 손가락 얼음창을 소모합니다.' },
    { k: 'frostbolt', c: s => s.brainFreeze && !s.thermalVoid && s.flurryCd <= 0 && s.freezing < 12 && s.fingers === 0 && s.orbCd > 0 && s.spikeCd > 0 && s.rayCd > 0, w: '두뇌 빙결을 들고 빙결 6~11중첩이면 진눈깨비를 바로 쓰지 말고 얼음 화살로 12중첩까지 올립니다.' },
    { k: 'iceLance', c: s => s.freezing >= 6, w: '빙결 6중첩 이상은 얼음창으로 털 수 있습니다. 단 두뇌 빙결을 들고 6~11중첩이면 12중첩 진눈깨비 준비가 우선입니다.' },
    { k: 'ray', c: s => s.rayCd <= 0, w: '서리 광선은 쿨이 왔으면 바로바로 털어줍니다. 단 서리의 손가락 2중첩이면 얼음창 1회가 먼저입니다.' },
    { k: 'flurry', c: s => s.flurryCd <= 0, w: '남는 창에서는 진눈깨비로 빙결을 다시 쌓습니다.' },
    { k: 'frostbolt', c: () => true, w: '남는 글쿨은 얼음 화살입니다.' },
  ];

  const frostAoeRules = [
    { k: 'blizzard', c: s => s.aoe && s.freezingRain && s.blizzardCd <= 0, w: '빙결의 비 광역이면 눈보라가 먼저입니다.' },
    { k: 'iceLance', c: s => s.fingers >= 2, w: '서리의 손가락 2중첩이면 얼음창으로 1개 먼저 털어야 합니다.' },
    { k: 'flurry', c: s => s.brainFreeze && !s.thermalVoid && s.freezing >= 12 && s.flurryCd <= 0, w: '진눈깨비를 쓸 때입니다: 두뇌 빙결 있음, 열기 동공 없음, 빙결 12중첩 이상.' },
    { k: 'frozenOrb', c: s => s.orbCd <= 0, w: '얼어붙은 구슬은 조건이 맞으면 바로바로 털어줍니다.' },
    { k: 'glacialSpike', c: s => s.spikeCd <= 0 && s.fingers < 2, w: '혹한의 쐐기는 서리의 손가락이 2중첩이 아닐 때 씁니다. 2중첩이면 얼음창 1회가 먼저입니다.' },
    { k: 'iceLance', c: s => s.fingers > 0, w: '서리의 손가락 얼음창을 소모합니다.' },
    { k: 'frostbolt', c: s => s.brainFreeze && !s.thermalVoid && s.flurryCd <= 0 && s.freezing < 12 && s.fingers === 0 && s.orbCd > 0 && s.spikeCd > 0 && s.rayCd > 0, w: '두뇌 빙결을 들고 빙결 6~11중첩이면 진눈깨비를 바로 쓰지 말고 얼음 화살로 12중첩까지 올립니다.' },
    { k: 'iceLance', c: s => s.freezing >= 6, w: '빙결 6중첩 이상은 얼음창으로 털 수 있습니다. 단 두뇌 빙결을 들고 6~11중첩이면 12중첩 진눈깨비 준비가 우선입니다.' },
    { k: 'ray', c: s => s.rayCd <= 0, w: '서리 광선은 쿨이 왔으면 바로바로 털어줍니다. 단 서리의 손가락 2중첩이면 얼음창 1회가 먼저입니다.' },
    { k: 'flurry', c: s => s.flurryCd <= 0, w: '남는 창에서는 진눈깨비로 빙결을 다시 쌓습니다.' },
    { k: 'frostbolt', c: () => true, w: '남는 글쿨은 얼음 화살입니다.' },
  ];

  function dispWarrior(s, k) {
    const a = W[k];
    return s.reck && a.rNm ? { ...a, nm: a.rNm, ic: a.rIc } : a;
  }

  const games = {
    'Warrior|Fury': {
      supports: build => build === '산왕' || build === '학살자',
      title: s => `${s.build} 분노 전사 · ${PROFILE[s.profile || 'single']}`,
      bar: s => {
        if (s.profile === 'aoe') {
          return s.build === '산왕'
            ? ['tclap', 'rampage', 'tblast', 'bt', 'execute', 'rblow', 'odyn']
            : ['odyn', 'tclap', 'tblast', 'bstorm', 'rampage', 'execute', 'bt', 'rblow', 'ww'];
        }
        return s.build === '산왕'
          ? ['rampage', 'tblast', 'bt', 'execute', 'rblow', 'odyn', 'tclap']
          : ['rampage', 'bt', 'execute', 'rblow', 'odyn', 'bstorm', 'ww'];
      },
      display: dispWarrior,
      rules: s => warriorRules[`${s.build}${s.profile === 'aoe' ? 'AOE' : ''}${s.reck ? 'ON' : 'OFF'}`],
      random(build, profile) {
        const aoe = profile === 'aoe';
        return {
          kind: 'warrior', build, profile, targets: aoe ? 3 + ri(6) : 1,
          reck: rb(aoe ? 0.45 : 0.4), exec: rb(0.2),
          rage: Math.floor(Math.random() * 13) * 10,
          enraged: rb(0.55), sd: rb(0.4),
          btCd: rb(0.5) ? 0 : 3, odynCd: rb(0.4) ? 0 : 6,
          bsCd: aoe ? (rb(0.55) ? 0 : 10) : 0,
          rbCharges: ri(3), tbCharges: ri(3),
        };
      },
      actionable(s, k) {
        if (k === 'rampage') return s.rage >= 80;
        if (k === 'bt') return s.btCd <= 0;
        if (k === 'execute') return s.sd || s.exec;
        if (k === 'rblow') return s.rbCharges > 0;
        if (k === 'odyn') return s.odynCd <= 0;
        if (k === 'bstorm') return s.bsCd <= 0 && (s.reck || s.profile === 'aoe');
        if (k === 'tblast') return s.tbCharges > 0;
        return true;
      },
      marker(s, k) {
        if (k === 'execute' && (s.sd || s.exec)) return '!';
        if (k === 'tblast' && s.tbCharges > 0) return String(s.tbCharges);
        if (k === 'tclap' && s.profile === 'aoe' && s.targets >= 6) return `${s.targets}T`;
        if (k === 'rampage' && s.rage >= 80 && (!s.enraged || s.rage > 100)) return '★';
        return '';
      },
      stateChips(s) {
        const out = [
          { ...AURA.enrage, on: s.enraged, pulse: s.enraged },
          { ...AURA.reck, on: s.reck, pulse: s.reck },
        ];
        if (s.sd) out.push({ ...AURA.suddenDeath, on: true, pulse: true, badge: '!' });
        if (s.exec) out.push({ ...AURA.execute, on: true, pulse: true, badge: '20' });
        if (s.profile === 'aoe') out.push({ ...AURA.targets, on: true, pulse: s.targets >= 6, badge: `${s.targets}T` });
        if (s.build === '산왕' || s.profile === 'aoe') out.push({ ...AURA.thunder, on: s.tbCharges > 0, pulse: s.tbCharges > 0, badge: s.tbCharges || '' });
        return out;
      },
      resource(s) {
        return { label: '분노', value: s.rage, pct: Math.min(100, s.rage / 1.2), cls: s.rage >= 100 ? 'warn' : '' };
      },
      unavailable(s, k) {
        if (k === 'rampage') return '분노 80 미만입니다.';
        if (k === 'bt' || k === 'odyn') return '쿨다운 중입니다.';
        if (k === 'execute') return '급살 프록도 처형 구간도 아닙니다.';
        if (k === 'rblow' || k === 'tblast') return '충전이 없습니다.';
        if (k === 'bstorm') return s.profile === 'aoe' ? '쿨다운 중입니다.' : '무모한 희생 창에서만 우선순위에 들어옵니다.';
        return '지금은 우선순위가 아닙니다.';
      },
    },
    'Mage|Frost': {
      supports: build => build === '주문술사',
      title: s => `주문술사 냉법 · ${PROFILE[s.profile || 'single']}`,
      bar: s => s.profile === 'aoe'
        ? ['blizzard', 'flurry', 'iceLance', 'frozenOrb', 'glacialSpike', 'ray', 'frostbolt']
        : ['flurry', 'iceLance', 'frozenOrb', 'glacialSpike', 'ray', 'frostbolt'],
      display: (s, k) => M[k],
      rules: s => s.profile === 'aoe' ? frostAoeRules : frostSingleRules,
      random(build, profile) {
        const brainFreeze = rb(0.45);
        const aoe = profile === 'aoe';
        const s = {
          kind: 'frost', build, profile, aoe,
          brainFreeze, thermalVoid: rb(0.33), fingers: ri(3),
          freezing: ri(21), orbCd: rb(0.45) ? 0 : 8,
          spikeCd: rb(0.4) ? 0 : 6, rayCd: rb(0.35) ? 0 : 22,
          flurryCd: brainFreeze || rb(0.7) ? 0 : 9,
          blizzardCd: rb(0.55) ? 0 : 10,
        };
        s.freezingRain = aoe && rb(0.65);
        return s;
      },
      actionable(s, k) {
        if (k === 'blizzard') return s.profile === 'aoe' && s.freezingRain && s.blizzardCd <= 0;
        if (k === 'flurry') return s.flurryCd <= 0;
        if (k === 'iceLance') return s.fingers > 0 || s.freezing >= 6;
        if (k === 'frozenOrb') return s.orbCd <= 0;
        if (k === 'glacialSpike') return s.spikeCd <= 0;
        if (k === 'ray') return s.rayCd <= 0;
        return true;
      },
      marker(s, k) {
        if (k === 'flurry' && s.brainFreeze) return 'BF';
        if (k === 'iceLance' && s.fingers > 0) return String(s.fingers);
        if (k === 'iceLance' && s.freezing >= 6) return '6+';
        if (k === 'frostbolt' && s.brainFreeze && !s.thermalVoid && s.freezing < 12) return '12';
        if (k === 'blizzard' && s.freezingRain) return '비';
        return '';
      },
      stateChips(s) {
        const out = [
          { ...AURA.brainFreeze, on: s.brainFreeze, pulse: s.brainFreeze },
          { ...AURA.fingers, on: s.fingers > 0, pulse: s.fingers > 0, badge: s.fingers || '' },
          { ...AURA.thermal, on: s.thermalVoid, pulse: s.thermalVoid },
          { ...AURA.freezing, on: s.freezing >= 6, pulse: s.freezing >= 6, badge: s.freezing },
        ];
        if (s.aoe) out.push({ ...AURA.aoe, on: true });
        if (s.freezingRain) out.push({ ...AURA.freezingRain, on: true, pulse: true });
        return out;
      },
      resource(s) {
        return { label: '빙결', value: s.freezing, pct: Math.min(100, s.freezing * 5), cls: s.freezing >= 12 ? 'warn' : '' };
      },
      unavailable(s, k) {
        if (k === 'iceLance') return '서리의 손가락이 없고 빙결도 6중첩 미만입니다.';
        if (k === 'flurry') return '진눈깨비 충전이 없습니다.';
        if (k === 'blizzard') return '빙결의 비 광역 상황이 아닙니다.';
        if (k === 'frozenOrb' || k === 'glacialSpike' || k === 'ray') return '쿨다운 중입니다.';
        return '지금은 우선순위가 아닙니다.';
      },
    },
  };

  function gameFor(cls, spec, build) {
    const g = games[`${cls}|${spec}`];
    return g && g.supports(build) ? g : null;
  }

  window.rotGameSupports = function (cls, spec, build) {
    return !!gameFor(cls, spec, build);
  };

  function correctRule(game, s) {
    const rules = game.rules(s);
    for (const r of rules) if (r.c(s)) return r;
    return rules[rules.length - 1];
  }

  function tierOf(game, s, k) {
    const rules = game.rules(s);
    for (let i = 0; i < rules.length; i++) if (rules[i].k === k) return i + 1;
    return rules.length;
  }

  function injectStyle() {
    if (document.getElementById('rg-style')) return;
    const css = `
.rg-ov{position:fixed;inset:0;z-index:9999;background:rgba(7,8,12,.92);display:flex;align-items:center;justify-content:center;font-family:inherit}
.rg-box{position:relative;width:min(820px,94vw);max-height:94vh;overflow:auto;background:#14161d;border:1px solid #343846;border-radius:10px;padding:20px 22px;color:#e9ecf4;box-shadow:0 20px 70px rgba(0,0,0,.55)}
.rg-top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px}.rg-title{font-size:17px;font-weight:700}.rg-badge{font-size:12px;font-weight:700;padding:3px 10px;border-radius:20px;background:#262a35;color:#d8dcec}.rg-x{margin-left:auto;cursor:pointer;background:none;border:none;color:#9aa0ad;font-size:22px;line-height:1}
.rg-state{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:10px;font-size:12px;color:#b9bfcc}.rg-resbar{flex:1;min-width:150px;height:14px;background:#242834;border-radius:7px;overflow:hidden}.rg-resfill{height:100%;background:#6aa6ff}.rg-resfill.warn{background:#e5aa39}
.rg-aura{display:flex;gap:11px;flex-wrap:wrap;margin:0 0 14px;padding:12px;background:#0d0f15;border:1px solid #252936;border-radius:8px}.rg-aura-ic{position:relative;width:44px;height:44px;border-radius:7px;border:2px solid #272b35;background:#111;opacity:.38}.rg-aura-ic.on{opacity:1;border-color:#f0c85c;box-shadow:0 0 14px rgba(240,200,92,.62),inset 0 0 9px rgba(255,240,160,.25)}.rg-aura-ic.on.pulse{border-color:#ffd15f;box-shadow:0 0 12px rgba(255,209,95,.9),0 0 26px rgba(255,176,62,.48),inset 0 0 10px rgba(255,240,174,.3);animation:rg-aura-glow .95s ease-in-out infinite}.rg-aura-ic.on.pulse:after{content:"";position:absolute;inset:-6px;border-radius:12px;border:1px solid rgba(255,224,122,.68);pointer-events:none}@keyframes rg-aura-glow{0%,100%{filter:brightness(1)}50%{filter:brightness(1.35)}}.rg-aura-ic img{width:100%;height:100%;border-radius:5px;display:block}.rg-bubble{position:absolute;right:-8px;bottom:-8px;min-width:22px;height:22px;padding:0 5px;border-radius:11px;background:#f0c85c;color:#141414;font-size:11px;font-weight:900;display:flex;align-items:center;justify-content:center;border:1px solid #111}
.rg-timer{height:8px;background:#242834;border-radius:5px;overflow:hidden;margin:6px 0 12px}.rg-timerfill{height:100%;background:#5dade2;width:100%;animation:rgtimer 5s linear forwards}@keyframes rgtimer{from{width:100%}to{width:0}}
.rg-mode{margin:6px 0 12px;padding:8px 10px;border:1px solid #2b3140;border-radius:7px;background:#10131a;color:#aeb5c3;font-size:12px}.rg-btn.sm{padding:6px 11px;font-size:12px}.rg-btn:disabled{opacity:.55;cursor:default}
.rg-profiles{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px}.rg-prof{cursor:pointer;border:1px solid #384050;background:#191d26;color:#d8ddec;border-radius:7px;padding:7px 13px;font-size:12px;font-weight:800}.rg-prof.active{border-color:#d19b38;background:#493315;color:#fff0c6;box-shadow:0 0 12px rgba(209,155,56,.24)}
.rg-tip{position:relative}.rg-tooltip{position:fixed;z-index:10050;width:360px;max-width:calc(100vw - 24px);padding:13px 14px;border-radius:8px;border:1px solid #4b5365;background:#070a10;color:#e9ecf4;box-shadow:0 18px 46px rgba(0,0,0,.72);font-size:13px;line-height:1.5;text-align:left;pointer-events:none;opacity:1}.rg-tooltip[hidden]{display:none}.rg-tt-head{display:flex;align-items:center;gap:10px;margin-bottom:9px}.rg-tt-head img{width:34px;height:34px;border-radius:6px;border:1px solid #596173;box-shadow:0 0 10px rgba(255,209,95,.2)}.rg-tt-title{font-size:14px;font-weight:800;color:#fff4c2}.rg-tt-lines{display:grid;gap:4px;color:#dce2ee;white-space:pre-line}.rg-tt-line:first-child{display:none}.rg-tt-wow{margin-top:10px;padding-top:9px;border-top:1px solid #2a2f3b;color:#9fb5d8;font-size:12px}
.rg-hint{font-size:13px;color:#cdd2dd;margin:0 0 10px}.rg-prog{font-size:12px;color:#9aa0ad}.rg-bar{display:grid;grid-template-columns:repeat(auto-fit,minmax(76px,1fr));gap:12px;padding:15px;background:#0d0f15;border:1px solid #252936;border-radius:8px}
.rg-tile{text-align:center;cursor:pointer;user-select:none}.rg-ic{width:58px;height:58px;border-radius:8px;margin:0 auto;background-size:cover;background-position:center;border:2px solid #272b35;position:relative;box-shadow:inset 0 0 0 1px rgba(255,255,255,.08)}.rg-tile.live .rg-ic{border-color:#ffd15f;box-shadow:0 0 10px rgba(255,209,95,.75),0 0 22px rgba(255,176,62,.32),inset 0 0 8px rgba(255,240,174,.25);animation:rg-glow 1.25s ease-in-out infinite}.rg-tile.live .rg-ic:after{content:"";position:absolute;inset:-5px;border-radius:12px;border:1px solid rgba(255,224,122,.55);pointer-events:none}@keyframes rg-glow{0%,100%{filter:brightness(1)}50%{filter:brightness(1.22)}}.rg-tile.dim{cursor:not-allowed}.rg-tile.dim .rg-ic{filter:grayscale(1) brightness(.45);border-color:#20242d}.rg-nm{font-size:11px;margin-top:5px;color:#d7dbe6;line-height:1.15}.rg-tile.dim .rg-nm{color:#6d7380}.rg-mk{position:absolute;top:-8px;right:-8px;min-width:20px;height:20px;padding:0 5px;border-radius:10px;background:#ffd15f;color:#111;font-size:10px;font-weight:900;display:flex;align-items:center;justify-content:center;border:1px solid #111}
.rg-msg{text-align:center;font-size:14px;font-weight:700;min-height:22px;margin-top:12px}.rg-ok{color:#69db8f}
.rg-fail{position:absolute;inset:0;background:rgba(11,9,11,.94);border-radius:10px;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:26px;text-align:center;animation:rgpop .2s ease}@keyframes rgpop{from{opacity:0;transform:scale(.98)}to{opacity:1;transform:none}}.rg-failh{font-size:20px;font-weight:800;color:#ff8585;margin-bottom:10px}.rg-answer{display:flex;align-items:center;gap:10px;justify-content:center;margin-bottom:10px}.rg-mini{width:34px;height:34px;border-radius:5px;border:2px solid #ffd15f;box-shadow:0 0 10px rgba(255,209,95,.55)}.rg-failw{font-size:14px;color:#e9ecf4;line-height:1.6;max-width:590px;margin-bottom:6px}.rg-failsub{font-size:12px;color:#9aa0ad;margin-bottom:18px}.rg-btns{display:flex;gap:10px;flex-wrap:wrap;justify-content:center}.rg-btn{cursor:pointer;background:#282d38;border:1px solid #464d5d;color:#e9ecf4;border-radius:7px;padding:9px 18px;font-size:13px;font-weight:700}.rg-btn.pri{background:#9a6b16;border-color:#bd8a2b;color:#fff0c6}
.rg-res h3{font-size:18px;margin:0 0 4px}.rg-grade{font-size:13px;color:#c9ced8;margin-bottom:12px}.rg-miss{max-height:42vh;overflow:auto;border-top:1px solid #2a2f3b;padding-top:10px;margin-bottom:14px}.rg-row{display:flex;gap:8px;font-size:12.5px;padding:7px 0;border-bottom:1px solid #222733;line-height:1.45}.rg-step{color:#8e95a3;min-width:34px}`;
    const st = document.createElement('style');
    st.id = 'rg-style';
    st.textContent = css;
    document.head.appendChild(st);
  }

  const el = (html) => {
    const d = document.createElement('div');
    d.innerHTML = html.trim();
    return d.firstChild;
  };

  function refreshWowhead() {
    const refresh = () => {
      try { window.$WowheadPower?.refreshLinks?.(); } catch (_) { /* external widget */ }
    };
    if (window.$WowheadPower) {
      refresh();
      return;
    }
    if (window.__wh_loading) return;
    window.__wh_loading = true;
    const s = document.createElement('script');
    s.src = 'https://wow.zamimg.com/widgets/power.js';
    s.onload = refresh;
    document.head.appendChild(s);
  }

  function gameTooltip() {
    let node = document.getElementById('rg-tooltip');
    if (!node) {
      node = document.createElement('div');
      node.id = 'rg-tooltip';
      node.className = 'rg-tooltip';
      node.hidden = true;
      document.body.appendChild(node);
    }
    return node;
  }

  function placeTooltip(target, node) {
    const margin = 10;
    const gap = 12;
    const r = target.getBoundingClientRect();
    node.style.left = '0px';
    node.style.top = '0px';
    const t = node.getBoundingClientRect();
    let left = r.left + (r.width / 2) - (t.width / 2);
    let top = r.bottom + gap;
    if (top + t.height > window.innerHeight - margin) top = r.top - t.height - gap;
    left = Math.max(margin, Math.min(left, window.innerWidth - t.width - margin));
    top = Math.max(margin, Math.min(top, window.innerHeight - t.height - margin));
    node.style.left = `${left}px`;
    node.style.top = `${top}px`;
  }

  function showGameTip(target) {
    const text = target.getAttribute('data-tip') || '';
    const lines = text.split('\n').map(v => v.trim()).filter(Boolean);
    const title = target.getAttribute('data-tip-title') || lines[0] || '';
    const icon = target.getAttribute('data-tip-icon') || '';
    const spellId = target.getAttribute('data-spell-id') || '';
    const node = gameTooltip();
    node.innerHTML = `
      <div class="rg-tt-head">
        ${icon ? `<img src="${SMALL(icon)}" alt="">` : ''}
        <div class="rg-tt-title">${esc(title)}</div>
      </div>
      <div class="rg-tt-lines">${lines.map(line => `<div class="rg-tt-line">${esc(line)}</div>`).join('')}</div>
      ${spellId ? `<div class="rg-tt-wow">Wowhead 주문 툴팁 연결됨 · spell ${esc(spellId)}</div>` : ''}`;
    node.hidden = false;
    placeTooltip(target, node);
  }

  function hideGameTip() {
    const node = document.getElementById('rg-tooltip');
    if (node) node.hidden = true;
  }

  function bindTips(root) {
    if (!root) return;
    root.querySelectorAll('.rg-tip[data-tip]').forEach(node => {
      if (node.dataset.tipBound) return;
      node.dataset.tipBound = '1';
      node.addEventListener('mouseenter', () => showGameTip(node));
      node.addEventListener('focus', () => showGameTip(node));
      node.addEventListener('mouseleave', hideGameTip);
      node.addEventListener('blur', hideGameTip);
    });
    refreshWowhead();
  }

  function auraTip(c) {
    const lines = [c.nm, c.on ? '활성' : '비활성'];
    if (c.badge !== undefined && c.badge !== '') lines.push(`표시: ${c.badge}`);
    return lines.join('\n');
  }

  function skillTip(game, s, k, live, mark) {
    const d = game.display(s, k);
    const lines = [d.nm, live ? '현재 사용 가능' : game.unavailable(s, k)];
    if (mark) lines.push(`아이콘 표시: ${mark}`);
    return lines.join('\n');
  }

  function auraHtml(chips) {
    return `<div class="rg-aura">${chips.map(c => `
      <div class="rg-aura-ic rg-tip ${c.on ? 'on' : ''} ${c.pulse ? 'pulse' : ''}" ${tipAttrs(c, auraTip(c))} tabindex="0">
        <img src="${SMALL(c.ic)}" alt="">
        ${c.badge !== undefined && c.badge !== '' ? `<span class="rg-bubble">${c.badge}</span>` : ''}
      </div>`).join('')}</div>`;
  }

  function answerHtml(game, s, k) {
    const d = game.display(s, k);
    return `<span class="rg-answer rg-tip" ${tipAttrs(d, d.nm)} tabindex="0"><img class="rg-mini" src="${IMG(d.ic)}" alt=""><b>${d.nm}</b></span>`;
  }

  function profileButtons(profile) {
    return `<div class="rg-profiles">
      ${Object.entries(PROFILE).map(([k, label]) =>
        `<button class="rg-prof ${profile === k ? 'active' : ''}" type="button" data-profile="${k}">${label}</button>`
      ).join('')}
    </div>`;
  }

  window.openRotGame = function (cls, spec, build) {
    const game = gameFor(cls, spec, build);
    if (!game) {
      alert('이 딜사이클 문제풀이는 아직 지원하지 않는 전문화입니다.');
      return;
    }
    injectStyle();
    let s, cr, no, correct, miss, timer, resolved, timed, profile = 'single';
    const ov = el('<div class="rg-ov"></div>');
    const box = el('<div class="rg-box"></div>');
    ov.appendChild(box);
    document.body.appendChild(ov);
    ov.addEventListener('click', e => { if (e.target === ov) close(); });

    function close() { clearTimeout(timer); hideGameTip(); ov.remove(); }
    function restart() { no = 0; correct = 0; miss = []; timed = false; next(); }
    function switchProfile(nextProfile) {
      if (!PROFILE[nextProfile] || nextProfile === profile) return;
      profile = nextProfile;
      restart();
    }
    function startTimer() {
      clearTimeout(timer);
      if (timed && !resolved) timer = setTimeout(onTimeout, LIMIT);
    }
    function startTimedTest() {
      if (timed || resolved) return;
      timed = true;
      renderPlay();
      startTimer();
    }
    function next() {
      clearTimeout(timer);
      resolved = false;
      if (no >= STEPS) { renderResult(); return; }
      no++;
      s = game.random(build, profile);
      cr = correctRule(game, s);
      renderPlay();
      startTimer();
    }

    function renderPlay() {
      hideGameTip();
      const res = game.resource(s);
      const tiles = game.bar(s).map(k => {
        const d = game.display(s, k);
        const live = game.actionable(s, k);
        const mk = game.marker(s, k);
        return `<div class="rg-tile rg-tip ${live ? 'live' : 'dim'}" data-k="${k}" ${tipAttrs(d, skillTip(game, s, k, live, mk))} tabindex="0">
          <div class="rg-ic" style="background-image:url('${IMG(d.ic)}')">${mk ? `<span class="rg-mk">${mk}</span>` : ''}</div>
          <div class="rg-nm">${d.nm}</div>
        </div>`;
      }).join('');
      box.innerHTML = `
        <div class="rg-top">
          <span class="rg-title">${game.title(s)} 문제풀이</span>
          <span class="rg-badge">${build}</span>
          <span class="rg-badge">${timed ? '5초 테스트' : '연습 모드'}</span>
          <span class="rg-prog">${no} / ${STEPS} · 정답 ${correct}</span>
          <button class="rg-btn sm" id="rg-test" type="button" ${timed ? 'disabled' : ''}>${timed ? '5초 테스트 중' : '5초 테스트 시작'}</button>
          <button class="rg-x" title="종료">×</button>
        </div>
        ${profileButtons(profile)}
        ${auraHtml(game.stateChips(s))}
        <div class="rg-state">
          <span>${res.label}</span>
          <div class="rg-resbar"><div class="rg-resfill ${res.cls}" style="width:${res.pct}%"></div></div>
          <span>${res.value}</span>
        </div>
        ${timed ? '<div class="rg-timer"><div class="rg-timerfill"></div></div>' : '<div class="rg-mode">시간 제한 없음 · 버프와 스킬 아이콘에 마우스를 올려 현재 상태를 확인하세요.</div>'}
        <div class="rg-hint">노란 테두리로 빛나는 아이콘 중 <b>지금 1순위</b>를 클릭</div>
        <div class="rg-bar">${tiles}</div>
        <div class="rg-msg" id="rg-msg"></div>`;
      box.querySelector('.rg-x').onclick = close;
      box.querySelector('#rg-test').onclick = startTimedTest;
      box.querySelectorAll('.rg-prof').forEach(b => {
        b.onclick = () => switchProfile(b.getAttribute('data-profile'));
      });
      box.querySelectorAll('.rg-tile').forEach(t => {
        t.onclick = () => { if (!resolved) pick(t.getAttribute('data-k')); };
      });
      bindTips(box);
    }

    function wrongWhy(k) {
      const pressed = game.display(s, k).nm;
      if (!game.actionable(s, k)) {
        return `${pressed}: ${game.unavailable(s, k)}`;
      }
      return `${game.display(s, cr.k).nm}이 더 우선입니다. ${cr.w} 누른 ${pressed}은 ${tierOf(game, s, k)}순위입니다.`;
    }

    function pick(k) {
      resolved = true;
      clearTimeout(timer);
      if (k === cr.k) {
        correct++;
        const m = box.querySelector('#rg-msg');
        if (m) {
          m.className = 'rg-msg rg-ok';
          m.innerHTML = timed
            ? `정답 ${answerHtml(game, s, cr.k)}`
            : `정답 ${answerHtml(game, s, cr.k)} <button class="rg-btn sm" id="rg-ok-next" type="button">다음 문제</button>`;
        }
        bindTips(m);
        box.querySelectorAll('.rg-tile').forEach(t => { t.onclick = null; });
        if (timed) setTimeout(next, 500);
        else box.querySelector('#rg-ok-next').onclick = next;
        return;
      }
      const why = wrongWhy(k);
      const answer = game.display(s, cr.k);
      miss.push({ no, answer, why });
      showFail('오답', why);
    }

    function onTimeout() {
      if (resolved) return;
      resolved = true;
      const why = `${game.display(s, cr.k).nm}: ${cr.w}`;
      const answer = game.display(s, cr.k);
      miss.push({ no, answer, why: `시간 초과. ${why}` });
      showFail('시간 초과', why);
    }

    function showFail(head, why) {
      const fail = el(`<div class="rg-fail">
        <div class="rg-failh">${head}</div>
        ${answerHtml(game, s, cr.k)}
        <div class="rg-failw">${why}</div>
        <div class="rg-failsub">${no} / ${STEPS} · 정답 ${correct}</div>
        <div class="rg-btns">
          <button class="rg-btn pri" id="rg-nx">다음 문제</button>
          <button class="rg-btn" id="rg-rs">다시하기</button>
          <button class="rg-btn" id="rg-cl">종료</button>
        </div>
      </div>`);
      box.appendChild(fail);
      bindTips(fail);
      fail.querySelector('#rg-nx').onclick = next;
      fail.querySelector('#rg-rs').onclick = restart;
      fail.querySelector('#rg-cl').onclick = close;
    }

    function renderResult() {
      hideGameTip();
      const pct = Math.round(correct / STEPS * 100);
      const grade = pct >= 95 ? 'S - 거의 완벽' : pct >= 85 ? 'A - 숙련' : pct >= 70 ? 'B - 무난' : pct >= 50 ? 'C - 연습 필요' : 'D - 우선순위 재숙지';
      const rows = miss.length ? miss.map(m =>
        `<div class="rg-row"><span class="rg-step">#${m.no}</span><img class="rg-mini" src="${IMG(m.answer.ic)}" alt=""><span>${m.why}</span></div>`
      ).join('') : '<div class="rg-row" style="color:#69db8f">틀린 곳 없음</div>';
      box.innerHTML = `
        <div class="rg-top"><span class="rg-title">${game.title({ build, profile })} 결과</span><button class="rg-x">×</button></div>
        <div class="rg-res">
          <h3>${correct} / ${STEPS} 정답 (${pct}%)</h3>
          <div class="rg-grade">등급 ${grade}</div>
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
