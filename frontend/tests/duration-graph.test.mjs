// node frontend/tests/duration-graph.test.mjs — 추가 패키지 없는 SFR-006 테스트
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
const read = path => readFile(new URL(path, import.meta.url), 'utf8');
const strip = source => source.replace(/^import[\s\S]*?from ["'][^"']+["'];/mg, '').replace(/export /g, '');
const model = vm.createContext({});
vm.runInContext(strip(await read('../js/components/durationGraph.js')), model);
const points = [
  { departTime: '2026-11-15T07:30:00+09:00', durationMin: 35 },
  { departTime: '2026-11-15T07:40:00+09:00', durationMin: 38 },
  { departTime: '2026-11-15T08:10:00+09:00', durationMin: 48 },
];
let chart = model.durationChartModel(points, points[1].departTime);
assert.equal((chart.points[1].x-chart.points[0].x)/(chart.points[2].x-chart.points[0].x), .25);
assert.equal(chart.recommendedX, chart.points[1].x);
assert(chart.points[0].y > chart.points[2].y);
assert.equal(model.durationChartModel([], '').points.length, 0);
assert.equal(model.durationChartModel([points[0]], points[0].departTime).recommendedX, 360);
assert.equal(model.durationChartModel(points, '2026-11-15T10:00:00+09:00').recommendedX, null);
const dirty = [points[2], points[0], { ...points[0], durationMin: 40 }, null,
  { departTime: 'invalid', durationMin: 1 }, { ...points[1], durationMin: -1 }, { ...points[1], durationMin: '38' }, { ...points[1], durationMin: NaN }, { ...points[1], durationMin: Infinity }];
const normalized = model.normalizeGraphPoints(dirty);
assert.equal(normalized.points.length, 2); assert.equal(normalized.points[0].durationMin, 40); assert.equal(normalized.discarded, 7);
for (const value of ['2026-02-30T10:00', '2026-11-15T24:00', '2026-11-15T12:61', '2026-11-15', '<svg>', null]) assert(Number.isNaN(model.graphTimestamp(value)));
assert.equal(model.graphTimestamp('2026-11-15T07:30'), model.graphTimestamp('2026-11-14T22:30:00Z'));
assert.equal(model.graphTime('2026-11-14T15:05:00Z'), '11/15 00:05');
assert.equal(model.graphTime('2026-12-31T15:05:00Z'), '1/1 00:05');
const routeGraphs = [{ routeId:'route-1', points }, { routeId:'unknown', points }];
assert.equal(model.normalizeRouteGraphs(routeGraphs, [{ id:'route-1' }]).size, 1);
assert.equal(model.normalizeRouteGraphs([...routeGraphs, routeGraphs[0]], [{ id:'route-1' }]).size, 0);
assert.equal(model.normalizeRouteGraphs([{ routeId:1, points }], [{ id:'1' }]).size, 0);
for (const graph of JSON.parse(await read('../js/mock/routeGraph.json'))) {
  const routes = JSON.parse(await read('../js/mock/routes.json'));
  assert(routes.some(route=>route.id===graph.routeId));
}
console.log('PASS: 시간 비례 X축·Y축·권장선·단일/빈 데이터·검증/정렬/중복·KST 자정/연말·ID 일치');

class Node {
  constructor() { this.events = {}; this.attrs = {}; this.dataset = {}; this.classList = { toggle() {} }; }
  setAttribute(k,v) { this.attrs[k]=v; }
  addEventListener(k,fn) { this.events[k]=fn; }
  removeEventListener(k,fn) { if (this.events[k] === fn) delete this.events[k]; }
  focus() { this.events.focus?.(); }
}
const container = new Node();
const outsideHandlers = new Set();
const popover = new Node(); popover.style = {setProperty(key,value){this[key]=value;}}; popover.querySelector = () => new Node();
popover.getBoundingClientRect = () => ({width:250,height:180});
const plot = new Node(); plot.getBoundingClientRect = () => ({left:0,top:0,width:700,height:270});
plot.contains = target => target === plot || container.nodes.includes(target) || target === popover;
const table = { contains: target => container.rows.includes(target) };
const scroll = new Node();
let mobile = false;
Object.defineProperty(container,'innerHTML',{ set(value) {
  this.html=value; this.nodes=[...value.matchAll(/class="duration-hit"/g)].map((_,i)=>{ const node=new Node();node.getBoundingClientRect=()=>({left:60+i*200,right:88+i*200,top:100,bottom:128});node.scrollIntoView=()=>{};return node; });
  this.rows=[...value.matchAll(/class="duration-row"/g)].map(()=>new Node());this.badges=this.rows.map(()=>({hidden:true}));this.readout={};
} });
container.querySelectorAll = selector => selector === '.duration-row' ? container.rows : selector === '.duration-selected' ? container.badges : container.nodes;
container.querySelector = selector => ({'.duration-readout':container.readout,'.duration-popover':popover,'.duration-plot':plot,'.duration-table':table,'.duration-scroll':scroll})[selector];
const renderer=vm.createContext({ durationChartModel:model.durationChartModel, graphTime:model.graphTime,durationChange:model.durationChange,summaryPosition:model.summaryPosition,icon:()=>'',
 document:{addEventListener:(name,fn)=>outsideHandlers.add(fn),removeEventListener:(name,fn)=>outsideHandlers.delete(fn)},
 window:{matchMedia:()=>({matches:mobile}),addEventListener(){},removeEventListener(){}},
 escapeHtml:value=>String(value).replaceAll('<','&lt;').replaceAll('"','&quot;') });
vm.runInContext(strip(await read('../js/components/charts.js')), renderer);
renderer.renderDurationChart(container,{points,routeName:'<img src=x>',routeId:'route-1',isExample:true,recommendedTime:points[1].departTime});
assert(container.html.includes('테스트용 예시')); assert(!container.html.includes('<img'));
assert.equal(container.nodes.length,3); assert.equal(container.dataset.routeId,'route-1');
container.nodes[0].events.mouseenter(); assert(container.readout.textContent.includes('35분'));
container.nodes[1].events.click(); assert(container.readout.textContent.includes('38분'));assert.equal(popover.hidden,false);assert(popover.innerHTML.includes('3분 증가'));assert(popover.innerHTML.includes('duration-popover-clock'));assert(popover.innerHTML.includes('자동차 기준'));assert(popover.innerHTML.includes('duration-mode'));
assert.equal(container.rows[1].attrs['aria-pressed'],'true');assert(popover.style['--tail-top'].endsWith('px'));assert.equal(container.badges[1].hidden,false);
container.nodes[1].events.click();assert.equal(popover.hidden,true);assert.equal(container.rows[1].attrs['aria-pressed'],'false');
container.rows[2].events.click();assert.equal(container.nodes[2].attrs['aria-pressed'],'true');assert.equal(container.rows[1].attrs['aria-pressed'],'false');
container.nodes[0].events.keydown({key:'End',preventDefault(){}}); assert(container.readout.textContent.includes('48분'));
container.nodes[2].events.keydown({key:'Escape'});assert.equal(popover.hidden,true);
container.nodes[0].events.keydown({key:'Enter',preventDefault(){}});assert.equal(popover.hidden,false);assert(popover.innerHTML.includes('비교할 이전 시간대 없음'));
for (const fn of outsideHandlers) fn({target:{}}); assert.equal(popover.hidden,true);
mobile=true;container.rows[1].events.click();assert.equal(popover.style.left,'');
container.events.keydown({key:'Escape'});assert.equal(popover.hidden,true);
assert.equal(outsideHandlers.size,1);
renderer.renderDurationChart(container,{points:[],message:'연동 대기'}); assert(container.html.includes('연동 대기')); assert.equal(container.nodes.length,0);assert.equal(outsideHandlers.size,0);
renderer.renderDurationChart(container,{points:[points[0]]}); assert(container.html.includes('데이터가 1개'));
console.log('PASS: SVG 렌더링·hover/터치/키보드·요약 토글/외부 닫기·표/지점 선택 동기화·모바일 위치·교체 시 이벤트 정리 (모의 DOM)');

let apiCalls=[], response=[], fail=false, aborted=false, timer;
const api=vm.createContext({ USE_MOCK:false, USE_MOCK_ROUTES:false, GRAPH_DATA_SOURCE:"off", location:{hostname:"localhost"}, BASE_URL:'/api',URLSearchParams,
  AbortController:class { constructor(){this.signal={};} abort(){aborted=true;this.signal.onabort?.();} },
  setTimeout:fn=>{timer=fn;return 1;}, clearTimeout(){},
  fetch:async(url,options)=>{apiCalls.push({url,options});if(fail) throw Error('offline');return {ok:true,json:async()=>response};}
});
vm.runInContext(strip(await read('../js/graphData.js')),api);
vm.runInContext(strip(await read('../js/api.js')),api);
assert.equal((await api.getRouteGraph()).graphs.length,0);assert.equal(apiCalls.length,0);
api.GRAPH_DATA_SOURCE="api"; response=routeGraphs;
const graphCards=[{id:'recommend',departTime:'2026-11-15T08:20:00+09:00'}]; // getRoutes 카드 -> card 파라미터
assert.equal((await api.getRouteGraph({from:'서울 & 부산',to:'김해',arrive:'2026-11-15T09:00:00+09:00'},graphCards)).graphs,routeGraphs);
assert.equal(new URL(apiCalls[0].url,'http://localhost').searchParams.get('from'),'서울 & 부산');
assert.deepEqual(new URL(apiCalls[0].url,'http://localhost').searchParams.getAll('card'),['recommend@2026-11-15T08:20:00+09:00']);
assert(apiCalls[0].options.signal); fail=true; await assert.rejects(api.getRouteGraph({},graphCards));
api.fetch=(url,options)=>new Promise((resolve,reject)=>{options.signal.onabort=()=>reject(Error("aborted"));}); const late=api.getRouteGraph({},graphCards); timer(); await assert.rejects(late); assert(aborted);
console.log('PASS: API 대기 시 무호출·실제 모드 URL/시그널·실패·10초 지연 취소·가짜 데이터 대체 없음');

// 결과 화면의 기존 카드 선택과 지도 호출은 유지하면서 그래프만 갱신한다.
const cards=[new Node(),new Node()]; cards.forEach(card=>{card.querySelector=()=>new Node();});
const list=new Node();list.querySelectorAll=()=>cards;
const chartNode=new Node(), summary={};
const elements={'route-list':list,'duration-chart':chartNode,'route-map':new Node(),'ai-title':{},'ai-text':{}};
const maps=[], drawings=[];
const page=vm.createContext({ normalizeRouteGraphs:model.normalizeRouteGraphs, ROUTE_COLORS:['#2563EB','#16A36A'], USE_MOCK:true,
 document:{querySelector:()=>summary,getElementById:id=>elements[id]},
 renderRouteMap:(node,options)=>maps.push(options),renderDurationChart:(node,options)=>{drawings.push(options);node.dataset.routeId=options.routeId;},
 formatRouteLabel:route=>route.name,escapeHtml:v=>String(v), dateOf:()=> '2026-11-15',timeOf:value=>value?.slice(11,16) ?? '미제공',formatBuffer:value=>value ? `${value}분` : '없음',formatWon:value=>`${value.toLocaleString('ko-KR')}원`,icon:()=>''
});
vm.runInContext(strip(await read('../js/pages/result.js')).replace(/\ninit\(\);\s*$/, ''),page);
const routes=[{id:'route-1',name:'추천',departTime:points[0].departTime,aiSummary:{}},{id:'route-2',name:'최단',departTime:points[1].departTime,aiSummary:{}}];
const update=page.setupResults({date:'2026-11-15',buffer:0},routes);
assert.equal(maps.length,1);assert(drawings.at(-1).message.includes('불러오는 중'));
cards[1].events.click();assert.equal(maps.at(-1).route.id,'route-2');assert.equal(drawings.at(-1).routeId,'route-2');
const mapCount=maps.length;
update({graphs:[{routeId:'route-1',points},{routeId:'route-2',points:[points[1]]}]});
assert.equal(maps.length,mapCount);assert.equal(drawings.at(-1).points.length,1);assert.equal(drawings.at(-1).recommendedTime,points[1].departTime);
assert.equal(drawings.at(-1).color,'#16A36A');
update({message:'그래프 API 실패'});assert.equal(drawings.at(-1).message,'그래프 API 실패');assert.equal(maps.length,mapCount);
cards[0].events.keydown({target:cards[0],key:'Enter',preventDefault(){}});assert.equal(maps.at(-1).route.id,'route-1');assert.equal(drawings.at(-1).routeId,'route-1');
for(const path of ['../js/components/durationGraph.js','../js/components/charts.js','../js/pages/result.js','../js/api.js']) new vm.Script(strip(await read(path)));
console.log('PASS: 결과 화면 카드/키보드 선택·지도/그래프 ID/색상 일치·늦은 응답 때 선택 유지·그래프 실패 뒤 지도 유지 (모의 DOM)');

const changes = [46,54,51,51].map((durationMin,i)=>({...points[0],departTime:`2026-11-15T08:${i}0:00+09:00`,durationMin}));
assert(model.durationChange(changes,1).text.includes('8분 증가'));
assert(model.durationChange(changes,2).text.includes('3분 단축'));
assert(model.durationChange(changes,3).text.includes('변화 없음'));
assert.equal(model.summaryPosition({width:700,height:270,cardWidth:270,cardHeight:210,x:100,y:50}).side,'right');
const placement=model.summaryPosition({width:700,height:270,cardWidth:270,cardHeight:210,x:650,y:260});
assert.equal(placement.side,'left');assert(placement.top+210<=270);assert(placement.left>=0);
const html=page.renderRouteCard({...routes[0],arriveTime:'2026-11-15T08:50:00+09:00',durationMin:45,distanceKm:28.7,toll:0,fuel:null},0,{date:'2026-11-15',buffer:10});
assert.equal([...html.matchAll(/class="route-metric"/g)].length,3);assert(html.includes('45분'));assert(html.includes('28.7km'));assert(html.includes('08:50 도착 예정'));assert(html.includes('여유 10분'));assert(html.includes('0원'));assert(!html.includes('star-button'));
// 지표는 라벨(small)·값(b) 2줄, 아이콘 타일 없음, 순서는 예상 소요시간 / 거리 / 통행료
assert.deepEqual([...html.matchAll(/<div class="route-metric"><small>([^<]+)<\/small><b>[^<]*<\/b><\/div>/g)].map(m=>m[1]),['예상 소요시간','거리','통행료']);
assert(!html.includes('route-metric-icon'));
assert.match(html,/<div class="arrival-info"><div class="arrival-main">[^]*?<b>08:50 도착 예정<\/b><\/div><span>여유 10분<\/span><\/div>/);
// 유류비는 응답에 값이 있어도 카드에 표시하지 않는다 (API·mock 필드는 그대로)
const paid=page.renderRouteCard({...routes[0],arriveTime:'2026-11-15T08:50:00+09:00',fuel:3900,toll:1300},0,{date:'2026-11-15',buffer:0});assert(paid.includes('1,300원'));
for (const card of [html, paid]) { assert(!card.includes('유류비')); assert(!card.includes('3,900원')); }
const missing=page.renderRouteCard({...routes[0],arriveTime:'2026-11-15T08:50:00+09:00',toll:null},0,{date:'2026-11-15',buffer:0});assert.equal([...missing.matchAll(/미제공/g)].length,3);
assert(!(await read('../js/pages/result.js')).includes('유류비'));
assert((await read('../js/mock/routes.json')).includes('"fuel"')); // mock 필드는 삭제하지 않는다
// 카드 색 규칙: 토큰 값과 선택/미선택 규칙. 같은 선택자에서 그 속성을 선언한 마지막 규칙(@media 안 포함)을 본다.
const tokens=await read('../css/base.css');
for (const [name,value] of [['--white','#ffffff'],['--blue-pale','#f5f8ff'],['--navy','#0b1f4b'],['--blue','#2563eb'],['--line','#e6eaf0']]) assert.match(tokens,new RegExp(`${name}: ${value};`));
const cardCss=(await read('../css/pages/result.css')).replace(/\/\*[\s\S]*?\*\//g,'');
const cssRules=[...cardCss.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([,s,body])=>({selectors:s.split(',').map(v=>v.trim()),decls:Object.fromEntries(body.split(';').map(d=>d.split(/:(.*)/s).map(v=>v.trim())).filter(([k,v])=>k&&v))}));
const lastDecl=(selector,prop)=>cssRules.filter(r=>r.selectors.includes(selector)&&prop in r.decls).at(-1)?.decls[prop];
assert.equal(lastDecl('.route-card','background'),'var(--white)');
assert.equal(lastDecl('.route-card.selected','background'),'var(--blue-pale)');
assert.equal(lastDecl('.route-card.selected','box-shadow'),'0 0 0 1px var(--blue)');
assert.equal(lastDecl('.departure-time','color'),'var(--navy)');
assert.equal(lastDecl('.route-card.selected .departure-time','color'),'var(--blue)');
assert.equal(lastDecl('.route-details','grid-template-columns'),'repeat(3, minmax(0, 1fr))');
assert.equal(lastDecl('.route-metric','border-left'),'1px solid var(--line)');
assert.equal(lastDecl('.arrival-info','border-top'),'1px solid var(--line)');
assert.equal(lastDecl('.route-card','--route-arrival'),'#1aa46d');
assert.equal(lastDecl('.arrival-main b','color'),'var(--route-arrival)');
console.log('PASS: 증가/단축/동일/첫 데이터·좌우 및 수직 위치 경계·3개 경로 지표(유류비 없음)·누락값·카드 색 규칙');

for(const y of [44,120,200]) {
  const placement=model.summaryPosition({width:700,height:270,cardWidth:250,cardHeight:180,x:400,y});
  assert.equal(placement.top+placement.tailTop,y);
  assert(placement.top>=0 && placement.top+180<=270);
}
console.log('PASS: 작은 말풍선 꼬리의 지점 Y좌표·상하 경계·표에서 Escape 닫기');
