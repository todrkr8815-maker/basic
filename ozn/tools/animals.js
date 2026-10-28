// 소·돼지 실루엣 위에 부위를 칠한 SVG를 만든다. 색은 CSS 클래스(z-g 구이, z-m 다목적, z-s 탕·찜·가공)로 지정한다.
function clipDefs(id, shapes){
  return '<clipPath id="'+id+'">'+shapes+'</clipPath>';
}
function zoneRects(list, clipId){
  var out='<g clip-path="url(#'+clipId+')">';
  list.forEach(function(z){
    out+='<rect x="'+z.x+'" y="'+z.y+'" width="'+z.w+'" height="'+z.h+'" class="zone z-'+z.c+(z.dash?' dash':'')+'"/>';
  });
  return out+'</g>';
}
function zoneLabels(list){
  return list.map(function(z){
    var lx=z.lx!=null?z.lx:z.x+z.w/2, ly=z.ly!=null?z.ly:z.y+z.h/2+4;
    return '<text x="'+lx+'" y="'+ly+'" text-anchor="middle" class="zt">'+z.t+'</text>';
  }).join('');
}

// ---------- 소 (왼쪽이 머리) ----------
var COW_SHAPES =
  '<path d="M150,95 C250,84 400,84 500,95 C540,100 560,130 555,170 C550,215 520,238 470,240 L200,240 C160,240 135,212 135,170 C135,130 140,105 150,95 Z"/>'+
  '<path d="M62,150 C56,132 72,114 92,108 L122,100 L128,150 L120,190 L102,182 C80,186 62,172 62,150 Z"/>'+
  '<path d="M104,108 L150,90 L176,96 L178,205 L142,205 L112,182 Z"/>'+
  '<rect x="150" y="222" width="32" height="84" rx="9"/><rect x="190" y="226" width="26" height="80" rx="9"/>'+
  '<rect x="484" y="206" width="40" height="100" rx="10"/><rect x="436" y="226" width="30" height="80" rx="9"/>';
var COW_ZONES = [
  {t:'앞다리',x:135,y:150,w:101,h:112,c:'m',lx:186,ly:212},
  {t:'목심',x:118,y:85,w:56,h:120,c:'m',lx:148,ly:150},
  {t:'등심',x:172,y:80,w:200,h:70,c:'g'},
  {t:'갈비',x:236,y:150,w:136,h:55,c:'g',lx:276,ly:190},
  {t:'양지',x:200,y:205,w:250,h:45,c:'s',lx:320,ly:233},
  {t:'',x:372,y:176,w:78,h:30,c:'s'},
  {t:'채끝',x:372,y:80,w:78,h:70,c:'g'},
  {t:'안심',x:300,y:150,w:150,h:26,c:'g',dash:1,lx:412,ly:168},
  {t:'우둔',x:450,y:80,w:110,h:80,c:'m'},
  {t:'설도',x:450,y:160,w:110,h:102,c:'m'},
  {t:'사태',x:140,y:262,w:82,h:48,c:'s'},
  {t:'사태',x:430,y:262,w:100,h:48,c:'s'}
];
function cow(){
  var s='<svg viewBox="0 0 620 330" class="animal" role="img" aria-label="소 부위 위치 도식" xmlns="http://www.w3.org/2000/svg"><defs>'+clipDefs('cowclip',COW_SHAPES)+'</defs>';
  s+='<g class="outline">'+COW_SHAPES+'</g>';              // 바깥 윤곽(굵은 선)
  s+='<g class="fillbase">'+COW_SHAPES+'</g>';              // 안쪽 면(윤곽선 겹침 제거)
  s+='<path d="M556,102 C582,130 584,200 574,258" class="tail"/><ellipse cx="573" cy="266" rx="7" ry="14" class="tuft"/>';
  s+='<ellipse cx="116" cy="96" rx="17" ry="7" transform="rotate(-28 116 96)" class="ear"/><circle cx="92" cy="130" r="3.5" class="eye"/>';
  s+=zoneRects(COW_ZONES,'cowclip');
    s+=zoneLabels(COW_ZONES);
  s+='<text x="66" y="212" text-anchor="middle" class="zh">머리</text>';
  s+='<text x="12" y="16" class="zh">◀ 앞(머리)</text><text x="608" y="16" text-anchor="end" class="zh">뒤(꼬리) ▶</text>';
  return s+'</svg>';
}

// ---------- 돼지 ----------
var PIG_SHAPES =
  '<path d="M150,100 C250,80 420,80 520,100 C562,115 574,160 558,202 C543,228 505,238 470,238 L190,238 C148,238 124,208 128,166 C130,132 138,110 150,100 Z"/>'+
  '<path d="M128,126 L88,140 C62,148 50,165 54,182 C58,198 82,200 98,192 L128,204 Z"/>'+
  '<rect x="150" y="226" width="30" height="52" rx="8"/><rect x="190" y="230" width="26" height="48" rx="8"/>'+
  '<rect x="486" y="214" width="34" height="64" rx="9"/><rect x="440" y="230" width="28" height="48" rx="8"/>';
var PIG_ZONES = [
  {t:'앞다리',x:128,y:150,w:92,h:128,c:'s',lx:172,ly:215},
  {t:'목심',x:128,y:84,w:76,h:66,c:'g'},
  {t:'등심',x:204,y:80,w:236,h:50,c:'m'},
  {t:'갈비',x:204,y:130,w:236,h:42,c:'g'},
  {t:'삼겹살',x:204,y:172,w:236,h:70,c:'g'},
  {t:'안심',x:330,y:130,w:110,h:16,c:'m',dash:1,lx:385,ly:142},
  {t:'뒷다리',x:440,y:80,w:140,h:204,c:'s',lx:507,ly:170}
];
var PIG_SPECIALS = [ // 특수부위: 점과 지시선
  {t:'항정살',x:134,y:168,lx:70,ly:240},
  {t:'가브리살',x:208,y:90,lx:262,ly:52,above:1},
  {t:'갈매기살',x:395,y:170,lx:430,ly:300}
];
function pig(withSpecials){
  var s='<svg viewBox="0 0 620 330" class="animal" role="img" aria-label="돼지 부위 위치 도식" xmlns="http://www.w3.org/2000/svg"><defs>'+clipDefs('pigclip',PIG_SHAPES)+'</defs>';
  s+='<g class="outline">'+PIG_SHAPES+'</g><g class="fillbase">'+PIG_SHAPES+'</g>';
  s+='<path d="M560,118 C586,112 592,140 576,146 C564,150 562,138 572,136" class="tail"/>';
  s+='<path d="M104,130 L116,104 L128,132 Z" class="ear"/><circle cx="84" cy="158" r="3.5" class="eye"/>';
  s+=zoneRects(PIG_ZONES,'pigclip')+zoneLabels(PIG_ZONES);
  if(withSpecials){
    PIG_SPECIALS.forEach(function(p){
      s+='<line x1="'+p.x+'" y1="'+p.y+'" x2="'+p.lx+'" y2="'+(p.above?p.ly+6:p.ly-14)+'" class="leader"/><circle cx="'+p.x+'" cy="'+p.y+'" r="4.5" class="dot"/>';
      s+='<text x="'+p.lx+'" y="'+p.ly+'" text-anchor="middle" class="zt sp">'+p.t+'</text>';
    });
  }
  s+='<text x="12" y="16" class="zh">◀ 앞(머리)</text><text x="608" y="16" text-anchor="end" class="zh">뒤(꼬리) ▶</text>';
  return s+'</svg>';
}

function legend(){
  return '<div class="legend"><span><i class="sw z-g"></i>구이</span><span><i class="sw z-m"></i>불고기·튀김·다목적</span><span><i class="sw z-s"></i>탕·찜·수육·가공</span></div>';
}
// 공통 스타일: 라이트 팔레트(인쇄용). 앱 화면은 CSS 변수로 덮어쓴다.
var CSS =
'.animal{width:100%;height:auto;display:block}'+
'.outline{fill:none;stroke:var(--ink,#1B2321);stroke-width:6;stroke-linejoin:round}'+
'.fillbase{fill:var(--card,#fff);stroke:none}'+
'.zone{stroke:var(--card,#fff);stroke-width:2}'+
'.z-g{fill:var(--accent-soft,#F3D3D5);}.z-m{fill:var(--mid-soft,#F1E5BF);}.z-s{fill:var(--done-soft,#CFE8DA);}'+
'.dash{stroke:var(--ink,#1B2321);stroke-width:1.5;stroke-dasharray:5 3}'+
'.zt{fill:var(--ink,#1B2321);font-size:15px;font-weight:700}.zt.sp{fill:var(--accent,#B0252E)}'+
'.zh{fill:var(--sub,#5E6A66);font-size:12px}.zin{font-size:11px}'+
'.tail{fill:none;stroke:var(--ink,#1B2321);stroke-width:5;stroke-linecap:round}.tuft{fill:var(--ink,#1B2321)}'+
'.ear{fill:var(--card,#fff);stroke:var(--ink,#1B2321);stroke-width:2.2}.eye{fill:var(--ink,#1B2321)}'+
'.leader{stroke:var(--accent,#B0252E);stroke-width:1.5}.dot{fill:var(--accent,#B0252E)}'+
'.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px;margin-top:4px}.legend span{display:inline-flex;align-items:center;gap:6px}'+
'.sw.z-g{background:var(--accent-soft,#F3D3D5)}.sw.z-m{background:var(--mid-soft,#F1E5BF)}.sw.z-s{background:var(--done-soft,#CFE8DA)}'+
'.sw{width:14px;height:14px;border-radius:3px;display:inline-block;border:1px solid var(--ink,#1B2321)}';
module.exports = {cow:cow, pig:pig, legend:legend, CSS:CSS};
