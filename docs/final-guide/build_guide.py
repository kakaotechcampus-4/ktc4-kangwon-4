"""Build the editable guide, a self-contained HTML manual, PDF, and test CSV."""
import csv
import html
import json
import re
from pathlib import Path
from collections import defaultdict
from base64 import b64encode

from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, Color, white
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, Table, TableStyle
from PIL import Image

from content import PAGES, TESTS, page

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[1]
OUTPDF=ROOT/'리본_서비스_전체_설명서.pdf'
WIDTH,HEIGHT=960,640
INK=HexColor('#191f28'); MUTED=HexColor('#59616d'); BRAND=HexColor('#be3d00'); PALE=HexColor('#fff3eb')
pdfmetrics.registerFont(TTFont('GuideKR','/Users/choidamul/Library/Fonts/NanumBarunGothic.ttf'))
pdfmetrics.registerFontFamily('GuideKR',normal='GuideKR',bold='GuideKR',italic='GuideKR',boldItalic='GuideKR')

API_ROWS=[
 ('GET','/login/form','로그인','카카오로 redirect, state 전달'),('POST','/login','콜백','code 교환, 토큰은 응답 헤더'),
 ('POST','/reissue','API 공통','Refresh-Token으로 재발급'),('POST','/logout','인증','서비스 로그아웃'),
 ('POST','/cases','진단 완료','Case·첫 PENDING 생성, 배경 판단'),('GET','/cases','진입·홈·상세','현재 확정 상태와 판단 상태'),
 ('GET','/cases/results','결과 입력','질문·충돌·선택형 가능 여부'),('POST','/cases/results','결과 입력','입력 접수, 최신 이력 검증'),
 ('GET','/cases/results/status','처리·반영 결과','history 번호로 판단 결과 확인'),('POST','/cases/results/decision','충돌 확인','항목별 선택 접수 후 재판단'),
 ('POST','/cases/retry','실패 복구','허용 실패 이력을 PENDING으로 재개'),('GET','/cases/logs','홈 활동·기록','사용자와 리본 작업 이력'),
 ('GET','/cases/roadmap','전체 순서','5단계·26개 작업 정의의 상태 조회'),('PUT','/cases/checklists/{task_id}','개별 작업','사용자 체크 기록·취소'),
 ('PUT','/cases/support-approval','심사 결과','true·false·null의 1차 결과 기록'),('PUT','/cases/closure-report','폐업 정보','실제 폐업일·사유·주소 저장'),
 ('PUT','/cases/deposit-return','보증금','FULL·PARTIAL·NONE 기록'),('GET','/cases/documents','서류함·점검','문서와 현재 점검 상태 조회'),
 ('POST','/cases/documents','서류 올리기','multipart 파일, 선택적 종류 hint'),('POST','/cases/documents/{document_id}/confirm','서류 확인','종류·확인값 저장, 조항 변경 재판단'),
 ('DELETE','/cases/documents/{document_id}','서류 빼기','문서 제거 및 이전 점검 무효화'),('POST','/cases/documents/check','서류 점검','신청인·실제 폐업일로 규칙 대조'),
 ('GET','/cases/documents/settlement.zip','제출 파일','통과·현재 digest 확인 후 ZIP'),('GET','/health','운영 상태','status 문자열, DB 접속 검사는 아님'),
]

roadmap_tasks=json.loads((ROOT/'roadmap-tasks.json').read_text())
flow_override={'before_photo':'서류함 연결 후 체크','contractor_documents':'서류함 연결 후 체크','closure_certificate':'서류함 연결 후 체크','support_approval':'1차 심사 결과 선택','closure_submission':'폐업 정보 기록','deposit_settlement':'보증금 반환 결과','document_check':'서류 점검','intake':'진단 정보 안내','closure_date':'시기 정보 안내'}
for offset in [0,13]:
    page(f'전체 작업 목록 {offset+1}부터 {offset+13}', '단계별 26개 정의와 입력 방식', [], [
        ('해당 여부는 서버가 정함','이 표는 전체 작업 정의입니다. 가게마다 해당 없음·확인 필요·진행 상태가 달라집니다. 실행의 우선순위는 현재 판단을 확인해야 하며 단계 번호만으로 실제 실행 순서를 확정하지 않습니다.'),
    ],['backend/app/agent/roadmap.py','frontend/src/lib/taskFlows.ts'],'기능 목록')
    PAGES[-1]['task_table']=[['단계','작업 ID','작업 이름','입력과 연결']]+[[str(t['stage']),t['id'],t['title'],flow_override.get(t['id'],'결과 전달과 재판단' if t['procedure_codes'] else '체크와 완료 취소')] for t in roadmap_tasks[offset:offset+13]]

page('API와 화면 연결 첫 번째','인증과 Case 판단',[],[
 ('판단 결과 6종', '결과 제출 응답의 result는 PENDING·UPDATED·NO_CHANGE·NEEDS_MORE_INFO·CONFLICT·FAILED입니다. 조회 시 judgment_status의 DONE과 결과 제출의 UPDATED는 같은 이름의 enum이 아닙니다. 타입과 표시를 adapter에서 구분합니다.'),
 ('HTTP와 업무 결과', 'HTTP 성공은 요청을 처리했다는 뜻이고, AI 업무 결과는 본문으로 확인합니다. 401은 인증, 404는 Case·이력 부재, 409는 낡은 판단·동시 진행·충돌 등 상태 문제, 422는 입력·업무 조건 불일치로 나눠 다룹니다.'),
],['backend/app/be/routers/auth.py','backend/app/be/routers/case.py'], 'API 표')
PAGES[-1]['table']=[['방식','API','화면','역할'], *API_ROWS[:12]]
page('API와 화면 연결 두 번째','로드맵과 서류',[],[
 ('문서 API의 범위', '업로드와 점검은 별도 요청입니다. 문서를 올렸다고 점검 통과나 기관 제출이 되지 않습니다. 원상복구 조항의 변경은 별도의 판단을 예약할 수 있지만, 금액 대조만으로 계획을 다시 돌리는 것은 아닙니다.'),
 ('소유권과 연결 기준', 'Case ID를 사용자가 자유롭게 골라 조작하게 하지 않고 인증된 회원의 Case를 찾습니다. 문서 UUID와 숫자 Case ID 연결, 최신 history와 충돌 참조의 일치 검사를 서버에서 수행합니다.'),
],['backend/app/be/routers/case.py','backend/app/be/routers/document.py'], 'API 표')
PAGES[-1]['table']=[['방식','API','화면','역할'], *API_ROWS[12:]]

page('이번 버전의 검증 결과','2026년 11월 7일 로컬 검증',[],[
 ('Frontend', 'npm test: 46개 파일, 658개 테스트 통과. npm run build: TypeScript 검사와 Vite 빌드 성공. npm run lint: 통과. jsdom의 문서 이동 미지원 출력은 있었지만 테스트 실패는 없었습니다.'),
 ('Backend', 'backend에서 Python 3.12 환경으로 python -m pytest tests -q 실행. 1,098 passed, 7 skipped, 7 warnings, 163.78초. 격리 MySQL 컨테이너를 사용하는 API·서비스·동시성 테스트도 포함합니다. 건너뛴 7개는 PERF=1에서만 실행하는 커넥션 부하 5개와 로드맵 성능 비교 2개입니다.'),
 ('UI 캡처', '최신 소스의 로컬 Vite 화면을 402×874 CSS 픽셀, 2배 해상도에서 실행했습니다. 로그인·진단 9종·주요 화면·시트·실패·미지원·완료 등 47장과 긴 화면 원본을 함께 보관합니다. 캡처 실행의 브라우저 pageerror는 0건입니다.'),
 ('해석의 범위', '자동 테스트는 모델 응답을 대체해 코드 계약과 보호 동작을 검증합니다. 실제 모델 정확도·응답 비용·운영 카카오 로그인·실제 사장님 사용성은 이번에 새로 측정하지 않았습니다. 빌드는 주 JS chunk 587.57kB 경고가 있어 초기 로딩 최적화 과제로 남깁니다.'),
 ('테스트 표를 읽는 법', '뒤의 92개는 기능별 점검 시나리오입니다. “자동화 연관” 84개는 관련 테스트 파일이 있는 점검 묶음이며 개별 수동 시나리오 전부를 이번에 브라우저로 수행했다는 뜻은 아닙니다. “수동 추가 권장” 8개는 실계정·실제 모델·사용자 확인이 필요합니다. P0는 핵심 상태·데이터 보호, P1은 사용성·경계 점검입니다.'),
],['frontend/package.json','backend/tests/test_pool_capacity.py','backend/tests/test_roadmap_query_perf.py','docs/final-guide/validation.txt'], '검증과 테스트')

for offset in range(0,len(TESTS),8):
    rows=TESTS[offset:offset+8]
    page(f'테스트 시나리오 {offset+1}부터 {offset+len(rows)}', '정상 흐름 · 경계값 · 예외 · 복구',[],[],[], '검증과 테스트')
    PAGES[-1]['tests']=rows

page('참조 자료와 최신화 기록','코드가 현재 동작의 기준',[],[
 ('소스 기준', 'origin/develop 4e64e0eedca5c2de3f88310f5190ff0ee1e43379를 fetch 후 현재 작업 브랜치에 fast-forward 반영했습니다. 이전 6553d16 대비 82개 커밋입니다. 문서 작성 중 서비스 기능 코드는 변경하지 않았습니다.'),
 ('기존 작업 보존', '업데이트 전 미커밋 변경은 git stash의 before-mentor-guide-latest-20261107에 보존했습니다. 복원 시 최신 구현과 충돌하거나 이미 반영된 내용은 최신 코드로 유지했습니다. 이전 변경 원문은 reports 대신 stash와 작업 당시 /tmp 패치에 남아 있으며, stash를 삭제하지 않았습니다.'),
 ('구현 근거', '각 페이지 하단에 경로를 적었습니다. API 목록은 app.main의 실제 OpenAPI에서 검증했습니다. 원고 content.py, 생성기 build_guide.py, 캡처 capture_screens.py, 화면 목록 screenshots.json, API 목록 api-inventory.json을 함께 둡니다.'),
 ('기존 문서와의 관계', 'docs/hero-scenario.md의 날짜별 결정 기록은 보존하고 맨 위에 최신 구현 확인을 추가했습니다. docs/tech-stack.md와 루트 README도 현재 구현과 설명서 링크로 갱신했습니다. 과거 실측은 해당 시점의 결과이며 오늘 성능으로 사용하지 않습니다.'),
 ('다시 만드는 방법', 'capture_screens.py는 로컬 5173 포트와 macOS Chrome, build_guide.py는 ReportLab·Pillow와 NanumBarunGothic.ttf를 사용합니다. 환경 의존 경로가 있어 다른 PC에서는 실행 경로를 바꿔야 합니다. 완성 HTML은 화면 이미지를 포함해 단일 파일로 오프라인 열람할 수 있습니다.'),
],['frontend/src/routes.tsx','backend/app/main.py','docs/hero-scenario.md','docs/tech-stack.md'], '참조')

FLOW_MAP={
 '처음부터 끝까지의 사용자 흐름':['로그인과 진단','지금 할 일 확인','현실에서 실행','결과 전달과 검수','상태 저장과 재계획'],
 '전체 기술 구조와 책임 분리':['React 화면','FastAPI 인증과 계약','LangGraph 판단과 검수','MySQL 상태와 파일'],
 '긴 AI 판단을 요청과 분리하는 방법':['입력 접수와 PENDING','응답과 커넥션 반환','배경 판단과 저장','화면에서 상태 조회'],
 'AI 구성요소가 각각 하는 일':['Procedure 근거','Info 사실과 충돌','Supervisor 행동 선택','Review 통과 후 반환'],
}
for p in PAGES:
 if p['title'] in FLOW_MAP:p['flow']=FLOW_MAP[p['title']]

def para(text,size=11.2,color=INK,leading=None):
    return Paragraph(html.escape(text).replace('\n','<br/>'),ParagraphStyle('p',fontName='GuideKR',fontSize=size,leading=leading or size*1.48,textColor=color,wordWrap='CJK',spaceAfter=0))

def fit_sections(sections,width,maxh):
    for sz in [11.5,11.1,10.7,10.3,9.9,9.5]:
        layout=[]; total=0
        for label,body in sections:
            p=para(body,sz); _,h=p.wrap(width,10000)
            layout.append((label,p,h));total+=18+h+12
        if total<=maxh:return layout,total,sz
    raise RuntimeError(f'Text overflow: {total}/{maxh}')

def image_data(id):
    path=ROOT/'images'/f'{id}.png'
    return 'data:image/png;base64,'+b64encode(path.read_bytes()).decode()

def draw_table(c,data,x,y,width,font=9.6,widths=None,padding=7):
    items=[[para(str(v),font,white if ri==0 else INK,leading=font*1.35)for v in row]for ri,row in enumerate(data)]
    tab=Table(items,colWidths=widths or [width/len(data[0])]*len(data[0]),repeatRows=1,hAlign='LEFT')
    tab.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),INK),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
        ('TOPPADDING',(0,0),(-1,-1),padding),('BOTTOMPADDING',(0,0),(-1,-1),padding),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[HexColor('#f5f6f8'),white]),
        ('LINEBELOW',(0,0),(-1,0),0.5,INK),
    ]))
    _,h=tab.wrap(width,10000)
    if y-h<65:raise RuntimeError(f'Table overflow {y-h}')
    tab.drawOn(c,x,y-h)
    return y-h

def build_pdf():
    c=canvas.Canvas(str(OUTPDF),pagesize=(WIDTH,HEIGHT),pageCompression=1)
    c.setTitle('리본 서비스 전체 설명서')
    c.setAuthor('RE:BORN 팀')
    c.setSubject('화면별 기능과 UI UX 기술 구조 테스트 발표 준비')
    qa=[]
    for index,p in enumerate(PAGES,1):
        c.setFillColor(white);c.rect(0,0,WIDTH,HEIGHT,fill=1,stroke=0)
        c.bookmarkPage(f'page-{index}');c.addOutlineEntry(p['title'],f'page-{index}',level=0,closed=False)
        c.setFillColor(BRAND);c.setFont('GuideKR',10);c.drawString(38,610,f'RE:BORN  /  {p["group"]}')
        title=para(p['title'],26)
        _,th=title.wrap(884,70);title.drawOn(c,38,592-th)
        c.setFont('GuideKR',10.5);c.setFillColor(MUTED);c.drawString(38,540,p['subtitle'])
        top=516
        if p.get('tests'):
            rows=p['tests']
            data=[['ID','기능','등급','조건과 동작','기대 결과']]+[[r['id'],r['area'],r['priority'],r['setup'],r['expected']]for r in rows]
            y=draw_table(c,data,38,top,884,font=10.1,widths=[63,110,40,320,351])
            lines=[]
            for r in rows:
                tag=f'{r["area"]}  {r["kind"]}  {r["source"]}'
                if tag not in lines:lines.append(tag)
            notes=para(' / '.join(lines),8.1,MUTED)
            _,nh=notes.wrap(884,10000)
            notes.drawOn(c,38,max(68,y-16-nh))
            qa.append(dict(page=index,min_y=min(y-16-nh,100),font=10.1,type='tests'))
        elif p.get('table') or p.get('task_table'):
            data=p.get('table') or p['task_table']
            widths=[58,318,125,383] if p.get('table') else [45,200,395,244]
            y=draw_table(c,data,38,top,884,font=9.2,widths=widths,padding=5)
            layout,total,sz=fit_sections(p['sections'],884,y-77)
            for label,b,h in layout:
                c.setFillColor(BRAND);c.setFont('GuideKR',11);c.drawString(38,y-20,label)
                b.drawOn(c,38,y-26-h);y-=h+43
            qa.append(dict(page=index,min_y=y,font=sz,type='api'))
        else:
            imgs=p['images'];nx=38;tw=884
            if imgs:
                panel=245 if len(imgs)==1 else 370
                nx=panel+62;tw=WIDTH-nx-38
                gap=12
                iw=(panel-gap*(len(imgs)-1))/len(imgs)
                for j,id in enumerate(imgs):
                    path=ROOT/'images'/f'{id}.png'
                    with Image.open(path) as im:origw,origh=im.size
                    scale=min(iw/origw,442/origh);w,h=origw*scale,origh*scale
                    x=38+j*(iw+gap)+(iw-w)/2
                    c.setFillColor(HexColor('#e8ebef'));c.roundRect(x-1,top-h-1,w+2,h+2,8,fill=1,stroke=0)
                    c.drawImage(str(path),x,top-h,width=w,height=h,mask='auto')
                    c.setFillColor(MUTED);c.setFont('GuideKR',7.5);c.drawCentredString(x+w/2,top-h-14,f'화면 예시 {id}')
            if p.get('flow'):
                flow=p['flow']; gap=18; bw=(884-gap*(len(flow)-1))/len(flow)
                for n,label in enumerate(flow):
                    bx=38+n*(bw+gap)
                    c.setFillColor(PALE);c.roundRect(bx,top-52,bw,48,8,fill=1,stroke=0)
                    fp=para(label,10.4,BRAND);_,fh=fp.wrap(bw-18,90);fp.drawOn(c,bx+9,top-28-fh/2)
                    if n<len(flow)-1:
                        c.setStrokeColor(BRAND);c.line(bx+bw+3,top-28,bx+bw+gap-3,top-28)
                        c.line(bx+bw+gap-6,top-25,bx+bw+gap-3,top-28)
                        c.line(bx+bw+gap-6,top-31,bx+bw+gap-3,top-28)
                top-=80
            layout,total,sz=fit_sections(p['sections'],tw,450-(80 if p.get('flow') else 0))
            y=top
            for label,b,h in layout:
                c.setFillColor(BRAND);c.setFont('GuideKR',11.3);c.drawString(nx,y-11,label)
                b.drawOn(c,nx,y-22-h);y-=18+h+12
            qa.append(dict(page=index,min_y=y,font=sz,type='screen' if imgs else 'text'))
        sources=('근거  '+ ' · '.join(p['sources'])) if p['sources'] else ''
        foot=para(sources,7.8,MUTED,10)
        _,fh=foot.wrap(800,1000);foot.drawOn(c,38,37)
        c.setFillColor(MUTED);c.setFont('GuideKR',8);c.drawRightString(922,20,f'{index:02d} / {len(PAGES):02d}    2026.11.07')
        c.showPage()
    c.save()
    (ROOT/'layout-qa.json').write_text(json.dumps(qa,ensure_ascii=False,indent=2))

def build_text():
    records=json.loads((ROOT/'screenshots.json').read_text())['records']
    byid={r['id']:r for r in records}
    for r in records:
        if (ROOT/'images'/f'{r["id"]}-full.png').exists():byid[r['id']+'-full']=r
    md=['# 리본 서비스 전체 설명서','\n2026년 11월 7일 · develop 4e64e0e','\nPDF와 HTML에는 화면 사진이 포함되어 있습니다. 사진은 저장소의 미리보기 데이터로 실행한 최신 React UI입니다.','\n## 목차']
    nav=[];sections=[]
    for i,p in enumerate(PAGES,1):
        nav.append(f'<a href="#page-{i}"><span>{i:02}</span> {html.escape(p["title"])}</a>')
        md.append(f'\n{i}. {p["title"]}')
        body=[f'<section id="page-{i}" class="chapter"><div class="eyebrow">{html.escape(p["group"])} · {i:02} / {len(PAGES)}</div><h1>{html.escape(p["title"])}</h1><p class="subtitle">{html.escape(p["subtitle"])}</p>']
        images=[]
        for id in p['images']:
            images.append(f'<figure><img src="{image_data(id)}" alt="{html.escape(id)} 実제 화면 캡처" loading="lazy"><figcaption>미리보기 화면 · {html.escape(byid[id]["url"].replace("http://127.0.0.1:5173", ""))}</figcaption></figure>')
        if p.get('flow'):body.append('<div class="flow">'+'<span>→</span>'.join('<b>'+html.escape(t)+'</b>'for t in p['flow'])+'</div>')
        if images:body.append('<div class="screen-layout"><div class="photos">'+''.join(images)+'</div><div>')
        for label,text in p['sections']:
            body.append(f'<h2>{html.escape(label)}</h2><p>{html.escape(text)}</p>')
        if images:body.append('</div></div>')
        if p.get('table') or p.get('task_table'):
            data=p.get('table') or p['task_table']
            body.append('<div class="table-wrap"><table>'+''.join('<tr>'+''.join(f'<{"th" if k==0 else "td"}>{html.escape(str(v))}</{"th" if k==0 else "td"}>'for v in r)+'</tr>'for k,r in enumerate(data))+'</table></div>')
        if p.get('tests'):
            body.append('<div class="table-wrap"><table><tr><th>ID</th><th>기능</th><th>등급</th><th>조건과 동작</th><th>기대 결과</th><th>확인 구분과 근거</th></tr>'+''.join('<tr>'+''.join(f'<td>{html.escape(str(r[k]))}</td>'for k in ['id','area','priority','setup','expected'])+f'<td>{html.escape(r["kind"])}<br><small>{html.escape(r["source"])}</small></td></tr>' for r in p['tests'])+'</table></div>')
        body.append('<p class="sources">근거 '+html.escape(' · '.join(p['sources']))+'</p></section>')
        sections.append(''.join(body))
    for i,p in enumerate(PAGES,1):
        md.extend([f'\n## {i:02} {p["title"]}',f'\n{p["subtitle"]}'])
        for id in p['images']:md.append(f'\n![{id}](images/{id}.png)')
        for label,text in p['sections']:md.extend([f'\n### {label}',f'\n{text}'])
        if p.get('table') or p.get('task_table'):
            data=p.get('table') or p['task_table']
            md.extend(['\n| '+' | '.join(data[0])+' |','| '+' | '.join(['---']*len(data[0]))+' |'])
            md.extend('| '+' | '.join(r)+' |'for r in data[1:])
        if p.get('tests'):
            md.extend(['\n| ID | 기능 | 등급 | 조건과 동작 | 기대 결과 | 구분 |','| --- | --- | --- | --- | --- | --- |'])
            md.extend('| '+' | '.join(r[k]for k in ['id','area','priority','setup','expected','kind'])+' |'for r in p['tests'])
            md.append('\n관련 테스트: '+' / '.join(dict.fromkeys(r['source']for r in p['tests'])))
        md.append('\n근거: '+' · '.join(f'`{s}`'for s in p['sources']))
    (ROOT/'설명서.md').write_text('\n'.join(md))
    css='''.flow{display:flex;align-items:center;gap:12px;margin:24px 0}.flow b{flex:1;padding:18px 10px;background:#fff3eb;color:#be3d00;border-radius:8px;font-size:13px;text-align:center}.flow span{color:#be3d00}*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:30px}body{margin:0;color:#191f28;background:#f5f6f8;font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;line-height:1.75}nav{position:fixed;inset:0 auto 0 0;width:285px;background:#171c24;color:#fff;overflow:auto;padding:26px 18px}nav b{font-size:23px}nav p{font-size:12px;color:#bdc4ce}nav a{display:block;color:#e6e9ee;text-decoration:none;padding:7px 8px;border-radius:5px;font-size:12px;line-height:1.6}nav a:hover{background:#303744}nav span{color:#ff8f54;margin-right:6px}input{width:100%;padding:12px;border:0;border-radius:8px;margin:15px 0}main{margin-left:285px;padding:24px}.chapter{max-width:1300px;margin:0 auto 24px;padding:36px;overflow-wrap:anywhere;background:white;border-radius:14px;box-shadow:0 2px 14px #00000006;scroll-margin-top:20px}h1{font-size:29px;line-height:1.35;margin:10px 0}h2{font-size:17px;color:#be3d00;margin:21px 0 6px}p{margin:0 0 12px}.eyebrow{font-size:12px;color:#be3d00}.subtitle,.sources{font-size:12px;color:#59616d}.screen-layout{display:grid;grid-template-columns:minmax(200px,40%) 1fr;gap:28px;margin-top:24px}.photos{display:flex;gap:12px;align-items:flex-start}figure{margin:0;flex:1;min-width:0}img{width:100%;height:auto;border:1px solid #e7e9ed;border-radius:9px}figcaption{font-size:10px;color:#737a85;overflow-wrap:anywhere}table{width:100%;border-collapse:collapse;font-size:12px}td,th{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid #e7e9ed}th{background:#191f28;color:white}td{overflow-wrap:anywhere}.table-wrap{overflow:auto}.sources{border-top:1px solid #eee;padding-top:12px;margin-top:24px;overflow-wrap:anywhere}.toolbar{display:flex;justify-content:space-between;gap:20px;margin-bottom:20px}.toolbar a,button{border:0;border-radius:7px;background:#be3d00;color:white;padding:9px 16px;text-decoration:none;cursor:pointer}small{font-size:10px;color:#59616d}@media(max-width:1000px){nav{position:relative;width:100%;max-height:230px}.flow{flex-direction:column;gap:6px}.flow b{width:100%}.flow span{transform:rotate(90deg)}.toolbar{flex-wrap:wrap}main{margin:0;padding:12px}.chapter{padding:22px}.screen-layout{grid-template-columns:minmax(0,1fr)}.screen-layout>*{min-width:0}.photos{max-width:600px}figure{max-width:300px}}@media print{nav,.toolbar{display:none}main{margin:0;padding:0}.chapter{break-before:page;box-shadow:none;border:0;padding:12px}.screen-layout{grid-template-columns:38% 1fr}body{background:white;font-size:10pt}h1{font-size:22pt}h2{font-size:12pt}a{color:inherit}}'''
    script="document.querySelector('#search').addEventListener('input',e=>{let q=e.target.value.toLowerCase();document.querySelectorAll('.chapter').forEach(x=>x.hidden=q&&!x.innerText.toLowerCase().includes(q));document.querySelectorAll('nav a').forEach(a=>a.hidden=document.querySelector(a.getAttribute('href')).hidden)})"
    doc='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>리본 서비스 전체 설명서</title><style>'+css+'</style><nav><b>리본 전체 설명서</b><p>2026.11.07 · develop 4e64e0e<br>화면·기능·기술·테스트·발표 대본</p><input id="search" placeholder="전체 설명에서 검색" aria-label="전체 설명 검색">'+''.join(nav)+'</nav><main><div class="toolbar"><span>사진 포함 오프라인 설명서 · 미리보기 예시 화면</span><button onclick="window.print()">인쇄 또는 PDF 저장</button></div>'+''.join(sections)+'</main><script>'+script+'</script></html>'
    doc=doc.replace(' 実제',' 실제')
    (ROOT/'리본_서비스_전체_설명서.html').write_text(doc)
    with (ROOT/'테스트_케이스.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['id','area','priority','setup','expected','kind','source']);writer.writeheader();writer.writerows(TESTS)
    (ROOT/'guide-index.json').write_text(json.dumps(dict(pages=len(PAGES),tests=len(TESTS),screenshots=len(records),titles=[p['title']for p in PAGES]),ensure_ascii=False,indent=2))

def verify_sources():
    missing=[]
    for p in PAGES:
        for s in p['sources']:
            if not (REPO/s).is_file():missing.append(s)
    for row in TESTS:
        if row['kind']=='자동화 연관':
            for s in row['source'].split(' · '):
                if not (REPO/s).is_file():missing.append(s)
    if missing:raise RuntimeError('Missing sources: '+repr(sorted(set(missing))))
    actual=json.loads((ROOT/'api-inventory.json').read_text())
    assert len(API_ROWS)==sum(len(x)for x in actual.values())
    for method,path,*_ in API_ROWS:assert method.lower()in actual[path],(method,path)

if __name__=='__main__':
    verify_sources();build_pdf();build_text()
    print(json.dumps(dict(pages=len(PAGES),tests=len(TESTS),pdf=str(OUTPDF)),ensure_ascii=False))
