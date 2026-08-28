(function(){
  const chatFeed = document.getElementById('chatFeed');
  const jumpToLatest = document.getElementById('jumpToLatest');
  const requestProgress = document.getElementById('requestProgress');
  const requestProgressLabel = document.getElementById('requestProgressLabel');

  if(!chatFeed) return;

  const AUTOSCROLL_EPSILON = 48;
  let autoScrollEnabled = true;

  function scrollFeed(force){
    if(force){ autoScrollEnabled = true; }
    if(autoScrollEnabled){
      chatFeed.scrollTop = chatFeed.scrollHeight;
    }
  }

  chatFeed.addEventListener('scroll', ()=>{
    const nearBottom = chatFeed.scrollHeight - (chatFeed.scrollTop + chatFeed.clientHeight) <= AUTOSCROLL_EPSILON;
    autoScrollEnabled = nearBottom;
    if(jumpToLatest){
      jumpToLatest.style.display = nearBottom ? 'none' : 'flex';
    }
  });

  if(jumpToLatest){
    jumpToLatest.addEventListener('click', ()=>{
      scrollFeed(true);
      jumpToLatest.style.display = 'none';
    });
  }

  function copyToClipboard(text){
    if(navigator.clipboard && window.isSecureContext){
      return navigator.clipboard.writeText(text);
    }
    return new Promise((resolve, reject)=>{
      try{
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly','');
        ta.style.position = 'absolute';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        ok ? resolve() : reject(new Error('execCommand failed'));
      }catch(err){
        reject(err);
      }
    });
  }

  function bindCopyButtons(){
    chatFeed.querySelectorAll('.chat-action-bar .copy-btn').forEach((btn)=>{
      if(btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', ()=>{
        const bubble = btn.closest('.chat-entry')?.querySelector('.chat-bubble');
        const text = bubble ? bubble.textContent || '' : '';
        const original = btn.textContent;
        copyToClipboard(text).then(()=>{
          btn.textContent = 'Copied!';
          setTimeout(()=>btn.textContent = original, 1200);
        }).catch(()=>{
          btn.textContent = 'Failed';
          setTimeout(()=>btn.textContent = original, 1200);
        });
      });
    });
  }

  bindCopyButtons();
  scrollFeed(true);

  function progressTextForAction(action){
    switch(action){
      case 'ask':
      case 'analyze_clauses':
        return 'Analyzing clauses, retrieval context, and checklist (quality-first — may take several minutes)…';
      case 'upload': return 'Uploading and parsing contract...';
      case 'export_reviewed_docx': return 'Generating reviewed DOCX with redlines...';
      case 'export_contract_commentary_docx': return 'Building DOCX with review comments…';
      case 'export_counterfactuals_csv': return 'Preparing counterfactuals CSV...';
      case 'export_mitigation_checklist_csv': return 'Preparing mitigation checklist CSV...';
      case 'export_verification_report_csv': return 'Preparing verification report CSV...';
      case 'remove_file': return 'Updating session files...';
      case 'reset': return 'Resetting workspace...';
      default: return 'Working on it...';
    }
  }

  function showProgress(message){
    if(requestProgress){
      requestProgress.style.display = 'flex';
    }
    if(requestProgressLabel){
      requestProgressLabel.textContent = message || 'Working on it...';
    }
    const loading = document.querySelector('#chatLoading');
    if(loading){ loading.style.display = 'inline-flex'; }
    document.querySelectorAll('.chat-shell button[type="submit"]').forEach((btn)=>{
      btn.disabled = true;
    });
  }

  function hideProgress(){
    if(requestProgress){
      requestProgress.style.display = 'none';
    }
    const loading = document.querySelector('#chatLoading');
    if(loading){ loading.style.display = 'none'; }
    document.querySelectorAll('.chat-shell button[type="submit"]').forEach((btn)=>{
      btn.disabled = false;
    });
  }

  const DOWNLOAD_ACTIONS = ['export_reviewed_docx','export_contract_commentary_docx','export_table_csv','export_counterfactuals_csv','export_mitigation_checklist_csv','export_verification_report_csv'];

  function handleExportFormSubmit(form, e){
    const action = form.querySelector('input[name="action"]')?.value || '';
    if(!DOWNLOAD_ACTIONS.includes(action)) return false;
    e.preventDefault();
    showProgress(progressTextForAction(action));
    const formData = new FormData(form);
    // form.action is shadowed by <input name="action">; prefer data-submit-url to avoid [object HTMLInputElement]
    let url = (form.dataset && form.dataset.submitUrl);
    if (!url || typeof url !== 'string' || url.includes('HTMLInputElement')) {
      url = (form.getAttribute?.('action') || '').toString();
      if (!url || url.includes('HTMLInputElement')) url = window.location.pathname || window.location.href;
    }
    const progressTimeout = setTimeout(hideProgress, 15000);
    fetch(url, {
      method: 'POST',
      body: formData,
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    }).then(res=>{
      if(!res.ok) throw new Error('Export failed');
      const ct = res.headers.get('Content-Type') || '';
      if(ct.includes('text/html')) throw new Error('Server returned error page');
      const cd = res.headers.get('Content-Disposition');
      let filename = 'download';
      if(cd){
        const m = cd.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
        if(m) filename = m[1].replace(/['"]/g,'').trim();
      }
      return res.blob().then(blob=> ({ blob, filename }));
    }).then(({ blob, filename })=>{
      const fallback = action === 'export_reviewed_docx' ? 'reviewed_contract.docx'
        : action === 'export_contract_commentary_docx' ? 'contract_with_review_comments.docx'
        : action === 'export_verification_report_csv' ? 'verification_report.csv' : 'export.csv';
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = filename && filename !== 'download' ? filename : fallback;
      document.body.appendChild(a);
      a.click();
      URL.revokeObjectURL(a.href);
      document.body.removeChild(a);
      clearTimeout(progressTimeout);
      hideProgress();
    }).catch(()=>{
      clearTimeout(progressTimeout);
      const submitUrl = (form.dataset && form.dataset.submitUrl) || (typeof form.getAttribute === 'function' ? form.getAttribute('action') : null) || window.location.pathname || window.location.href;
      if (submitUrl && typeof submitUrl === 'string' && !submitUrl.includes('HTMLInputElement')) {
        form.setAttribute('action', submitUrl);
      }
      form.submit();
    }).finally(()=>{
      clearTimeout(progressTimeout);
      hideProgress();
    });
    return true;
  }

  function bindProgressToForms(){
    document.querySelectorAll('.chat-shell form').forEach((form)=>{
      if(form.dataset.progressBound === '1') return;
      form.dataset.progressBound = '1';
      form.addEventListener('submit', (e)=>{
        const actionInput = form.querySelector('input[name="action"]');
        const action = actionInput ? actionInput.value : '';
        // Only export-form uses fetch/download; others do normal submit
        if(form.classList.contains('export-form') && handleExportFormSubmit(form, e)) return;
        showProgress(progressTextForAction(action));
        // Don't preventDefault - let form submit (ask, upload, remove_file)
      });
    });
  }

  bindProgressToForms();

  document.querySelectorAll('.upload-input').forEach((uploadInput)=>{
    if(uploadInput.dataset.uploadBound === '1') return;
    uploadInput.dataset.uploadBound = '1';
    uploadInput.addEventListener('change', ()=>{
      const uploadForm = uploadInput.closest('form');
      if(!uploadForm) return;
      showProgress(progressTextForAction('upload'));
      uploadForm.submit();
      setTimeout(()=>{ uploadInput.value = ''; }, 0);
    });
  });

  function getCookie(name){
    const v = `; ${document.cookie}`;
    const parts = v.split(`; ${name}=`);
    if(parts.length === 2) return parts.pop().split(';').shift() || '';
    return '';
  }

  const asyncEnabledEl = document.getElementById('contract-analyzer-async-enabled');
  if(asyncEnabledEl){
    let asyncOn = false;
    try{
      asyncOn = JSON.parse(asyncEnabledEl.textContent) === true;
    }catch(e){
      asyncOn = false;
    }
    if(asyncOn){
      const btn = document.getElementById('analyzeClausesAsyncBtn');
      const form = document.getElementById('analyzeClausesForm');
      if(btn && form){
        btn.addEventListener('click', async ()=>{
          if(btn.disabled) return;
          const fd = new FormData(form);
          showProgress('Queued background analysis; waiting for job to complete…');
          btn.disabled = true;
          document.querySelectorAll('.chat-shell button[type="submit"]').forEach((b)=>{ b.disabled = true; });
          try{
            const csrftoken = getCookie('csrftoken');
            const resp = await fetch(form.getAttribute('action') || window.location.pathname, {
              method: 'POST',
              body: fd,
              headers: Object.assign(
                {'X-Requested-With': 'XMLHttpRequest'},
                csrftoken ? {'X-CSRFToken': csrftoken} : {},
              ),
              credentials: 'same-origin',
            });
            const data = await resp.json().catch(()=>({}));
            if(!resp.ok){
              throw new Error(data.error || resp.statusText || 'enqueue failed');
            }
            const jobId = data.job_id;
            const pollUrl = data.poll_url || `/api/analysis/jobs/${jobId}/`;
            let delayMs = 800;
            for(let i=0;i<720;i++){
              await new Promise((r)=>setTimeout(r, delayMs));
              delayMs = Math.min(delayMs + 400, 6000);
              const pr = await fetch(pollUrl, {credentials:'same-origin', headers:{'X-Requested-With':'XMLHttpRequest'}});
              if(!pr.ok) throw new Error('status poll failed');
              const st = await pr.json();
              if(st.status === 'succeeded' || st.status === 'failed' || st.status === 'cancelled'){
                hideProgress();
                if(st.status !== 'succeeded'){
                  alert('Analysis failed: ' + (st.error_message || 'unknown'));
                }else{
                  window.location.reload();
                  return;
                }
                break;
              }
            }
          }catch(err){
            hideProgress();
            alert((err && err.message) ? err.message : String(err));
          }finally{
            document.querySelectorAll('.chat-shell button[type="submit"]').forEach((b)=>{ b.disabled = false; });
            btn.disabled = false;
          }
        });
      }
    }
  }

  // TODO: Extend with drag-and-drop if desired. Ensure any fetch/XHR targets https:// in production.
})();
