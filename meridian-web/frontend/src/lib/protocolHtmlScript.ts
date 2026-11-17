/** Скрипты экспортируемого HTML-протокола: тема (до отрисовки), вкладки, плеер. */

/** В <head>, до CSS: сохранённый выбор темы → data-theme (без выбора работает prefers-color-scheme). */
export const PROTOCOL_HTML_THEME_INIT = `
(function(){try{var t=localStorage.getItem('meridian-export-theme');if(t==='dark'||t==='light')document.documentElement.setAttribute('data-theme',t);}catch(e){}})();
`;

/** Переключатель темы, вкладки Транскрипция/Протокол; плеер — только если на странице есть #player. */
export const PROTOCOL_HTML_SCRIPT = `
(function(){
var root=document.documentElement;
var tbtn=document.getElementById('theme-toggle');
function curTheme(){
var t=root.getAttribute('data-theme');
if(t==='dark'||t==='light')return t;
return window.matchMedia&&window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';
}
function paintTheme(){
if(!tbtn)return;
var dark=curTheme()==='dark';
tbtn.textContent=dark?'\\u2600':'\\u263E';
tbtn.setAttribute('aria-label',dark?'Включить светлую тему':'Включить тёмную тему');
}
if(tbtn){
tbtn.addEventListener('click',function(){
var next=curTheme()==='dark'?'light':'dark';
root.setAttribute('data-theme',next);
try{localStorage.setItem('meridian-export-theme',next);}catch(e){}
paintTheme();
});
}
paintTheme();

var tabs=[].slice.call(document.querySelectorAll('[data-tab]'));
var panes=[].slice.call(document.querySelectorAll('[data-pane]'));
function showTab(name){
tabs.forEach(function(b){
var on=b.getAttribute('data-tab')===name;
b.classList.toggle('active',on);
b.setAttribute('aria-selected',on?'true':'false');
});
panes.forEach(function(p){p.hidden=p.getAttribute('data-pane')!==name;});
}
tabs.forEach(function(b){
b.addEventListener('click',function(){showTab(b.getAttribute('data-tab'));window.scrollTo(0,0);});
});

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
if(!rows.length)return;
showTab('transcript');
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
