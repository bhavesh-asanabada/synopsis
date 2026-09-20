// Cloud storage controls share the existing settings and document panes.
export function connectorFields(config, escape, safeUrl) {
  return `<section class="settings-section" id="cloud-connectors"><div class="settings-heading">Cloud document storage</div>
    <p class="field-hint">Save new uploads and watched-folder imports to a connected drive. A local copy stays in your upload folder for OCR, reading, and backups. Existing documents can be saved from their details pane.</p>
    <label class="form-field">Save new documents to<select id="cloud-destination" aria-label="Save new documents to"><option value="local" ${config.destination==='local'?'selected':''}>Local folder only</option>${Object.entries(config.providers).map(([id,c])=>`<option value="${id}" ${config.destination===id?'selected':''} ${!c.connected?'disabled':''}>${escape(c.name)}${!c.connected?' (connect first)':''}</option>`).join('')}</select></label>
    <button type="button" class="button secondary small" data-cloud-action="destination">Apply storage destination</button>
    ${Object.entries(config.providers).map(([id,c])=>`<details class="connector-card" data-connector="${id}" ${c.connected?'':'open'}><summary><strong>${escape(c.name)}</strong><span>${c.connected?'Connected':'Not connected'}</span></summary>
      ${c.connected?`<p class="field-hint">${escape(c.account)} · ${escape(c.folderName)}</p>${c.folderUrl?`<a class="text-button" href="${escape(safeUrl(c.folderUrl))}" target="_blank" rel="noopener noreferrer">Open cloud folder</a>`:''}<button type="button" class="text-button danger" data-cloud-action="disconnect" data-provider="${id}">Disconnect ${escape(c.name)}</button>`:`
      <p class="field-hint">Register an OAuth web application with ${id==='google'?'Google Cloud and enable the Drive API':'Microsoft Entra (personal and/or work accounts)'}. Add this exact redirect URI:</p>
      <code class="connector-redirect">${escape(c.redirectUri)}</code>
      <p class="field-hint">${id==='google'?'Use the drive.file scope. Synopsis creates a dedicated folder when you connect.':'Use delegated Files.ReadWrite and offline_access permissions. The folder is created in your OneDrive if needed. If the portal rejects an HTTP 127.0.0.1 redirect, reopen Synopsis using localhost with the same port, then copy the redirect URI shown there.'} <a href="${id==='google'?'https://developers.google.com/identity/protocols/oauth2/web-server':'https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app'}" target="_blank" rel="noopener noreferrer">Provider setup guide</a></p>
      <label class="form-field">${escape(c.name)} client ID<input data-cloud-field="clientId" value="${escape(c.clientId)}" maxlength="500" autocomplete="off"></label>
      <label class="form-field">${escape(c.name)} client secret<input data-cloud-field="clientSecret" type="password" maxlength="4096" autocomplete="new-password" placeholder="${c.hasClientSecret?'Leave blank to keep saved secret':'OAuth application secret'}"></label>
      ${id==='onedrive'?`<label class="form-field">Microsoft tenant<input data-cloud-field="tenant" value="${escape(c.tenant||'common')}" placeholder="common" maxlength="100"></label>`:''}
      <label class="form-field">${escape(c.name)} folder name<input data-cloud-field="folderName" value="${escape(c.folderName||'Synopsis')}" maxlength="100"></label>
      <button type="button" class="button secondary small" data-cloud-action="connect" data-provider="${id}">Connect ${escape(c.name)}</button>`}
    </details>`).join('')}
    <p class="field-hint">Connecting opens provider sign-in in this tab; save other preference edits first. Connection changes and Apply storage destination save immediately. Credentials stay in the local database and are excluded from exported backups. Disconnecting or deleting a local reference keeps its cloud copy.</p>
    <p id="cloud-settings-status" role="status" class="field-hint"></p>
  </section>`;
}

export function cloudDetail(item, escape, safeUrl) {
  if(!item.fileName)return '';
  const job=item.cloudStorage, name=job?.provider==='google'?'Google Drive':'OneDrive';
  return `<div class="cloud-document"><div class="detail-section-title">CLOUD STORAGE</div>${job?`<p class="field-hint"><strong>${escape(name)} · ${escape(({queued:'Waiting to upload',uploading:'Uploading…',saved:'Saved',error:'Needs attention',paused:'Paused'})[job.status]||job.status)}</strong></p>${job.error?`<p class="field-hint cloud-transfer-error">${escape(job.error)}</p>`:''}${job.url?`<a class="text-button" href="${escape(safeUrl(job.url))}" target="_blank" rel="noopener noreferrer">Open cloud copy</a>`:''}`:'<p class="field-hint">Local copy. Choose a connected drive in Settings to save this document to cloud.</p>'}
    ${!item.trashed?`<div class="field-buttons">${job?.status==='error'?'<button type="button" class="text-button" data-cloud-action="retry">Retry cloud upload</button>':''}<button type="button" class="text-button" data-cloud-action="save" ${['queued','uploading'].includes(job?.status)?'disabled':''}>Save to cloud</button></div>`:''}</div>`;
}

export function installCloudUI({api, escape, safeUrl, toast, refresh, state, openSettings}) {
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-cloud-action]');if(!button)return;
    const action=button.dataset.cloudAction, provider=button.dataset.provider;
    button.disabled=true;
    const status=document.querySelector('#cloud-settings-status');
    try {
      if(action==='connect') {
        const card=button.closest('[data-connector]'), body={};
        card.querySelectorAll('[data-cloud-field]').forEach(input=>body[input.dataset.cloudField]=input.value);
        await api(`/connectors/${provider}/configure`,{method:'POST',body});
        card.querySelector('[type=password]').value='';
        const result=await api(`/connectors/${provider}/connect`,{method:'POST'});
        location.assign(result.url);return;
      }
      if(action==='disconnect') {
        if(!confirm('Disconnect this account? Future uploads will use local storage. Existing cloud copies remain in your drive.'))return;
        await api(`/connectors/${provider}/disconnect`,{method:'POST'});
      }else if(action==='destination') {
        await api('/connectors/destination',{method:'POST',body:{destination:document.querySelector('#cloud-destination').value}});
      }else if(action==='save'||action==='retry') {
        await api(`/connectors/items/${state.selected}/${action}`,{method:'POST'});
        await refresh({detail:true});toast('Cloud transfer queued');return;
      }
      const config=await api('/connectors');
      document.querySelector('#cloud-connectors').outerHTML=connectorFields(config,escape,safeUrl);
      document.querySelector('#cloud-settings-status').textContent=action==='disconnect'?'Account disconnected. Cloud copies were kept.':'Storage destination saved.';
      await refresh({detail:true});
    }catch(error){if(status)status.textContent=error.message;toast(error.message,true);}
    finally{button.disabled=false;}
  });
  const result=new URL(location.href).searchParams.get('connector');
  if(result){history.replaceState(null,'',location.pathname);openSettings('cloud').then(()=>{
    document.querySelector('#cloud-connectors')?.scrollIntoView();
    document.querySelector('#cloud-settings-status').textContent=result==='connected'?'Account connected. Select it as the storage destination to save new uploads.':'Connection failed or was canceled. Check your client credentials, exact redirect URI, consent permissions, and network, then connect again.';
  }).catch(error=>toast(error.message,true));}
}
