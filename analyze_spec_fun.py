"""스펙 재미 분석 — 유튜브 10개 영상(2026-06~07, 한밤 12.x) 재미 평가 큐레이션 + 로그 실측 대조.

메타탭(성능/파스)과 별개로 "이 스펙이 재미있는가"를 다룸.
 - yt_score: 영상들의 재미 평가 컨센서스 (0~5). 갈리면 split_note 에 명시.
 - 축(1~5, 영상 근거 직접 정리): impact 타격감 / proc 프록·도박 / burst 폭딜맛 /
   flow 로테 흐름 / fantasy 연출·판타지
 - mobility 는 큐레이션이 아니라 로그 실측(spec_difficulty_v2 move_pen 역산).
 - verify: 영상 주장을 로그 실측(APM·버튼수·스킬순서다양성·킬CV·이동민감)으로 대조한 결과.

자막 원문: data/transcripts/fun_1~10.txt
출력: data/spec_fun.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA = Path(__file__).parent / "data"

SOURCES = [
    {"id": "V1", "channel": "Vesp", "title": "I Ranked The MOST FUN DPS in Midnight (27스펙 전체)", "url": "https://www.youtube.com/watch?v=lZB2tejQLtM"},
    {"id": "V6", "channel": "Vesp", "title": "The MOST FUN Spec in Midnight (부정 심층)", "url": "https://www.youtube.com/watch?v=FwW6_RPkAaw"},
    {"id": "V9", "channel": "Vesp", "title": "The 4 MOST FUN DPS Specs in Midnight", "url": "https://www.youtube.com/watch?v=Eib82TCAO8w"},
    {"id": "K2", "channel": "KaidGames", "title": "RANKING MOST FUN CLASSES IN MIDNIGHT", "url": "https://www.youtube.com/watch?v=eMJM2QHVyfY"},
    {"id": "K10", "channel": "KaidGames2", "title": "MOST FUN CLASSES SEASON 1 (갱신판)", "url": "https://www.youtube.com/watch?v=9LphBAjyoTU"},
    {"id": "MF3", "channel": "Marcelian&Flame", "title": "Most FUN Ranged DPS Tier List", "url": "https://www.youtube.com/watch?v=cJpg_k7OE7I"},
    {"id": "MF7", "channel": "Marcelian&Flame", "title": "TOP 5 DPS To Main in Midnight", "url": "https://www.youtube.com/watch?v=Q_hSAubsQUk"},
    {"id": "DD4", "channel": "The Drowsy Dragon", "title": "3 MOST Fun DPS In Midnight", "url": "https://www.youtube.com/watch?v=97vUW75LDRM"},
    {"id": "P8", "channel": "Petko", "title": "The MOST FUN RANGED to Main", "url": "https://www.youtube.com/watch?v=sYfsoIxa7Rw"},
    {"id": "RM5", "channel": "Recoil Mojo", "title": "Ranked Every Spec by FUN (PvP 시점 — 참고)", "url": "https://www.youtube.com/watch?v=nXCathWCKbM"},
]

# (class, spec): dict —
#   yt: 컨센서스 0~5 / n: 언급 영상 수 / impact·proc·burst·flow·fantasy: 1~5 큐레이션
#   note: 한줄평 / split: 평가 갈림 메모("" 가능) / verify: 로그 실측 대조
#   yt_notes: [(출처id, 평가, 요지), ...]
FUN: dict[tuple[str, str], dict] = {
    ("Hunter", "Survival"): dict(
        yt=5.0, n=7, impact=5, proc=3.5, burst=3.5, flow=4.5, fantasy=3,
        note="10영상 중 유일하게 전원 상위권 — 붐스틱 한 방 + 물 흐르는 로테",
        split="",
        verify="✓ '로테가 물 흐르듯' — 버튼 18개인데 1분에 50번 정도라 손이 급하지 않음. 붐스틱 손맛은 로그로 잴 수 없어 영상 평가 그대로 둠",
        yt_notes=[
            ("V1", "S", "붐스틱은 게임 최고의 버튼 중 하나, 폭탄이 쿨을 계속 돌려줌. 단점: 테이크다운 쿨기가 밋밋한 뎀증"),
            ("K10", "Giga Fun", "로테 흐름·프록·붐스틱 '누르는 게 웃김'. 샷건 컨셉이 판타지랑 안 맞는 건 옥에 티"),
            ("DD4", "추천 3선", "생존력도 진짜 좋아짐. 단일/광 로테가 비슷해 장기 지루함 가능성은 언급"),
        ]),
    ("Priest", "Shadow"): dict(
        yt=4.5, n=6, impact=4, proc=4, burst=4, flow=4.5, fantasy=5,
        note="Vesp 전체 1위 — 촉수·유령 군단 연출 + 적당한 복잡도",
        split="",
        verify="✓ '복잡도가 딱 적당' — 버튼 22개, 누르는 순서도 다채로운 편이라 말과 데이터가 맞음. 움직이면서 딜하기도 원딜 중 자유로운 편",
        yt_notes=[
            ("V1", "S(1위)", "복잡도가 딱 적당, 유령 군단 연출. 촉수 슬램 아펙스는 '게임 최고'"),
            ("P8", "원딜 1위", "비주얼 압도적, 머리 덜 쓰고 최대치 뽑기 좋아짐, 차단 기본 제공"),
            ("MF3", "중상", "정체성(단일이냐 광이냐)이 애매한 건 아쉬움 — 마인드 시어 그리움"),
        ]),
    ("Warlock", "Affliction"): dict(
        yt=4.5, n=7, impact=4, proc=4, burst=4, flow=4, fantasy=4,
        note="리워크 대성공 — 도트 스펙 정체성 복귀 + 씨앗 연쇄폭발",
        split="",
        verify="✓ 1분에 46번으로 손은 가장 한가한 축인데 재미 평가는 최상위 — '느긋하게 도트 깔다 씨앗 한 방' 스타일이라, 재미가 손 바쁨과는 별개임을 보여주는 스펙. 무빙에도 강한 편",
        yt_notes=[
            ("V9", "top4", "영혼조각이 넘쳐서 못 쓸 지경(좋은 문제). 씨앗 3연발 터지는 맛"),
            ("DD4", "추천 1선", "도트가 다시 주인공. 다크 하베스트가 딜+힐 동시에. 단점: 도트 연장 수단 없어 갱신 노동"),
            ("MF7", "top5", "'가장 강한 도트를 계속 얹는' 흑마 본연의 맛"),
        ]),
    ("Death Knight", "Unholy"): dict(
        yt=4.3, n=6, impact=5, proc=3.5, burst=4.5, flow=4, fantasy=5,
        note="네크로맨서 판타지 완성 + 역병 폭발 한 방 — 단 평가 갈림",
        split="Vesp '전부 맞물리는 최고 근딜' vs Kaid '자동으로 굴러가서 할 게 없다' — 같은 자동화를 정반대로 읽음",
        verify="△ 갈림의 정체 — 데이터를 보면 킬마다 딜이 거의 안 출렁이고(안정 1위권) 알아서 잘 굴러가는 스펙. 이걸 '편하다'로 읽으면 Vesp, '심심하다'로 읽으면 Kaid — 둘 다 맞는 말",
        yt_notes=[
            ("V6", "최애 후보", "역병 폭발(페스틸런스)은 '게임에서 가장 만족스러운 버튼'. 근딜인데 원거리서 로테 대부분 가능"),
            ("K2", "Not Great", "자동화에 선택권을 뺏김 — '스펙이 알아서 행군'"),
            ("DD4", "추천 2선", "타겟 스왑 개선·디시즈 자동 유지 등 설계 칭찬. 아펙스 비주얼은 아쉬움"),
        ]),
    ("Rogue", "Outlaw"): dict(
        yt=4.3, n=5, impact=3, proc=5, burst=3, flow=4, fantasy=3.5,
        note="'한밤 최대 반전' — 프록이 쉴 새 없이 터지는 도박 스펙",
        split="Recoil Mojo만 롤더본 자체를 싫어함(구식 도적 취향)",
        verify="✓ '쉴 틈이 없다' — 킬마다 딜 출렁임이 전체 2위(운빨 크고), 1분에 68번으로 손도 바쁨. 도박 스펙이라는 말이 데이터 그대로",
        yt_notes=[
            ("MF7", "top5", "'무작위와 우스꽝스러운 재미의 등대'. 롤더본 버프가 서열화돼 스트레스 없이 도박만 남음"),
            ("K10", "Giga Fun", "프록이 끊이지 않아 페이스가 안 죽음 — 지루할 틈이 없다"),
            ("V1", "A", "다음 버튼 생각할 게 항상 있어 완전 몰입. 잭팟은 '로또 당첨'"),
        ]),
    ("Warlock", "Demonology"): dict(
        yt=4.2, n=5, impact=3.5, proc=2.5, burst=4, flow=3.5, fantasy=5,
        note="'게임 최고의 클래스 판타지' — 아르거스 차원문에서 악마 군단 소환",
        split="",
        verify="✓ 킬마다 딜이 안정적 — 티란트 한 방이 정해진 대로 터지는 스펙이라 연출은 화려해도 딜은 매번 비슷하게 나옴. '판타지 최고'는 전 영상이 동의",
        yt_notes=[
            ("MF3", "Giga Fun(1위)", "판타지 최고 — 아르거스에서 악마 소환. 임프 3마리 돌려주는 To Hell and Back 최애"),
            ("V1", "A", "티란트가 차원문 열고 군단장·핏로드·임프 군단 소환 — 스펙 판타지 1등"),
            ("P8", "원딜 3위", "요즘 진짜 부드럽고 쉬움, 차단 2개 옵션 등 QoL 대폭"),
        ]),
    ("Demon Hunter", "Devourer"): dict(
        yt=4.0, n=5, impact=4, proc=2, burst=4, flow=3, fantasy=4.5,
        note="신스펙 — 미친 기동성 + 별 떨어뜨리는 한 방. 단 단순 스팸 우려",
        split="Kaid·M&F·Mojo 최상위 vs Vesp C('비주얼이 밋밋한 로테를 캐리')",
        verify="✓ Vesp가 '단순 스팸'이라며 C 준 게 데이터로도 확인 — 버튼 11개, 누르는 순서 다양함 둘 다 전체 꼴찌. '기동성 미쳤다'도 사실 — 움직여도 딜 손해가 원딜 중 가장 적은 축",
        yt_notes=[
            ("MF7", "top5", "자원 저글링(분노+영혼)이 신선, 로테 암기가 아니라 위치·계획으로 실력 표현"),
            ("V1", "C", "붕괴하는 별은 '핵 떨어뜨리는' 최고의 한 방인데 나머지가 스팸 — 물릴 수 있음"),
            ("K10", "Giga Fun", "기동성 미쳤고 빌드마다 플레이가 진짜 다름"),
        ]),
    ("Mage", "Frost"): dict(
        yt=3.8, n=6, impact=3.5, proc=3.5, burst=3, flow=4, fantasy=3.5,
        note="'단순한 스펙을 재밌게 만드는 교과서' — 빙결 스택 셰터 엔진",
        split="Kaid '한밤 최고 설계' vs Vesp '밋밋한 일직선'(아이시 베인 상실 큼)",
        verify="△ 갈림의 정체 — 킬마다 딜 출렁임이 전체에서 가장 작음 = 굴곡 없는 스펙. '믿음직하다'와 '밋밋하다'는 같은 데이터를 다르게 읽은 것",
        yt_notes=[
            ("K10", "Giga Fun", "캡스톤+플러리·아이스랜스 상호작용으로 엔진 전체가 맞물림"),
            ("MF7", "top5", "빙결 20스택 쌓고 한 번에 깨는 맛. 한 키에 스킬이 변신(레이 오브 프로스트→혜성폭풍)"),
            ("V1", "C", "아이시 베인 삭제가 뼈아픔, 전반적으로 평평한 느낌"),
        ]),
    ("Shaman", "Enhancement"): dict(
        yt=3.8, n=4, impact=5, proc=4, burst=4, flow=4, fantasy=4.5,
        note="'한밤 리워크 최고 성공작' — 템페스트는 게임 최고 손맛 버튼",
        split="",
        verify="✓ '만족스럽게 복잡함' — 버튼 20개, 1분에 83번, 누르는 순서 다양함까지 전부 최상위권. 손 많이 가는 재미가 데이터 그대로. 대신 킬마다 딜 출렁임은 큰 편",
        yt_notes=[
            ("K10", "Giga Fun", "예전엔 귀찮게 복잡했는데 지금은 만족스럽게 복잡함. 비주얼·사운드 최고"),
            ("V1", "B", "템페스트는 '누르면 느껴지는' 게임 최고 피드백 버튼"),
        ]),
    ("Evoker", "Devastation"): dict(
        yt=3.6, n=4, impact=5, proc=3, burst=5, flow=4, fantasy=4,
        note="'버튼 하나에 큰 숫자' 클래식 감성 — 초반 몰빵 폭딜",
        split="MF3 '붕괴별 한 방 최고' vs 너프로 재미까지 죽었다는 불만 병존",
        verify="✓ '한 방 큰 숫자' — 킬마다 딜 출렁임이 큰 편. 초반에 폭딜을 몰빵하는 구조라 잘 터진 킬과 아닌 킬 차이가 큼",
        yt_notes=[
            ("P8", "원딜 2위", "컨슘 플레임 선폭딜이 타 스펙 2배 수준, 호버로 무빙 캐스팅"),
            ("MF3", "Giga Fun", "옛날 파이로·카오스볼트 같은 '누르면 미터기가 오르는' 몇 안 남은 스펙"),
            ("V1", "B", "플레임셰이퍼는 전부 맞물리는데 스케일커맨더 딥브레스는 '미화된 다운타임'"),
        ]),
    ("Rogue", "Subtlety"): dict(
        yt=3.6, n=4, impact=3.5, proc=3, burst=4.5, flow=3, fantasy=3.5,
        note="쉐도우 댄스 충전으로 '욕심 vs 정확' 선택하는 폭딜 창",
        split="Kaid Giga Fun vs Vesp '게임에서 제일 기본적인 빌드-스펜더'",
        verify="△ Vesp의 '단순하다'는 데이터와 맞음 — 누르는 순서 다양함이 하위권. 대신 폭딜 창은 킬마다 안정적으로 터짐",
        yt_notes=[
            ("K10", "Giga Fun", "유연한 폭딜 창이 게임 최고 메커니즘 — 얼마나 욕심낼지 내가 결정"),
            ("V1", "B", "버튼 하나로 콤보 다 차서 생각할 게 없음, 댄스 숙련 표현도 사라짐"),
        ]),
    ("Druid", "Feral"): dict(
        yt=3.5, n=3, impact=3.5, proc=4, burst=3, flow=5, fantasy=4,
        note="Vesp S — '전부 맞물리는' 출혈 흐름 + 스냅샷 숙련 유지",
        split="",
        verify="✓ '전부 맞물린다' — 누르는 순서가 다채로운 상위권. 단 킬마다 딜 출렁임이 전체 1위 — 잘 풀린 킬과 망한 킬 차이가 제일 큰 도박 스펙이기도 함",
        yt_notes=[
            ("V1", "S", "로테가 초부드럽게 흐르고 립 틱이 공짜 피니셔 프록을 계속 뱉음"),
            ("K2", "Okay", "여전히 야성답긴 한데 한밤 신규 요소가 임팩트 부족"),
        ]),
    ("Shaman", "Elemental"): dict(
        yt=3.5, n=4, impact=4, proc=4, burst=4, flow=3, fantasy=5,
        note="'세상을 번개로 밝히는' 연출 최고봉 — 단 단순화 논쟁",
        split="MF3 '캐스터판 야수냥이 됐다'(과단순화) vs Vesp A(볼타익 블레이즈 중독성)",
        verify="△ '너무 단순해졌다'는 말 대비 버튼 17개로 중간은 됨. 진짜 문제는 움직일 때 딜 손해가 전체 최악권 — 연출은 최고인데 무빙 구간이 고통",
        yt_notes=[
            ("V1", "A", "9~11초마다 광역 용암폭발, 시각적으로 게임 최고 스펙 중 하나"),
            ("MF3", "하위", "너무 단순해져서 팔 게 없음 — 고양이 보여준 가능성을 정술은 놓침"),
        ]),
    ("Death Knight", "Frost"): dict(
        yt=3.5, n=3, impact=3.5, proc=4, burst=4, flow=4.5, fantasy=3.5,
        note="킬링머신 프록 리듬 + 빌더-스펜더 저글링",
        split="",
        verify="✓ '프록 리듬' — 버튼 21개, 누르는 순서도 다채로운 상위권. 대신 움직일 때 딜 손해가 전체 최악권이라 무빙 보스에선 재미가 스트레스로 바뀔 수 있음",
        yt_notes=[
            ("V1", "B", "모든 버튼이 다음 버튼에 영향 — 리듬감. 프로스트사이드 광역 맛"),
            ("K2", "Fun", "만족스러운 프록 흐름과 강한 리듬, 사이클마다 변주"),
        ]),
    ("Mage", "Arcane"): dict(
        yt=3.5, n=5, impact=3, proc=3, burst=4, flow=3.5, fantasy=3,
        note="빌드 따라 재미가 극과 극 — 미사일 빌드 A vs 오브 빌드 F",
        split="Kaid '캡스톤 설계 최고' vs Vesp '오브 빌드는 RNG 막히면 손가락만 빤다'",
        verify="✓ 'RNG 막히면 손가락만 빤다'(Vesp)가 데이터 그대로 — 킬마다 딜 출렁임 전체 최악. 운 좋은 킬과 아닌 킬 차이가 가장 큰 스펙",
        yt_notes=[
            ("K10", "Giga Fun", "탤런트가 자원 생성-소비 방식 자체를 바꿈 — 최상급 설계"),
            ("V1", "B", "미사일 빌드는 A, 오브 빌드는 20% 실패 확률에 발 묶이는 F"),
        ]),
    ("Warrior", "Fury"): dict(
        yt=3.2, n=3, impact=3.5, proc=3, burst=4, flow=4, fantasy=4,
        note="람페이지 연타 폭주 기관차 — 더 크고 더 사나워짐",
        split="",
        verify="✓ '미친 속도' — 1분에 74번, 버튼 22개. 람페이지 연타라는 말이 데이터 그대로",
        yt_notes=[
            ("V1", "B", "무모한 희생 중 람페이지를 좌우연타 — 초고속. 오딘의 분노는 밋밋"),
            ("K2", "Fun", "리워크 없이도 더 크고 사납게 — 이미 좋던 걸 증폭"),
        ]),
    ("Warrior", "Arms"): dict(
        yt=3.2, n=3, impact=4, proc=3, burst=3.5, flow=3.5, fantasy=3.5,
        note="드디어 쿨기가 정렬됨 + 데몰리시 '콜로서스 손맛'",
        split="",
        verify="✓ '쿨기가 맞물린다' — 누르는 순서 다양함 전체 1위. 버튼 조합이 가장 다채로운 스펙",
        yt_notes=[
            ("V1", "B", "데몰리시는 게임 최고 손맛 버튼 중 하나 — '피의 콜로서스'"),
            ("K2", "Fun", "클리브 감각과 히로익 스트라이크 한 방이 스프레드시트 이상"),
        ]),
    ("Rogue", "Assassination"): dict(
        yt=3.3, n=3, impact=3, proc=2.5, burst=3, flow=3, fantasy=3,
        note="가장 개선된 스펙 중 하나 — 단 '심심해질 수 있음' 공통 지적",
        split="",
        verify="△ 1분에 79번(전체 3위)으로 손은 바쁜데 누르는 순서 다양함은 하위 — '같은 걸 빠르게 반복'하는 스펙. 단순한데 바쁨",
        yt_notes=[
            ("V1", "B", "크림슨 템페스트 리워크로 확 나아짐. 다만 메인으론 물릴 만큼 단순"),
            ("K2", "Fun", "독·출혈 암살자 판타지는 확실"),
        ]),
    ("Demon Hunter", "Havoc"): dict(
        yt=3.2, n=2, impact=4, proc=3, burst=3.5, flow=3.5, fantasy=4,
        note="알드라치 12연격 사운드 + 백투백 데스 스윕",
        split="",
        verify="△ Kaid는 '가지치기됐다'는데 버튼은 24개로 전체 최다 — 체감과 데이터가 어긋나는 케이스. '왜 딜하다 말고 대쉬로 빠져야 하냐'는 불만은 로그로 못 잼",
        yt_notes=[
            ("V1", "B", "아이빔→블레이드 댄스 리셋으로 연속 스윕. '전부 조각내는' 오디오"),
            ("K2", "Fun", "게임에서 가장 멋진 콤보 순간들 — 다만 상위 티어엔 못 미침"),
        ]),
    ("Monk", "Windwalker"): dict(
        yt=3.0, n=3, impact=3.5, proc=3, burst=3.5, flow=4.5, fantasy=4,
        note="'진짜 무술가처럼 콤보가 이어짐' — 단 개성 상실 논쟁",
        split="Vesp '콤보 맛 확실' vs Kaid '매끈해진 대신 개성 잃음'",
        verify="✓ '콤보 무술가' — 누르는 순서 다양함 전체 2위. 콤보 연계가 데이터로도 최상위",
        yt_notes=[
            ("V1", "B", "RSK+FoF가 드래곤 펀치로, 그게 또 다음으로 — MMA 콤보 그 자체"),
            ("K2", "Okay", "무빙 플러리시들이 사라져 개성이 죽음"),
        ]),
    ("Druid", "Balance"): dict(
        yt=3.2, n=4, impact=3, proc=3, burst=3, flow=2.5, fantasy=2.5,
        note="'감탄은 하는데 중독은 안 되는' 설계 — 일식 강제 휴식기 불만",
        split="",
        verify="✓ 불만의 핵심(일식 사이 강제 휴식)은 로그에 안 잡히지만, 나머지는 원만 — 킬마다 딜 안정적, 무빙에도 강한 편. 문제는 '내 맘대로 못 한다'는 느낌",
        yt_notes=[
            ("V1", "B", "스펜더끼리 서로 공짜 프록 — 좋음. 근데 일식 밖 10~20초는 '젖은 국수'"),
            ("MF3", "중간", "일식 충전 설계는 다른 스펙이 배워야 할 '역블로트' 모범"),
        ]),
    ("Paladin", "Retribution"): dict(
        yt=2.8, n=3, impact=4, proc=3.5, burst=3.5, flow=3, fantasy=4,
        note="'불꽃놀이' 화려함 vs '자동운전' — 극단으로 갈리는 스펙",
        split="Vesp B(단순-but-화려의 모범, 신성한 목적 프록 최애) vs Kaid 최하(수동적·밋밋·자동운전)",
        verify="△ 데이터는 Vesp 쪽 — 1분에 84.5번으로 전체에서 손이 제일 바쁨. '자동운전'과는 거리가 멂. 다만 같은 버튼을 반복하는 비중이 높은 것도 사실",
        yt_notes=[
            ("V1", "B", "온 세상이 불꽃놀이 — 심플하지만 프록(신성한 목적)이 계속 터짐"),
            ("K2", "Not Fun", "한밤에서 루프가 거의 안 바뀜 — 수동적이고 밋밋"),
        ]),
    ("Evoker", "Augmentation"): dict(
        yt=2.8, n=4, impact=2, proc=2, burst=3, flow=3, fantasy=3,
        note="'지원 판타지'가 취향을 극단으로 가름 — 흑룡 컨셉 vs 남 좋은 일",
        split="MF3 '미니블러드러스트+분신 연장 전례없는 재미' vs Vesp 'DPS로 안 침' vs Mojo '내가 버스 타고 싶지 태우기 싫다'",
        verify="△ 재미 갈림은 취향 문제. 다만 '아군 챙기는 게 일의 대부분'인 건 사실(특임 부담 전체 1위) — 내 딜 보는 재미를 원하면 비추, 지원하는 재미면 유일무이",
        yt_notes=[
            ("MF3", "상위", "흑룡이 돼서 시간 조작 — 크로노맨서 미니블러드러스트가 별미"),
            ("V1", "C", "잘 만든 서포터인데 '진짜 DPS'로 분류 안 함"),
        ]),
    ("Mage", "Fire"): dict(
        yt=2.5, n=4, impact=3, proc=3, burst=3.5, flow=3, fantasy=3.5,
        note="'독한 전 애인' — 좋아하던 걸 다 뺏긴 스펙",
        split="Kaid만 Fun(핫 스트릭 맛 유지), 나머지는 과가지치기 혹평",
        verify="✓ '버튼 3개'는 과장이지만 방향은 맞음 — 버튼 14개 하위권. 움직일 때 딜 손해도 전체 최악. '쿨기를 내 맘대로 못 쓴다'는 불만은 로그 밖이지만 혹평과 방향이 같음",
        yt_notes=[
            ("V1", "C", "빠르고 몰입되긴 하는데 쿨기 통제력이 사라짐 — 그게 스킬 표현의 전부였는데"),
            ("MF3", "하위", "'계속 생각나는 독한 전 애인' — 뼈에 살이 없다, 12.1 리워크 기도 중"),
        ]),
    ("Warlock", "Destruction"): dict(
        yt=2.3, n=5, impact=3, proc=2.5, burst=3, flow=2.5, fantasy=3.5,
        note="'2타겟 왕'이지만 제일 밋밋한 흑마 — 새 장난감 없음",
        split="",
        verify="✓ '제자리 포탑' — 무빙 보스에서 딜 손해가 없는 유일한 축(제자리 캐스팅 설계라 남들이 손해 볼 때 상대적 이득). 밋밋하다는 평가와 구조가 맞아떨어짐",
        yt_notes=[
            ("V1", "C", "비주얼은 만족스러운데 기본 빌더-스펜더라 금방 물림"),
            ("MF3", "하위", "말할수록 한 티어 더 내리고 싶어짐 — 디시메이션 삭제가 뼈아픔"),
        ]),
    ("Hunter", "Marksmanship"): dict(
        yt=1.5, n=4, impact=2, proc=2, burst=2.5, flow=2, fantasy=2.5,
        note="'재밌는 버전을 보여주고 뺏어간' 스펙 — 과가지치기 혹평 일색",
        split="",
        verify="✓ '느려지고 밋밋해짐' 그대로 — 1분에 41번, 버튼 14개, 둘 다 전체 최저권. '너무 많이 깎아냈다'는 평이 데이터로 확인되는 대표 사례",
        yt_notes=[
            ("V1", "D", "폭발 사격·스트림라인 삭제, 래피드 파이어는 뎀 없는 필러 — '블리자드 머리로 그게 말이 되냐'"),
            ("MF3", "하위", "스크랩된 첫 아펙스(프록이 프록을 낳는 설계)가 '게임 최고였을 것' — 왜 뺏었나"),
        ]),
    ("Hunter", "Beast Mastery"): dict(
        yt=1.3, n=5, impact=1, proc=1, burst=2, flow=1.5, fantasy=2.5,
        note="재미 평가 전체 꼴찌 — '알아서 굴러가는 밍밍한 수프'",
        split="Recoil Mojo(PvP·레벨링 렌즈)만 1픽 — 펫 강력·런앤건·태그 편의",
        verify="✓ '알아서 굴러간다' — 킬마다 딜이 거의 안 출렁이고(최저권) 움직임도 자유. 성능·파스(메타탭 상위)와 재미 평가(꼴찌)가 정반대인 대표 스펙 — 본캐 참고",
        yt_notes=[
            ("V1", "F", "'아무도 BM을 더 쉽게 해달라고 안 했다' — 바브드 샷 상호작용 전부 삭제, 하이라이트 없는 일직선"),
            ("K2", "Not Fun", "혼자 플레이되는 스펙 — 프록 순간도, 결정할 것도 없음"),
            ("RM5", "1픽", "(PvP 렌즈) 확팩 초 펫은 항상 사기 + 런앤건·카이팅 맛"),
        ]),
}


def main() -> None:
    v2 = {(r["class"], r["spec"]): r
          for r in json.loads((DATA / "spec_difficulty_v2.json").read_text(encoding="utf-8"))["rows"]}
    kr = {(r["class"], r["spec"]): r["kr"] for r in v2.values()}

    rows = []
    for (cls, spec), f in FUN.items():
        m = v2.get((cls, spec), {})
        move_pen = m.get("move_pen")
        rows.append({
            "class": cls, "spec": spec, "kr": kr.get((cls, spec), f"{cls} {spec}"),
            "yt_score": f["yt"], "yt_n": f["n"],
            "impact": f["impact"], "proc": f["proc"], "burst": f["burst"],
            "flow": f["flow"], "fantasy": f["fantasy"],
            # mobility 는 실측: 이동 잦은 보스에서 딜 유지력 (move_pen 역산 0~5)
            "mobility": round((1 - move_pen) * 5, 1) if move_pen is not None else None,
            "note": f["note"], "split_note": f["split"], "verify": f["verify"],
            "yt_notes": [{"src": s, "tier": t, "text": x} for s, t, x in f["yt_notes"]],
            "log": {k: m.get(k) for k in ("apm", "unique_spells", "bigram_entropy", "avg_cv", "move_pen")},
        })
    rows.sort(key=lambda r: -r["yt_score"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    out = {
        "_meta": {
            "date": "2026-07-03",
            "sources": SOURCES,
            "method": "유튜브 10영상에서 스펙별 재미 평가·이유 추출(자막 원문 data/transcripts/fun_*.txt) → "
                      "컨센서스 0~5 산정, 갈리면 split_note. 축 5개는 영상 근거 직접 정리(1~5), "
                      "mobility 만 로그 실측(move_pen 역산). verify = 영상 주장 vs 로그 실측 대조.",
            "caveat": "재미는 주관 — 점수보다 갈림(split)과 근거를 볼 것. RM5는 PvP 렌즈라 가중 낮음. "
                      "K2/K10 은 같은 채널의 재업이라 사실상 한 목소리.",
        },
        "rows": rows,
    }
    p = DATA / "spec_fun.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved -> {p.name} ({len(rows)} specs)")

    try:
        from update_log import record
        record(action="analyze_spec_fun", params={"videos": len(SOURCES)},
               result={"specs": len(rows), "top": rows[0]["kr"], "bottom": rows[-1]["kr"]},
               files=["data/spec_fun.json"])
    except Exception as e:
        print(f"[update_log] skip: {e}")


if __name__ == "__main__":
    main()
