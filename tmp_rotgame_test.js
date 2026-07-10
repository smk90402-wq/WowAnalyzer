// rotgame 룰 정합성 테스트 (게이트 1 자동화):
// 모든 게임×빌드×프로필에서 무작위 상태 N개 → 정답 룰이 항상 actionable 인지,
// 마지막 폴백까지 도달 불가능한 상태가 없는지 확인.
const stub = {
  addEventListener() {}, appendChild() {}, removeChild() {},
  createElement: () => ({ style: {}, set innerHTML(v) {}, appendChild() {}, remove() {}, addEventListener() {}, querySelectorAll: () => [], querySelector: () => null, setAttribute() {}, getBoundingClientRect: () => ({}) }),
  getElementById: () => null, querySelectorAll: () => [], querySelector: () => null,
  head: { appendChild() {} }, body: { appendChild() {} },
};
global.window = { addEventListener() {} };
global.document = stub;
require('./app/static/rotgame.js');

// 내부 games 객체에 접근할 수 없으므로 파일을 다시 읽어 eval 로 노출
const fs = require('fs');
let src = fs.readFileSync('./app/static/rotgame.js', 'utf8');
src = src.replace("window.rotGameSupports = function", "window.__games = games; window.rotGameSupports = function");
eval(src);
const games = global.window.__games;

let bad = 0, total = 0;
for (const [key, game] of Object.entries(games)) {
  const builds = { 'Warrior|Fury': ['산왕', '학살자'], 'Warrior|Arms': ['학살자', '거신'], 'Mage|Frost': ['주문술사'] }[key] || [];
  for (const build of builds) {
    for (const profile of ['single', 'aoe']) {
      for (let i = 0; i < 5000; i++) {
        total++;
        const s = game.random(build, profile);
        const rules = game.rules(s);
        if (!rules) { console.log(`RULES 없음: ${key} ${build} ${profile}`); bad++; break; }
        let cr = null;
        for (const r of rules) if (r.c(s)) { cr = r; break; }
        if (!cr) cr = rules[rules.length - 1];
        if (!game.actionable(s, cr.k)) {
          bad++;
          if (bad < 8) console.log(`모순: ${key} ${build} ${profile} 정답=${cr.k} 인데 사용 불가`, JSON.stringify(s));
        }
      }
    }
  }
}
console.log(`검사 ${total}건, 모순 ${bad}건`);
process.exit(bad ? 1 : 0);
