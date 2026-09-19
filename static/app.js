const $ = (selector) => document.querySelector(selector);
const escape = (value = '') => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths = {
  library:'M4 5h4v15H4z M10 5h4v15h-4z m7 0 4 1-3 14-4-1z',
  plus:'M12 5v14M5 12h14', search:'m21 21-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  star:'m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z',
  clock:'M12 8v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
  review:'M9 3h6l1 3h4v15H4V6h4z M8 13l3 3 5-6',
  folder:'M3 6h7l2 2h9v12H3z', tag:'M3 3h8l10 10-8 8L3 11zM7 7h.01',
  trash:'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7',
  settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1z',
  export:'M12 15V3m-4 4 4-4 4 4M4 13v7h16v-7', upload:'M12 16V4m-5 5 5-5 5 5M4 15v6h16v-6',
  file:'M14 2H5v20h14V7zM14 2v6h5M8 12h8M8 16h6',
  book:'M12 5c-4-3-8-2-10-1v15c3-2 7-2 10 0 3-2 7-2 10 0V4c-2-1-6-2-10 1v14',
  check:'m5 12 4 4L19 6', close:'m6 6 12 12M6 18 18 6', down:'m6 9 6 6 6-6',
  grid:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  list:'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
  table:'M3 4h18v16H3zM3 9h18M3 14h18M9 4v16M15 4v16',
  filter:'M4 7h16M7 12h10M10 17h4', arrow:'M4 12h16m-6-6 6 6-6 6',
  external:'M14 3h7v7m0-7L10 14M10 3H3v18h18v-7',
  quote:'M4 6h6v7H6c0 3 2 4 4 4v2c-4 0-6-3-6-7zM14 6h6v7h-4c0 3 2 4 4 4v2c-4 0-6-3-6-7z',
  edit:'m15 3 6 6-12 12H3v-6zM12 6l6 6', copy:'M9 9h12v12H9zM15 9V3H3v12h6',
  spark:'m12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3z',
  restore:'M3 10a9 9 0 1 1 1 8M3 4v6h6', info:'M12 10v7M12 7h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
  link:'m10 14 4-4M8 16l-2 2a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0M16 8l2-2a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0',
};
function icon(name, cls='') {return `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name] || paths.file}"/></svg>`;}
const state = {items:[], collections:[], counts:{}, duplicateIds:[], scope:'all', tag:'', query:'', sort:'recent', view:'list', unread:false, selected:null, detail:null, tab:'info', checked:new Set(), noteDraft:'', modal:'', uploadTab:'files', uploadResults:[], readerTab:'original'};
const typeLabels = {'article-journal':'Journal article', book:'Book', chapter:'Book chapter', 'paper-conference':'Conference paper', thesis:'Thesis', report:'Report', webpage:'Web page', document:'Document'};
const libraryColumns = [
  ['title','Title'], ['authors','Authors'], ['year','Year'], ['journal','Publication'],
  ['type','Type'], ['tags','Tags'], ['doi','DOI'], ['publisher','Publisher'],
  ['volume','Volume'], ['issue','Issue'], ['pages','Pages'], ['fileName','File name'],
  ['collections','Collections'], ['read','Reading status'], ['status','Processing status'],
  ['reviewed','Metadata review'], ['createdAt','Date added'], ['updatedAt','Date modified'],
];
const defaultColumns = ['title','authors','year','journal','type'];
const tablePreferenceKey = 'synopsis.library-view';
state.columnOrder = libraryColumns.map(([key])=>key);
state.columns = [...defaultColumns];
try {
  const saved = JSON.parse(localStorage.getItem(tablePreferenceKey));
  if (saved && typeof saved === 'object') {
    if (['list','grid','table'].includes(saved.view)) state.view = saved.view;
    const valid = keys => Array.isArray(keys) ? [...new Set(keys.filter(k=>state.columnOrder.includes(k)))] : [];
    const order = valid(saved.order), columns = valid(saved.columns);
    state.columnOrder = [...order,...state.columnOrder.filter(k=>!order.includes(k))];
    if (columns.length) state.columns = columns;
  }
} catch { /* Unavailable storage or old preferences should not prevent loading. */ }
function saveLibraryView() {
  try { localStorage.setItem(tablePreferenceKey,JSON.stringify({view:state.view,order:state.columnOrder,columns:state.columns})); }
  catch { /* The current session still keeps its preferences. */ }
}
function setLibraryView(view) {state.view=view;saveLibraryView();renderList();}
function columnLabel(key) {return libraryColumns.find(([id])=>id===key)[1];}
function visibleColumns() {return state.columnOrder.filter(key=>state.columns.includes(key));}
function columnValue(item,key) {
  if (key==='type') return typeLabels[item.type]||item.type;
  if (key==='authors'||key==='tags') return (item[key]||[]).join('; ');
  if (key==='collections') return state.collections.filter(c=>item.collections.includes(c.id)).map(c=>c.name).join('; ');
  if (key==='read') return item.read?'Read':'To read';
  if (key==='reviewed') return item.reviewed?'Reviewed':'Needs review';
  if (key==='status') return ({ready:'Ready',queued:'Queued',processing:'Processing',error:'Needs attention'})[item.status]||item.status;
  if (key==='createdAt'||key==='updatedAt') return item[key]?formatDate(item[key]):'';
  return item[key]||'';
}
function renderTable(items) {
  const columns=visibleColumns();
  return `<div class="library-table-scroll" tabindex="0" role="region" aria-label="Reference table"><table class="library-table"><caption class="visually-hidden">Library references. Drag column headers to reorder, or focus a header and press Alt plus an arrow key.</caption><thead><tr><th scope="col" class="table-control"><span class="visually-hidden">Select</span></th>${columns.map(key=>`<th scope="col" data-column="${key}" class="column-${key}" draggable="true"><button class="column-header" data-column-header="${key}" title="Drag to reorder; Alt + Left or Right to move">${columnLabel(key)}<span aria-hidden="true">⠿</span></button></th>`).join('')}<th scope="col" class="table-control"><span class="visually-hidden">Starred</span></th></tr></thead><tbody>${items.map(item=>`<tr class="table-reference ${state.selected===item.id?'selected':''}" data-id="${item.id}" tabindex="0" aria-label="${escape(item.title)}" aria-selected="${state.selected===item.id}"><td class="table-control"><input type="checkbox" data-check="${item.id}" aria-label="Select ${escape(item.title)}" ${state.checked.has(item.id)?'checked':''}></td>${columns.map(key=>`<td class="column-${key}" title="${escape(columnValue(item,key))}">${escape(columnValue(item,key))||'—'}</td>`).join('')}<td class="table-control"><button class="icon-button star-button ${item.starred?'starred':''}" data-star="${item.id}" aria-label="${item.starred?'Unstar':'Star'} reference">${icon('star')}</button></td></tr>`).join('')}</tbody></table></div>`;
}
function openColumnChooser(focusKey) {
  state.modal='columns';
  modal('Choose columns','Choose which details appear. Drag table headers to reorder them, or use the arrows below.',`<div class="modal-body"><div class="column-options">${state.columnOrder.map((key,index)=>`<div class="column-option"><label><input type="checkbox" data-column-toggle="${key}" ${state.columns.includes(key)?'checked':''}>${columnLabel(key)}</label><button class="icon-button" data-column-move="${key}" data-direction="-1" aria-label="Move ${columnLabel(key)} earlier" ${index===0?'disabled':''}>↑</button><button class="icon-button" data-column-move="${key}" data-direction="1" aria-label="Move ${columnLabel(key)} later" ${index===state.columnOrder.length-1?'disabled':''}>↓</button></div>`).join('')}</div><div class="form-actions"><button class="button secondary" data-action="reset-columns">Reset columns</button><button class="button primary" data-action="close-modal">Done</button></div></div>`);
  if(focusKey) document.querySelector(`[data-column-toggle="${focusKey}"]`)?.focus();
}
function moveColumn(key,target) {
  const from=state.columnOrder.indexOf(key), to=state.columnOrder.indexOf(target);
  if(from<0||to<0||from===to)return;
  state.columnOrder.splice(from,1);state.columnOrder.splice(to,0,key);
  saveLibraryView();renderList();
}
let searchTimer, refreshSerial=0, detailSerial=0, pollTimer, lastFocus;
async function api(path, options={}) {
  const headers = {'X-Synopsis-Request':'1', ...options.headers};
  if (options.body && !(options.body instanceof FormData)) {headers['Content-Type']='application/json'; options.body=JSON.stringify(options.body);}
  const response = await fetch('/api' + path, {...options, headers});
  if (!response.ok) {let message;try {message=(await response.json()).error;} catch {message='Could not reach Synopsis. Please try again.';} throw Error(message);}
  return response.json();
}
function toast(message, error=false) {const el=document.createElement('div');el.className='toast'+(error?' error':'');el.innerHTML=icon(error?'info':'check')+`<span>${escape(message)}</span>`;$('#toast-region').replaceChildren(el);setTimeout(()=>el.remove(),6000);}
function activeItems(){return state.items.filter(i=>!i.trashed);}
function visibleItems(){
  let items=state.items.filter(i=>state.scope==='trash'?i.trashed:!i.trashed);
  if (state.scope==='starred') items=items.filter(i=>i.starred);
  if (state.scope==='unread'||state.unread) items=items.filter(i=>!i.read);
  if (state.scope==='review') items=items.filter(i=>!i.reviewed);
  if (state.scope==='duplicates') items=items.filter(i=>state.duplicateIds.includes(i.id));
  if (state.scope.startsWith('collection:')) items=items.filter(i=>i.collections.includes(state.scope.slice(11)));
  if (state.tag) items=items.filter(i=>i.tags.includes(state.tag));
  return items.sort(state.sort==='title'?(a,b)=>a.title.localeCompare(b.title):state.sort==='year'?(a,b)=>(Number(b.year)||0)-(Number(a.year)||0):(a,b)=>b.createdAt.localeCompare(a.createdAt));
}
async function refresh({detail=false}={}) {
  const serial=++refreshSerial;
  const result=await api('/library'+(state.query?'?q='+encodeURIComponent(state.query):''));
  if(serial!==refreshSerial)return;
  Object.assign(state,result);
  const allIds=new Set(state.items.map(i=>i.id));
  state.checked=new Set([...state.checked].filter(id=>allIds.has(id)));
  renderSidebar();renderList();
  if(detail&&state.selected)await loadDetail(state.selected);
  if(!state.selected)renderDetail();
  const pending=state.items.some(i=>['queued','processing'].includes(i.status));
  clearTimeout(pollTimer);
  if(pending)pollTimer=setTimeout(()=>refresh({detail:state.detail&&['queued','processing'].includes(state.detail.status)}).catch(e=>toast(e.message,true)),1600);
  if(state.modal==='upload'&&state.uploadTab==='files')renderUploadResults();
}
function renderSidebar(){
  const nav=[['all','library','My library'],['starred','star','Starred'],['unread','book','To read'],['review','review','Needs review'],['duplicates','copy','Duplicates'],['trash','trash','Trash']];
  $('#navigation').innerHTML=nav.map(([key,i,label])=>`<button class="nav-item ${state.scope===key?'active':''}" data-scope="${key}">${icon(i)}<span>${label}</span><span class="nav-count">${state.counts[key]||0}</span></button>`).join('');
  const collectionMarkup=(parent=null,depth=0)=>state.collections.filter(c=>c.parent===parent).map(c=>`<button class="nav-item collection-item ${state.scope==='collection:'+c.id?'active':''}" style="padding-left:${14+depth*14}px" data-scope="collection:${c.id}">${icon('folder')}<span>${escape(c.name)}</span><span class="nav-count">${activeItems().filter(i=>i.collections.includes(c.id)).length}</span></button>${collectionMarkup(c.id,depth+1)}`).join('');
  $('#collections').innerHTML=collectionMarkup()||'<p class="sidebar-hint">A new project deserves<br>a little space of its own.</p><button class="text-button new-collection" data-action="collection">+ Create a collection</button>';
  const tags=[...new Set(activeItems().flatMap(i=>i.tags))].sort();
  $('#tags').innerHTML=tags.length?tags.map((t,n)=>`<button class="sidebar-tag ${state.tag===t?'selected':''}" data-tag="${escape(t)}"><span class="tag-dot color-${n%4}"></span>${escape(t)}</button>`).join(''):'<p class="sidebar-hint">Tags you add to references<br>will appear here.</p>';
}
function renderList(){
  const items=visibleItems();
  const collection=state.collections.find(c=>'collection:'+c.id===state.scope);
  const title=collection?.name||({all:'My library',starred:'Starred',unread:'To read',review:'Needs review',duplicates:'Duplicates',trash:'Trash'})[state.scope]||'My library';
  $('#page-title').innerHTML=escape(title)+'<span class="heading-dot">.</span>';
  $('#breadcrumb').textContent=title;
  $('#page-description').textContent=({all:'A home for everything you’re curious about.',starred:'The ideas you keep coming back to.',unread:'Your next discovery is waiting.',review:'A second look makes a better reference.',duplicates:'References with the same DOI or title.',trash:'A second chance for the things you set aside.'})[state.scope]||'One project. All the pieces, together.';
  $('#result-count').innerHTML=`<strong>${items.length}</strong> reference${items.length===1?'':'s'}${state.query?' found':''}`;
  $('#select-all').hidden=!items.length;
  $('#filter-bar').innerHTML=(state.tag?`<button class="filter-chip" data-action="clear-tag">${icon('tag')}${escape(state.tag)}${icon('close')}</button>`:'')+(state.unread?'<button class="filter-chip" data-action="toggle-unread">Unread only ×</button>':'')+(collection?`<button class="text-button collection-manage" data-action="manage-collection">${icon('edit')}Manage collection</button>`:'');
  $('#unread-toggle').classList.toggle('active',state.unread);
  for(const view of ['list','grid','table']){
    $('#view-'+view).classList.toggle('active',state.view===view);
    $('#view-'+view).setAttribute('aria-pressed',String(state.view===view));
  }
  $('#choose-columns').hidden=state.view!=='table';
  const bulk=state.checked.size;
  $('#bulk-bar').innerHTML=bulk?`<div class="bulk-actions"><strong>${bulk} selected</strong><button data-action="cite-selected">${icon('quote')}Cite / export</button><button data-action="organize-selected">${icon('folder')}Organize</button><button data-action="read-selected">${icon('check')}Mark read</button><button data-action="trash-selected">${icon(state.scope==='trash'?'restore':'trash')}${state.scope==='trash'?'Restore':'Trash'}</button><button class="icon-button" data-action="clear-selection" aria-label="Clear selection">${icon('close')}</button></div>`:'';
  $('#item-list').className=state.view==='grid'?'item-grid':state.view==='table'?'item-table':'item-list';
  if(!items.length){
    const emptyLibrary=!state.counts.all&&state.scope==='all'&&!state.query&&!state.tag;
    $('#item-list').innerHTML=emptyLibrary?`<div class="welcome"><div class="welcome-art"><div class="paper paper-back"><span></span><span></span><span></span></div><div class="paper paper-front"><div class="paper-symbol">${icon('spark')}</div><span></span><span></span><span class="short"></span><div class="paper-highlight"></div><span></span><span class="short"></span></div><span class="art-orbit orbit-one">+</span><span class="art-orbit orbit-two">✳</span><div class="art-label">A NEW CHAPTER</div></div><div class="eyebrow">GOOD RESEARCH STARTS WITH A SINGLE IDEA</div><h2>Your next discovery<br>starts here.</h2><p>Bring your papers, notes, and big questions.<br>We’ll help you keep the pieces together.</p><button class="button primary" data-action="upload">${icon('plus')}Add your first document</button><div class="welcome-sub">or drag and drop a document anywhere</div><div class="feature-strip"><div>${icon('upload')}<span><strong>Collect effortlessly</strong><small>PDFs, scans, and documents</small></span></div><div>${icon('spark')}<span><strong>Let the details find you</strong><small>OCR & automatic metadata</small></span></div><div>${icon('quote')}<span><strong>Make every source count</strong><small>Organize, annotate, and cite</small></span></div></div>`:`<div class="empty-state">${icon(state.scope==='trash'?'trash':'search')}<h2>${state.scope==='review'?'All caught up.':'Nothing here just yet.'}</h2><p>${state.query||state.tag?'Try a different search or clear your filters.':'References you add to this view will appear here.'}</p>${state.query||state.tag?'<button class="button secondary" data-action="clear-filters">Clear filters</button>':'<button class="button secondary" data-action="upload">Add to library</button>'}</div>`;
    return;
  }
  if(state.view==='table'){
    const scrollLeft=$('.library-table-scroll')?.scrollLeft||0;
    $('#item-list').innerHTML=renderTable(items);
    $('.library-table-scroll').scrollLeft=scrollLeft;return;
  }
  $('#item-list').innerHTML=items.map(i=>{
    const processing=['queued','processing'].includes(i.status);
    return `<article class="reference ${state.selected===i.id?'selected':''} ${i.read?'is-read':''}" data-id="${i.id}" tabindex="0" aria-label="${escape(i.title)}"><div class="reference-select"><input type="checkbox" aria-label="Select ${escape(i.title)}" data-check="${i.id}" ${state.checked.has(i.id)?'checked':''}></div><div class="document-icon ${i.type==='book'?'book-icon':''}">${icon(i.type==='book'?'book':'file')}<small>${i.fileName?escape(i.fileName.split('.').pop().toUpperCase()):'REF'}</small></div><div class="reference-body"><div class="reference-topline"><span>${escape(typeLabels[i.type]||'Reference')}</span>${i.year?`<span>·</span><span>${escape(i.year)}</span>`:''}${!i.read?'<span class="unread-dot" title="Unread"></span>':''}</div><h3>${escape(i.title)}</h3><p class="reference-authors">${escape(i.authors.length?i.authors.slice(0,3).join(' · ')+(i.authors.length>3?' et al.':''):'Authors not yet added')}</p><div class="reference-bottom">${processing?`<span class="processing-status"><span class="spinner"></span>${escape(i.progress)}</span>`:i.status==='error'?'<span class="error-status">Processing needs attention</span>':`<span class="journal">${escape(i.journal||i.publisher||'Personal library')}</span>`}<div class="reference-tags">${i.publicationStatus?.updates?.length?`<span class="review-pill publication-alert">${i.publicationStatus.updates.some(u=>u.type.includes("retraction"))?"Retraction reported":"Publication update"}</span>`:""}${i.tags.slice(0,2).map(t=>`<span class="tag-pill">${escape(t)}</span>`).join('')}${!i.reviewed&&!processing?'<span class="review-pill">Review</span>':''}</div></div></div><button class="icon-button star-button ${i.starred?'starred':''}" data-star="${i.id}" title="${i.starred?'Unstar':'Star'} reference" aria-label="${i.starred?'Unstar':'Star'} reference">${icon('star')}</button></article>`;
  }).join('');
}
async function loadDetail(id){
  const serial=++detailSerial;
  if(state.selected!==id){state.tab='info';state.noteDraft='';}
  state.selected=id;
  const item=await api('/items/'+id);
  if(serial!==detailSerial)return;
  state.detail=item;renderDetail();renderList();
}
function metaRow(label,value){return value?`<div class="meta-row"><dt>${label}</dt><dd>${escape(value)}</dd></div>`:'';}
function renderDetail(){
  const el=$('#detail-panel'), i=state.detail;
  if(!i){el.innerHTML=`<div class="detail-placeholder"><div class="detail-illustration">${icon('book')}</div><div class="eyebrow">ROOM FOR A CLOSER LOOK</div><h2>The details<br>make the difference.</h2><p>Select a reference to explore its<br>metadata, notes, and highlights.</p><div class="detail-rule"></div><blockquote>Good ideas rarely arrive alone.<br>Keep your sources close,<br>and see what connects.<cite>YOUR RESEARCH, CONNECTED.</cite></blockquote></div>`;return;}
  const pending=['queued','processing'].includes(i.status);
  el.innerHTML=`<div class="detail-top"><span>REFERENCE DETAILS</span><div><button class="icon-button" data-action="edit" title="Edit reference" aria-label="Edit reference">${icon('edit')}</button><button class="icon-button" data-action="close-detail" title="Close details" aria-label="Close details">${icon('close')}</button></div></div><div class="detail-heading"><div class="detail-type">${icon('file')}${escape(typeLabels[i.type]||'Reference')}</div><h2>${escape(i.title)}</h2><p>${escape(i.authors.join('; ')||'No authors added')}</p><div class="detail-primary-actions"><button class="button primary small" data-action="reader" ${!i.fileName?'disabled':''}>${icon('book')}Read document</button><button class="button secondary small" data-action="cite">${icon('quote')}Cite</button></div></div><div class="detail-tabs">${['info','notes','highlights'].map(t=>`<button class="${state.tab===t?'active':''}" data-tab="${t}">${t==='info'?'Overview':t==='notes'?`Notes <span>${i.notes.length}</span>`:`Highlights <span>${i.annotations.length}</span>`}</button>`).join('')}</div><div class="detail-content">${state.tab==='info'?`
    ${i.publicationStatus?.updates?.length?`<div class="notice warning">${icon('info')}<div><strong>Publication update reported</strong><p>${i.publicationStatus.updates.map(u=>escape(u.type)).join(', ')}${i.publicationStatus.error?' · last check failed; results may be stale':''}</p><button class="text-button" data-research="settings">View publication notices</button></div></div>`:''}
    ${pending?`<div class="notice"><span class="spinner"></span><div><strong>Making sense of your document</strong><p>${escape(i.progress)}</p></div></div>`:!i.reviewed?`<div class="notice ${i.status==='error'?'warning':''}">${icon(i.status==='error'?'info':'spark')}<div><strong>${i.status==='error'?'A little help is needed':'Metadata ready for review'}</strong><p>${i.status==='error'?escape(i.progress):'Check the extracted details before citing.'}</p>${i.status==='error'?'<button class="text-button" data-action="retry">Retry processing</button>':'<button class="text-button" data-action="reviewed">'+icon('check')+'Looks good</button>'}</div></div>`:''}
    ${i.warnings.length&&i.status!=='error'?`<p class="field-hint">${i.warnings.map(escape).join('<br>')}</p>`:''}
    <div class="detail-section-title">BIBLIOGRAPHIC DETAILS<button class="text-button" data-action="edit">Edit</button></div><dl class="metadata">${metaRow('Year',i.year)}${metaRow('Publication',i.journal)}${metaRow('Volume / issue',[i.volume,i.issue].filter(Boolean).join(' / '))}${metaRow('Pages',i.pages)}${metaRow('Publisher',i.publisher)}${metaRow('DOI',i.doi)}${metaRow('Source',({crossref:'Crossref · DOI match',ocr:'OCR extraction',document:'Document text',manual:'Manually added',import:'Bibliography import'})[i.source])}</dl>
    ${i.url?`<a class="text-button source-link" href="${escape(safeUrl(i.url))}" target="_blank" rel="noopener noreferrer">View source${icon('external')}</a>`:''}
    ${i.abstract?`<div class="detail-section-title">ABSTRACT</div><p class="abstract">${escape(i.abstract)}</p>`:''}
    <div class="detail-section-title">TAGS & COLLECTIONS<button class="text-button" data-action="organize">Edit</button></div><div class="detail-tags">${i.tags.map(t=>`<span class="tag-pill">${escape(t)}</span>`).join('')||'<span class="muted">No tags yet</span>'}</div><div class="detail-collections">${state.collections.filter(c=>i.collections.includes(c.id)).map(c=>`<span>${icon('folder')}${escape(c.name)}</span>`).join('')||'<span class="muted">Not in a collection</span>'}</div>
    ${i.fileName?`<div class="detail-section-title">ATTACHMENT</div><a class="attachment" href="/api/items/${i.id}/file?download=1" download>${icon('file')}<span><strong>${escape(i.fileName)}</strong><small>${formatSize(i.fileSize)}${i.pageCount?' · '+i.pageCount+' pages':''}</small></span>${icon('export')}</a>`:''}
    <div class="detail-section-title">RESEARCH TOOLS</div><button class="detail-action" data-research="insights">${icon("spark")}Insights & extraction details</button><button class="detail-action" data-research="reader">${icon("book")}Advanced reader</button><button class="detail-action" data-research="documents">${icon("copy")}Versions & attachments</button><div class="detail-section-title">LIBRARY</div><button class="detail-action" data-action="toggle-read">${icon(i.read?'book':'check')}${i.read?'Mark as unread':'Mark as read'}</button><button class="detail-action" data-action="trash">${icon(i.trashed?'restore':'trash')}${i.trashed?'Restore to library':'Move to trash'}</button>${i.trashed?'<button class="detail-action danger" data-action="delete">Permanently delete</button>':''}<p class="added-date">Added ${formatDate(i.createdAt)}</p>
  `:state.tab==='notes'?`<form id="note-form"><label class="field-label" for="note-text">A thought worth keeping</label><textarea id="note-text" name="text" rows="5" placeholder="Connect ideas, ask questions, make it your own…" required maxlength="50000">${escape(state.noteDraft)}</textarea><button class="button primary small" type="submit">${icon('plus')}Save note</button></form><div class="notes-list">${i.notes.map(n=>`<div class="note"><div><small>${formatDate(n.createdAt)}</small><button class="icon-button" data-note-delete="${n.id}" aria-label="Delete note">${icon('trash')}</button></div><p>${escape(n.text)}</p></div>`).join('')||'<p class="field-hint">Your notes stay with this reference and are included in library search.</p>'}</div>`:`<p class="field-hint">Keep meaningful passages with a page reference. Select text in the reader’s Extracted text view, or add a passage below.</p><button class="button secondary small" data-action="highlight">${icon('plus')}Add a highlight</button><div class="notes-list">${i.annotations.map(a=>`<div class="highlight"><div><small>Page ${a.page}</small><button class="icon-button" data-highlight-delete="${a.id}" aria-label="Delete highlight">${icon('trash')}</button></div><p>${escape(a.text)}</p></div>`).join('')||'<div class="small-empty">The important parts will find a home here.</div>'}</div>`}</div>`;
}
function safeUrl(value){try{const u=new URL(value);return ['http:','https:'].includes(u.protocol)?u.href:'#';}catch{return '#';}}
function formatSize(bytes){return bytes>1024*1024?(bytes/1024/1024).toFixed(1)+' MB':Math.max(1,Math.round(bytes/1024))+' KB';}
function formatDate(date){return new Date(date).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'});}
function modal(title,subtitle,body,wide=false){
  const dialog=$('#modal');if(!dialog.open)lastFocus=document.activeElement;
  dialog.className=wide?'wide-modal':'';
  $('#modal-content').innerHTML=`<div class="modal-heading"><div><h2 id="dialog-title">${title}</h2><p>${subtitle}</p></div><button class="icon-button" data-action="close-modal" aria-label="Close dialog">${icon('close')}</button></div>${body}`;
  if(!dialog.open)dialog.showModal();
}
function closeModal(){ $('#modal').close();state.modal='';lastFocus?.focus(); }
function openUpload(tab='files'){
  state.modal='upload';state.uploadTab=tab;
  modal('A new addition.','Every great idea has a starting point.',`<div class="modal-tabs">${[['files','Upload documents'],['doi','Add by DOI'],['manual','Manual entry'],['import','Import library']].map(([key,label])=>`<button data-upload-tab="${key}" class="${key===tab?'active':''}">${label}</button>`).join('')}</div><div class="modal-body">${tab==='files'?`<button class="upload-zone" data-action="choose-files"><span class="upload-orbit">${icon('upload')}</span><strong>Drop your documents here</strong><span>or <u>browse files</u> to get started</span><small>PDF, images, DOCX, TXT, Markdown · up to 100 MB per batch</small></button><div class="upload-explainer">${icon('spark')}<p><strong>The details, taken care of.</strong><br>Synopsis extracts text, scans image pages with OCR, and uses detected DOIs to fill in bibliographic details.</p></div><div id="upload-results"></div><p class="privacy-note">${icon('info')}Documents are processed locally. Only detected DOIs are sent to Crossref when metadata lookup is enabled.</p>`:tab==='doi'?`<form id="doi-form"><label class="field-label" for="doi-input">Document DOI</label><input id="doi-input" name="doi" placeholder="10.1038/nature14539" required><p class="field-hint">Paste a DOI or a doi.org link. We’ll retrieve its title, authors, publication, and date from Crossref.</p><div class="form-actions"><button type="submit" class="button primary">${icon('search')}Find reference</button></div></form>`:tab==='manual'?metadataForm({},'create-form'): `<div class="import-illustration">${icon('library')}</div><h3 class="centered">Bring your research with you.</h3><p class="centered muted">Import a bibliography from Zotero or another reference manager.<br>Supported formats: BibTeX, RIS, and CSL-JSON.</p><button class="button primary centered-button" data-action="choose-import">${icon('upload')}Choose bibliography file</button><p class="field-hint centered">Reference metadata is imported. Document attachments and notes<br>are not included in these bibliography formats.</p>`}</div>`);
  if(tab==='files')renderUploadResults();
}
function renderUploadResults(){const el=$('#upload-results');if(!el)return;el.innerHTML=state.uploadResults.map(r=>{const live=state.items.find(i=>i.id===r.id)||r;return `<div class="upload-result">${icon(r.error?'info':r.duplicate?'copy':live.status==='ready'?'check':'file')}<div><strong>${escape(r.fileName||r.title)}</strong><small>${escape(r.error||(r.duplicate?'Already in your library':live.status==='ready'?'Added · ready for review':live.progress))}</small></div>${r.id?`<button class="text-button" data-open-upload="${r.id}">View${icon('arrow')}</button>`:''}</div>`;}).join('');}
async function uploadFiles(files){
  if(!files.length)return;
  if(files.length>20)throw Error('Add up to 20 documents at a time.');
  if([...files].reduce((n,f)=>n+f.size,0)>99*1024*1024)throw Error('Please keep each upload batch under 100 MB.');
  const data=new FormData();for(const file of files)data.append('files',file);
  if(state.scope.startsWith('collection:'))data.append('collection',state.scope.slice(11));
  openUpload('files');$('#upload-results').innerHTML='<div class="upload-result"><span class="spinner"></span>Uploading your documents…</div>';
  const result=await api('/upload',{method:'POST',body:data});state.uploadResults=result.items;
  await refresh();renderUploadResults();toast(`${result.items.filter(i=>!i.error).length} document(s) received`);
}
function field(label,name,value='',type='text'){return `<label class="form-field">${label}<input type="${type}" name="${name}" value="${escape(value)}" ${name==='title'?'required':''} ${name==='year'?'pattern="[0-9]{4}" maxlength="4"':''}></label>`;}
function metadataForm(i,id){return `<form id="${id}" class="metadata-form"><label class="form-field">Reference type<select name="type">${Object.entries(typeLabels).map(([key,label])=>`<option value="${key}" ${i.type===key?'selected':''}>${label}</option>`).join('')}</select></label>${field('Title','title',i.title)}<label class="form-field">Authors <span class="muted">— one per line, preferably Last, First</span><textarea name="authors" rows="2" placeholder="Curie, Marie">${escape((i.authors||[]).join('\n'))}</textarea></label><div class="form-grid">${field('Year','year',i.year)}${field('Publication / journal','journal',i.journal)}${field('Volume','volume',i.volume)}${field('Issue','issue',i.issue)}${field('Pages','pages',i.pages)}${field('Publisher','publisher',i.publisher)}</div>${field('DOI','doi',i.doi)}${field('Source URL','url',i.url,'url')}<label class="form-field">Abstract<textarea name="abstract" rows="4">${escape(i.abstract)}</textarea></label><div class="form-actions"><button type="button" class="button secondary" data-action="close-modal">Cancel</button><button type="submit" class="button primary">${icon('check')}${id==='create-form'?'Add reference':'Save changes'}</button></div></form>`;}
function openEdit(){state.modal='edit';modal('A closer look.','Fine-tune the details of this reference.',`<div class="modal-body">${metadataForm(state.detail,'edit-form')}</div>`);}
function openCollection(manage=false){
  state.modal='collection';const c=manage?state.collections.find(c=>'collection:'+c.id===state.scope):null;
  modal(c?'Make it your own.':'A place for a new project.',c?'Rename this collection or remove it from your workspace.':'Keep related ideas together in a collection.',`<form id="collection-form" class="modal-body" data-collection-id="${c?.id||''}">${field('Collection name','name',c?.name||'')} ${!c?`<label class="form-field">Inside collection<select name="parent"><option value="">None — top-level collection</option>${state.collections.map(c=>`<option value="${c.id}">${escape(c.name)}</option>`).join('')}</select></label>`:''}<div class="form-actions">${c?'<button type="button" class="button danger-button" data-action="delete-collection">Delete collection</button>':''}<button class="button primary" type="submit">${c?'Save changes':'Create collection'}</button></div><p class="field-hint">Collections organize your references. Removing a collection keeps its references in your library.</p></form>`);
}
function selectedIds(bulk=false){return bulk?[...state.checked]:[state.selected];}
function openOrganize(bulk=false){
  state.modal='organize';state.organizeBulk=bulk;state.organizeIds=selectedIds(bulk);const i=bulk?null:state.detail;
  modal('Everything in its place.',bulk?'Add tags and collections to the selected references.':'Give this reference a little context.',`<form id="organize-form" class="modal-body">${field(bulk?'Tags to add (comma separated)':'Tags (comma separated)','tags',i?.tags.join(', ')||'')}<div class="field-label">${bulk?'Add to collections':'Collections'}</div><div class="collection-checks">${state.collections.map(c=>`<label><input type="checkbox" name="collections" value="${c.id}" ${i?.collections.includes(c.id)?'checked':''}>${icon('folder')}${escape(c.name)}</label>`).join('')||'<p class="muted">Create a collection from the sidebar to organize references.</p>'}</div><div class="form-actions"><button class="button primary" type="submit">Save organization</button></div></form>`);
}
async function openCite(ids){
  if(!ids.length){toast('Add or select a reference first.');return;}
  state.modal='cite';state.citeIds=ids;state.citation='';
  modal('Give your sources their due.',`${ids.length} reference${ids.length===1?'':'s'} · formatted and ready to use`, `<div class="modal-body"><label class="form-field">Citation style<select id="citation-style"><option value="apa">APA 7th edition</option><option value="modern-language-association">MLA 9th edition</option><option value="chicago-author-date">Chicago author–date</option><option value="vancouver">Vancouver</option></select></label><div class="citation-preview" id="citation-preview">Formatting your bibliography…</div><div class="form-actions"><button class="button primary" data-action="copy-citation">${icon('copy')}Copy bibliography</button></div><div class="modal-divider"></div><div class="field-label">EXPORT REFERENCES</div><div class="export-options">${[['bibtex','BibTeX','.bib'],['ris','RIS','.ris'],['csl','CSL-JSON','.json']].map(([format,label,ext])=>`<button data-export="${format}">${icon('export')}<strong>${label}</strong><small>${ext}</small></button>`).join('')}</div></div>`);
  await updateCitation();
}
async function updateCitation(){state.citation='';state.citationHtml='';$('#citation-preview').textContent='Formatting your bibliography…';const style=$('#citation-style').value;const result=await api('/bibliography',{method:'POST',body:{ids:state.citeIds,style}});if(state.modal==='cite'&&$('#citation-style').value===style){state.citation=result.text;state.citationHtml=result.html;$('#citation-preview').innerHTML=result.html;}}
async function exportItems(format){
  const response=await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json','X-Synopsis-Request':'1'},body:JSON.stringify({ids:state.citeIds,format})});
  if(!response.ok)throw Error((await response.json()).error);
  const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download='synopsis-library.'+({bibtex:'bib',ris:'ris',csl:'json'})[format];a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Bibliography exported');
}
async function openSettings(){
  state.modal='settings';const s=await api('/settings');
  modal('Your workspace, your way.','A few thoughtful defaults. Room to make it yours.',`<form id="settings-form" class="modal-body"><div class="settings-section"><div class="settings-heading">${icon('spark')}Document intelligence</div><label class="toggle-row"><span><strong>Automatic DOI metadata lookup</strong><small>Send detected DOIs to Crossref to retrieve reference details.<br>Your documents stay on this computer.</small></span><input type="checkbox" name="metadataLookup" ${s.metadataLookup?'checked':''}></label><label class="form-field">OCR language<select name="ocrLanguage" ${!s.languages.length?'disabled':''}>${s.languages.filter(l=>l!=='osd').map(l=>`<option value="${escape(l)}" ${s.ocrLanguage===l?'selected':''}>${l==='eng'?'English':escape(l)}</option>`).join('')}</select></label><p class="field-hint">${s.ocrAvailable?'Tesseract is installed and ready. Additional OCR languages can be installed on your computer.':'Tesseract was not found. Install it to recognize text in scanned PDFs and images.'}</p></div><div class="settings-section"><div class="settings-heading">${icon('folder')}Document storage</div><label class="form-field" for="upload-directory">Upload folder<input id="upload-directory" name="uploadDirectory" type="text" value="${escape(s.uploadDirectory)}" placeholder="${escape(s.defaultUploadDirectory)}" aria-describedby="upload-directory-hint" autocomplete="off" spellcheck="false"></label><p class="field-hint" id="upload-directory-hint">Enter a folder path on the computer running Synopsis, such as ~/Documents/Synopsis, or browse for one. Missing folders are created when you save. New uploads and watched-folder imports use this location; existing documents stay in their current folders.</p><div class="field-buttons"><button class="text-button" type="button" data-action="browse-upload-folder">${icon('folder')}Browse…</button><button class="text-button" type="button" data-action="default-upload-folder" data-default-folder="${escape(s.defaultUploadDirectory)}">Use default folder</button></div></div><div class="settings-section"><div class="settings-heading">${icon('folder')}Your library is local</div><p class="muted">References, notes, and original files are stored on this computer. Cloud sync and shared libraries are not available in this version.</p><a class="button secondary" href="/api/backup">${icon('export')}Download library backup</a><p class="field-hint">A ZIP containing your library data and original documents.</p></div><div class="form-actions"><button class="button primary" type="submit">Save preferences</button></div><p class="version-note">Synopsis 0.1 · Made for curious minds.</p></form>`);
}
function openReader(tab='original'){
  state.readerTab=tab;state.modal='reader';const i=state.detail;
  const suffix=i.fileName.split('.').pop().toLowerCase();const isImage=['png','jpg','jpeg','webp'].includes(suffix);const hasPreview=suffix==='pdf'||isImage;
  if(!hasPreview)state.readerTab='text';
  modal(escape(i.title),`${escape(i.authors.slice(0,2).join(' · '))}${i.year?' · '+escape(i.year):''}`,`<div class="reader-toolbar"><div class="modal-tabs"><button data-reader-tab="original" class="${state.readerTab==='original'?'active':''}" ${!hasPreview?'disabled':''}>Original document</button><button data-reader-tab="text" class="${state.readerTab==='text'?'active':''}">Extracted text</button></div><div><button class="button secondary small" data-action="highlight-selection">${icon('plus')}Save a highlight</button><a class="icon-button" href="/api/items/${i.id}/file?download=1" title="Download original">${icon('export')}</a></div></div><div class="reader-body">${state.readerTab==='original'?(isImage?`<img class="document-image" alt="${escape(i.title)}" src="/api/items/${i.id}/file">`:`<iframe title="Document reader" src="/api/items/${i.id}/file"></iframe>`):`<div class="extracted-text" id="extracted-text">${escape(i.text||'No extracted text yet. Processing may still be running, or the document needs attention.')}</div>`}</div>`,true);
}
function openHighlight(text=''){
  state.modal='highlight';modal('Keep the important part.','Highlights stay connected to their source.',`<form id="highlight-form" class="modal-body"><label class="form-field">Passage<textarea name="text" rows="7" required maxlength="10000">${escape(text)}</textarea></label><label class="form-field">Page<input type="number" name="page" value="1" min="1" max="${Math.max(1,state.detail.pageCount)}" required></label><div class="form-actions"><button class="button primary" type="submit">Save highlight</button></div></form>`);
}
async function patch(id,fields){await api('/items/'+id,{method:'PATCH',body:fields});await refresh({detail:id===state.selected});}
const actions={
  'default-upload-folder':()=>{$('#upload-directory').value=$('[data-default-folder]').dataset.defaultFolder;},
  'browse-upload-folder':async()=>{const button=$('[data-action="browse-upload-folder"]');button.disabled=true;try{const result=await api('/settings/browse-folder',{method:'POST'});if(result.path)$('#upload-directory').value=result.path;}finally{button.disabled=false;}},
  upload:()=>openUpload(), 'choose-files':()=>$('#file-input').click(), 'choose-import':()=>$('#import-input').click(),
  'close-modal':closeModal, collection:()=>openCollection(), 'manage-collection':()=>openCollection(true), settings:openSettings,
  'export-library':()=>openCite(visibleItems().map(i=>i.id)), 'cite-selected':()=>openCite([...state.checked]), cite:()=>openCite([state.selected]),
  'copy-citation':async()=>{if(!state.citation)throw Error('Please wait for the bibliography to finish.');if(window.ClipboardItem){await navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([state.citationHtml],{type:'text/html'}),'text/plain':new Blob([state.citation],{type:'text/plain'})})]);}else{await navigator.clipboard.writeText(state.citation);}toast('Bibliography copied');},
  'view-list':()=>setLibraryView('list'),'view-grid':()=>setLibraryView('grid'),'view-table':()=>setLibraryView('table'),
  'choose-columns':()=>openColumnChooser(),
  'reset-columns':()=>{state.columns=[...defaultColumns];state.columnOrder=libraryColumns.map(([key])=>key);saveLibraryView();renderList();openColumnChooser('title');},
  'toggle-unread':()=>{state.unread=!state.unread;renderList();},'clear-tag':()=>{state.tag='';renderSidebar();renderList();},
  'clear-filters':async()=>{state.query='';state.tag='';state.unread=false;$('#search').value='';await refresh();},
  'select-all':()=>{state.checked=new Set(visibleItems().map(i=>i.id));renderList();},'clear-selection':()=>{state.checked.clear();renderList();},
  'close-detail':()=>{state.detail=null;state.selected=null;detailSerial++;renderDetail();renderList();},
  edit:openEdit, organize:()=>openOrganize(), 'organize-selected':()=>openOrganize(true),
  reviewed:async()=>{await patch(state.selected,{reviewed:true});toast('Reference reviewed');},
  retry:async()=>{await api('/items/'+state.selected+'/retry',{method:'POST'});await refresh({detail:true});toast('Processing restarted');},
  'toggle-read':()=>patch(state.selected,{read:!state.detail.read}),
  trash:async()=>{const trashed=!state.detail.trashed;await patch(state.selected,{trashed});toast(trashed?'Moved to trash':'Restored to library');},
  'read-selected':async()=>{for(const id of state.checked)await api('/items/'+id,{method:'PATCH',body:{read:true}});await refresh({detail:true});toast('References marked as read');},
  'trash-selected':async()=>{for(const id of state.checked)await api('/items/'+id,{method:'PATCH',body:{trashed:state.scope!=='trash'}});state.checked.clear();await refresh({detail:true});toast('Library updated');},
  delete:()=>{state.modal='confirm';modal('Delete this reference?','This permanently removes the reference, its notes, and its original document.',`<div class="modal-body"><p>${escape(state.detail.title)}</p><div class="form-actions"><button class="button secondary" data-action="close-modal">Keep in trash</button><button class="button danger-button" data-action="confirm-delete">Permanently delete</button></div></div>`);},
  'confirm-delete':async()=>{await api('/items/'+state.selected,{method:'DELETE'});closeModal();actions['close-detail']();await refresh();toast('Reference deleted');},
  'delete-collection':async()=>{await api('/collections/'+state.scope.slice(11),{method:'DELETE'});state.scope='all';closeModal();await refresh({detail:true});toast('Collection removed; references kept');},
  reader:()=>openReader(),highlight:()=>openHighlight(),
  'highlight-selection':()=>{const selection=window.getSelection();const text=state.readerTab==='text'&&$('#extracted-text')?.contains(selection.anchorNode)?selection.toString():'';openHighlight(text);},
  sidebar:()=>$('#sidebar').classList.toggle('mobile-open'),
};
document.addEventListener('click',async event=>{
  const button=event.target.closest('button,a[data-action]');const article=event.target.closest('.reference,.table-reference');
  try{
    if(event.target.matches('[data-check]')){const id=event.target.dataset.check;if(event.target.checked)state.checked.add(id);else state.checked.delete(id);renderList();return;}
    if(button?.dataset.columnMove){
      const key=button.dataset.columnMove, index=state.columnOrder.indexOf(key);
      moveColumn(key,state.columnOrder[index+Number(button.dataset.direction)]);
      openColumnChooser(key);return;
    }
    if(button?.dataset.action){await actions[button.dataset.action]?.();return;}
    if(button?.dataset.scope){state.scope=button.dataset.scope;state.tag='';state.checked.clear();$('#sidebar').classList.remove('mobile-open');renderSidebar();renderList();return;}
    if(button?.dataset.tag){state.tag=state.tag===button.dataset.tag?'':button.dataset.tag;renderSidebar();renderList();return;}
    if(button?.dataset.star){const i=state.items.find(i=>i.id===button.dataset.star);await patch(i.id,{starred:!i.starred});return;}
    if(button?.dataset.tab){state.tab=button.dataset.tab;renderDetail();return;}
    if(button?.dataset.uploadTab){openUpload(button.dataset.uploadTab);return;}
    if(button?.dataset.openUpload){closeModal();await loadDetail(button.dataset.openUpload);return;}
    if(button?.dataset.export){await exportItems(button.dataset.export);return;}
    if(button?.dataset.readerTab){openReader(button.dataset.readerTab);return;}
    if(button?.dataset.noteDelete){await api(`/items/${state.selected}/notes/${button.dataset.noteDelete}`,{method:'DELETE'});await refresh({detail:true});return;}
    if(button?.dataset.highlightDelete){await api(`/items/${state.selected}/annotations/${button.dataset.highlightDelete}`,{method:'DELETE'});await refresh({detail:true});return;}
    if(article&&!button){if(state.selected!==article.dataset.id){state.tab='info';state.noteDraft='';}await loadDetail(article.dataset.id);}
  }catch(e){toast(e.message,true);}
});
document.addEventListener('submit',async event=>{
  event.preventDefault();const form=event.target;const data=new FormData(form);const submit=form.querySelector('[type=submit]');if(submit)submit.disabled=true;
  try{
    if(form.id==='create-form'||form.id==='edit-form'){
      const body=Object.fromEntries(data);body.authors=body.authors.split('\n').map(a=>a.trim()).filter(Boolean);body.reviewed=true;
      if(form.id==='create-form'){if(state.scope.startsWith('collection:'))body.collections=[state.scope.slice(11)];const i=await api('/items',{method:'POST',body});closeModal();await refresh();await loadDetail(i.id);toast('Reference added');}
      else{await patch(state.selected,body);closeModal();toast('Reference updated');}
    }else if(form.id==='doi-form'){
      const result=await api('/lookup',{method:'POST',body:{doi:data.get('doi')}});state.modal='upload';modal('A reference, found.','Review these details before adding it to your library.',`<div class="modal-body">${metadataForm(result,'create-form')}</div>`);
    }else if(form.id==='collection-form'){
      const id=form.dataset.collectionId;const result=await api('/collections'+(id?'/'+id:''),{method:id?'PATCH':'POST',body:Object.fromEntries(data)});if(!id)state.scope='collection:'+result.id;closeModal();await refresh();toast(id?'Collection updated':'Collection created');
    }else if(form.id==='note-form'){
      await api('/items/'+state.selected+'/notes',{method:'POST',body:{text:data.get('text')}});state.noteDraft='';await refresh({detail:true});toast('Note saved');
    }else if(form.id==='organize-form'){
      const tags=data.get('tags').split(',').map(t=>t.trim()).filter(Boolean), collections=data.getAll('collections');
      for(const id of state.organizeIds){const current=state.items.find(i=>i.id===id);const bulk=state.organizeBulk;await api('/items/'+id,{method:'PATCH',body:{tags:bulk?[...new Set([...current.tags,...tags])]:tags,collections:bulk?[...new Set([...current.collections,...collections])]:collections}});}
      closeModal();await refresh({detail:true});toast('Organization saved');
    }else if(form.id==='settings-form'){
      const body={metadataLookup:data.get('metadataLookup')==='on',uploadDirectory:data.get('uploadDirectory')};if(data.has('ocrLanguage'))body.ocrLanguage=data.get('ocrLanguage');await api('/settings',{method:'PATCH',body});closeModal();toast('Preferences saved');
    }else if(form.id==='highlight-form'){
      await api('/items/'+state.selected+'/annotations',{method:'POST',body:{text:data.get('text'),page:Number(data.get('page'))}});closeModal();state.tab='highlights';await refresh({detail:true});toast('Highlight saved');
    }
  }catch(e){toast(e.message,true);}finally{if(submit)submit.disabled=false;}
});
$('#search').addEventListener('input',e=>{state.query=e.target.value;clearTimeout(searchTimer);searchTimer=setTimeout(()=>refresh().catch(e=>toast(e.message,true)),220);});
$('#sort').addEventListener('change',e=>{state.sort=e.target.value;renderList();});
document.addEventListener('input',e=>{if(e.target.id==='note-text')state.noteDraft=e.target.value;});
document.addEventListener('change',e=>{if(e.target.id==='citation-style')updateCitation().catch(e=>toast(e.message,true));});
document.addEventListener('change',e=>{
  const key=e.target.dataset.columnToggle;if(!key)return;
  if(!e.target.checked&&state.columns.length===1){e.target.checked=true;toast('Keep at least one column visible.',true);return;}
  state.columns=e.target.checked?[...state.columns,key]:state.columns.filter(k=>k!==key);
  saveLibraryView();renderList();
});
$('#file-input').addEventListener('change',async e=>{try{await uploadFiles(e.target.files);}catch(err){toast(err.message,true);}finally{e.target.value='';}});
$('#import-input').addEventListener('change',async e=>{try{if(!e.target.files.length)return;const data=new FormData();data.append('file',e.target.files[0]);const result=await api('/import',{method:'POST',body:data});closeModal();await refresh();toast(`Imported ${result.items.length} references`);}catch(err){toast(err.message,true);}finally{e.target.value='';}});
$('#modal').addEventListener('cancel',()=>{state.modal='';});
$('#modal').addEventListener('click',e=>{if(e.target===$('#modal')){const r=$('#modal').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)closeModal();}});
let draggedColumn=null;
document.addEventListener('dragstart',e=>{
  const header=e.target.closest('th[data-column]');if(!header)return;
  draggedColumn=header.dataset.column;e.dataTransfer.effectAllowed='move';
  e.dataTransfer.setData('text/plain',draggedColumn);header.classList.add('dragging');
});
function clearColumnDrag(){
  document.querySelectorAll('.library-table th').forEach(h=>h.classList.remove('dragging','drop-target'));
}
document.addEventListener('dragover',e=>{
  if(!draggedColumn)return;
  const header=e.target.closest('th[data-column]');if(!header)return;
  e.preventDefault();e.dataTransfer.dropEffect='move';
  document.querySelectorAll('.library-table .drop-target').forEach(h=>h.classList.remove('drop-target'));
  header.classList.add('drop-target');
});
document.addEventListener('drop',e=>{
  if(!draggedColumn)return;
  const header=e.target.closest('th[data-column]');
  if(header){e.preventDefault();const key=draggedColumn;moveColumn(key,header.dataset.column);document.querySelector(`[data-column-header="${key}"]`)?.focus();}
  draggedColumn=null;clearColumnDrag();
});
document.addEventListener('dragend',()=>{draggedColumn=null;clearColumnDrag();});
let dragDepth=0;
document.addEventListener('dragenter',e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();dragDepth++;$('#drop-overlay').hidden=false;}});
document.addEventListener('dragover',e=>{if(e.dataTransfer.types.includes('Files'))e.preventDefault();});
document.addEventListener('dragleave',e=>{if(!e.dataTransfer.types.includes('Files'))return;e.preventDefault();dragDepth--;if(dragDepth<=0)$('#drop-overlay').hidden=true;});
document.addEventListener('drop',async e=>{if(!e.dataTransfer.files.length)return;e.preventDefault();dragDepth=0;$('#drop-overlay').hidden=true;try{await uploadFiles(e.dataTransfer.files);}catch(err){toast(err.message,true);}});
document.addEventListener('keydown',e=>{
  const key=e.target.dataset.columnHeader;
  if(key&&e.altKey&&['ArrowLeft','ArrowRight'].includes(e.key)){
    e.preventDefault();const columns=visibleColumns();
    moveColumn(key,columns[columns.indexOf(key)+(e.key==='ArrowLeft'?-1:1)]);
    document.querySelector(`[data-column-header="${key}"]`)?.focus();return;
  }
  if(e.key==='/'&&!['INPUT','TEXTAREA'].includes(document.activeElement.tagName)&&!$('#modal').open){e.preventDefault();$('#search').focus();}
  if((e.metaKey||e.ctrlKey)&&e.key===','){e.preventDefault();openSettings().catch(e=>toast(e.message,true));}
  if(e.key==='Enter'&&e.target.matches('.reference,.table-reference'))loadDetail(e.target.dataset.id).catch(e=>toast(e.message,true));
});
for(const [id,name] of Object.entries({'settings-icon':'settings','breadcrumb-icon':'library','export-icon':'export','add-icon':'plus','search-icon':'search','unread-toggle':'filter','view-list':'list','view-grid':'grid','view-table':'table','footer-icon':'spark'}))$('#'+id).innerHTML=icon(name);
refresh().catch(e=>{toast(e.message,true);$('#item-list').innerHTML='<div class="empty-state"><h2>We couldn’t load your library.</h2><p>Make sure the Flask server is running, then refresh this page.</p></div>';});

// Small, explicit interface for the research workspace module.
export {state, api, icon, escape, toast, refresh, loadDetail, safeUrl};
