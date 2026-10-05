const $ = s => document.querySelector(s);
const view = $('#view');
let currentView = 'dashboard';
let bankPage = 1;
let generatedPage = 1;
let reviewPage = 1;
let currentQuestion = null;
let currentAttempt = null;
let aiEnabled = false;
let examState = null;
let examTimer = null;
let todayPlan = null;
const labels = {review:'복습',weak:'취약 분야',new:'새 문제',generated:'AI 문제',practice:'다시 연습'};

function esc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
async function api(path, options={}) {
  const response = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : '요청을 처리하지 못했습니다.');
  return data;
}
function notice(message) { const n=$('#notice'); n.textContent=message; n.classList.add('show'); setTimeout(()=>n.classList.remove('show'),5000); }
function fail(error) { notice(error.message || String(error)); }
function aiProgress(message) { return `<span class="ai-progress" role="status"><span class="ai-spinner" aria-hidden="true"></span>${esc(message)}</span>`; }
function setView(name) {
  if(examTimer){clearInterval(examTimer);examTimer=null}
  examState=null;
  currentView=name;
  const title={dashboard:'대시보드',today:'오늘의 학습',bank:'문제은행',generated:'AI 생성 문제',exams:'회차별 시험',wrong:'오답노트',review:'복습 문제',theory:'이론 노트'}[name];
  $('#page-title').textContent=title;
  document.querySelectorAll('#nav button').forEach(b=>b.classList.toggle('active',b.dataset.view===name));
  ({dashboard,today,bank,generated,exams,wrong,review,theory})[name]().catch(fail);
}
function rowHtml(q, generated=false) {
  const name=generated ? 'AI 생성 문제' : `${q.year}년 ${q.round}회 · ${q.number}번`;
  const title=q.preview || q.question_text || `${q.category} 문제`;
  return `<div class="row" data-open="${generated?'g':'q'}:${q.id}"><div class="num">${generated?'AI':esc(q.number)}</div><div class="row-main"><div class="row-title">${esc(title)}</div><div class="row-meta">${esc(name)} · ${esc(q.category||'기타')} / ${esc(q.subcategory||'기본 개념')}</div></div><span class="pill ${q.completed?'green':''}">${q.completed?'완료':esc(q.reason ? labels[q.reason] : q.category||'연습')}</span></div>`;
}
async function dashboard() {
  const [data,status,plan]=await Promise.all([api('/api/dashboard'),api('/api/status'),api('/api/study/today')]);
  const rate=data.attempts ? Math.round(data.correct/data.attempts*100) : 0;
  view.innerHTML=`<div class="grid stats">
    <div class="card"><div class="stat-label">누적 풀이</div><div class="stat-value">${data.attempts}</div><div class="stat-foot">완료된 채점</div></div>
    <div class="card"><div class="stat-label">정답률</div><div class="stat-value">${rate}%</div><div class="stat-foot">${data.correct}문제 정답</div></div>
    <div class="card"><div class="stat-label">학습 데이터</div><div class="stat-value">${status.questions}</div><div class="stat-foot">${status.rounds}개 회차</div></div>
    <div class="card"><div class="stat-label">권장 난이도</div><div class="stat-value">Lv.${data.difficulty}</div><div class="stat-foot">최근 5문제 기준</div></div></div>
    <div class="section-head"><div><h2>오늘의 학습</h2><p>전에 푼 문제 3~5개를 복습하고 나머지는 새로운 기출문제를 풉니다.</p></div></div>
    <div class="hero"><div><small>YOUR DAILY PLAN</small><h2>오늘은 ${plan.items.length}문제를 준비했어요</h2><p>풀이 결과에 따라 다음 복습 날짜가 자동으로 조정됩니다.</p></div><button class="button light" data-view-go="today">학습 시작 →</button></div>
    <div class="grid split"><div><div class="section-head"><h2>취약 개념</h2></div><div class="card">${data.skills.length ? data.skills.slice(0,6).map(s=>`<div class="skill"><div class="skill-name">${esc(s.subcategory)}</div><div class="track"><i style="width:${Math.round(s.score*100)}%"></i></div><strong>${Math.round(s.score*100)}</strong></div>`).join('') : '<div class="note">문제를 풀면 분야별 숙련도가 표시됩니다.</div>'}</div></div>
    <div><div class="section-head"><h2>학습 흐름</h2></div><div class="card"><div class="note">문제 풀이 → 채점 → 오답 분석 → 개념 복습 → 유사 문제 → 다음 복습 예약</div><div class="actions"><button class="button ghost sm" data-view-go="bank">문제 찾기</button><button class="button ghost sm" data-view-go="exams">회차별 시험</button><button class="button ghost sm" data-view-go="wrong">오답 보기</button></div></div></div></div>`;
}
async function today() {
  const plan=await api('/api/study/today');
  if(currentView!=='today') return;
  todayPlan=plan;
  renderToday();
}
function renderToday() {
  const plan=todayPlan;
  const counts={};plan.items.forEach(q=>counts[q.category]=(counts[q.category]||0)+1);
  const done=plan.items.filter(q=>q.completed).length;
  const reviews=plan.items.filter(q=>q.reason==='review').length;
  view.innerHTML=`<div class="section-head daily-heading"><div><h2>맞춤 학습 계획</h2><p>현재 권장 난이도 Lv.${plan.difficulty} · ${done}/${plan.items.length} 완료 · 복습 ${reviews}개 / 새 기출 ${plan.items.length-reviews}개</p><p>${plan.items.length<20?'아직 풀지 않은 기출문제가 부족해 준비 가능한 문제만 표시합니다.':'새 문제로 바꿔도 기존 풀이 기록과 오답노트는 유지됩니다.'}</p></div><button id="refresh-today" class="button ghost">↻ 오늘의 문제 20개 생성</button></div><div class="category-summary">${Object.entries(counts).map(([category,count])=>`<span class="pill gray">${esc(category)} ${count}</span>`).join('')}</div>
  <div class="list">${plan.items.length ? plan.items.map(q=>rowHtml(q,q.generated)).join('') : '<div class="empty">학습 문제가 없습니다.</div>'}</div>`;
  $('#refresh-today').onclick=()=>refreshToday().catch(fail);
}
async function refreshToday() {
  const button=$('#refresh-today');
  if(button.disabled) return;
  button.disabled=true;
  button.textContent='문제를 바꾸고 있습니다…';
  try {
    const plan=await api('/api/study/today/refresh',{method:'POST'});
    if(currentView!=='today') return;
    todayPlan=plan;
    renderToday();
    notice(`${plan.items.length}문제로 오늘의 학습을 새로 준비했습니다.`);
  } finally {
    button.disabled=false;
    button.textContent='↻ 오늘의 문제 20개 생성';
  }
}
async function bank() {
  view.innerHTML=`<div class="toolbar"><input id="search" placeholder="문제 내용 검색"><select id="year"><option value="">전체 연도</option>${[2026,2025,2024,2023,2022,2021,2020].map(y=>`<option>${y}</option>`).join('')}</select><select id="round"><option value="">전체 회차</option><option>1</option><option>2</option><option>3</option><option>4</option></select><select id="category"><option value="">전체 분야</option>${['프로그래밍','데이터베이스','보안','네트워크','소프트웨어 공학','기타'].map(x=>`<option>${x}</option>`).join('')}</select><button id="search-btn" class="button ghost">검색</button><button id="expected-btn" class="button">AI 예상문제</button><div id="expected-status"></div></div><div id="bank-results"></div><div id="pages" class="page-controls"></div>`;
  $('#search-btn').onclick=()=>{bankPage=1;loadBank().catch(fail)};
  $('#search').onkeydown=e=>{if(e.key==='Enter'){$('#search-btn').click()}};
  $('#expected-btn').onclick=()=>generateExpected().catch(fail);
  await loadBank();
}
async function loadBank() {
  const args=new URLSearchParams({page:bankPage,size:20});
  for(const id of ['year','round','category']) if($('#'+id).value) args.set(id,$('#'+id).value);
  if($('#search').value.trim()) args.set('search',$('#search').value.trim());
  const data=await api('/api/questions?'+args);
  $('#bank-results').innerHTML=`<div class="section-head"><h2>${data.total}개 문제</h2></div><div class="list">${data.items.map(q=>rowHtml(q)).join('') || '<div class="empty">조건에 맞는 문제가 없습니다.</div>'}</div>`;
  $('#pages').innerHTML=`<button class="button muted sm" id="prev" ${bankPage===1?'disabled':''}>이전</button><span>${bankPage} / ${Math.max(1,Math.ceil(data.total/20))}</span><button class="button muted sm" id="next" ${bankPage*20>=data.total?'disabled':''}>다음</button>`;
  $('#prev').onclick=()=>{bankPage--;loadBank().catch(fail)}; $('#next').onclick=()=>{bankPage++;loadBank().catch(fail)};
}
async function generated() {
  const data=await api(`/api/generated?page=${generatedPage}&size=20`);
  view.innerHTML=`<div class="section-head"><div><h2>AI 생성 문제 ${data.total}개</h2><p>생성 후 검증을 통과한 문제입니다. 문제를 열어 풀고 답을 확인하세요.</p></div></div><div class="list">${data.items.map(q=>rowHtml(q,true)).join('') || '<div class="empty">아직 검증을 통과한 AI 생성 문제가 없습니다. 문제은행에서 AI 예상문제를 만들 수 있습니다.</div>'}</div><div id="generated-pages" class="page-controls"></div>`;
  $('#generated-pages').innerHTML=`<button class="button muted sm" id="generated-prev" ${generatedPage===1?'disabled':''}>이전</button><span>${generatedPage} / ${Math.max(1,Math.ceil(data.total/20))}</span><button class="button muted sm" id="generated-next" ${generatedPage*20>=data.total?'disabled':''}>다음</button>`;
  $('#generated-prev').onclick=()=>{generatedPage--;generated().catch(fail)};
  $('#generated-next').onclick=()=>{generatedPage++;generated().catch(fail)};
}
async function exams() {
  const data=await api('/api/exams');
  view.innerHTML=`<div class="section-head"><div><h2>연도·회차 선택</h2><p>선택한 회차의 20문항을 순서대로 풀고 한 번에 제출합니다.</p></div></div><div class="grid exam-grid">${data.items.map(item=>`<button class="card exam-card" data-exam="${item.year}:${item.round}"><small>${item.year}년</small><strong>${item.round}회 실기</strong><span>${item.question_count}문항 · 시험 시작 →</span></button>`).join('')}</div>`;
}
function examClock() {
  if(!examState) return;
  const seconds=Math.floor((Date.now()-examState.startedAt)/1000);
  const clock=$('#exam-time');
  if(clock) clock.textContent=`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;
}
async function examSession(year,round) {
  const data=await api(`/api/exams/${year}/${round}`);
  examState={year,round,items:data.items,answers:{},index:0,startedAt:Date.now(),results:null};
  $('#page-title').textContent=`${year}년 ${round}회 시험`;
  renderExamQuestion();
  examTimer=setInterval(examClock,1000);
}
function renderExamQuestion() {
  const s=examState,q=s.items[s.index];
  const answered=s.items.filter(item=>(s.answers[item.id]||'').trim()).length;
  view.innerHTML=`<div class="exam-top"><div><span class="eyebrow">EXAM MODE</span><h2>${s.year}년 ${s.round}회 · ${s.index+1}/20</h2><p>답안을 모두 작성한 뒤 제출하면 결과를 확인할 수 있습니다.</p></div><div class="exam-clock"><small>경과 시간</small><strong id="exam-time">00:00</strong></div></div>
  <div class="exam-pager">${s.items.map((item,i)=>`<button data-exam-index="${i}" class="${i===s.index?'active':''} ${(s.answers[item.id]||'').trim()?'answered':''}">${item.number}</button>`).join('')}</div>
  <div class="card exam-question"><div class="question-meta"><span class="pill">${esc(q.category)} / ${esc(q.subcategory)}</span><span>${q.number}번 문제</span></div><div class="question-text">${esc(q.question_text)}</div>${q.local_images.map(url=>`<img class="question-image" src="${esc(url)}" alt="문제 첨부 이미지">`).join('')}<textarea id="exam-answer" placeholder="답안을 입력하세요">${esc(s.answers[q.id]||'')}</textarea></div>
  <div class="exam-footer"><button class="button muted" data-exam-prev ${s.index===0?'disabled':''}>← 이전</button><span>${answered}/20 답안 작성</span><button class="button muted" data-exam-next ${s.index===19?'disabled':''}>다음 →</button><button class="button" data-exam-submit>20문제 제출</button></div>`;
  examClock();
}
async function submitExam() {
  if(!examState || examState.results) return;
  const button=$('[data-exam-submit]');button.disabled=true;button.textContent='채점 중…';
  try {
    const seconds=Math.floor((Date.now()-examState.startedAt)/1000);
    const answers=examState.items.map(item=>({question_id:item.id,user_answer:examState.answers[item.id]||''}));
    const data=await api(`/api/exams/${examState.year}/${examState.round}/submit`,{method:'POST',body:JSON.stringify({answers,elapsed_seconds:seconds})});
    if(examTimer){clearInterval(examTimer);examTimer=null}
    examState.results=data.results;
    renderExamResults();
  } catch(error){button.disabled=false;button.textContent='20문제 제출';throw error}
}
function renderExamResults() {
  const s=examState,results=s.results;
  const correct=results.filter(r=>r.is_correct===true).length;
  const pending=results.filter(r=>r.is_correct===null).length;
  view.innerHTML=`<div class="hero"><div><small>EXAM COMPLETE</small><h2>${s.year}년 ${s.round}회 결과</h2><p>정답 ${correct}/20 · 직접 판정 ${pending}문항${pending?' (판정 후 최종 점수 확인)':''}</p></div><button class="button light" data-view-go="exams">다른 회차 선택</button></div><div class="section-head"><h2>문항별 결과</h2></div><div class="list">${results.map(r=>`<div class="card exam-result"><div class="exam-result-head"><strong>${r.number}번</strong><span class="pill ${r.is_correct===true?'green':r.is_correct===false?'red':'gray'}">${r.is_correct===true?'정답':r.is_correct===false?'오답':'직접 판정'}</span></div><div class="note">내 답안: ${esc(r.user_answer||'(미작성)')}</div><div class="exam-answer-key">게시된 답안: ${esc(r.correct_answer)}</div>${r.is_correct===null?`<div class="actions"><button class="button ghost sm" data-exam-review="${r.attempt_id}:true">맞았어요</button><button class="button danger sm" data-exam-review="${r.attempt_id}:false">틀렸어요</button></div>`:''}</div>`).join('')}</div>`;
}
async function reviewExamAttempt(attemptId,correct) {
  await api(`/api/attempts/${attemptId}/review`,{method:'POST',body:JSON.stringify({is_correct:correct})});
  const result=examState.results.find(item=>item.attempt_id===attemptId);
  result.is_correct=correct;
  renderExamResults();
}
let wrongFilter = '전체';
let theoryFilter = '전체';

function renderTheoryCardHtml(t, canDelete = true) {
  const isAi = t.source === 'ai_wrong_analysis';
  return `<div class="card theory-card" data-theory-id="${t.id}">
    <div class="theory-card-head">
      <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap">
        <small style="color:var(--blue);font-weight:700">${esc(t.category)} / ${esc(t.subcategory)}</small>
        ${isAi ? '<span class="pill purple">✦ AI 오답 암기노트</span>' : '<span class="pill gray">기본 개념</span>'}
      </div>
      ${canDelete && isAi ? `<button class="btn-del-theory" data-del-theory="${t.id}" title="이론 삭제" aria-label="이론 삭제">×</button>` : ''}
    </div>
    <h3>${esc(t.title || t.subcategory)}</h3>
    <p class="theory-summary">${esc(t.summary || '')}</p>
    ${t.memorization_tip ? `<div class="theory-box memorization-box">
      <div class="theory-box-title">🌟 쉽게 외우는 암기 비법 & 꿀팁</div>
      <div class="theory-box-content">${esc(t.memorization_tip)}</div>
    </div>` : ''}
    ${t.common_mistakes ? `<div class="theory-box mistake-box">
      <div class="theory-box-title">⚠️ 시험 함정 & 자주 하는 실수</div>
      <div class="theory-box-content">${esc(t.common_mistakes)}</div>
    </div>` : ''}
    ${t.example ? `<div class="theory-box example-box">
      <div class="theory-box-title">💡 핵심 예시 & 풀이 패턴</div>
      <pre>${esc(t.example)}</pre>
    </div>` : ''}
    ${t.created_at ? `<div class="theory-foot"><small>${esc((t.created_at || '').slice(0, 10))}</small></div>` : ''}
  </div>`;
}

async function wrong() {
  const data = await api('/api/wrong-answers');
  if (currentView !== 'wrong') return;
  const items = data.items || [];
  const categories = ['전체', ...new Set(items.map(item => item.category).filter(Boolean))];
  if (!categories.includes(wrongFilter)) wrongFilter = '전체';

  const filteredItems = wrongFilter === '전체' ? items : items.filter(i => i.category === wrongFilter);

  view.innerHTML = `
    <div class="section-head">
      <div>
        <h2>오답노트 (${items.length}개)</h2>
        <p>틀린 문제들을 복습하고, AI 분석으로 유형별 맞춤 이론과 쉬운 암기 비법을 받아보세요.</p>
      </div>
      <div class="actions">
        <button id="btn-open-wrong-ai" class="button" ${items.length ? '' : 'disabled'}>
          <span style="margin-right:6px">✦</span>AI 분석 (유형별 선택)
        </button>
      </div>
    </div>
    ${items.length ? `
      <div class="filter-pills" id="wrong-filter-bar">
        ${categories.map(cat => {
          const count = cat === '전체' ? items.length : items.filter(i => i.category === cat).length;
          return `<button class="filter-pill ${cat === wrongFilter ? 'active' : ''}" data-wrong-filter="${esc(cat)}">${esc(cat)} <small>(${count})</small></button>`;
        }).join('')}
      </div>
    ` : ''}
    <div class="list" id="wrong-list-container">
      ${filteredItems.length ? filteredItems.map(q => `
        <div class="row" data-open="${q.question_id ? 'q' : 'g'}:${q.question_id || q.generated_question_id}" data-attempt-id="${q.last_attempt_id || ''}">
          <div class="num">${q.number || 'AI'}</div>
          <div class="row-main">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
              <span class="pill sm">${esc(q.category)} / ${esc(q.subcategory)}</span>
              ${q.year ? `<small style="color:var(--muted)">${q.year}년 ${q.round}회 ${q.number}번</small>` : ''}
            </div>
            <div class="row-title">${esc(q.question_text || 'AI 생성 문제')}</div>
            <div class="row-meta">오답 <strong>${q.wrong_count}회</strong> · 다음 복습 ${esc((q.next_review_at || '').slice(0, 10))}${q.wrong_reason ? ' · ' + esc(q.wrong_reason) : ''}</div>
          </div>
          <div class="row-actions" style="display:flex;align-items:center;gap:8px;flex-shrink:0">
            <button type="button" class="button ghost sm" data-single-ai="${q.question_id ? 'q' : 'g'}:${q.question_id || q.generated_question_id}" data-attempt="${q.last_attempt_id || ''}" title="이 문제 AI 상세 분석">✦ AI 분석</button>
            <span class="pill red">다시 풀기</span>
          </div>
        </div>
      `).join('') : '<div class="empty">해당 유형에 기록된 오답이 없습니다.</div>'}
    </div>
  `;

  const btnOpenAi = $('#btn-open-wrong-ai');
  if (btnOpenAi) {
    btnOpenAi.onclick = () => openWrongAnalysisModal(items);
  }

  const filterBar = $('#wrong-filter-bar');
  if (filterBar) {
    filterBar.querySelectorAll('[data-wrong-filter]').forEach(btn => {
      btn.onclick = () => {
        wrongFilter = btn.dataset.wrongFilter;
        wrong().catch(fail);
      };
    });
  }
}

function openWrongAnalysisModal(items) {
  if (!items || items.length === 0) {
    notice('분석할 오답 문제가 없습니다.');
    return;
  }
  const groupMap = new Map();
  items.forEach(q => {
    const cat = q.category || '기타';
    const sub = q.subcategory || '기본 개념';
    const key = `${cat}:::${sub}`;
    if (!groupMap.has(key)) {
      groupMap.set(key, { category: cat, subcategory: sub, questions: [] });
    }
    groupMap.get(key).questions.push(q);
  });
  const groups = Array.from(groupMap.values());

  const modalBody = $('#modal-body');
  modalBody.innerHTML = `
    <div class="analysis-modal-content">
      <div class="modal-header-section">
        <div class="pill purple" style="margin-bottom:8px">✦ AI 오답 정복 가이드</div>
        <h2 style="margin:0 0 8px">오답 유형별 AI 분석 & 암기자료 생성</h2>
        <p class="note" style="margin:0">
          틀린 문제 유형을 선택하면, AI가 오답 원인을 분석하여 <strong>핵심 이론 요약</strong>과 <strong>쉽게 외울 수 있는 암기 비법</strong>을 제공합니다.<br>
          생성된 이론은 <strong>[이론 노트]</strong>에 자동 저장되어 언제든 다시 학습할 수 있습니다.
        </p>
      </div>

      <div class="analysis-selection-bar">
        <div class="selection-info">
          선택된 유형: <strong id="sel-type-count" style="color:var(--blue)">${groups.length}</strong>개 (총 <strong id="sel-q-count">${items.length}</strong>문제)
        </div>
        <div class="actions" style="margin:0">
          <button type="button" class="button ghost sm" id="btn-sel-all">전체 선택</button>
          <button type="button" class="button muted sm" id="btn-desel-all">선택 해제</button>
        </div>
      </div>

      <div class="analysis-type-list" id="analysis-type-list">
        ${groups.map((g, idx) => `
          <div class="analysis-type-card selected" data-idx="${idx}" id="type-card-${idx}">
            <label class="analysis-type-label">
              <input type="checkbox" class="type-check" data-idx="${idx}" checked>
              <div class="analysis-type-header">
                <strong>${esc(g.category)} ❯ ${esc(g.subcategory)}</strong>
                <span class="pill red">${g.questions.length}문제 오답</span>
              </div>
            </label>
            <div class="analysis-type-preview">
              <div class="preview-snippet">
                대표 문제: ${esc(g.questions[0].question_text.slice(0, 85))}...
              </div>
              <button type="button" class="link-button sm toggle-q-list" data-toggle-list="${idx}">
                포함된 오답 문제 보기 (${g.questions.length}개) ▾
              </button>
              <div class="questions-accordion hidden" id="q-list-${idx}">
                ${g.questions.map(q => `
                  <div class="mini-q-item">
                    <div class="mini-q-title">▪ ${esc(q.question_text.slice(0, 110))}...</div>
                    ${q.wrong_reason ? `<div class="mini-q-reason">오답 원인: ${esc(q.wrong_reason)}</div>` : ''}
                  </div>
                `).join('')}
              </div>
            </div>
          </div>
        `).join('')}
      </div>

      <div class="modal-footer-actions">
        <button type="button" class="button" id="btn-start-ai-analysis" style="flex:1">
          <span style="margin-right:6px">✦</span>선택한 유형 AI 분석 시작 (${groups.length}개)
        </button>
        <button type="button" class="button muted" data-close>취소</button>
      </div>
    </div>
  `;

  $('#modal').classList.remove('hidden');
  $('#modal').setAttribute('aria-hidden', 'false');
  $('.modal-card').scrollTop = 0;

  function updateSelectionCounts() {
    const checkedBoxes = Array.from(modalBody.querySelectorAll('.type-check:checked'));
    const checkedCount = checkedBoxes.length;
    let totalQ = 0;
    checkedBoxes.forEach(cb => {
      const idx = Number(cb.dataset.idx);
      totalQ += groups[idx].questions.length;
    });
    $('#sel-type-count').textContent = checkedCount;
    $('#sel-q-count').textContent = totalQ;
    const runBtn = $('#btn-start-ai-analysis');
    runBtn.disabled = checkedCount === 0;
    runBtn.innerHTML = `<span style="margin-right:6px">✦</span>선택한 유형 AI 분석 시작 (${checkedCount}개)`;

    groups.forEach((_, idx) => {
      const card = $(`#type-card-${idx}`);
      const isChecked = card.querySelector('.type-check').checked;
      card.classList.toggle('selected', isChecked);
    });
  }

  modalBody.querySelectorAll('.type-check').forEach(cb => {
    cb.onchange = updateSelectionCounts;
  });

  modalBody.querySelectorAll('.toggle-q-list').forEach(btn => {
    btn.onclick = () => {
      const idx = btn.dataset.toggleList;
      const listEl = $(`#q-list-${idx}`);
      const isHidden = listEl.classList.toggle('hidden');
      btn.textContent = isHidden ? `포함된 오답 문제 보기 (${groups[idx].questions.length}개) ▾` : `문제 목록 접기 (${groups[idx].questions.length}개) ▴`;
    };
  });

  $('#btn-sel-all').onclick = () => {
    modalBody.querySelectorAll('.type-check').forEach(cb => { cb.checked = true; });
    updateSelectionCounts();
  };

  $('#btn-desel-all').onclick = () => {
    modalBody.querySelectorAll('.type-check').forEach(cb => { cb.checked = false; });
    updateSelectionCounts();
  };

  $('#btn-start-ai-analysis').onclick = async () => {
    const checkedBoxes = Array.from(modalBody.querySelectorAll('.type-check:checked'));
    if (checkedBoxes.length === 0) {
      notice('분석할 유형을 1개 이상 선택해 주세요.');
      return;
    }
    const selectedGroups = checkedBoxes.map(cb => groups[Number(cb.dataset.idx)]);
    const selectedTypes = selectedGroups.map(g => ({ category: g.category, subcategory: g.subcategory }));
    const selectedWrongIds = selectedGroups.flatMap(g => g.questions.map(q => q.id));

    modalBody.innerHTML = `
      <div class="ai-loading-box">
        <div class="ai-loading-spinner">✦</div>
        <h3>AI가 선택한 오답 유형을 분석하고 있습니다…</h3>
        <p>선택하신 <strong>${selectedGroups.length}개 유형</strong>의 틀린 문제와 오답 원인을 분석하여<br>
        <strong>핵심 이론 요약</strong>과 <strong>쉽게 외울 수 있는 암기 비법 & 꿀팁</strong>을 작성 중입니다.</p>
        <div class="loading-subtext">💡 분석이 완료되면 [이론 노트]에 영구 저장됩니다. (약 5~15초 소요)</div>
      </div>
    `;

    try {
      const res = await api('/api/wrong-answers/analyze', {
        method: 'POST',
        body: JSON.stringify({ types: selectedTypes, wrong_ids: selectedWrongIds })
      });

      modalBody.innerHTML = `
        <div class="analysis-result-view">
          <div class="success-callout">
            <div class="success-callout-icon">🎉</div>
            <div>
              <h3>AI 분석 완료! ${res.items.length}개의 맞춤 이론 및 암기자료 생성</h3>
              <p>선택하신 유형의 핵심 이론과 암기 비법이 <strong>[이론 노트]</strong>에 자동 저장되었습니다.</p>
            </div>
          </div>
          <div class="actions" style="margin:16px 0;justify-content:space-between">
            <button type="button" class="button" id="btn-goto-theory-view">
              이론 노트에서 전체 보기 →
            </button>
            <button type="button" class="button muted" data-close>닫기</button>
          </div>
          <div class="generated-cards-list">
            ${res.items.map(t => renderTheoryCardHtml(t, false)).join('')}
          </div>
        </div>
      `;

      $('#btn-goto-theory-view').onclick = () => {
        closeModal();
        setView('theory');
      };
    } catch (err) {
      modalBody.innerHTML = `
        <div class="analysis-modal-content">
          <div class="result" style="background:#fff0f0;color:#9b2c2c">
            <strong>AI 분석 중 오류가 발생했습니다.</strong>
            <p>${esc(err.message)}</p>
          </div>
          <div class="actions">
            <button type="button" class="button" onclick="openWrongAnalysisModal(items)">다시 시도</button>
            <button type="button" class="button muted" data-close>닫기</button>
          </div>
        </div>
      `;
    }
  };
}

async function review() {
  const data = await api(`/api/review-questions?page=${reviewPage}&size=20`);
  if (currentView !== 'review') return;
  view.innerHTML = `<div class="section-head"><div><h2>복습 문제 ${data.total}개</h2><p>전에 풀었던 문제를 모았습니다. 문제를 열어 다시 풀 수 있습니다.</p></div></div><div class="list">${data.items.map(q => rowHtml({ ...q, reason: 'review' }, Boolean(q.generated))).join('') || '<div class="empty">아직 풀었던 문제가 없습니다.</div>'}</div><div id="review-pages" class="page-controls"></div>`;
  $('#review-pages').innerHTML = `<button class="button muted sm" id="review-prev" ${reviewPage === 1 ? 'disabled' : ''}>이전</button><span>${reviewPage} / ${Math.max(1, Math.ceil(data.total / 20))}</span><button class="button muted sm" id="review-next" ${reviewPage * 20 >= data.total ? 'disabled' : ''}>다음</button>`;
  $('#review-prev').onclick = () => { reviewPage--; review().catch(fail); };
  $('#review-next').onclick = () => { reviewPage++; review().catch(fail); };
}

async function theory() {
  const data = await api('/api/theory');
  if (currentView !== 'theory') return;
  const items = data.items || [];

  const aiItems = items.filter(t => t.source === 'ai_wrong_analysis');
  const localItems = items.filter(t => t.source !== 'ai_wrong_analysis');

  const categories = ['전체', '✦ AI 오답 암기노트', '기본 개념', ...new Set(items.map(t => t.category).filter(Boolean))];
  if (!categories.includes(theoryFilter)) theoryFilter = '전체';

  let filtered = items;
  if (theoryFilter === '✦ AI 오답 암기노트') {
    filtered = aiItems;
  } else if (theoryFilter === '기본 개념') {
    filtered = localItems;
  } else if (theoryFilter !== '전체') {
    filtered = items.filter(t => t.category === theoryFilter);
  }

  view.innerHTML = `
    <div class="section-head">
      <div>
        <h2>이론 노트 (${items.length}개)</h2>
        <p>오답 분석으로 얻은 맞춤형 암기 비법과 핵심 개념 카드입니다.</p>
      </div>
      <div class="actions">
        <button class="button ghost sm" data-view-go="wrong">
          <span style="margin-right:4px">↺</span>오답노트에서 AI 분석하기
        </button>
      </div>
    </div>

    ${aiItems.length > 0 ? `
      <div class="theory-cta-banner">
        <div>
          <p>✦ <strong>AI 오답 맞춤 암기노트 ${aiItems.length}개</strong>가 저장되어 있습니다. 취약 유형의 핵심 암기 비법을 반복 복습하세요!</p>
        </div>
        <button class="button sm light" data-view-go="wrong">새 오답 분석하기</button>
      </div>
    ` : `
      <div class="theory-cta-banner">
        <div>
          <p>💡 <strong>오답노트에서 [AI 분석]을 실행</strong>하면, 내가 틀린 문제 유형에 꼭 맞춘 핵심 이론과 쉬운 암기 비법이 여기에 자동으로 누적 저장됩니다.</p>
        </div>
        <button class="button sm" data-view-go="wrong">오답 분석하러 가기 →</button>
      </div>
    `}

    <div class="filter-pills" id="theory-filter-bar">
      ${categories.map(cat => {
        let count = items.length;
        if (cat === '✦ AI 오답 암기노트') count = aiItems.length;
        else if (cat === '기본 개념') count = localItems.length;
        else if (cat !== '전체') count = items.filter(t => t.category === cat).length;
        return `<button class="filter-pill ${cat === theoryFilter ? 'active' : ''}" data-theory-filter="${esc(cat)}">${esc(cat)} <small>(${count})</small></button>`;
      }).join('')}
    </div>

    <div class="grid split" id="theory-cards-grid">
      ${filtered.length ? filtered.map(t => renderTheoryCardHtml(t, true)).join('') : '<div class="empty">해당 필터에 등록된 이론이 없습니다.</div>'}
    </div>
  `;

  const filterBar = $('#theory-filter-bar');
  if (filterBar) {
    filterBar.querySelectorAll('[data-theory-filter]').forEach(btn => {
      btn.onclick = () => {
        theoryFilter = btn.dataset.theoryFilter;
        theory().catch(fail);
      };
    });
  }
}
async function openSingleQuestionAnalysis(kind, id, attemptId) {
  if (!aiEnabled) { notice('.env에 API 키를 입력하세요.'); return; }
  const generated = kind === 'g';
  const q = await api(generated ? `/api/generated/${id}` : `/api/questions/${id}`);
  currentQuestion = { ...q, generated };
  const images = generated ? [] : (q.local_images || []);

  const modalBody = $('#modal-body');
  modalBody.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <span class="pill purple">✦ AI 오답 상세 분석</span>
      <span class="pill sm">${esc(q.category)} / ${esc(q.subcategory)}</span>
    </div>
    <h2 class="question-title">${generated ? 'AI 생성 문제' : `${q.year}년 ${q.round}회 ${q.number}번`}</h2>
    <div class="question-text">${esc(q.question_text)}</div>
    ${images.map(url => `<img class="question-image" src="${esc(url)}" alt="문제 첨부 이미지" loading="lazy">`).join('')}
    <div class="result" style="margin-top:14px">
      <div class="note" style="margin-bottom:4px">게시된 정답</div>
      <pre style="margin:0">${esc(q.correct_answer || q.answer)}</pre>
      ${q.explanation ? `<div class="note" style="margin-top:8px">${esc(q.explanation)}</div>` : ''}
    </div>
    <div id="single-ai-output" style="margin-top:14px">
      ${aiProgress('AI가 이 문제의 오답 원인과 핵심 풀이를 분석하고 있습니다…')}
    </div>
    <div class="actions modal-footer-actions" style="margin-top:16px">
      <button type="button" class="button" id="btn-solve-now">직접 다시 풀기</button>
      <button type="button" class="button muted" data-close>닫기</button>
    </div>
  `;
  $('#modal').classList.remove('hidden');
  $('#modal').setAttribute('aria-hidden', 'false');
  $('.modal-card').scrollTop = 0;

  $('#btn-solve-now').onclick = () => openQuestion(kind, id, attemptId);

  try {
    let result;
    if (attemptId) {
      result = await api(`/api/attempts/${attemptId}/analyze`, { method: 'POST' });
    } else {
      result = {
        feedback: "오답 원인을 분석하여 취약 개념을 집중 복습하세요.",
        steps: ["정답과 이전 풀이를 대조하여 계산 과정 및 문법을 확인합니다."],
        cause: "풀이 단계별 차이점을 점검하세요.",
        weak_concepts: [q.subcategory || q.category]
      };
    }
    const steps = Array.isArray(result.steps) ? result.steps.map(step => String(step).replace(/^\s*\d+[.)]\s*/, '')) : [];
    $('#single-ai-output').innerHTML = `
      <div class="result ai-analysis" style="border:1px solid #d5ddf6">
        <strong style="color:var(--blue);font-size:15px;display:block;margin-bottom:8px">✦ AI 상세 오답 분석</strong>
        <p>${esc(result.feedback || '')}</p>
        ${steps.length ? `<strong style="display:block;margin:10px 0 6px">차근차근 풀이 단계</strong><ol>${steps.map(s => `<li>${esc(s)}</li>`).join('')}</ol>` : ''}
        ${result.cause ? `<strong style="display:block;margin:10px 0 4px">내 답과 비교</strong><p>${esc(result.cause)}</p>` : ''}
        ${result.next_tip ? `<strong style="display:block;margin:10px 0 4px">💡 시험장 확인 팁</strong><p>${esc(result.next_tip)}</p>` : ''}
        ${result.weak_concepts?.length ? `<div class="note" style="margin-top:8px">취약 개념: ${esc(result.weak_concepts.join(', '))}</div>` : ''}
      </div>
    `;
  } catch (err) {
    $('#single-ai-output').innerHTML = `
      <div class="result" style="color:#b34d4d">
        AI 분석을 불러오는 중 오류가 발생했습니다: ${esc(err.message)}
      </div>
    `;
  }
}

async function openQuestion(kind, id, attemptId = null) {
  const generated = kind === 'g';
  const q = await api(generated ? `/api/generated/${id}` : `/api/questions/${id}`);
  const dailyIndex = currentView === 'today' && todayPlan ? todayPlan.items.findIndex(item => item.id === q.id && Boolean(item.generated) === generated) : -1;
  currentQuestion = { ...q, generated, dailyIndex };
  currentAttempt = attemptId;
  const images = generated ? [] : (q.local_images || []);
  const isWrongView = currentView === 'wrong';

  $('#modal-body').innerHTML = `
    ${dailyIndex >= 0 ? `<div class="note daily-position">오늘의 학습 ${dailyIndex + 1} / ${todayPlan.items.length}</div>` : ''}
    ${isWrongView ? `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;background:#f5f7fd;padding:9px 13px;border-radius:10px">
        <span class="pill red" style="font-size:11px">오답 복습 문제</span>
        <button type="button" class="button ghost sm" id="btn-quick-ai" style="padding:5px 10px;font-size:11.5px">✦ AI 오답 분석 바로보기</button>
      </div>
    ` : ''}
    <span class="pill">${esc(q.category)} / ${esc(q.subcategory)}</span>
    <h2 class="question-title">${generated ? 'AI 생성 문제' : `${q.year}년 ${q.round}회 ${q.number}번`}</h2>
    <div class="question-text">${esc(q.question_text)}</div>
    ${images.map(url => `<img class="question-image" src="${esc(url)}" alt="문제 첨부 이미지" loading="lazy">`).join('')}
    <div class="question-form">
      <textarea id="answer-input" placeholder="답을 입력하세요"></textarea>
      <div class="actions">
        <button id="submit-answer" class="button">답안 제출</button>
        <button id="close-question" class="button muted">나중에 풀기</button>
      </div>
    </div>
    <div id="answer-result"></div>
  `;
  $('#modal').classList.remove('hidden');
  $('#modal').setAttribute('aria-hidden', 'false');
  $('#submit-answer').onclick = () => submitAnswer().catch(fail);
  $('#close-question').onclick = closeModal;
  if ($('#btn-quick-ai')) {
    $('#btn-quick-ai').onclick = () => openSingleQuestionAnalysis(kind, id, attemptId).catch(fail);
  }
  $('.modal-card').scrollTop = 0;
}
function closeModal(){ $('#modal').classList.add('hidden'); $('#modal').setAttribute('aria-hidden','true');currentQuestion=null; }
function completeDailyQuestion() {
  if(!currentQuestion||currentQuestion.dailyIndex<0||!todayPlan) return;
  const index=currentQuestion.dailyIndex;
  todayPlan.items[index].completed=true;
  if(currentView==='today') renderToday();
  if($('#next-daily')) return;
  const last=index===todayPlan.items.length-1;
  $('#post-actions').insertAdjacentHTML('beforeend',`<button id="next-daily" class="button">${last?'오늘의 학습 목록으로':'다음 문제 →'}</button>`);
  $('#next-daily').onclick=async()=>{
    const button=$('#next-daily');
    button.disabled=true;
    try {
      if(last){closeModal();return}
      const next=todayPlan.items[index+1];
      await openQuestion(next.generated?'g':'q',next.id);
    } catch(error){button.disabled=false;fail(error)}
  };
}
async function submitAnswer() {
  const input=$('#answer-input'); const answer=input.value.trim(); if(!answer){notice('답을 입력하세요.');return}
  $('#submit-answer').disabled=true;
  try {
    const result=await api('/api/attempts',{method:'POST',body:JSON.stringify({[currentQuestion.generated?'generated_question_id':'question_id']:currentQuestion.id,user_answer:answer,mode:currentView})});
    currentAttempt=result.attempt_id;
    const auto=result.result;
    $('#answer-result').innerHTML=`<div class="result"><strong>${auto?(auto.is_correct?'정답입니다!':'오답입니다.'): '정답을 보고 직접 채점해 주세요.'}</strong><div class="note">게시된 답안</div><pre>${esc(result.correct_answer)}</pre>${result.explanation?`<div class="note">${esc(result.explanation)}</div>`:''}</div><div class="actions" id="post-actions">${auto?'':`<button class="button ghost sm" data-self="true">맞았어요</button><button class="button danger sm" data-self="false">틀렸어요</button>`}${auto&&!auto.is_correct?'<button class="button ghost sm" id="analyze">AI 오답 분석</button>':''}<button class="button muted sm" id="theory-link">이론 보기</button><button class="button muted sm" id="similar">유사 문제 생성</button></div><div id="ai-feedback"></div>`;
    $('.question-form').classList.add('hidden');
    document.querySelectorAll('[data-self]').forEach(b=>b.onclick=()=>selfReview(b.dataset.self==='true').catch(fail));
    if($('#analyze')) $('#analyze').onclick=()=>analyze().catch(fail);
    $('#theory-link').onclick=()=>{closeModal();setView('theory')};
    $('#similar').onclick=()=>similar().catch(fail);
    if(auto) completeDailyQuestion();
  } catch(error){$('#submit-answer').disabled=false;throw error}
}
async function selfReview(correct) {
  const data=await api(`/api/attempts/${currentAttempt}/review`,{method:'POST',body:JSON.stringify({is_correct:correct})});
  document.querySelectorAll('[data-self]').forEach(b=>b.remove());
  $('#post-actions').insertAdjacentHTML('afterbegin',correct?'<span class="pill green">정답 기록 완료</span>':'<span class="pill red">오답 기록 완료</span><button class="button ghost sm" id="analyze">AI 오답 분석</button>');
  if($('#analyze')) $('#analyze').onclick=()=>analyze().catch(fail);
  completeDailyQuestion();
  notice(`다음 복습: ${data.next_review_at.slice(0,10)}`);
}
async function analyze() {
  if(!aiEnabled){notice('.env에 API 키를 입력하세요.');return}
  const question=currentQuestion;
  $('#ai-feedback').innerHTML=aiProgress('오답을 분석하고 풀이의 정확성을 검수하고 있습니다…');
  try {
    const result=await api(`/api/attempts/${currentAttempt}/analyze`,{method:'POST'});
    if(currentQuestion!==question) return;
    const steps=Array.isArray(result.steps)?result.steps.map(step=>String(step).replace(/^\s*\d+[.)]\s*/,'')):[];
    $('#ai-feedback').innerHTML=`<div class="result ai-analysis"><strong>AI 오답 분석</strong><p>${esc(result.feedback||'')}</p>${steps.length?`<strong>차근차근 풀이</strong><ol>${steps.map(step=>`<li>${esc(step)}</li>`).join('')}</ol>`:''}<strong>내 답과 비교</strong><p>${esc(result.cause||'')}</p>${result.next_tip?`<strong>다음에는 이렇게 확인하세요</strong><p>${esc(result.next_tip)}</p>`:''}${result.weak_concepts?.length?`<div class="note">복습할 개념: ${esc(result.weak_concepts.join(', '))}</div>`:''}</div>`;
  } catch(error) {if(currentQuestion!==question)return;$('#ai-feedback').innerHTML=`<div class="result">${esc(error.message)} <button class="button ghost sm" id="retry-analyze">다시 시도</button></div>`;$('#retry-analyze').onclick=()=>analyze().catch(fail)}
}
async function similar() {
  if(!aiEnabled){notice('.env에 API 키를 입력하세요.');return}
  const question=currentQuestion;
  const button=$('#similar');
  if(button.disabled) return;
  button.disabled=true;
  const payload={mode:'similar',category:currentQuestion.category,subcategory:currentQuestion.subcategory};
  if(!currentQuestion.generated) payload.source_question_id=currentQuestion.id;
  $('#ai-feedback').innerHTML=aiProgress('새 문제를 만들고 검증하고 있습니다…');
  try {
    const result=await api('/api/generated',{method:'POST',body:JSON.stringify(payload)});
    if(currentQuestion!==question) return;
    if(!result.valid){$('#ai-feedback').innerHTML=`<div class="result">검증을 통과하지 못했습니다. ${esc((result.issues||[]).join(', '))}</div>`;return}
    await openQuestion('g',result.id);
  } catch(error) {if(currentQuestion!==question)return;$('#ai-feedback').innerHTML=`<div class="result">${esc(error.message)} <button class="button ghost sm" id="retry-similar">다시 시도</button></div>`;$('#retry-similar').onclick=()=>similar().catch(fail)}
  finally {button.disabled=false}
}
async function generateExpected() {
  if(!aiEnabled){notice('.env에 API 키를 입력하세요.');return}
  const button=$('#expected-btn');
  if(button.disabled) return;
  button.disabled=true;
  const status=$('#expected-status');
  status.innerHTML=aiProgress('AI가 문제를 만들고 검증하고 있습니다…');
  const category=$('#category').value || '프로그래밍';
  const subcategory=category==='프로그래밍'?'Java':category==='데이터베이스'?'SQL·설계':category==='보안'?'보안 개념':category==='네트워크'?'네트워크 개념':category==='소프트웨어 공학'?'개발·테스트':'기본 개념';
  try {
    const result=await api('/api/generated',{method:'POST',body:JSON.stringify({category,subcategory,mode:'expected'})});
    if(result.valid) await openQuestion('g',result.id);
    else status.innerHTML=`<span class="ai-status-error" role="alert">검증 실패: ${esc((result.issues||[]).join(', '))}</span>`;
  } catch(error) {status.innerHTML=`<span class="ai-status-error" role="alert">${esc(error.message)}</span>`}
  finally {button.disabled=false;if(!status.querySelector('.ai-status-error'))status.innerHTML=''}
}
document.addEventListener('click',event=>{
  const nav=event.target.closest('[data-view],[data-view-go]'); if(nav){setView(nav.dataset.view||nav.dataset.viewGo);return}
  const exam=event.target.closest('[data-exam]'); if(exam){const [year,round]=exam.dataset.exam.split(':').map(Number);examSession(year,round).catch(fail);return}
  const index=event.target.closest('[data-exam-index]'); if(index&&examState){examState.index=Number(index.dataset.examIndex);renderExamQuestion();return}
  if(event.target.closest('[data-exam-prev]')&&examState){examState.index=Math.max(0,examState.index-1);renderExamQuestion();return}
  if(event.target.closest('[data-exam-next]')&&examState){examState.index=Math.min(19,examState.index+1);renderExamQuestion();return}
  if(event.target.closest('[data-exam-submit]')){submitExam().catch(fail);return}
  const review=event.target.closest('[data-exam-review]'); if(review){const [id,correct]=review.dataset.examReview.split(':');reviewExamAttempt(Number(id),correct==='true').catch(fail);return}
  const singleAiBtn = event.target.closest('[data-single-ai]');
  if (singleAiBtn) {
    event.stopPropagation();
    const [kind, id] = singleAiBtn.dataset.singleAi.split(':');
    const attemptId = singleAiBtn.dataset.attempt ? Number(singleAiBtn.dataset.attempt) : null;
    openSingleQuestionAnalysis(kind, Number(id), attemptId).catch(fail);
    return;
  }
  const row=event.target.closest('[data-open]'); if(row){const [kind,id]=row.dataset.open.split(':');const attemptId = row.dataset.attemptId ? Number(row.dataset.attemptId) : null;openQuestion(kind,Number(id),attemptId).catch(fail);return}
  if(event.target.closest('[data-close]')) closeModal();
  const delTheoryBtn = event.target.closest('[data-del-theory]');
  if (delTheoryBtn) {
    const id = Number(delTheoryBtn.dataset.delTheory);
    if (confirm('이 AI 이론 노트를 삭제하시겠습니까?')) {
      api(`/api/theory/${id}`, { method: 'DELETE' })
        .then(() => { notice('이론 노트가 삭제되었습니다.'); theory().catch(fail); })
        .catch(fail);
    }
    return;
  }
});
document.addEventListener('input',event=>{
  if(event.target.id==='exam-answer'&&examState){examState.answers[examState.items[examState.index].id]=event.target.value;const count=examState.items.filter(item=>(examState.answers[item.id]||'').trim()).length;const footer=$('.exam-footer span');if(footer)footer.textContent=`${count}/20 답안 작성`}
});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal()});
$('#today-date').textContent=new Intl.DateTimeFormat('ko-KR',{dateStyle:'full'}).format(new Date());
api('/api/status').then(s=>{aiEnabled=s.ai_enabled;$('#ai-status').textContent=aiEnabled?'API 키 설정됨':'API 키 입력 전';$('#ai-dot').classList.toggle('on',aiEnabled)}).catch(fail);
setView('dashboard');
