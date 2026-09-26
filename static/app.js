const $ = s => document.querySelector(s);
const view = $('#view');
let currentView = 'dashboard';
let bankPage = 1;
let generatedPage = 1;
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
  const title={dashboard:'대시보드',today:'오늘의 학습',bank:'문제은행',generated:'AI 생성 문제',exams:'회차별 시험',wrong:'오답노트',theory:'이론 노트'}[name];
  $('#page-title').textContent=title;
  document.querySelectorAll('#nav button').forEach(b=>b.classList.toggle('active',b.dataset.view===name));
  ({dashboard,today,bank,generated,exams,wrong,theory})[name]().catch(fail);
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
    <div class="section-head"><div><h2>오늘의 학습</h2><p>복습 예정 · 취약 분야 · 새 문제를 순서대로 학습하세요.</p></div></div>
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
  view.innerHTML=`<div class="section-head daily-heading"><div><h2>맞춤 학습 계획</h2><p>현재 권장 난이도 Lv.${plan.difficulty} · ${done}/${plan.items.length} 완료 · 분야별로 배분한 문제입니다.</p><p>새 문제로 바꿔도 기존 풀이 기록과 오답노트는 유지됩니다.</p></div><button id="refresh-today" class="button ghost">↻ 다른 20문제 받기</button></div><div class="category-summary">${Object.entries(counts).map(([category,count])=>`<span class="pill gray">${esc(category)} ${count}</span>`).join('')}</div>
  <div class="list">${plan.items.length ? plan.items.map(q=>rowHtml(q,q.reason==='generated')).join('') : '<div class="empty">학습 문제가 없습니다.</div>'}</div>`;
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
    button.textContent='↻ 다른 20문제 받기';
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
async function wrong() {
  const data=await api('/api/wrong-answers');
  view.innerHTML=`<div class="section-head"><div><h2>다시 풀어볼 문제</h2><p>오답 원인과 다음 복습 날짜를 확인하세요.</p></div></div><div class="list">${data.items.length ? data.items.map(q=>`<div class="row" data-open="${q.question_id?'q':'g'}:${q.question_id||q.generated_question_id}"><div class="num">${q.number||'AI'}</div><div class="row-main"><div class="row-title">${esc(q.question_text||'AI 생성 문제')}</div><div class="row-meta">오답 ${q.wrong_count}회 · 다음 복습 ${esc((q.next_review_at||'').slice(0,10))}${q.wrong_reason?' · '+esc(q.wrong_reason):''}</div></div><span class="pill red">다시 풀기</span></div>`).join(''):'<div class="empty">아직 기록된 오답이 없습니다.</div>'}</div>`;
}
async function theory() {
  const data=await api('/api/theory');
  view.innerHTML=`<div class="section-head"><div><h2>핵심 개념 정리</h2><p>오답 뒤 짧게 복습하는 개념 카드입니다.</p></div></div><div class="grid split">${data.items.map(t=>`<div class="card theory-card"><small>${esc(t.category)} / ${esc(t.subcategory)}</small><h3>${esc(t.title||t.subcategory)}</h3><p>${esc(t.summary||'이 개념의 요약을 아직 만들지 않았습니다.')}</p>${t.example?`<div class="note">예시: ${esc(t.example)}</div>`:''}${t.common_mistakes?`<div class="note">자주 하는 실수: ${esc(t.common_mistakes)}</div>`:''}<div class="actions"><button class="button ghost sm" data-theory="${esc(t.category)}|${esc(t.subcategory)}">AI로 설명 만들기</button></div><div class="theory-ai-output" aria-live="polite"></div></div>`).join('')}</div>`;
}
async function explainTheory(button) {
  if(!aiEnabled){notice('.env에 API 키를 입력하세요.');return}
  const [category,subcategory]=button.dataset.theory.split('|');
  const output=button.closest('.theory-card').querySelector('.theory-ai-output');
  button.disabled=true;
  output.innerHTML=aiProgress('AI가 설명을 만들고 있습니다…');
  try {
    const result=await api('/api/theory/explain',{method:'POST',body:JSON.stringify({category,subcategory})});
    output.innerHTML=`<div class="ai-theory-result"><strong>${esc(result.title)}</strong><p>${esc(result.summary)}</p>${result.example?`<div class="note">예시: ${esc(result.example)}</div>`:''}${result.common_mistakes?`<div class="note">자주 하는 실수: ${esc(result.common_mistakes)}</div>`:''}<small>이 설명은 화면을 벗어나면 사라집니다.</small></div>`;
  } catch(error) {
    output.innerHTML=`<span class="ai-status-error" role="alert">${esc(error.message)}</span>`;
  } finally { button.disabled=false; }
}
async function openQuestion(kind,id) {
  const generated=kind==='g';
  const q=await api(generated?`/api/generated/${id}`:`/api/questions/${id}`);
  const dailyIndex=currentView==='today'&&todayPlan ? todayPlan.items.findIndex(item=>item.id===q.id&&(item.reason==='generated')===generated) : -1;
  currentQuestion={...q,generated,dailyIndex}; currentAttempt=null;
  const images=generated?[]:(q.local_images||[]);
  $('#modal-body').innerHTML=`${dailyIndex>=0?`<div class="note daily-position">오늘의 학습 ${dailyIndex+1} / ${todayPlan.items.length}</div>`:''}<span class="pill">${esc(q.category)} / ${esc(q.subcategory)}</span><h2 class="question-title">${generated?'AI 생성 문제':`${q.year}년 ${q.round}회 ${q.number}번`}</h2>
    <div class="question-text">${esc(q.question_text)}</div>${images.map(url=>`<img class="question-image" src="${esc(url)}" alt="문제 첨부 이미지" loading="lazy">`).join('')}
    <div class="question-form"><textarea id="answer-input" placeholder="답을 입력하세요"></textarea><div class="actions"><button id="submit-answer" class="button">답안 제출</button><button id="close-question" class="button muted">나중에 풀기</button></div></div><div id="answer-result"></div>`;
  $('#modal').classList.remove('hidden'); $('#modal').setAttribute('aria-hidden','false');
  $('#submit-answer').onclick=()=>submitAnswer().catch(fail);
  $('#close-question').onclick=closeModal;
  $('.modal-card').scrollTop=0;
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
      await openQuestion(next.reason==='generated'?'g':'q',next.id);
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
  const row=event.target.closest('[data-open]'); if(row){const [kind,id]=row.dataset.open.split(':');openQuestion(kind,Number(id)).catch(fail);return}
  if(event.target.closest('[data-close]')) closeModal();
  const theoryButton=event.target.closest('[data-theory]');
  if(theoryButton) explainTheory(theoryButton).catch(fail);
});
document.addEventListener('input',event=>{
  if(event.target.id==='exam-answer'&&examState){examState.answers[examState.items[examState.index].id]=event.target.value;const count=examState.items.filter(item=>(examState.answers[item.id]||'').trim()).length;const footer=$('.exam-footer span');if(footer)footer.textContent=`${count}/20 답안 작성`}
});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal()});
$('#today-date').textContent=new Intl.DateTimeFormat('ko-KR',{dateStyle:'full'}).format(new Date());
api('/api/status').then(s=>{aiEnabled=s.ai_enabled;$('#ai-status').textContent=aiEnabled?'API 키 설정됨':'API 키 입력 전';$('#ai-dot').classList.toggle('on',aiEnabled)}).catch(fail);
setView('dashboard');
