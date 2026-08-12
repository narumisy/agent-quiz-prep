(function () {
  const OPTION_KEYS = ['A', 'B', 'C', 'D', 'E', 'F'];
  const STORAGE_KEY = 'agent_quiz_stats_v1';

  const typeLabel = {
    single: '单选',
    multiple: '多选',
    judge: '判断'
  };

  let mode = 'all';
  let quiz = [];
  let current = 0;
  let correctCount = 0;
  let wrongCount = 0;

  let stats = loadStats();

  const questionCard = document.getElementById('questionCard');
  const typeBadge = document.getElementById('typeBadge');
  const categoryBadge = document.getElementById('categoryBadge');
  const answerStatus = document.getElementById('answerStatus');
  const questionText = document.getElementById('questionText');
  const optionsList = document.getElementById('optionsList');
  const feedback = document.getElementById('feedback');
  const submitBtn = document.getElementById('submitBtn');
  const nextBtn = document.getElementById('nextBtn');
  const progressText = document.getElementById('progressText');
  const progressFill = document.getElementById('progressFill');
  const correctCountEl = document.getElementById('correctCount');
  const wrongCountEl = document.getElementById('wrongCount');
  const cumRateEl = document.getElementById('cumRate');
  const wrongBadge = document.getElementById('wrongBadge');
  const modeAllBtn = document.getElementById('modeAll');
  const modeWrongBtn = document.getElementById('modeWrong');
  const footerText = document.getElementById('footerText');

  function loadStats() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) return JSON.parse(raw);
    } catch (e) { /* ignore */ }
    return { questions: {} };
  }

  function saveStats() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(stats));
    } catch (e) { /* ignore */ }
  }

  function getQStat(id) {
    return stats.questions[id] || { correct: 0, wrong: 0 };
  }

  function recordResult(id, isCorrect) {
    const s = getQStat(id);
    if (isCorrect) s.correct++;
    else s.wrong++;
    stats.questions[id] = s;
    saveStats();
  }

  function wrongQuestionIds() {
    return Object.keys(stats.questions).filter(function (id) {
      const s = stats.questions[id];
      return s.wrong > 0 && s.wrong >= s.correct;
    }).map(Number);
  }

  function shuffle(arr) {
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  function buildQuiz() {
    let pool;
    if (mode === 'wrong') {
      const ids = wrongQuestionIds();
      pool = QUESTIONS.filter(function (q) { return ids.indexOf(q.id) !== -1; });
    } else {
      pool = QUESTIONS.slice();
    }
    pool = pool.map(function (q) {
      return { id: q.id, type: q.type, category: q.category, question: q.question, options: q.options.slice(), answer: q.answer.slice(), analysis: q.analysis };
    });
    pool.sort(function (a, b) {
      const ca = (getQStat(a.id).correct + getQStat(a.id).wrong);
      const cb = (getQStat(b.id).correct + getQStat(b.id).wrong);
      if (ca !== cb) return ca - cb;
      return Math.random() - 0.5;
    });
    quiz = pool;
  }

  function shuffleOptions(q) {
    const indices = q.options.map(function (_, i) { return i; });
    for (let i = indices.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      const t = indices[i]; indices[i] = indices[j]; indices[j] = t;
    }
    const newOptions = indices.map(function (i) { return q.options[i]; });
    const newAnswer = [];
    indices.forEach(function (origIdx, newIdx) {
      if (q.answer.indexOf(origIdx) !== -1) newAnswer.push(newIdx);
    });
    q.options = newOptions;
    q.answer = newAnswer;
  }

  function updateCumRate() {
    let total = 0;
    let correct = 0;
    Object.keys(stats.questions).forEach(function (id) {
      const s = stats.questions[id];
      total += s.correct + s.wrong;
      correct += s.correct;
    });
    cumRateEl.textContent = total > 0 ? Math.round((correct / total) * 100) + '%' : '--';

    const wrongIds = wrongQuestionIds();
    if (wrongIds.length > 0) {
      wrongBadge.textContent = wrongIds.length;
      wrongBadge.style.display = 'inline-block';
    } else {
      wrongBadge.style.display = 'none';
    }
  }

  function updateStats() {
    progressText.textContent = `${current + 1}/${quiz.length}`;
    progressFill.style.width = `${((current + 1) / quiz.length) * 100}%`;
    correctCountEl.textContent = correctCount;
    wrongCountEl.textContent = wrongCount;
    updateCumRate();
  }

  function setMode(m) {
    mode = m;
    modeAllBtn.classList.toggle('active', m === 'all');
    modeWrongBtn.classList.toggle('active', m === 'wrong');
    startRound();
  }

  function startRound() {
    buildQuiz();
    current = 0;
    correctCount = 0;
    wrongCount = 0;
    nextBtn.textContent = '下一题';
    render();
  }

  function render() {
    if (quiz.length === 0) {
      renderEmpty();
      return;
    }

    const q = quiz[current];
    shuffleOptions(q);
    questionCard.style.display = 'block';

    typeBadge.textContent = typeLabel[q.type];
    categoryBadge.textContent = q.category;
    answerStatus.style.display = 'none';
    answerStatus.className = 'badge';
    questionText.textContent = `${q.id}. ${q.question}`;

    optionsList.innerHTML = '';
    q.options.forEach((opt, i) => {
      const div = document.createElement('div');
      div.className = 'option';
      div.dataset.index = i;

      const key = document.createElement('span');
      key.className = 'option-key';
      key.textContent = OPTION_KEYS[i];

      const label = document.createElement('span');
      label.textContent = opt;

      div.appendChild(key);
      div.appendChild(label);

      div.addEventListener('click', function () {
        if (this.classList.contains('disabled')) return;
        if (q.type === 'multiple') {
          this.classList.toggle('selected');
        } else {
          optionsList.querySelectorAll('.option').forEach(function (o) {
            o.classList.remove('selected');
          });
          this.classList.add('selected');
        }
      });

      optionsList.appendChild(div);
    });

    feedback.style.display = 'none';
    submitBtn.style.display = 'inline-block';
    submitBtn.disabled = false;
    nextBtn.style.display = 'none';
    nextBtn.disabled = false;

    updateStats();
    footerText.textContent = `共 ${quiz.length} 题 · 第 ${current + 1} 题${mode === 'wrong' ? ' · 错题重练' : ''}`;
  }

  function renderEmpty() {
    questionCard.innerHTML = `
      <div style="text-align:center;padding:30px 0">
        <div style="font-size:48px;margin-bottom:12px">🎯</div>
        <h2 style="margin-bottom:8px">太棒了，暂无错题</h2>
        <p style="color:#718096;line-height:1.7">所有题目的答对次数都已超过答错次数。<br>点击下方按钮切换回全部题目继续刷题。</p>
        <button class="btn btn-primary" id="backAllBtn" style="max-width:280px;margin:20px auto 0">返回全部题目</button>
      </div>
    `;
    progressFill.style.width = '0%';
    progressText.textContent = '0/0';
    correctCountEl.textContent = '0';
    wrongCountEl.textContent = '0';
    updateCumRate();
    footerText.textContent = '错题重练模式 · 暂无错题';

    document.getElementById('backAllBtn').addEventListener('click', function () {
      setMode('all');
    });
  }

  function getSelected() {
    const selected = [];
    optionsList.querySelectorAll('.option.selected').forEach(function (o) {
      selected.push(parseInt(o.dataset.index, 10));
    });
    return selected;
  }

  function submit() {
    const q = quiz[current];
    const selected = getSelected();

    if (selected.length === 0) {
      feedback.innerHTML = '<strong>请先选择一个答案</strong>';
      feedback.className = 'feedback no';
      feedback.style.display = 'block';
      return;
    }
    const isCorrect =
      selected.length === q.answer.length &&
      selected.every(function (i) { return q.answer.indexOf(i) !== -1; });

    recordResult(q.id, isCorrect);

    answerStatus.textContent = isCorrect ? '回答正确' : '回答错误';
    answerStatus.className = 'badge ' + (isCorrect ? 'ok' : 'no');
    answerStatus.style.display = 'inline-block';

    feedback.style.display = 'none';

    renderAnswerPanel(q, selected, isCorrect);

    if (isCorrect) {
      correctCount++;
    } else {
      wrongCount++;
    }
    updateStats();

    submitBtn.style.display = 'none';
    nextBtn.style.display = 'inline-block';

    if (current === quiz.length - 1) {
      nextBtn.textContent = '查看结果';
    } else {
      nextBtn.textContent = '下一题';
    }
  }

  function renderAnswerPanel(q, selected, isCorrect) {
    const answerOptions = q.answer.map(function (i) {
      return OPTION_KEYS[i] + '. ' + q.options[i];
    }).join('<br>');
    const selectedText = selected.map(function (i) {
      return OPTION_KEYS[i] + '. ' + q.options[i];
    }).join('<br>');

    const verdict = isCorrect
      ? '<div class="answer-verdict ok">回答正确</div>'
      : '<div class="answer-verdict no">回答错误</div>';

    let selectedBlock = '';
    if (!isCorrect) {
      selectedBlock = `<div class="answer-block"><span class="answer-label no-label">你的答案</span><div class="answer-content">${selectedText}</div></div>`;
    }

    optionsList.innerHTML = `
      <div class="answer-panel">
        ${verdict}
        <div class="answer-block">
          <span class="answer-label ok-label">正确答案</span>
          <div class="answer-content">${answerOptions}</div>
        </div>
        ${selectedBlock}
        <div class="answer-block">
          <span class="answer-label info-label">解析</span>
          <div class="answer-content">${q.analysis}</div>
        </div>
      </div>
    `;
  }

  function next() {
    if (current < quiz.length - 1) {
      current++;
      render();
    } else {
      showResult();
    }
  }

  function showResult() {
    const total = quiz.length;
    const rate = Math.round((correctCount / total) * 100);

    let emoji;
    let advice;
    if (rate >= 90) {
      emoji = '🎉';
      advice = '掌握扎实，决赛很有希望！重点回归多选和判断易错点。';
    } else if (rate >= 75) {
      emoji = '👍';
      advice = '掌握不错，建议针对错题板块再刷一遍手册。';
    } else if (rate >= 60) {
      emoji = '💪';
      advice = '基础尚可，重点复习薄弱板块，多做几次。';
    } else {
      emoji = '📚';
      advice = '建议先通读备考手册，再回来重新测试。';
    }

    questionCard.innerHTML = `
      <div style="text-align:center;padding:20px 0">
        <div style="font-size:56px;margin-bottom:12px">${emoji}</div>
        <h2 style="margin-bottom:8px">本轮自测完成</h2>
        <p style="font-size:18px;color:#4a5568">答对 <strong style="color:#38a169">${correctCount}</strong> / ${total} 题</p>
        <p style="font-size:14px;color:#a0aec0;margin-top:4px">本轮正确率 ${rate}%</p>
        <p style="margin-top:16px;color:#718096;line-height:1.7">${advice}</p>
        <div style="display:flex;gap:12px;max-width:400px;margin:20px auto 0">
          <button class="btn btn-primary" id="againBtn">再来一轮</button>
          <button class="btn btn-next" id="wrongBtn" style="flex:1">错题重练</button>
        </div>
      </div>
    `;

    progressFill.style.width = '100%';
    progressText.textContent = `${total}/${total}`;
    footerText.textContent = `本套 ${total} 题 · 正确率 ${rate}%`;

    document.getElementById('againBtn').addEventListener('click', function () {
      startRound();
    });
    document.getElementById('wrongBtn').addEventListener('click', function () {
      setMode('wrong');
    });
  }

  submitBtn.addEventListener('click', submit);
  nextBtn.addEventListener('click', next);
  modeAllBtn.addEventListener('click', function () { setMode('all'); });
  modeWrongBtn.addEventListener('click', function () { setMode('wrong'); });

  startRound();
})();
