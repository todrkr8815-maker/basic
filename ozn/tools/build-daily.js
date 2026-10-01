#!/usr/bin/env node
// 사용법: node ozn/tools/build-daily.js ozn/daily/data/2026-10-01.json
// 입력 JSON({date, day, ideas, market, news, newsNote})과 ozn/cards.json 의 학습 카드를 합쳐
// ozn/daily/YYYY-MM-DD.html (A4 인쇄용) 과 .pdf 를 만든다. PDF 생성이 실패하면 HTML만 남긴다.
const fs = require('fs'), path = require('path'), cp = require('child_process');
const animals = require('./animals.js');
const root = path.resolve(__dirname, '..');
const dataFile = path.resolve(process.argv[2]);
const d = JSON.parse(fs.readFileSync(dataFile, 'utf8'));
const cards = JSON.parse(fs.readFileSync(path.join(root, 'cards.json'), 'utf8'));
const card = d.card || cards.find(c => c.n === d.day);
if (!card) { console.error('카드를 찾을 수 없습니다: day=' + d.day); process.exit(1); }
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const DOW = ['일','월','화','수','목','금','토'];
const dt = new Date(d.date + 'T00:00:00Z');
const dateKo = d.date.replace(/-/g, '.') + ' (' + DOW[dt.getUTCDay()] + ')';

function diagram(kind) {
  if (!kind) return '';
  const svg = kind === 'beef' ? animals.cow() : animals.pig(card.specials === true || kind === 'pork-special');
  return '<figure class="fig">' + svg + animals.legend() +
    '<figcaption>부위 위치를 보여 주는 도식입니다. 점선은 몸 안쪽의 부위(안심)입니다. 실제 모양과 비율은 다릅니다.</figcaption></figure>';
}
const sections = card.sections.map(s =>
  '<h3>' + esc(s.h) + '</h3>' + s.p.map(p => '<p>' + esc(p) + '</p>').join('')).join('');
const field = '<ul>' + card.field.map(x => '<li>' + esc(x) + '</li>').join('') + '</ul>';
const quiz = card.quiz.map((q, i) => '<li><b>' + esc(q.q) + '</b><div class="write"></div></li>').join('');
const answers = card.quiz.map((q, i) => '<li>' + esc(q.a) + '</li>').join('');
const ideas = (d.ideas || []).map(i =>
  '<div class="idea"><div class="tag">' + esc(i.tag) + '</div><div><b>' + esc(i.title) + '</b><p>' + esc(i.body) + '</p></div></div>').join('');
const news = (d.news || []).map(n =>
  '<article class="news"><h4>' + esc(n.title) + '</h4><div class="meta">' + esc(n.source) + ' · ' + esc(n.date) +
  (n.url ? ' · ' + esc(n.url) : '') + '</div><p>' + esc(n.summary) + '</p>' +
  (n.impact ? '<p class="impact"><b>오즈네이쳐에 의미:</b> ' + esc(n.impact) + '</p>' : '') + '</article>').join('');

const html = '<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>오즈네이쳐 데일리 ' + esc(d.date) + '</title><style>' +
'@page{size:A4;margin:14mm 13mm 16mm}' +
':root{--ink:#1B2321;--sub:#55625E;--line:#CBD3CF;--card:#fff;--accent:#B0252E;--accent-soft:#F3D3D5;--mid-soft:#F1E5BF;--done-soft:#CFE8DA;--tint:#F3F5F4}' +
'*{box-sizing:border-box}body{margin:0;color:var(--ink);background:#fff;font:10.5pt/1.7 "Noto Sans KR","Noto Sans CJK KR","Malgun Gothic","Apple SD Gothic Neo","WenQuanYi Zen Hei",sans-serif}' +
'header{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2.5px solid var(--ink);padding-bottom:6px;margin-bottom:10px}' +
'.brand{font-size:9pt;letter-spacing:.08em;color:var(--accent);font-weight:700}h1{font-size:17pt;line-height:1.3;margin:2px 0 0}' +
'.date{font-size:10pt;color:var(--sub);text-align:right;white-space:nowrap}' +
'h2{font-size:13pt;margin:0 0 6px;padding:3px 10px;background:var(--ink);color:#fff;border-radius:4px}' +
'h3{font-size:11.5pt;margin:12px 0 2px;padding-top:6px;border-top:1px solid var(--line);break-after:avoid}' +
'p{margin:0 0 6px;text-align:justify;word-break:keep-all}.intro{color:var(--sub)}' +
'.fig{margin:8px 0;padding:6px 10px;border:1px solid var(--line);border-radius:6px;break-inside:avoid}' +
'figcaption{font-size:8.5pt;color:var(--sub);margin-top:2px}' +
'.box{border-left:4px solid var(--accent);background:var(--tint);padding:6px 10px;margin:8px 0;break-inside:avoid}' +
'.box b.l{display:block;font-size:9pt;color:var(--accent);letter-spacing:.04em}.box ul{margin:2px 0 0;padding-left:18px}' +
'.quiz li{margin-bottom:4px;break-inside:avoid}.write{border-bottom:1px dotted var(--sub);height:22px}.quiz li .write+.write{margin-top:2px}' +
'.ans{font-size:8.5pt;color:var(--sub);border-top:1px dashed var(--line);margin-top:6px;padding-top:4px}.ans ol{margin:2px 0 0;padding-left:18px}' +
'.idea{display:flex;gap:10px;padding:7px 0;border-bottom:1px solid var(--line);break-inside:avoid}.idea p{margin:0}' +
'.tag{flex:none;width:66px;height:22px;text-align:center;font-size:8.5pt;font-weight:700;background:var(--accent-soft);color:var(--accent);border-radius:4px;line-height:22px}' +
'.mk{display:grid;grid-template-columns:1fr 1fr;gap:10px}.mk div{background:var(--tint);padding:6px 10px;border-radius:4px;break-inside:avoid}.mk b{display:block;font-size:10pt}' +
'.news{padding:6px 0;border-bottom:1px solid var(--line);break-inside:avoid}.news h4{margin:0;font-size:10.5pt}.meta{font-size:8.5pt;color:var(--sub);margin-bottom:2px;word-break:break-all}.impact{background:var(--tint);padding:3px 8px;border-radius:3px}' +
'.note{font-size:8.5pt;color:var(--sub);margin-top:6px}.memo{margin-top:10px;break-inside:avoid}.memo .write{height:26px}' +
'.pb{break-before:page}section{margin-bottom:12px}' +
animals.CSS + '</style></head><body>' +
'<header><div><div class="brand">오즈네이쳐 육류 데일리</div><h1>' + esc(card.title) + '</h1></div><div class="date">' + esc(dateKo) + '<br>학습 Day ' + esc(d.day) + '</div></header>' +
'<section><h2>오늘의 학습 카드</h2><p class="intro">' + esc(card.intro) + '</p>' + diagram(card.diagram) + sections +
'<div class="box"><b class="l">손님에게 이렇게 설명하세요</b>' + esc(card.script) + '</div>' +
'<div class="box"><b class="l">현장 포인트</b>' + field + '</div>' +
'<div class="box"><b class="l">콘텐츠로 만들기</b>' + esc(card.content) + '</div>' +
'<p class="note">확인처: ' + esc(card.sources) + '</p></section>' +
'<section class="quiz"><h2>오늘의 퀴즈 (소리 내어 말해 보고, 아래에 한 줄로 적기)</h2><ol>' + quiz + '</ol>' +
'<div class="ans"><b>정답과 해설</b><ol>' + answers + '</ol></div></section>' +
'<section class="pb"><h2>이런 아이디어 어떠세요?</h2>' + ideas + '</section>' +
'<section><h2>세계 소·돼지고기 시장 흐름</h2><div class="mk"><div><b>소고기</b>' + esc((d.market || {}).beef) + '</div><div><b>돼지고기</b>' + esc((d.market || {}).pork) + '</div></div></section>' +
'<section><h2>뉴스 요약</h2>' + news + '<p class="note">' + esc(d.newsNote || '') + '</p></section>' +
'<section class="memo"><h2>메모</h2><b>오늘 새로 알게 된 것</b><div class="write"></div><div class="write"></div><b>고객에게 써 볼 한마디</b><div class="write"></div><div class="write"></div></section>' +
'</body></html>';

const out = path.join(root, 'daily', d.date + '.html');
fs.writeFileSync(out, html);
console.log('HTML', out);

// PDF 생성 (Playwright 크로미움). 실패해도 HTML은 남는다.
const pdfScript = `
const path=require('path');
let pw;
for (const p of ['playwright','playwright-core',(process.env.NODE_PATH||'')+'/playwright',require('child_process').execSync('npm root -g').toString().trim()+'/playwright']) { try{ pw=require(p); break;}catch(e){} }
if(!pw) { console.error('playwright 모듈 없음'); process.exit(2); }
(async()=>{
  const opts = process.env.PLAYWRIGHT_BROWSERS_PATH ? {} : {};
  let b; try { b = await pw.chromium.launch(opts); } catch(e) { b = await pw.chromium.launch({executablePath:'/opt/pw-browsers/chromium'}); }
  const p = await b.newPage();
  await p.goto('file://'+process.argv[2]);
  await p.waitForTimeout(800);
  await p.pdf({path:process.argv[3],format:'A4',printBackground:true,displayHeaderFooter:true,
    headerTemplate:'<span></span>',
    footerTemplate:'<div style="font-size:8px;width:100%;text-align:center;color:#666">오즈네이쳐 육류 데일리 · '+process.argv[4]+' · <span class="pageNumber"></span>/<span class="totalPages"></span></div>',
    margin:{top:'14mm',bottom:'16mm',left:'13mm',right:'13mm'}});
  await b.close();
})().catch(e=>{console.error(e.message);process.exit(3)});`;
const tmp = path.join(root, 'daily', '.pdf-tmp.js');
fs.writeFileSync(tmp, pdfScript);
const pdf = out.replace(/\.html$/, '.pdf');
const r = cp.spawnSync('node', [tmp, out, pdf, d.date], { stdio: 'inherit' });
fs.unlinkSync(tmp);
console.log(r.status === 0 ? 'PDF ' + pdf : 'PDF 생성 실패(HTML만 저장됨)');

// 지난 브리핑 목차(ozn/daily/README.md): 날짜 내림차순으로 PDF 링크와 학습 주제를 나열한다.
try {
  const dir = path.join(root, 'daily');
  const rows = fs.readdirSync(dir).filter(f => /^\d{4}-\d{2}-\d{2}\.html$/.test(f)).map(f => f.slice(0, 10)).sort().reverse().map(date => {
    let title = '', day = '';
    try { const j = JSON.parse(fs.readFileSync(path.join(dir, 'data', date + '.json'), 'utf8')); day = j.day;
      const c = j.card || cards.find(x => x.n === j.day); title = c ? c.title : ''; } catch (e) {}
    const hasPdf = fs.existsSync(path.join(dir, date + '.pdf'));
    return '| ' + date + ' | ' + day + ' | ' + title + ' | ' + (hasPdf ? '[PDF](' + date + '.pdf)' : '-') + ' |';
  });
  fs.writeFileSync(path.join(dir, 'README.md'), '# 지난 브리핑 목차\n\n날짜를 눌러 PDF를 열면 됩니다. 최신 날짜가 위에 있습니다.\n\n| 날짜 | Day | 학습 주제 | 파일 |\n|---|---|---|---|\n' + rows.join('\n') + '\n');
} catch (e) { console.error('목차 생성 실패', e.message); }
