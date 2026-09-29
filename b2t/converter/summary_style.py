"""Shared visual theme for summary HTML, images and print exports."""

SUMMARY_LINKS = '<div class="b2t-report-links">\n<span>转录网址：<a href="https://b2t.kkkzoz.top" target="_blank" rel="noopener noreferrer">https://b2t.kkkzoz.top</a></span>\n<a class="b2t-project-link" href="https://github.com/KKKZOZ/bilibili2text" target="_blank" rel="noopener noreferrer" aria-label="GitHub 项目 KKKZOZ/bilibili2text"><svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 .75a11.25 11.25 0 0 0-3.56 21.92c.56.1.77-.24.77-.54v-2.1c-3.13.68-3.79-1.33-3.79-1.33-.51-1.3-1.25-1.65-1.25-1.65-1.02-.7.08-.69.08-.69 1.13.08 1.72 1.16 1.72 1.16 1 1.72 2.64 1.22 3.28.93.1-.73.39-1.22.71-1.5-2.5-.28-5.13-1.25-5.13-5.56 0-1.23.44-2.23 1.16-3.02-.12-.28-.5-1.43.11-2.98 0 0 .95-.3 3.1 1.16a10.8 10.8 0 0 1 5.63 0c2.15-1.46 3.1-1.16 3.1-1.16.61 1.55.23 2.7.11 2.98.72.79 1.16 1.79 1.16 3.02 0 4.32-2.63 5.27-5.14 5.55.4.35.76 1.04.76 2.1v3.09c0 .3.2.65.77.54A11.25 11.25 0 0 0 12 .75Z"/></svg><span>KKKZOZ/bilibili2text</span></a>\n</div>'

SUMMARY_CSS = """
.b2t-report-links{display:flex;align-items:center;justify-content:center;gap:10px 20px;flex-wrap:wrap;margin-top:14px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;font-size:18px;line-height:1.6;text-align:center;color:#64748b}.b2t-report-links a{color:inherit;text-decoration:underline;text-underline-offset:3px;overflow-wrap:anywhere}.b2t-report-links>span{min-width:0}.b2t-report-links .b2t-project-link{display:inline-flex;align-items:center;gap:6px}.b2t-project-link svg{flex-shrink:0}

body:has(.summary-document) { background:#f2f5f7; padding:24px 16px; }
.markdown-body.summary-document {
  max-width:860px; padding:44px 46px; background:#fff; color:#414b55;
  border-radius:8px; border-top:4px solid #e6a17e;
  box-shadow:0 8px 30px #25384b0b; font-size:17px; line-height:1.85;
  overflow-wrap:anywhere; color-scheme:light;
}
.summary-document .summary-header { margin-bottom:36px; padding-bottom:24px; border-bottom:1px solid #e9edf0; }
.summary-document .summary-title { margin:0; padding:0; border:0; color:#242d35; font-size:34px; line-height:1.45; font-weight:750; }
.summary-document .summary-meta { display:flex; flex-wrap:wrap; gap:8px 24px; margin-top:18px; color:#65717d; font-size:12px; }
.summary-document .summary-meta-item { display:inline-flex; flex-wrap:wrap; gap:6px; }
.summary-document h2 { margin:38px 0 20px; padding-bottom:12px; border-bottom:1px solid #e9edf0; color:#242d35; font-size:24px; line-height:1.55; }
.summary-document h3 { margin:26px 0 12px; color:#242d35; font-size:19px; line-height:1.6; }
.summary-document p, .summary-document ul, .summary-document ol { margin-bottom:18px; }
.summary-document li + li { margin-top:8px; }
.summary-document li::marker { color:#c8562e; }
.summary-document a { color:#23658b; text-underline-offset:3px; }
.summary-document a:focus-visible { outline:2px solid #c8562e; outline-offset:3px; }
.summary-document blockquote { margin:24px 0; padding:18px 22px; background:#edf7ff; border-left:3px solid #6997ad; border-radius:6px; color:#426779; }
.summary-document blockquote > :last-child { margin-bottom:0; }
.summary-document table { margin:24px 0; font-size:14px; line-height:1.7; }
.summary-document th, .summary-document td { border:1px solid #e9edf0; padding:12px; }
.summary-document thead th { background:#f2f5f7; color:#242d35; }
.summary-document .stock-table-cards { gap:18px; margin:24px 0; }
.summary-document .stock-table-card { width:100%; padding:22px; border-color:#e9edf0; border-radius:9px; background:#fff; }
.summary-document .stock-table-head { flex-wrap:wrap; margin-bottom:16px; }
.summary-document .stock-table-head h3 { margin:0; }
.summary-document .stock-table-fields { gap:14px 20px; margin-bottom:16px; }
.summary-document .stock-table-field p { line-height:1.8; }
.summary-document .stock-status-metrics { padding-top:14px; gap:10px; }
.summary-document .stock-table-time-link { color:#23658b; border-color:#d6eaf3; background:#edf7ff; }
@media (max-width:600px) {
  body:has(.summary-document) { padding:0; }
  .markdown-body.summary-document { padding:28px 20px; border-radius:0; box-shadow:none; font-size:16px; }
  .summary-document .summary-title { font-size:26px; }
  .summary-document h2 { font-size:22px; }
  .summary-document .stock-table-card { padding:16px; }
  .summary-document .stock-table-fields { grid-template-columns:1fr; }
  .summary-document .stock-status-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); }
}
@media print {
  body:has(.summary-document) { background:white; padding:0; }
  .markdown-body.summary-document { max-width:none; padding:0; border:0; border-radius:0; box-shadow:none; font-size:11pt; }
  .summary-document .summary-title { font-size:24pt; }
  .summary-document h2 { font-size:17pt; }
  .summary-document h3 { font-size:14pt; }
  .summary-document h1, .summary-document h2, .summary-document h3 { break-after:avoid; }
  .summary-document .stock-table-card, .summary-document tr { break-inside:avoid; }
  .summary-document thead { display:table-header-group; }
  .summary-document p { orphans:3; widows:3; }
}
"""
