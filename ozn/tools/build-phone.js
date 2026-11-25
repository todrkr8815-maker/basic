#!/usr/bin/env node
// 사용법: node ozn/tools/build-phone.js  →  ozn/phone/ozn-today.html 생성
// 폰용 페이지(Artifact로 게시할 단일 HTML)를 cards.json 과 daily/data/*.json 으로 만든다.
const fs = require('fs'), path = require('path');
const animals = require('./animals.js');
const root = path.resolve(__dirname, '..');
const tpl = fs.readFileSync(path.join(root, 'phone', 'template.html'), 'utf8');
const cards = JSON.parse(fs.readFileSync(path.join(root, 'cards.json'), 'utf8'))
  .map(c => ({ n: c.n, title: c.title, diagram: c.diagram, intro: c.intro, sections: c.sections, script: c.script, summary: c.summary, sources: c.sources }));
const dataDir = path.join(root, 'daily', 'data');
const br = fs.readdirSync(dataDir).filter(f => /^\d{4}-\d{2}-\d{2}\.json$/.test(f)).sort()
  .map(f => JSON.parse(fs.readFileSync(path.join(dataDir, f), 'utf8')))
  .map(b => ({ date: b.date, day: b.day, ideas: b.ideas, market: b.market, news: b.news, newsNote: b.newsNote }));
const svg = { beef: animals.cow(), pork: animals.pig(false), 'pork-special': animals.pig(true) };
const kst = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 16).replace('T', ' ');
const j = o => JSON.stringify(o).replace(/<\/script/gi, '<\\/script');
const out = tpl.replace('/*ANIMALS_CSS*/', animals.CSS).replace('/*BRIEFINGS*/[]', j(br)).replace('/*CARDS*/[]', j(cards)).replace('/*SVG*/{}', j(svg)).replace('/*UPDATED*/', kst + ' (한국시간)');
fs.writeFileSync(path.join(root, 'phone', 'ozn-today.html'), out);
console.log('phone page', out.length, 'bytes,', br.length, 'briefings,', cards.length, 'cards');
