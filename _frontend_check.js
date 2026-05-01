let uploaded=0, resultReady=false, batchReady=false, appUnlocked=false;
const API_BASE=(new URLSearchParams(window.location.search).get('api')||window.__MEDISHIELD_API_BASE__||'http://127.0.0.1:8000');
const selectedFiles=[null,null,null,null];
let lastScanResult=null;

function getPipelineOutput(){
  return lastScanResult&&lastScanResult.pipeline_output?lastScanResult.pipeline_output:{};
}

function getPipelineFinal(){
  const pipeline=getPipelineOutput();
  return pipeline&&pipeline.final_output?pipeline.final_output:{};
}

function getEffectiveParsedData(){
  const backendParsed=lastScanResult&&lastScanResult.parsed_data?lastScanResult.parsed_data:{};
  const pipeline=getPipelineOutput();
  const rootParsed=pipeline&&pipeline.ocr&&pipeline.ocr.final_data?pipeline.ocr.final_data:{};
  return {
    medicine_name: rootParsed.medicine_name||backendParsed.medicine_name||'',
    batch_number: rootParsed.batch_number||backendParsed.batch_number||'',
    mfg_date: rootParsed.mfg_date||backendParsed.mfg_date||'',
    exp_date: rootParsed.expiry_date||rootParsed.exp_date||backendParsed.exp_date||'',
    manufacturer: rootParsed.manufacturer||backendParsed.manufacturer||'',
  };
}

const SLOT_COLORS=['#1a3a4a','#1a2a4a','#3a1a2a','#1a3a2a'];
const SLOT_LABELS=['IMG_FRONT','IMG_BACK','IMG_STRIP','IMG_QR'];
const OCR_DATA=[
  ['Metformin 500mg','Batch B202','Jan 2024','Dec 2026'],
  ['Metformin 500mg','Batch B201','Jan 2024','Dec 2026'],
  ['Metformin 500mg','Batch B202','Jan 2024','Dec 2026'],
  ['QR: Decoded','Mfr: Cipla','Lot: 4421','—'],
];

function nav(id){
  if(!appUnlocked&&id!=='auth')id='auth';
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('on'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('on'));
  document.querySelectorAll('.icon-btn').forEach(b=>b.classList.remove('on'));
  document.getElementById('pg-'+id).classList.add('on');
  const ti=['scan','result','batch','about'].indexOf(id);
  document.querySelectorAll('.tab')[ti]&&document.querySelectorAll('.tab')[ti].classList.add('on');
  if(id==='profile')document.getElementById('profileBtn').classList.add('on');
  if(id==='settings')document.getElementById('settingsBtn').classList.add('on');
  if(id==='result'&&!resultReady){buildResult();resultReady=true}
  if(id==='batch'&&!batchReady){buildBatch();batchReady=true}
  playPageMotion(id);
}

function upload(i){
  const slot=document.getElementById('s'+i);
  const img=document.getElementById('si'+i);
  if(slot.classList.contains('filled')){
    if(img.dataset.blobUrl){URL.revokeObjectURL(img.dataset.blobUrl);delete img.dataset.blobUrl}
    selectedFiles[i]=null;
    img.src='';
    slot.classList.remove('filled','just-filled');
    slot.classList.add('just-cleared');
    setTimeout(()=>slot.classList.remove('just-cleared'),240);
    uploaded--;updateBtn();showToast(SLOT_LABELS[i]+' removed');return;
  }

  const picker=document.createElement('input');
  picker.type='file';
  picker.accept='image/*';
  picker.onchange=()=>{
    const file=picker.files&&picker.files[0];
    if(!file)return;

    selectedFiles[i]=file;
    if(img.dataset.blobUrl){URL.revokeObjectURL(img.dataset.blobUrl)}
    const blobUrl=URL.createObjectURL(file);
    img.src=blobUrl;
    img.dataset.blobUrl=blobUrl;

    slot.classList.add('filled','just-filled');
    setTimeout(()=>slot.classList.remove('just-filled'),520);
    uploaded=selectedFiles.filter(Boolean).length;
    updateBtn();
    showToast(SLOT_LABELS[i]+' accepted');
  };
  picker.click();
}

function updateBtn(){
  const b=document.getElementById('abtn');
  b.disabled=uploaded===0;
  b.classList.toggle('ready',uploaded>0);
  b.textContent=uploaded===0?'Upload at least 1 image to scan':`Analyze ${uploaded} image${uploaded>1?'s':''}  —  Detect risk`;
}

function animateCount(el,to,duration=750){
  const from=parseInt(el.textContent,10)||0;
  const start=performance.now();
  function frame(now){
    const p=Math.min((now-start)/duration,1);
    const eased=1-Math.pow(1-p,3);
    el.textContent=Math.round(from+(to-from)*eased);
    if(p<1)requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function pressFeedback(el,evt){
  if(evt){
    const r=el.getBoundingClientRect();
    el.style.setProperty('--rx',(evt.clientX-r.left)+'px');
    el.style.setProperty('--ry',(evt.clientY-r.top)+'px');
  }
  el.classList.remove('press');
  void el.offsetWidth;
  el.classList.add('press');
}

function showToast(msg){
  const t=document.getElementById('toast');
  if(!t)return;
  clearTimeout(showToast.timer);
  t.textContent=msg;
  t.classList.add('show');
  showToast.timer=setTimeout(()=>t.classList.remove('show'),1450);
}

function toggleSwitch(el){
  el.classList.toggle('on');
}

let authMode='login';

function switchAuth(mode){
  authMode=mode;
  document.getElementById('authForm').classList.remove('auth-hidden');
  document.getElementById('authSuccess').classList.add('auth-hidden');
  document.getElementById('authLoginTab').classList.toggle('active',mode==='login');
  document.getElementById('authSignupTab').classList.toggle('active',mode==='signup');
  document.querySelectorAll('.auth-signup-only').forEach(el=>el.classList.toggle('auth-hidden',mode!=='signup'));
  document.getElementById('authLoginRow').classList.toggle('auth-hidden',mode!=='login');
  document.getElementById('authTitle').textContent=mode==='login'?'Welcome back':'Get started free';
  document.getElementById('authSubtitle').textContent=mode==='login'?'Sign in to access your MediShield dashboard':'Scan your first medicine in under 2 minutes';
  document.getElementById('authSubmit').textContent=mode==='login'?'Sign In':'Create Account';
  document.getElementById('authSwitchText').textContent=mode==='login'?"Don't have an account?":'Already have an account?';
  document.getElementById('authSwitchBtn').textContent=mode==='login'?'Sign up free':'Sign in';
  document.getElementById('authSwitchBtn').setAttribute('onclick',`switchAuth('${mode==='login'?'signup':'login'}')`);
}

function submitAuth(evt){
  const btn=document.getElementById('authSubmit');
  pressFeedback(btn,evt);
  btn.classList.add('loading');
  btn.disabled=true;
  setTimeout(()=>{
    btn.classList.remove('loading');
    btn.disabled=false;
    document.getElementById('authForm').classList.add('auth-hidden');
    document.getElementById('authSuccess').classList.remove('auth-hidden');
    document.getElementById('authSuccessTitle').textContent=authMode==='login'?'Welcome back!':'Account created!';
    document.getElementById('authSuccessText').textContent=authMode==='login'?'Redirecting to your dashboard...':'Verification email sent. Check your inbox.';
    showToast(authMode==='login'?'Signed in':'Account created');
    setTimeout(unlockApp,850);
  },1150);
}

function unlockApp(){
  appUnlocked=true;
  document.getElementById('appShell').classList.remove('auth-locked');
  nav('scan');
}

function playPageMotion(id){
  const page=document.getElementById('pg-'+id);
  if(!page)return;
  const targets=page.querySelectorAll('.hero-title,.hero-sub,.upload-zone,.hint,.field-wrap,.btn-primary,.steps .step,.result-hero,.sec,.sig,.tbl-wrap,.anom,.drug-wrap,.stat,.chart-card,.geo-item,.feat,.arch,.quote-card,.auth-shell,.auth-brand,.auth-card,.auth-feature,.auth-scan-bar,.account-card,.setting-card,.activity,.metric');
  targets.forEach((el,i)=>{
    el.classList.add('motion-target');
    el.classList.remove('in');
    el.style.transitionDelay=Math.min(i*32,420)+'ms';
  });
  requestAnimationFrame(()=>targets.forEach(el=>el.classList.add('in')));
}

async function startScan(evt){
  pressFeedback(document.getElementById('abtn'),evt);
  document.getElementById('abtn').disabled=true;
  document.getElementById('abtn').classList.remove('ready');
  const sw=document.getElementById('stepWrap');sw.style.display='block';
  showToast('Analysis started');
  const files=selectedFiles.filter(Boolean);
  if(files.length===0){
    showToast('Upload at least one image first');
    updateBtn();
    return;
  }

  let i=0;
  const runStep=()=>new Promise((resolve)=>{
    if(i>0){const prev=document.getElementById('p'+(i-1));prev.classList.remove('live');prev.classList.add('done');prev.querySelector('.step-num').textContent='✓'}
    if(i<7){document.getElementById('p'+i).classList.add('live');i++;setTimeout(resolve,380+Math.random()*220)}
    else resolve();
  });

  for(let step=0;step<7;step++){
    await runStep();
  }

  try{
    const fd=new FormData();
    files.forEach((file)=>fd.append('images',file,file.name));

    const res=await fetch(`${API_BASE}/scan`,{method:'POST',body:fd});
    if(!res.ok){
      const text=await res.text();
      throw new Error(text||'Scan failed');
    }

    lastScanResult=await res.json();
    
    // Auto-populate form fields with extracted values
    const parsed=getEffectiveParsedData();
    if(parsed){
      if(parsed.medicine_name){
        document.getElementById('mname').value=parsed.medicine_name;
        showToast(`Extracted: ${parsed.medicine_name}`);
      }else if(lastScanResult.drug_info&&lastScanResult.drug_info.name){
        document.getElementById('mname').value=lastScanResult.drug_info.name;
        showToast(`Detected medicine: ${lastScanResult.drug_info.name}`);
      }else if(!document.getElementById('mname').value){
        showToast('Could not detect medicine name. Please enter it manually.');
      }
      if(parsed.batch_number){
        document.getElementById('bnum').value=parsed.batch_number;
        showToast(`Batch detected: ${parsed.batch_number}`);
      }
    }
    
    showToast('Risk report ready');
    resultReady=false;
    nav('result');
    document.querySelectorAll('.tab')[1].classList.add('on');
  }catch(err){
    console.error(err);
    showToast(`Backend scan failed. Is API running at ${API_BASE}?`);
    updateBtn();
  }
}

function buildResult(){
  const parsed=getEffectiveParsedData();
  const pipelineFinal=getPipelineFinal();
  const enteredMed=(document.getElementById('mname').value||'').trim();
  const med=enteredMed||parsed.medicine_name||(lastScanResult&&lastScanResult.drug_info&&lastScanResult.drug_info.name)||'';
  const batch=parsed.batch_number||document.getElementById('bnum').value||'B202';
  const n=Math.max(1,uploaded||1);
  const score=typeof pipelineFinal.CONFIDENCE_SCORE==='number'
    ? Math.round(pipelineFinal.CONFIDENCE_SCORE)
    : lastScanResult&&typeof lastScanResult.risk_score==='number'
      ? Math.round(lastScanResult.risk_score)
      : 36;

  if(med){
    document.getElementById('mname').value=med;
  }

  const scanSummary=pipelineFinal.FINAL_VERDICT||lastScanResult&&lastScanResult.status||'SCAN';
  document.getElementById('rsub').textContent=`${med} · Batch ${batch} · ${scanSummary}`;
  document.getElementById('rbatch').textContent=batch;
  document.getElementById('rimg').textContent=n;
  document.getElementById('rid').textContent='SCN-'+Math.floor(Math.random()*90000+10000);
  document.getElementById('rconf').textContent=typeof pipelineFinal.CONFIDENCE_SCORE==='number'
    ? (pipelineFinal.CONFIDENCE_SCORE>=70?'HIGH':pipelineFinal.CONFIDENCE_SCORE>=40?'MEDIUM':'LOW')
    : n>=3?'MEDIUM':'LOW';

  const apiStatus=pipelineFinal.FINAL_VERDICT?String(pipelineFinal.FINAL_VERDICT).toUpperCase():(lastScanResult&&lastScanResult.status?String(lastScanResult.status).toUpperCase():'');
  const st=apiStatus||(score>=60?'SUSPICIOUS':score>=40?'CAUTION':'LIKELY SAFE');
  const sc=score>=75?'danger':score>=40?'warn':'safe';
  const heroClass=score>=60?'risk-high':score>=40?'risk-mid':'risk-low';
  const ac=score>=75?'#ff5f57':score>=40?'#ffbc42':'#58a6ff';
  const reasons=Array.isArray(pipelineFinal.TOP_3_REASONS)&&pipelineFinal.TOP_3_REASONS.length
    ? pipelineFinal.TOP_3_REASONS
    : [];
  const conflict=reasons.length>1 || (lastScanResult&&Array.isArray(lastScanResult.reasons)&&lastScanResult.reasons.length>1);
  const impact=pipelineFinal.FINAL_VERDICT
    ? pipelineFinal.FINAL_VERDICT.replace(/_/g,' ')
    : score>=60?'Hold for pharmacist review':score>=40?'Verify before dispensing':'No immediate red flags';
  const riskCopy=pipelineFinal.CONFIDENCE_BASIS_SUMMARY
    || (score>=60
      ?'The package shows a high-impact mismatch pattern. Treat this scan as a stop signal until the batch and packaging are verified.'
      :score>=40
        ?'The scan found moderate uncertainty. Review the highlighted signals before accepting this medicine.'
        :'Signals are aligned and the package behavior looks normal for this demo scan.');
  const hero=document.querySelector('#pg-result .result-hero');
  hero.classList.remove('risk-high','risk-mid','risk-low');
  hero.classList.add(heroClass);
  document.getElementById('rstat').textContent=st;document.getElementById('rstat').className='r-status '+sc;
  document.getElementById('riskCopy').textContent=riskCopy;
  document.getElementById('riskBandLabel').textContent=impact.toUpperCase();
  document.getElementById('riskFill').style.width=score+'%';
  document.getElementById('riskPin').style.left=score+'%';
  animateCount(document.getElementById('rnum'),score,820);
  const circ=289,off=circ-(score/100)*circ;
  document.getElementById('rarc').setAttribute('stroke-dashoffset',off);
  document.getElementById('rarc').setAttribute('stroke',ac);
  document.getElementById('rglow').setAttribute('stroke-dashoffset',off);
  document.getElementById('rglow').setAttribute('stroke',ac);

  const ml=pipelineFinal.ML_INSIGHTS||lastScanResult&&lastScanResult.ml_insights||{};
  const visionScore=typeof ml.visual_anomaly_score==='number' ? Math.round(ml.visual_anomaly_score*100) : (conflict?62:38);
  const ocrNoise=typeof ml.ocr_noise_score==='number' ? Math.round(ml.ocr_noise_score*100) : (conflict?88:18);
  const imageQuality=typeof ml.image_quality_score==='number' ? Math.round(ml.image_quality_score*100) : 50;
  const mlConfidence=typeof ml.ml_confidence==='number' ? Math.round(ml.ml_confidence*100) : 50;
  const sigs=[
    {key:'Vision AI',val:String(visionScore),vc:visionScore>=60?'a':'g',meter:visionScore,note:ml.packaging_type&&ml.packaging_type!=='Unknown'?`Packaging type: ${ml.packaging_type}`:'Root pipeline visual anomaly score',cls:visionScore>=60?'mid':'good',
     ico:'<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>'},
    {key:'OCR noise',val:String(ocrNoise),vc:ocrNoise>=60?'a':'g',meter:ocrNoise,note:'Higher values mean more text noise and weaker OCR stability',cls:ocrNoise>=60?'mid':'good',
     ico:'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'},
    {key:'Image quality',val:String(imageQuality),vc:imageQuality>=60?'g':'a',meter:imageQuality,note:'Derived from blur, brightness, and contrast',cls:'good',
     ico:'<path d="M13 10V3L4 14h7v7l9-11h-7z"/>'},
    {key:'Confidence',val:String(mlConfidence),vc:mlConfidence>=60?'g':'a',meter:mlConfidence,note:pipelineFinal.CONFIDENCE_BASIS_SUMMARY||'Combined OCR and ML support score',cls:'good',
     ico:'<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>'},
    {key:'Consistency',val:conflict?'MISMATCH':'OK',vc:conflict?'r':'g',meter:conflict?88:12,note:conflict?'Batch differs across images':'All fields match across images',cls:conflict?'bad':'good',
     ico:'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'},
    {key:'Geo spread',val:conflict?'HIGH':'LOW',vc:conflict?'a':'g',meter:conflict?69:14,note:conflict?'Multiple-city scan pattern':'Single city distribution',cls:conflict?'mid':'good',
     ico:'<circle cx="12" cy="10" r="3"/><path d="M12 2a8 8 0 00-8 8c0 5.25 8 14 8 14s8-8.75 8-14a8 8 0 00-8-8z"/>'},
  ];
  document.getElementById('sigGrid').innerHTML=sigs.map(s=>`
    <div class="sig ${s.cls}">
      <div class="sig-top">
        <div class="sig-icon"><svg viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="1.5" stroke-linecap="round">${s.ico}</svg></div>
        <div class="sig-key">${s.key}</div>
      </div>
      <div class="sig-val ${s.vc}">${s.val}</div>
      <div class="sig-note">${s.note}</div>
      <div class="sig-meter"><span data-meter="${s.meter}"></span></div>
    </div>`).join('');
  requestAnimationFrame(()=>{
    document.querySelectorAll('#sigGrid .sig-meter span').forEach(m=>{m.style.width=m.dataset.meter+'%'});
  });

  const frows=[
    ['Medicine name',med,med,n>=3?med:'—',med,'ok'],
    ['Batch number',batch,conflict?'B201':batch,n>=3?batch:'—',batch,conflict?'mm':'ok'],
    ['MFG date',parsed.mfg_date||'Jan 2024',parsed.mfg_date||'Jan 2024',n>=3?(parsed.mfg_date||'Jan 2024'):'—',parsed.mfg_date||'Jan 2024','ok'],
    ['EXP date',parsed.exp_date||'Dec 2026',parsed.exp_date||'Dec 2026',n>=3?(parsed.exp_date||'Dec 2026'):'—',parsed.exp_date||'Dec 2026','ok'],
    ['Manufacturer',parsed.manufacturer||'Cipla Ltd',parsed.manufacturer||'Cipla Ltd',n>=3?(parsed.manufacturer||'Cipla Ltd'):'—',parsed.manufacturer||'Cipla Ltd','ok'],
    ['QR code','—','—','—','N/A','na'],
  ];
  document.getElementById('ftbody').innerHTML=frows.map(r=>`<tr>
    <td class="fn">${r[0]}</td><td class="fv">${r[1]}</td><td class="fv">${r[2]}</td>
    <td class="fv" style="color:var(--text3)">${r[3]}</td>
    <td class="fv" style="font-weight:600">${r[4]}</td>
    <td><span class="badge ${r[5]}">${r[5]==='ok'?'OK':r[5]==='mm'?'MISMATCH':'N/A'}</span></td>
  </tr>`).join('');

  const anoms=reasons.length?reasons.map((reason,index)=>({
    s:String(reason).toLowerCase().includes('high')?'h':String(reason).toLowerCase().includes('medium')?'m':'l',
    t:String(reason).replace(/^\[[^\]]+\]\s*/,''),
    d:String(reason),
  })):conflict?[
    {s:'h',t:'Batch number mismatch',d:'Images show conflicting batch numbers. This is a strong counterfeit indicator.'},
    {s:'m',t:'Geographic burst detected',d:'Suspicious distribution pattern across cities within minutes.'},
    {s:'m',t:'Packaging print anomaly',d:'Vision AI flagged a packaging anomaly on the front image.'},
    {s:'l',t:'Missing QR code',d:'No QR code present. Independent verification unavailable.'},
  ]:[
    {s:'l',t:'Moderate AI uncertainty',d:'Root pipeline did not find a critical mismatch signal.'},
    {s:'l',t:'Missing QR code',d:'QR code absent. Independent verification unavailable; rely on other signals.'},
  ];
  document.getElementById('anomList').innerHTML=anoms.map((a,i)=>`
    <div class="anom ${a.s}">
      <span class="anom-index">${String(i+1).padStart(2,'0')}</span>
      <span class="anom-sev">${a.s==='h'?'HIGH':a.s==='m'?'MEDIUM':'LOW'}</span>
      <div><div class="anom-title">${a.t}</div><div class="anom-desc">${a.d}</div></div>
    </div>`).join('');

  const di=drugInfo(med,lastScanResult&&lastScanResult.drug_info?lastScanResult.drug_info:null);
  document.getElementById('drugWrap').innerHTML=`
    <div class="drug-header">
      <div class="drug-n">${di.name}</div>
      <div class="drug-cls">${di.cls}</div>
    </div>
    <div class="drug-cols">
      <div><div class="drug-sec-hd">DISEASES / CONDITIONS</div>${di.uses.map(u=>`<div class="drug-li">${u}</div>`).join('')}</div>
      <div><div class="drug-sec-hd">AI ASSISTANT</div>${di.fx.map(e=>`<div class="drug-li">${e}</div>`).join('')}</div>
    </div>
    <div class="drug-warn"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" style="flex-shrink:0;margin-top:1px"><path d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/></svg> ${di.warn}</div>`;

  playPageMotion('result');
}

function drugInfo(n,apiDrugInfo){
  if(apiDrugInfo){
    const uses=Array.isArray(apiDrugInfo.conditions_treated)&&apiDrugInfo.conditions_treated.length
      ? apiDrugInfo.conditions_treated
      : Array.isArray(apiDrugInfo.uses)&&apiDrugInfo.uses.length
        ? apiDrugInfo.uses
        : ['Information not available','Consult a pharmacist','Check package insert'];
    const aiNotes=[];
    if(apiDrugInfo.assistant_summary) aiNotes.push(apiDrugInfo.assistant_summary);
    if(apiDrugInfo.generic_name) aiNotes.push(`Generic name: ${apiDrugInfo.generic_name}`);
    if(apiDrugInfo.therapeutic_class) aiNotes.push(`Class: ${apiDrugInfo.therapeutic_class}`);
    if(apiDrugInfo.dosage) aiNotes.push(`Dosage: ${apiDrugInfo.dosage}`);
    if(apiDrugInfo.manufacturer) aiNotes.push(`Manufacturer: ${apiDrugInfo.manufacturer}`);
    if(Array.isArray(apiDrugInfo.reference_sources)&&apiDrugInfo.reference_sources.length){
      apiDrugInfo.reference_sources.forEach(src=>aiNotes.push(`Reference: ${src}`));
    }
    const risks=Array.isArray(apiDrugInfo.risks)&&apiDrugInfo.risks.length
      ? apiDrugInfo.risks
      : [];
    const riskText=risks.length
      ? `Risks: ${risks.join(' | ')}`
      : 'Uses and side effects are informational only. Final treatment decisions should come from a qualified clinician or pharmacist.';
    if(!aiNotes.length) aiNotes.push('Medicine explanation not available in the current dataset.');
    return{name:apiDrugInfo.name||n||'Unknown Medicine',cls:apiDrugInfo.therapeutic_class||'MEDICINE PROFILE',uses,fx:aiNotes,warn:apiDrugInfo.is_fake_medicine||apiDrugInfo.is_banned?'This medicine matched a high-risk reference list. Verify the package and source before use.':riskText};
  }
  const k=n.toLowerCase();
  if(k.includes('metformin'))return{name:'Metformin',cls:'BIGUANIDE · ANTIDIABETIC',uses:['Type 2 diabetes','Gestational diabetes','Polycystic ovary syndrome (PCOS)'],fx:['AI summary: Metformin is commonly used for type 2 diabetes, gestational diabetes, and sometimes PCOS.','Reference: https://www.nhs.uk/medicines/metformin/about-metformin/'],warn:'Uses are based on NHS reference information. Final treatment advice should come from a clinician.'};
  if(k.includes('paracetamol')||k.includes('acetaminophen')||k.includes('crocin')||k.includes('calpol'))return{name:'Paracetamol / Acetaminophen',cls:'ANALGESIC · ANTIPYRETIC',uses:['Fever','Mild to moderate pain','Headache','Body pain'],fx:['AI summary: This medicine is commonly used to reduce fever and relieve mild to moderate pain.','Reference: https://medlineplus.gov/druginfo/meds/a681004.html'],warn:'Uses are based on MedlinePlus reference information. Final treatment advice should come from a clinician.'};
  if(k.includes('amoxicillin'))return{name:'Amoxicillin',cls:'ANTIBIOTIC · PENICILLIN',uses:['Chest infections','Dental abscess','Ear infections','Other bacterial infections'],fx:['AI summary: Amoxicillin is commonly used for bacterial infections such as chest infections and dental abscesses.','Reference: https://www.nhs.uk/medicines/amoxicillin/'],warn:'Uses are based on NHS reference information. Antibiotics should only be used with proper medical guidance.'};
  if(k.includes('salbutamol'))return{name:'Salbutamol',cls:'BRONCHODILATOR',uses:['Asthma','COPD','Wheezing','Breathlessness'],fx:['AI summary: Salbutamol is commonly used to relieve asthma and COPD symptoms such as wheezing and breathlessness.','Reference: https://www.nhs.uk/medicines/salbutamol-inhaler/about-salbutamol-inhalers/'],warn:'Uses are based on NHS reference information. Inhaler use should follow clinician guidance.'};
  if(k.includes('omeprazole'))return{name:'Omeprazole',cls:'PROTON PUMP INHIBITOR',uses:['Heartburn','Acid reflux / GORD','Stomach ulcers','H. pylori-related ulcer treatment'],fx:['AI summary: Omeprazole is commonly used for heartburn, acid reflux, GORD, and stomach-ulcer treatment.','Reference: https://www.nhs.uk/medicines/omeprazole/'],warn:'Uses are based on NHS reference information.'};
  if(k.includes('pantoprazole')||k.includes('pantocid'))return{name:'Pantoprazole',cls:'PROTON PUMP INHIBITOR',uses:['GERD','Esophagus healing from acid damage','High stomach acid conditions'],fx:['AI summary: Pantoprazole is commonly used for GERD and other conditions involving excess stomach acid.','Reference: https://medlineplus.gov/druginfo/meds/a601246.html'],warn:'Uses are based on MedlinePlus reference information.'};
  if(k.includes('amlodipine'))return{name:'Amlodipine',cls:'CALCIUM CHANNEL BLOCKER',uses:['High blood pressure','Angina','Coronary artery disease'],fx:['AI summary: Amlodipine is commonly used for high blood pressure and certain chest-pain and heart-vessel conditions.','Reference: https://medlineplus.gov/druginfo/meds/a692044.html'],warn:'Uses are based on MedlinePlus reference information.'};
  if(k.includes('aspirin'))return{name:'Aspirin',cls:'NSAID / ANTIPLATELET',uses:['Fever','Pain and inflammation','Heart attack prevention','Stroke prevention'],fx:['AI summary: Aspirin is commonly used for pain and fever, and in some cases to help prevent heart attacks or strokes.','Reference: https://medlineplus.gov/druginfo/meds/a682878.html'],warn:'Uses are based on MedlinePlus reference information. Aspirin is not suitable for everyone.'};
  if(k.includes('keytruda')||k.includes('pembrolizumab'))return{name:'Keytruda / Pembrolizumab',cls:'IMMUNOTHERAPY',uses:['Solid tumors','Soft tissue cancers','Blood cancers'],fx:['AI summary: Pembrolizumab is used to treat multiple cancer types by helping the immune system slow or stop cancer-cell growth.','Reference: https://medlineplus.gov/druginfo/meds/a614048.html'],warn:'Uses are based on MedlinePlus reference information and this medicine requires specialist oncology supervision.'};
  return{name:n||'Unknown Medicine',cls:'UNCLASSIFIED',uses:['Information not available','Consult a pharmacist','Check package insert'],fx:['Medicine explanation not available in the current dataset.'],warn:'Medicine not recognized. Consult a qualified pharmacist or physician before use.'};
}

function buildBatch(){
  const scans=[
    {t:'09:55',c:'Mumbai',id:'SCN-001',f:'—'},{t:'10:02',c:'Mumbai',id:'SCN-002',f:'BURST'},
    {t:'10:03',c:'Delhi',id:'SCN-003',f:'BURST'},{t:'10:03',c:'Pune',id:'SCN-004',f:'BURST'},
    {t:'10:04',c:'Mumbai',id:'SCN-005',f:'BURST'},{t:'10:04',c:'Hyderabad',id:'SCN-006',f:'GEO'},
    {t:'10:05',c:'Delhi',id:'SCN-007',f:'GEO'},{t:'11:20',c:'Pune',id:'SCN-008',f:'—'},
    {t:'13:15',c:'Mumbai',id:'SCN-009',f:'—'},{t:'14:02',c:'Hyderabad',id:'SCN-010',f:'—'},
    {t:'15:30',c:'Delhi',id:'SCN-011',f:'—'},{t:'17:44',c:'Mumbai',id:'SCN-012',f:'—'},
  ];
  document.getElementById('scanTbody').innerHTML=scans.map(s=>`<tr>
    <td class="fv" style="font-family:var(--mono);font-size:11px">${s.t}</td>
    <td class="fv">${s.c}</td>
    <td class="fn">${s.id}</td>
    <td><span class="badge ${s.f!=='—'?'mm':'ok'}">${s.f}</span></td>
  </tr>`).join('');

  const ctx=document.getElementById('tlChart').getContext('2d');
  new Chart(ctx,{type:'bar',data:{
    labels:['09:55','10:02','10:03a','10:03b','10:04a','10:04b','10:05','11:20','13:15','14:02','15:30','17:44'],
    datasets:[{label:'Scans',data:[1,1,1,1,1,1,1,1,1,1,1,1],
      backgroundColor:['#58a6ff','#ff5f57','#ff5f57','#ff5f57','#ff5f57','#ffbc42','#ffbc42','#58a6ff','#58a6ff','#58a6ff','#58a6ff','#58a6ff'],
      borderRadius:4,borderSkipped:false}]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{label:v=>`${v.raw} scan(s)`}}},
      scales:{
        x:{grid:{color:'rgba(79,158,255,0.04)'},ticks:{color:'#8b93ab',font:{size:9,family:'JetBrains Mono'},maxRotation:45,autoSkip:false}},
        y:{grid:{color:'rgba(79,158,255,0.04)'},ticks:{color:'#8b93ab',font:{size:9},stepSize:1},min:0,max:2}}}});

  document.querySelectorAll('#geoList .geo-bar-fill').forEach((bar,i)=>{
    const target=bar.style.width;
    bar.style.width='0%';
    bar.style.transition='width 0.8s cubic-bezier(.2,.7,.2,1)';
    setTimeout(()=>{bar.style.width=target},90+i*70);
  });

  drawNet();
  playPageMotion('batch');
}

function drawNet(){
  const c=document.getElementById('netC');
  const dpr=devicePixelRatio||1;
  c.width=(c.offsetWidth||700)*dpr;c.height=200*dpr;
  const ctx=c.getContext('2d');ctx.scale(dpr,dpr);
  const W=c.offsetWidth||700,H=200;
  const nodes=[
    {x:W/2,y:H/2,r:28,col:'#ffbc42',lbl:'B202',sub:'batch'},
    {x:W*.15,y:H*.28,r:20,col:'#ff5f57',lbl:'Mumbai',sub:'5'},
    {x:W*.82,y:H*.22,r:16,col:'#ffbc42',lbl:'Delhi',sub:'3'},
    {x:W*.18,y:H*.78,r:14,col:'#4f9eff',lbl:'Pune',sub:'2'},
    {x:W*.84,y:H*.76,r:14,col:'#58a6ff',lbl:'Hyderabad',sub:'2'},
  ];
  nodes.slice(1).forEach(n=>{
    ctx.beginPath();ctx.moveTo(nodes[0].x,nodes[0].y);ctx.lineTo(n.x,n.y);
    ctx.strokeStyle=n.col+'30';ctx.lineWidth=n.col==='#ff5f57'?2:1;
    ctx.setLineDash(n.col==='#ff5f57'?[]:[4,4]);ctx.stroke();ctx.setLineDash([]);
  });
  nodes.forEach(n=>{
    ctx.beginPath();ctx.arc(n.x,n.y,n.r,0,Math.PI*2);
    ctx.fillStyle=n.col+'18';ctx.fill();
    ctx.strokeStyle=n.col;ctx.lineWidth=1.5;ctx.stroke();
    ctx.fillStyle=n.col;ctx.textAlign='center';ctx.textBaseline='middle';
    ctx.font=`600 10px Outfit,system-ui,sans-serif`;ctx.fillText(n.lbl,n.x,n.y-5);
    ctx.font=`9px JetBrains Mono,monospace`;ctx.fillStyle=n.col+'88';ctx.fillText(n.sub,n.x,n.y+7);
  });
}

updateBtn();
playPageMotion('auth');

// --- predictor hookup: when user types a medicine name, query backend predictor and update drug panel
let predictTimer=null;
async function fetchPredict(name){
  if(!name||name.trim().length<2) return null;
  try{
    const res=await fetch(`${API_BASE}/predict?name=`+encodeURIComponent(name.trim()));
    if(!res.ok) return null;
    const data=await res.json();
    return data;
  }catch(e){
    return null;
  }
}

function applyPredictToPanel(pred){
  if(!pred||!pred.name) return;
  const apiDrugInfo={
    name: pred.name,
    therapeutic_class: pred.diseaseArea?pred.diseaseArea.join(' | '):undefined,
    uses: pred.diseaseArea&&pred.diseaseArea.length?pred.diseaseArea:pred.usedFor?[pred.usedFor]:[],
    assistant_summary: pred.usedFor||'',
    risks: pred.caution? [pred.caution] : [],
    is_fake_medicine: false,
    generic_name: pred.aliases&&pred.aliases.length?pred.aliases[0]:undefined,
  };
  const di=drugInfo(pred.name, apiDrugInfo);
  document.getElementById('drugWrap').innerHTML=`
    <div class="drug-header">
      <div class="drug-n">${di.name}</div>
      <div class="drug-cls">${di.cls}</div>
    </div>
    <div class="drug-cols">
      <div><div class="drug-sec-hd">DISEASES / CONDITIONS</div>${di.uses.map(u=>`<div class="drug-li">${u}</div>`).join('')}</div>
      <div><div class="drug-sec-hd">AI ASSISTANT</div>${di.fx.map(e=>`<div class="drug-li">${e}</div>`).join('')}</div>
    </div>
    <div class="drug-warn"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" style="flex-shrink:0;margin-top:1px"><path d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/></svg> ${di.warn}</div>`;
}

const mnameInput=document.getElementById('mname');
if(mnameInput){
  mnameInput.addEventListener('input', (e)=>{
    clearTimeout(predictTimer);
    const v=e.target.value;
    predictTimer=setTimeout(async()=>{
      const pred=await fetchPredict(v);
      if(pred) applyPredictToPanel(pred);
    }, 450);
  });
  mnameInput.addEventListener('blur', async(e)=>{
    clearTimeout(predictTimer);
    const pred=await fetchPredict(e.target.value);
    if(pred) applyPredictToPanel(pred);
  });
}

document.addEventListener('pointermove',e=>{
  document.documentElement.style.setProperty('--spot-x',e.clientX+'px');
  document.documentElement.style.setProperty('--spot-y',e.clientY+'px');
},{passive:true});

window.addEventListener('scroll',()=>{
  document.querySelector('.nav').classList.toggle('scrolled',window.scrollY>8);
},{passive:true});

document.querySelectorAll('.tab,.btn-primary,.auth-submit,.auth-tab,.auth-oauth button,.icon-btn').forEach(btn=>{
  btn.addEventListener('pointerdown',e=>pressFeedback(btn,e));
});

document.querySelectorAll('.slot,.sig,.feat,.stat,.chart-card,.result-hero,.drug-wrap,.auth-shell,.account-card,.setting-card').forEach(el=>{
  el.classList.add('micro-lift');
});