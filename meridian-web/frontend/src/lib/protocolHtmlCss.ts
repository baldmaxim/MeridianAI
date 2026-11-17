/**
 * CSS экспортируемого HTML-протокола: повторяет вид страницы задачи на сайте
 * (BatchJobDetail / MarkdownView / BatchTranscript). Токены — копия index.css (обе темы);
 * хардкод цветов только в объявлении токенов, правила используют var(--…).
 */

const DARK_TOKENS =
  '--bg:#080A0F;--surface:#111520;--elevated:#161C2C;--text:#EDF2FF;--text-2:#8896B3;--muted:#7A859E;' +
  '--border:rgba(255,255,255,.06);--border-strong:rgba(255,255,255,.12);--border-amber:rgba(245,166,35,.25);' +
  '--accent:#F5A623;--glow:rgba(245,166,35,.12);--blue:#5B9CF6;--green:#2EE59D;--red:#FF4B6E;color-scheme:dark';

const LIGHT_TOKENS =
  '--bg:#F3F5F9;--surface:#FFFFFF;--elevated:#E9EDF4;--text:#141A29;--text-2:#4A5670;--muted:#5B677E;' +
  '--border:rgba(20,26,41,.12);--border-strong:rgba(20,26,41,.2);--border-amber:rgba(147,91,0,.35);' +
  '--accent:#935B00;--glow:rgba(147,91,0,.1);--blue:#1D5CC0;--green:#0A7348;--red:#C41E3F;color-scheme:light';

export const PROTOCOL_HTML_CSS = `
:root{${DARK_TOKENS};
--f-body:'Inter',system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
--f-head:'Syne','Inter',system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
--f-mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media (prefers-color-scheme:light){:root:not([data-theme="dark"]){${LIGHT_TOKENS}}}
:root[data-theme="light"]{${LIGHT_TOKENS}}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:120px;scroll-padding-bottom:16px}
body{margin:0;background:var(--bg);color:var(--text);font:13px/1.5 var(--f-body);overflow-wrap:anywhere;-webkit-tap-highlight-color:transparent}
button,a{touch-action:manipulation}
.page{max-width:960px;margin:0 auto;padding:12px max(12px,env(safe-area-inset-right)) 48px max(12px,env(safe-area-inset-left))}

/* шапка: имя файла + дата + переключатель темы */
.head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;min-height:44px}
.file-name{margin:0;font:600 13px/1.4 var(--f-body);color:var(--text);min-width:0}
.date{font:400 10px var(--f-mono);color:var(--muted)}
.theme-btn{margin-left:auto;flex:none;width:44px;height:44px;border:1px solid var(--border-strong);border-radius:8px;background:var(--surface);color:var(--text);font-size:18px;line-height:1;cursor:pointer}
.theme-btn:hover{border-color:var(--accent)}
.theme-btn:focus-visible,.tab:focus-visible{outline:2px solid var(--accent);outline-offset:2px}

/* липкий блок: вкладки + плеер */
.sticky{position:sticky;top:0;z-index:10;background:var(--bg);padding:4px 0 8px}
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--border)}
.tab{min-height:44px;padding:0 14px;margin-bottom:-1px;background:transparent;border:0;border-bottom:2px solid transparent;color:var(--text-2);cursor:pointer;font:600 11px var(--f-mono);letter-spacing:.06em}
.tab:hover{color:var(--text)}
.tab.active{border-bottom-color:var(--accent);color:var(--accent)}
audio{display:block;width:100%;height:36px;margin-top:8px}
.audio-err{margin:8px 0 0;padding:10px 12px;border:1px solid var(--red);color:var(--red);border-radius:8px;font-size:13px}
.audio-err[hidden]{display:none}
.pane{margin-top:12px}
.print-h{display:none}

/* протокол — как MarkdownView.module.css */
.card{padding:14px 18px;border-radius:8px;background:var(--surface)}
.doc{display:flex;flex-direction:column;gap:6px;font-family:var(--f-body);color:var(--text)}
.h2{margin:12px 0 0;padding-bottom:4px;font:800 15px/1.5 var(--f-head);letter-spacing:.02em;color:var(--accent);border-bottom:1px solid var(--border-amber)}
.h3{margin:8px 0 0;font:700 13px/1.5 var(--f-body);color:var(--text)}
.p{margin:0;font-size:13px;line-height:1.65;color:var(--text-2)}
.ul{margin:2px 0;padding-left:18px;display:flex;flex-direction:column;gap:4px}
.li{font-size:13px;line-height:1.55;color:var(--text-2)}
.table-wrap{overflow-x:auto;margin:6px 0}
.table{border-collapse:collapse;width:100%;font-size:12.5px}
.th{text-align:left;padding:7px 10px;background:var(--elevated);color:var(--text);font-weight:700;border:1px solid var(--border);white-space:nowrap}
.td{padding:7px 10px;color:var(--text-2);border:1px solid var(--border);vertical-align:top}
code{font-family:var(--f-mono);font-size:12px;background:var(--surface);padding:1px 5px;border-radius:4px;color:var(--accent)}
strong{color:var(--text);font-weight:700}
mark{background:color-mix(in srgb,var(--accent) 22%,transparent);color:var(--text);font-weight:inherit;padding:0 3px;border-radius:3px;-webkit-box-decoration-break:clone;box-decoration-break:clone}
.chip{display:inline-block;font:400 10px/1.5 var(--f-mono);color:var(--muted);background:var(--elevated);padding:0 5px;border-radius:4px;white-space:nowrap}
a.tc{color:inherit;text-decoration:none;border-bottom:1px dotted currentColor}
a.tc:hover{color:var(--accent)}
.doc a.tc{color:var(--accent)}
.chip a.tc{color:inherit}
.chip a.tc:hover{color:var(--accent)}

/* транскрипция — как BatchTranscript.module.css */
.seg-list{display:flex;flex-direction:column;gap:10px;padding:4px 2px}
.seg{display:flex;gap:12px;align-items:flex-start;padding:4px 8px;border-radius:6px;border-left:2px solid transparent;transition:background .15s}
.has-audio .seg{cursor:pointer}
.seg.active{background:var(--glow);border-left-color:var(--accent)}
.seg-meta{display:flex;flex-direction:column;gap:2px;flex:none;width:88px}
.seg-speaker{font:700 10px var(--f-mono);letter-spacing:.02em}
.seg-time{font:400 10px var(--f-mono);color:var(--muted)}
.seg-body{flex:1;min-width:0}
.seg-text{font:400 13px/1.6 var(--f-body);color:var(--text)}
.seg-ru{display:flex;gap:6px;align-items:baseline;margin-top:3px;font-size:12.5px;line-height:1.55;color:var(--text-2)}
.ru-tag{flex:none;font:700 9px var(--f-mono);letter-spacing:.08em;color:var(--blue);border:1px solid color-mix(in srgb,var(--blue) 27%,transparent);border-radius:4px;padding:0 4px}
.t0{color:var(--blue)}.t1{color:var(--green)}.t2{color:var(--accent)}.t3{color:var(--red)}
.t4{color:color-mix(in srgb,var(--blue) 55%,var(--red) 45%)}.t5{color:color-mix(in srgb,var(--blue) 50%,var(--green) 50%)}
.t6{color:color-mix(in srgb,var(--red) 50%,var(--accent) 50%)}.t7{color:color-mix(in srgb,var(--green) 50%,var(--accent) 50%)}

@media (max-width:480px){
.card{padding:12px}
.seg{flex-direction:column;gap:2px}
.seg-meta{flex-direction:row;gap:10px;width:auto}
.tab{flex:1;padding:0 8px}
}
@media (prefers-reduced-motion:reduce){
html{scroll-behavior:auto}
.seg{transition:none}
}
@media print{
:root,:root[data-theme="dark"],:root[data-theme="light"]{${LIGHT_TOKENS}}
.sticky,.theme-btn,.audio-err{display:none!important}
.pane,.pane[hidden]{display:block}
.pane{margin-top:16px}
.print-h{display:block;margin:0 0 8px;font:800 15px var(--f-head);color:var(--accent)}
.page{max-width:none;padding:0}
.card{padding:0;background:none}
.seg{break-inside:avoid;cursor:auto}
.seg.active{background:none;border-left-color:transparent}
mark{background:none;text-decoration:underline}
}
`;
