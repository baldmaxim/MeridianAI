/** CSS и скрипт экспортируемого HTML-протокола. Самодостаточный документ: без внешних ресурсов. */

export const PROTOCOL_HTML_CSS = `
:root{--bg:#080A0F;--surface:#111520;--elevated:#161C2C;--text:#EDF2FF;--muted:#8896B3;--border:#232B40;--accent:#F5A623;--accent-bg:rgba(245,166,35,.16);--err:#FF4B6E;
--t0:#5B9CF6;--t1:#2EE59D;--t2:#F5A623;--t3:#FF4B6E;--t4:#A78BDA;--t5:#3FD0C9;--t6:#FF8A5B;--t7:#B5D84A}
@media (prefers-color-scheme:light){:root{--bg:#F5F6FA;--surface:#FFFFFF;--elevated:#EEF0F6;--text:#161C2C;--muted:#586079;--border:#D5DAE6;--accent:#B26B00;--accent-bg:rgba(245,166,35,.22);--err:#C62848;
--t0:#2F6FD0;--t1:#0E8F5C;--t2:#B26B00;--t3:#C62848;--t4:#7A56B8;--t5:#13827C;--t6:#C4501A;--t7:#6B8A10}}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:150px;scroll-padding-bottom:16px}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;overflow-wrap:anywhere}
.top{position:sticky;top:0;z-index:10;background:var(--surface);border-bottom:1px solid var(--border);padding:8px 12px}
.top-in{max-width:960px;margin:0 auto}
.nav{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.nav a{color:var(--muted);text-decoration:none;padding:8px 14px;border-radius:8px;border:1px solid var(--border);font-size:14px;min-height:40px;display:inline-flex;align-items:center}
.nav a:hover{color:var(--text);border-color:var(--accent)}
.nav-title{margin-left:auto;color:var(--muted);font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:50%}
audio{display:block;width:100%;margin-top:8px;height:44px}
.audio-err{margin-top:8px;padding:10px 12px;border:1px solid var(--err);color:var(--err);border-radius:8px;font-size:14px}
.audio-err[hidden]{display:none}
main{max-width:960px;margin:0 auto;padding:16px 12px 48px}
h1{font-size:20px;margin:8px 0 4px}
.meta{color:var(--muted);font-size:13px;margin:0 0 8px}
h2{font-size:17px;color:var(--accent);margin:28px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--accent)}
h3{font-size:15px;margin:18px 0 6px}
p{margin:6px 0;color:var(--muted)}
ul,ol{margin:6px 0;padding-left:22px}
li{margin:4px 0}
strong{color:var(--text)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.9em;background:var(--elevated);padding:1px 5px;border-radius:4px}
.table-wrap{overflow-x:auto;margin:10px 0}
table{border-collapse:collapse;min-width:100%;font-size:14px}
th,td{border:1px solid var(--border);padding:6px 10px;text-align:left;vertical-align:top}
th{background:var(--elevated)}
a.tc{color:var(--accent);text-decoration:none;border-bottom:1px dotted var(--accent);white-space:nowrap}
a.tc:hover{background:var(--accent-bg)}
.seg{display:flex;gap:12px;padding:8px 10px;border-radius:8px;border-left:3px solid transparent}
.has-audio .seg{cursor:pointer}
.seg:hover{background:var(--elevated)}
.seg.active{background:var(--accent-bg);border-left-color:var(--accent)}
.seg-meta{flex:0 0 92px;display:flex;flex-direction:column;gap:2px;font-size:13px}
.seg-speaker{font-weight:700}
.seg-time{color:var(--muted);font-variant-numeric:tabular-nums}
.seg-body{flex:1;min-width:0}
.seg-ru{color:var(--muted);font-size:14px;margin-top:2px}
.t0{color:var(--t0)}.t1{color:var(--t1)}.t2{color:var(--t2)}.t3{color:var(--t3)}.t4{color:var(--t4)}.t5{color:var(--t5)}.t6{color:var(--t6)}.t7{color:var(--t7)}
@media (max-width:480px){.seg{flex-direction:column;gap:2px}.seg-meta{flex-direction:row;gap:10px;flex-basis:auto}.nav-title{display:none}}
@media print{
:root{--bg:#fff;--surface:#fff;--elevated:#f1f1f1;--text:#000;--muted:#333;--border:#999;--accent:#8a5200;--accent-bg:transparent;
--t0:#000;--t1:#000;--t2:#000;--t3:#000;--t4:#000;--t5:#000;--t6:#000;--t7:#000}
.top{display:none}main{max-width:none;padding:0}.seg{break-inside:avoid;cursor:auto}
}
`;

/** Плеер: клик по реплике и таймкоду → перемотка, подсветка текущей реплики. */
export const PROTOCOL_HTML_SCRIPT = `
(function(){
var audio=document.getElementById('player');
if(!audio)return;
var rows=[].slice.call(document.querySelectorAll('.seg'));
var starts=rows.map(function(r){return parseFloat(r.getAttribute('data-start'))||0;});
var cur=-1;
function idxAt(t){var i=-1;for(var k=0;k<starts.length;k++){if(starts[k]<=t+0.15)i=k;else break;}return i;}
function setActive(i,block){
if(i===cur)return;
if(cur>=0&&rows[cur])rows[cur].classList.remove('active');
cur=i;
if(i>=0&&rows[i]){rows[i].classList.add('active');rows[i].scrollIntoView({block:block});}
}
function seek(t){audio.currentTime=t;var p=audio.play();if(p&&p.catch)p.catch(function(){});}
document.addEventListener('click',function(e){
var tc=e.target.closest&&e.target.closest('.tc');
if(tc){
e.preventDefault();
var t=parseFloat(tc.getAttribute('data-t'))||0;
seek(t);
var i=idxAt(t);
if(i===cur&&rows[i])rows[i].scrollIntoView({block:'center'});
else setActive(i,'center');
return;
}
var row=e.target.closest&&e.target.closest('.seg');
if(row){
var sel=window.getSelection&&window.getSelection();
if(sel&&String(sel).length)return;
seek(parseFloat(row.getAttribute('data-start'))||0);
}
});
audio.addEventListener('timeupdate',function(){setActive(idxAt(audio.currentTime),'nearest');});
audio.addEventListener('error',function(){
var b=document.getElementById('audio-err');
if(b)b.hidden=false;
});
})();
`;
