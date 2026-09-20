import {state,api,escape as e,refresh,openSettings} from './app.js';

const dialog=document.querySelector('#chat-dialog');
const launcher=document.querySelector('#chat-launcher');
const $=s=>dialog.querySelector(s);
const C={current:null,conversations:[],files:[],selected:new Set(),draft:'',mode:'auto',web:false,full:false,busy:false,error:'',filter:'',capabilities:{},retry:null};
let pollTimer,lastFocus;

async function reloadData(){
  const [library,conversations]=await Promise.all([api('/library'),api('/chat/conversations')]);
  C.files=library.items.filter(item=>!item.trashed&&!item.mergedInto&&item.fileName);
  C.conversations=conversations.conversations;C.capabilities=conversations;
}
async function open(full=false){
  lastFocus=document.activeElement;
  try{
    await reloadData();
    if(!C.current&&!C.selected.size){
      const ids=state.checked.size?[...state.checked]:state.selected?[state.selected]:[];
      C.selected=new Set(ids.filter(id=>C.files.some(file=>file.id===id)));
    }
    setLayout(full);render();pollFiles();$('#chat-message').focus();
  }catch(error){launcher.textContent='Chat unavailable — retry';launcher.title=error.message;}
}
function setLayout(full){
  if(dialog.open)dialog.close();C.full=full;
  dialog.className=full?'chat-full':'chat-mini';
  if(full)dialog.showModal();else dialog.show();
  launcher.hidden=true;
}
function close(){dialog.close();launcher.hidden=false;clearTimeout(pollTimer);lastFocus?.focus();}
function fresh(){
  if(C.busy)return;
  C.current=null;C.draft='';C.error='';C.retry=null;C.mode='auto';C.web=false;render();
}
function render(){
  dialog.innerHTML=`<header class="chat-header"><div class="chat-heading"><span class="chat-mark">✧</span><div><h2 id="chat-title">Synopsis chat</h2><small>${C.full?'A workspace for questions, ideas, and designs':'Your research, in conversation'}</small></div></div><div class="chat-header-actions"><button class="icon-button" data-chat-action="files" aria-label="Choose chat files">▤</button><button class="icon-button" data-chat-action="new" aria-label="New conversation" ${C.busy?'disabled':''}>＋</button><button class="icon-button" data-chat-action="expand" aria-label="${C.full?'Minimize chat':'Expand chat workspace'}">${C.full?'↙':'↗'}</button><button class="icon-button" data-chat-action="close" aria-label="Close chat">×</button></div></header>
    <div class="chat-layout"><aside class="chat-side" aria-label="Chat files and conversations">
      <label class="chat-label">Conversation<select id="chat-history" ${C.busy?'disabled':''}><option value="">New conversation</option>${C.conversations.map(c=>`<option value="${e(c.id)}" ${C.current?.id===c.id?'selected':''}>${e(c.title)}</option>`).join('')}</select></label>
      <div class="chat-history-actions"><button class="text-button" data-chat-action="new" ${C.busy?'disabled':''}>+ New chat</button>${C.current?`<a class="text-button" href="/api/chat/conversations/${C.current.id}/export" download>Export</a><button class="text-button danger" data-chat-action="delete" ${C.busy?'disabled':''}>Delete chat</button>`:''}</div>
      <div class="chat-file-heading"><strong>Choose files</strong><button class="text-button" data-chat-action="upload" ${C.busy?'disabled':''}>+ Add files</button></div>
      <input id="chat-file-search" type="search" aria-label="Filter chat files" placeholder="Find a document…" value="${e(C.filter)}">
      <p class="chat-hint">Only selected files are used. Choose up to 30.</p><div id="chat-files"></div>
      <button class="text-button" data-chat-action="clear-files" ${C.busy?'disabled':''}>Clear file selection</button>
      <button class="button secondary small chat-settings-button" data-chat-action="settings">AI &amp; tool settings</button>
    </aside><main class="chat-main"><div class="chat-context"><button class="text-button" data-chat-action="files"><span id="chat-file-count">${C.selected.size}</span> files selected</button><span>${e(C.capabilities.ai?.enabled?C.capabilities.ai.model:'Local source search')}</span></div>
      <div id="chat-messages" role="log" aria-live="polite" aria-label="Chat messages"></div>
      <div id="chat-error" role="alert" ${C.error?'':'hidden'}>${e(C.error)}</div>
      <form id="chat-composer"><div class="chat-composer-options"><label>Mode<select id="chat-mode" ${C.busy?'disabled':''}>${[['auto','Auto'],['answer','Answer'],['image','Generate image'],['architecture','Architecture diagram']].map(([id,label])=>`<option value="${id}" ${C.mode===id?'selected':''}>${label}</option>`).join('')}</select></label><label class="chat-web-toggle" title="Enable Brave web search in AI & tool settings"><input id="chat-web" type="checkbox" ${C.web?'checked':''} ${C.busy||!C.capabilities.webSearch?.enabled||!C.capabilities.webSearch?.hasApiKey?'disabled':''}>Search web</label><button class="text-button" type="button" data-chat-action="settings" aria-label="Chat settings">Settings</button></div>
      <div class="chat-input-row"><textarea id="chat-message" aria-label="Chat message" rows="2" maxlength="4000" placeholder="Ask a question, imagine an image, or design a system…" ${C.busy?'disabled':''}>${e(C.draft)}</textarea><button id="chat-send" class="button primary" type="submit" aria-label="Send chat message" ${C.busy?'disabled':''}>${C.busy?'…':'↑'}</button></div><p id="chat-status" class="chat-hint">${C.busy?'Working on your request. Images may take a few minutes.':'Enter to send · Shift + Enter for a new line'}</p></form>
    </main></div><input id="chat-upload" type="file" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.webp,.docx,.txt,.md" multiple hidden>`;
  renderFiles();renderMessages();updateSend();
}
function renderFiles(){
  const files=C.files.filter(file=>(file.title+' '+file.fileName).toLowerCase().includes(C.filter.toLowerCase()));
  $('#chat-files').innerHTML=files.map(file=>`<label class="chat-file"><input type="checkbox" data-chat-file="${file.id}" ${C.selected.has(file.id)?'checked':''} ${C.busy||(!C.selected.has(file.id)&&C.selected.size>=30)?'disabled':''}><span><strong>${e(file.title)}</strong><small>${e(file.fileName)}${['queued','processing'].includes(file.status)?' · Processing…':file.status==='error'?' · OCR needs attention':''}</small></span></label>`).join('')||'<p class="chat-hint">No matching documents. Add files to your library to ask about them.</p>';
  const missing=[...C.selected].filter(id=>!C.files.some(file=>file.id===id));
  if(missing.length)$('#chat-files').insertAdjacentHTML('beforeend','<p class="chat-hint danger">Some selected files are unavailable. Clear the selection or restore them from Trash.</p>');
  $('#chat-file-count').textContent=C.selected.size;
}
function sourceMarkup(source,index){
  const url=source.kind==='web'?source.url:`/api/items/${source.itemId}/file#page=${source.page||1}`;
  // Source URLs have already been validated server-side; retain a browser-side scheme check.
  const safe=/^https?:\/\//i.test(url)||url.startsWith('/api/items/')?url:'#';
  return `<details class="chat-source"><summary>${index+1}. ${source.kind==='web'?'Web':'File'} · ${e(source.title)}${source.page?' · p. '+source.page:''}</summary><blockquote>${e(source.quote||source.text)}</blockquote><a href="${e(safe)}" target="_blank" rel="noopener noreferrer">Open source ↗</a>${source.kind==='web'?'<small>Search-result excerpt; full page not fetched.</small>':''}</details>`;
}
function renderMessages(){
  const messages=C.current?.messages||[];
  $('#chat-messages').innerHTML=messages.length?messages.map(message=>`<article class="chat-message chat-${message.role}"><div class="chat-message-meta">${message.role==='user'?'You':'Synopsis'}${message.model?' · '+e(message.model):''}</div><div class="chat-message-text">${e(message.text)}</div>
    ${message.artifact?`<div class="chat-artifact"><div class="chat-artifact-preview"><img src="${message.artifact.url}" alt="${message.artifact.kind==='diagram'?e(message.artifact.diagram.title):'Image generated from your prompt'}" loading="lazy"></div><div class="chat-artifact-actions"><a href="${message.artifact.url}?download=1" download>Download ${message.artifact.kind==='diagram'?'SVG':'PNG'}</a>${message.artifact.kind==='diagram'?`<a href="${message.artifact.url}?format=json" download>Diagram data</a><button data-chat-zoom="1.25" aria-label="Zoom in diagram">＋</button><button data-chat-zoom="0.8" aria-label="Zoom out diagram">−</button>`:''}</div>${message.artifact.kind==='diagram'?`<details class="chat-source"><summary>Components &amp; connections</summary>${message.artifact.diagram.nodes.map(n=>`<p>${e(n.id)}: ${e(n.label)}</p>`).join('')}${message.artifact.diagram.edges.map(edge=>`<p>${e(edge.from)} → ${e(edge.to)}${edge.label?' · '+e(edge.label):''}</p>`).join('')}</details>`:''}</div>`:''}
    ${message.notice?`<p class="chat-hint">${e(message.notice)}</p>`:''}${message.sources?.length?`<div class="chat-sources">${message.sources.map(sourceMarkup).join('')}</div>`:''}</article>`).join(''):
    `<div class="chat-welcome"><span>✧</span><h3>Where will your curiosity take you?</h3><p>Explore your papers, ask a follow-up, or turn an idea into a visual.</p><button data-chat-example="answer">Summarize my selected files</button><button data-chat-example="architecture">Design a research platform architecture</button><button data-chat-example="image">Generate an image of a scientific discovery</button><button class="text-button" data-chat-action="settings">Configure AI &amp; tools</button></div>`;
  if(C.busy)$('#chat-messages').insertAdjacentHTML('beforeend','<div class="chat-working"><span class="spinner"></span> Gathering context and generating…</div>');
  $('#chat-messages').scrollTop=$('#chat-messages').scrollHeight;
}
function updateSend(){
  const pending=C.files.some(file=>C.selected.has(file.id)&&['queued','processing'].includes(file.status));
  $('#chat-send').disabled=C.busy||!C.draft.trim()||pending;
  if(!C.busy)$('#chat-status').textContent=pending?'Waiting for selected files to finish OCR…':'Enter to send · Shift + Enter for a new line';
}
async function pollFiles(){
  clearTimeout(pollTimer);
  if(!dialog.open||!C.files.some(file=>['queued','processing'].includes(file.status)))return;
  pollTimer=setTimeout(async()=>{try{await reloadData();if(dialog.open){renderFiles();updateSend();pollFiles();}}catch{}},1500);
}
async function upload(files){
  if(C.busy||!files.length)return;
  try{
    const data=new FormData();for(const file of files)data.append('files',file);
    C.error='';$('#chat-status').textContent='Uploading documents…';
    const result=await api('/upload',{method:'POST',body:data});
    for(const file of result.items){if(file.id&&C.selected.size<30)C.selected.add(file.id);}
    C.error=result.items.filter(file=>file.error).map(file=>file.fileName+': '+file.error).join('\n');
    await refresh();await reloadData();render();pollFiles();
  }catch(error){C.error=error.message;render();}
}
async function send(){
  if(C.busy||!C.draft.trim())return;
  const payload={message:C.draft.trim(),fileIds:[...C.selected],mode:C.mode,web:C.web};
  const signature=JSON.stringify(payload);
  if(!C.retry||C.retry.signature!==signature)C.retry={signature,id:crypto.randomUUID()};
  payload.requestId=C.retry.id;C.busy=true;C.error='';render();
  try{
    if(!C.current)C.current=await api('/chat/conversations',{method:'POST',body:{}});
    C.current=await api(`/chat/conversations/${C.current.id}/messages`,{method:'POST',body:payload});
    C.draft='';C.retry=null;await reloadData();
  }catch(error){C.error=error.message;}
  finally{C.busy=false;render();if(dialog.open)$('#chat-message').focus();}
}
document.addEventListener('click',event=>{const button=event.target.closest('[data-chat-open]');if(button){document.querySelector('#sidebar').classList.remove('mobile-open');open(button.dataset.chatOpen==='full');}});
dialog.addEventListener('submit',event=>{event.preventDefault();event.stopPropagation();send();});
dialog.addEventListener('input',event=>{
  if(event.target.id==='chat-message'){C.draft=event.target.value;updateSend();}
  if(event.target.id==='chat-file-search'){C.filter=event.target.value;renderFiles();}
});
dialog.addEventListener('change',async event=>{
  const target=event.target;
  if(target.dataset.chatFile){target.checked?C.selected.add(target.dataset.chatFile):C.selected.delete(target.dataset.chatFile);renderFiles();updateSend();}
  if(target.id==='chat-mode')C.mode=target.value;
  if(target.id==='chat-web')C.web=target.checked;
  if(target.id==='chat-upload')await upload(target.files);
  if(target.id==='chat-history'){
    if(!target.value){fresh();return;}
    try{C.current=await api('/chat/conversations/'+target.value);C.selected=new Set(C.current.fileIds||[]);C.draft='';C.error='';C.retry=null;render();}
    catch(error){C.error=error.message;render();}
  }
});
dialog.addEventListener('keydown',event=>{
  if(event.target.id==='chat-message'&&event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();event.stopPropagation();if(!$('#chat-send').disabled)send();}
  // Keep the library search shortcut out of chat text and selectors.
  event.stopPropagation();
});
dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
dialog.addEventListener('click',async event=>{
  event.stopPropagation();const button=event.target.closest('button');if(!button)return;
  const action=button.dataset.chatAction;
  if(action==='close')close();
  if(action==='expand'){setLayout(!C.full);render();}
  if(action==='files'){dialog.classList.toggle('chat-show-files');$('#chat-file-search').focus();}
  if(action==='new')fresh();
  if(action==='clear-files'){C.selected.clear();renderFiles();updateSend();}
  if(action==='upload')$('#chat-upload').click();
  if(action==='settings'){close();await openSettings();}
  if(action==='delete'&&C.current&&!C.busy&&window.confirm('Delete this conversation and its generated artifacts? Your library documents will remain.')){
    try{await api('/chat/conversations/'+C.current.id,{method:'DELETE'});await reloadData();fresh();}catch(error){C.error=error.message;render();}
  }
  if(button.dataset.chatExample){C.mode=button.dataset.chatExample;C.draft=button.textContent;render();$('#chat-message').focus();}
  if(button.dataset.chatZoom){const img=button.closest('.chat-artifact').querySelector('img');const zoom=Math.max(1,Math.min(4,Number(img.dataset.zoom||1)*Number(button.dataset.chatZoom)));img.dataset.zoom=zoom;img.style.width=(zoom*100)+'%';img.style.maxWidth='none';}
});
dialog.addEventListener('dragover',event=>{if(event.dataTransfer.types.includes('Files')){event.preventDefault();event.stopPropagation();}});
dialog.addEventListener('drop',event=>{if(event.dataTransfer.files.length){event.preventDefault();event.stopPropagation();document.querySelector('#drop-overlay').hidden=true;upload(event.dataTransfer.files);}});
