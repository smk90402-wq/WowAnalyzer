"""분노 전사 프록 우선순위 치트시트 위젯(HTML) — 색상 타일+약어 (이미지 없음, 안정적).

각 스킬 = 색상 타일(역할별 색) + 약어 + 한글명 + 조건. 무모한 희생 ON/OFF 분리.
출력: data/tmp_fury_cheatsheet.html (show_widget에 그대로 투입)
"""
# 스킬 → (약어, 배경색 600-stop, 변형 표시군)
SK = {
    '광란': ('광란', '#A32D2D'),
    '우레 작렬': ('우레', '#185FA5'),
    '피의 갈증': ('갈증', '#993556'),
    '피범벅': ('피범', '#993556'),
    '마무리 일격': ('처형', '#854F0B'),
    '분노의 강타': ('강타', '#993C1D'),
    '분쇄의 타격': ('분타', '#993C1D'),
    '천둥벼락': ('천둥', '#0F6E56'),
    '소용돌이': ('회전', '#5F5E5A'),
    '오딘의 격노': ('오딘', '#534AB7'),
    '칼날폭풍': ('칼폭', '#3B6D11'),
    '분쇄': ('분쇄', '#888780'),
}


def tile(n, name, cond, accent=False, xfrom=None):
    abbr, bg = SK[name]
    ring = 'box-shadow:0 0 0 2px var(--color-text-warning)' if accent else ''
    bnum = 'bg1' if accent else 'bg0'
    xf = f'<div class="xf">←{xfrom}</div>' if xfrom else ''
    return (f'<div class="tile"><div class="iw">'
            f'<div class="ic" style="background:{bg};{ring}">{abbr}</div>'
            f'<span class="num {bnum}">{n}</span></div>'
            f'<div class="nm">{name}</div><div class="cd">{cond}</div>{xf}</div>')


def strip(tiles):
    return f'<div class="strip">{"".join(tiles)}</div>'


def section(title, sub, off, on_head, on):
    return (f'<div class="sec"><div class="sh"><span class="st">{title}</span>'
            f'<span class="ss">{sub}</span></div>'
            f'<div class="ph"><i class="ti ti-flame" aria-hidden="true"></i> 평상시 (무모한 희생 OFF)</div>'
            f'{strip(off)}'
            f'<div class="ph on"><i class="ti ti-bolt" aria-hidden="true"></i> 무모한 희생 ON — {on_head}</div>'
            f'{strip(on)}</div>')


sl_off = [tile(1, '광란', '비격노/캡', accent=True), tile(2, '오딘의 격노', '쿨마다'),
          tile(3, '마무리 일격', '급살/처형'), tile(4, '피의 갈증', '쿨마다'),
          tile(5, '광란', '일반'), tile(6, '분쇄', '5초↓ 1회'),
          tile(7, '분노의 강타', '필러'), tile(8, '소용돌이', '최하위')]
sl_on = [tile(1, '광란', '비격노/캡', accent=True), tile(2, '칼날폭풍', '+폭풍망치'),
         tile(3, '오딘의 격노', '쿨'), tile(4, '피범벅', '변형', xfrom='피의 갈증'),
         tile(5, '광란', '일반'), tile(6, '마무리 일격', '처형'),
         tile(7, '분쇄의 타격', '변형', xfrom='분노의 강타')]
mt_off = [tile(1, '광란', '비격노/캡', accent=True), tile(2, '우레 작렬', '2충전'),
          tile(3, '피의 갈증', '쿨·엔진'), tile(4, '마무리 일격', '급살/처형'),
          tile(5, '우레 작렬', '1충전'), tile(6, '광란', '일반'),
          tile(7, '분노의 강타', '필러'), tile(8, '천둥벼락', '최하위')]
mt_on = [tile(1, '오딘의 격노', '버스트'), tile(2, '광란', '비격노/캡', accent=True),
         tile(3, '우레 작렬', '2충전'), tile(4, '피범벅', '변형', xfrom='피의 갈증'),
         tile(5, '광란', '일반'), tile(6, '우레 작렬', '충전'),
         tile(7, '마무리 일격', '처형'), tile(8, '분쇄의 타격', '변형', xfrom='분노의 강타'),
         tile(9, '천둥벼락', '필러')]

html = f'''<style>
.ic{{width:46px;height:46px;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:15px;font-weight:500;letter-spacing:-0.5px}}
.tile{{width:64px;flex:0 0 64px;text-align:center}}.iw{{position:relative;width:46px;height:46px;margin:0 auto}}
.num{{position:absolute;top:-7px;left:-7px;width:19px;height:19px;border-radius:50%;font-size:11px;font-weight:500;display:flex;align-items:center;justify-content:center;border:1px solid var(--color-background-primary)}}
.bg1{{background:var(--color-text-warning);color:#fff}}.bg0{{background:var(--color-text-primary);color:var(--color-background-primary)}}
.nm{{font-size:11px;font-weight:500;color:var(--color-text-primary);line-height:1.15;margin-top:4px}}
.cd{{font-size:9.5px;color:var(--color-text-secondary);line-height:1.1}}.xf{{font-size:9px;color:var(--color-text-tertiary);line-height:1.1}}
.strip{{display:flex;align-items:flex-start;gap:9px;flex-wrap:wrap;padding:11px 12px;background:var(--color-background-secondary);border-radius:var(--border-radius-md)}}
.sec{{margin-bottom:1.4rem}}.sh{{display:flex;align-items:baseline;gap:8px;margin-bottom:8px}}
.st{{font-size:16px;font-weight:500;color:var(--color-text-primary)}}.ss{{font-size:12px;color:var(--color-text-secondary)}}
.ph{{font-size:12px;font-weight:500;color:var(--color-text-secondary);margin:0 0 6px 2px}}.ph.on{{color:var(--color-text-warning);margin-top:10px}}
</style>
<h2 class="sr-only">분노 전사 산왕·학살자 프록 우선순위를 누르는 순서대로 정리한 치트시트</h2>
<div style="padding:0.5rem 0">
<div style="background:var(--color-background-info);color:var(--color-text-info);font-size:12.5px;font-weight:500;padding:8px 12px;border-radius:var(--border-radius-md);margin-bottom:1.2rem">
0순위 규칙 — 비격노거나 분노 100 초과면 무엇보다 먼저 ①광란. 그 외엔 위에서부터 '지금 되는(빛나는)' 첫 버튼.
</div>
{section('🗡 학살자', '단일 · 천둥벼락 없음, 소용돌이가 필러', sl_off, '칼날폭풍 격노 상태에서 쿨마다', sl_on)}
{section('⚡ 산왕', '단일 · 소용돌이 없음, 천둥벼락이 필러 · 투신 동반', mt_off, '투신+무모한 희생+오딘 함께', mt_on)}
<div style="font-size:11px;color:var(--color-text-tertiary);line-height:1.6;margin-top:0.3rem">
①②③… = 누르는 순서(위가 우선) · <span style="color:var(--color-text-warning)">노란 ①</span> = 항상 최우선 체크 · 변형(←) = 무모한 희생 중 자동 교체(피의 갈증→피범벅, 분노의 강타→분쇄의 타격) · 광역 6타겟+ 산왕은 천둥벼락 도배
</div></div>'''

open('data/tmp_fury_cheatsheet.html', 'w', encoding='utf-8').write(html)
print('len(html)=', len(html))
