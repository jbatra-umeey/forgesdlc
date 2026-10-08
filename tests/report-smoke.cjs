// Dependency-free DOM smoke test; not a rendered-browser layout test.
const fs=require('fs');
const vm=require('vm');
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.textContent='';this.className='';this.classList={toggle:()=>{}};}
 append(child){this.children.push(child)}
 replaceChildren(){this.children=[]}
}
const elements=new Map();
const document={getElementById:id=>{if(!elements.has(id))elements.set(id,new Element('div'));return elements.get(id)},createElement:tag=>new Element(tag)};
const file=process.argv[2];if(!file)throw new Error('usage: node tests/report-smoke.cjs REPORT_HTML');
const html=fs.readFileSync(file,'utf8');
const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
if(scripts.length!==1)throw new Error('Report must have one inline script');
vm.runInNewContext(scripts[0][1],{document,console});
const get=id=>elements.get(id);
if(get('cards').children.length!==3)throw new Error('Expected three scenario cards');
if(!get('notice').textContent.includes('REFERENCE REPLAY'))throw new Error('Mode label missing');
const allCount=get('timeline').children.length;
get('controls').children.find(button=>button.dataset.filter==='C').onclick();
if(get('timeline').children.length<5)throw new Error('C evidence missing');
if(get('timeline').children.some(row=>row.children[1].textContent!=='C'))throw new Error('Scenario filter incorrect');
get('controls').children[0].onclick();
if(get('timeline').children.length!==allCount)throw new Error('All-scenarios filter incorrect');
if(!JSON.parse(get('raw').textContent).scenarios.C.issue.operation_key)throw new Error('Remediation issue missing');
console.log(JSON.stringify({passed:true,scenarioCards:3,timelineEvents:allCount,filtersVerified:true,renderedBrowser:false}));
