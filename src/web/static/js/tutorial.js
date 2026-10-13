/** Isolated practice; all snapshots and permitted choices come from the engine. */
const TUTORIAL_STORAGE_KEY = '5dchess.tutorial.v2';
let tutorialData = null;
let tutorialIndex = 0;
let tutorialPhase = 'quiz';
let tutorialRequest = 0;
let tutorialOpener = null;
let tutorialMoves = [];
let tutorialSelection = null;
let tutorialHint = false;
let tutorialFeedback = '';
const tutorialCompleted = new Set();

function tutorialSaved() {
    try { return JSON.parse(localStorage.getItem(TUTORIAL_STORAGE_KEY) || 'null'); }
    catch (_) { return null; }
}
function tutorialSeen() { return Boolean(tutorialSaved()); }
function saveTutorialProgress(status = 'learning') {
    try {
        localStorage.setItem(TUTORIAL_STORAGE_KEY, JSON.stringify({
            status, lesson: tutorialData?.[tutorialIndex]?.id, completed: [...tutorialCompleted],
        }));
    } catch (_) { /* The course also works when browser storage is unavailable. */ }
}
async function openTutorial() {
    const dialog = document.getElementById('tutorial-dialog');
    if (dialog.open) return;
    tutorialOpener = document.activeElement;
    dialog.showModal();
    if (tutorialData) { renderTutorial(); return; }
    await loadTutorial();
}
async function loadTutorial() {
    const owner = ++tutorialRequest;
    const content = document.getElementById('tutorial-content');
    content.setAttribute('aria-busy', 'true');
    content.textContent = '正在准备练习棋盘…';
    for (const id of ['tutorial-next', 'tutorial-reset', 'tutorial-prev']) document.getElementById(id).disabled = true;
    const result = await api('/api/tutorial');
    if (owner !== tutorialRequest || !document.getElementById('tutorial-dialog').open) return;
    content.setAttribute('aria-busy', 'false');
    if (isErrorResult(result) || result?.version !== 2 || !Array.isArray(result?.lessons) || !result.lessons.length) {
        content.innerHTML = '<p role="alert">练习暂时无法加载。你的对局未受影响，可以重试或稍后再学。</p><button class="ghost-btn" onclick="loadTutorial()">重新加载</button>';
        return;
    }
    tutorialData = result.lessons;
    const saved = tutorialSaved();
    if (Array.isArray(saved?.completed)) {
        for (const lesson of tutorialData) if (saved.completed.includes(lesson.id)) tutorialCompleted.add(lesson.id);
    }
    tutorialIndex = Math.max(0, tutorialData.findIndex(lesson => lesson.id === saved?.lesson));
    resetTutorialLesson();
}
function closeTutorial() {
    ++tutorialRequest;
    saveTutorialProgress(tutorialData && tutorialCompleted.size === tutorialData.length ? 'completed' : 'dismissed');
    document.getElementById('tutorial-dialog').close();
    tutorialOpener?.focus();
}
function resetTutorialLesson() {
    if (!tutorialData) return;
    tutorialMoves = [];
    tutorialSelection = null;
    tutorialHint = false;
    tutorialFeedback = '';
    tutorialPhase = tutorialData[tutorialIndex].plans ? 'select' : 'quiz';
    renderTutorial();
    saveTutorialProgress();
    document.getElementById('tutorial-dialog').scrollTop = 0;
    document.getElementById('tutorial-title').focus({preventScroll: true});
}
function goTutorialLesson(index) {
    if (!tutorialData || index < 0 || index >= tutorialData.length) return;
    tutorialIndex = index;
    resetTutorialLesson();
}
function nextTutorialLesson() {
    if (tutorialPhase !== 'done') return;
    if (tutorialIndex < tutorialData.length - 1) { goTutorialLesson(tutorialIndex + 1); return; }
    const missing = tutorialData.findIndex(lesson => !tutorialCompleted.has(lesson.id));
    if (missing >= 0) { goTutorialLesson(missing); return; }
    closeTutorial();
}
function tutorialSameSquare(a, b) { return a?.board.key === b?.board.key && a?.x === b?.x && a?.y === b?.y; }
function tutorialSameMove(a, b) { return tutorialSameSquare(a.source, b.source) && tutorialSameSquare(a.destination, b.destination); }
function tutorialPlans() {
    return (tutorialData[tutorialIndex].plans || []).filter(plan =>
        tutorialMoves.every((move, i) => tutorialSameMove(move, plan.steps[i].move)));
}
function tutorialChoices() {
    return tutorialPlans().flatMap(plan => plan.steps[tutorialMoves.length] ? [plan.steps[tutorialMoves.length].move] : []);
}
function tutorialState() {
    const lesson = tutorialData[tutorialIndex];
    if (!lesson.plans) return lesson.snapshot;
    const plan = tutorialPlans()[0];
    if (['quiz', 'done'].includes(tutorialPhase)) return plan.after_submit;
    return tutorialMoves.length ? plan.steps[tutorialMoves.length - 1].after_move : plan.steps[0].before;
}
function tutorialSquareLabel(square) {
    return `${coordLabel(square.board)} · ${'abcdefgh'[square.x]}${8 - square.y}`;
}
function tutorialCell(key, x, y) {
    if (!['select', 'target'].includes(tutorialPhase)) return;
    const square = {board: {key}, x, y};
    const choices = tutorialChoices();
    if (tutorialSelection) {
        const move = choices.find(item => tutorialSameSquare(item.source, tutorialSelection) && tutorialSameSquare(item.destination, square));
        if (move) {
            tutorialMoves.push(move);
            tutorialSelection = null;
            tutorialHint = false;
            tutorialFeedback = `已走：${move.display_notation}`;
            tutorialPhase = tutorialMoves.length === tutorialPlans()[0].steps.length ? 'submit' : 'select';
            renderTutorial();
            document.getElementById(tutorialPhase === 'submit' ? 'tutorial-submit' : 'tutorial-instruction')?.focus();
            return;
        }
    }
    const source = choices.find(item => tutorialSameSquare(item.source, square));
    if (source) {
        tutorialSelection = source.source;
        tutorialPhase = 'target';
        tutorialFeedback = '';
    } else {
        const board = tutorialState()?.boards.find(item => item.key === key);
        tutorialFeedback = board?.historical ? '这是历史棋盘，不能从这里选子；只有蓝色落点才可进入历史。'
            : '本课只练习指定棋子和目标。请按任务选子，或使用“给我提示”；正式对局会提供全部合法走法。';
    }
    renderTutorial();
    if (source) document.querySelector('#tutorial-boards .target')?.focus();
}
function undoTutorialMove() {
    if (!tutorialMoves.length || ['quiz', 'done'].includes(tutorialPhase)) return;
    tutorialMoves.pop();
    tutorialSelection = null;
    tutorialFeedback = '已撤回练习中的一步，真实对局未受影响。';
    tutorialPhase = 'select';
    renderTutorial();
}
function hintTutorial() {
    tutorialHint = true;
    renderTutorial();
    document.getElementById('tutorial-instruction')?.focus();
}
function submitTutorialAction() {
    if (tutorialPhase !== 'submit' || !tutorialState()?.can_submit) return;
    tutorialPhase = 'quiz';
    tutorialFeedback = '';
    renderTutorial();
    document.getElementById('tutorial-question')?.focus();
}
function answerTutorial(index) {
    if (tutorialPhase !== 'quiz') return;
    const lesson = tutorialData[tutorialIndex];
    if (index !== lesson.quiz.correct) {
        tutorialFeedback = `再想一想：${lesson.quiz.explanation}`;
    } else {
        tutorialPhase = 'done';
        tutorialCompleted.add(lesson.id);
        tutorialFeedback = `答对了！${lesson.quiz.explanation}`;
        saveTutorialProgress(tutorialCompleted.size === tutorialData.length ? 'completed' : 'learning');
    }
    renderTutorial();
    document.getElementById(tutorialPhase === 'done' ? 'tutorial-next' : 'tutorial-question').focus();
}
function tutorialInstruction(lesson, state) {
    if (['quiz', 'done'].includes(tutorialPhase)) return lesson.plans ? lesson.success : '读完说明后，回答下方的问题，检查自己是否理解。';
    if (tutorialPhase === 'submit') return '红框已清空，王安全检查通过。现在点击“提交行动”，结束白方行动。';
    if (tutorialSelection) {
        const destinations = tutorialChoices().filter(move => tutorialSameSquare(move.source, tutorialSelection));
        return `已选 ${tutorialSquareLabel(tutorialSelection)}。请选择蓝色落点：${[...new Set(destinations.map(move => tutorialSquareLabel(move.destination)))].join(' 或 ')}。`;
    }
    if (lesson.independent && !tutorialHint) return `还有 ${state.required_count} 张棋盘需推进。请自己找到白兵，选择走子顺序。`;
    return `第 ${tutorialMoves.length + 1} 手：选择 ${tutorialSquareLabel(tutorialChoices()[0].source)} 的亮框棋子。`;
}
function renderTutorial() {
    if (!tutorialData) return;
    const lesson = tutorialData[tutorialIndex];
    const state = tutorialState();
    const title = document.getElementById('tutorial-title');
    title.textContent = `${tutorialIndex + 1} · ${lesson.title}`;
    document.getElementById('tutorial-progress').textContent = `${lesson.stage} · 第 ${tutorialIndex + 1} / ${tutorialData.length} 课 · 已掌握 ${tutorialCompleted.size} / ${tutorialData.length}`;
    const nav = document.getElementById('tutorial-steps');
    nav.replaceChildren();
    tutorialData.forEach((item, index) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'tutorial-tab';
        button.textContent = `${tutorialCompleted.has(item.id) ? '✓ ' : ''}${index + 1} ${item.title}`;
        button.setAttribute('aria-current', index === tutorialIndex ? 'step' : 'false');
        button.onclick = () => goTutorialLesson(index);
        nav.appendChild(button);
    });
    const showQuiz = ['quiz', 'done'].includes(tutorialPhase);
    const content = document.getElementById('tutorial-content');
    content.innerHTML = `<p class="tutorial-description">${escapeHtml(lesson.description)}</p>
        <ul class="tutorial-points">${lesson.points.map(point => `<li>${escapeHtml(point)}</li>`).join('')}</ul>
        ${lesson.piece_guide ? `<div class="tutorial-table-wrap"><table class="tutorial-table"><caption>棋子走法对照（四个方向：横、纵、时间、时间线）</caption><thead><tr><th>棋子</th><th>普通国际象棋</th><th>增加时空之后</th></tr></thead><tbody>${lesson.piece_guide.map(row => `<tr>${row.map(cell => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : ''}
        <p id="tutorial-instruction" class="tutorial-instruction" role="status" tabindex="-1">${escapeHtml(tutorialInstruction(lesson, state))}</p>
        ${state ? `<div class="tutorial-state"><span>行动方：<strong>${colorLabel(state.turn)}</strong></span><span>当前需推进：<strong>${state.required_count} 张棋盘</strong></span><span>${showQuiz && lesson.plans ? '已提交，轮到对手' : state.can_submit ? '可以提交' : '尚不能提交'}</span></div>
        <p class="tutorial-legend">红框：必须推进 · 紫色：当前时刻 · 灰色：历史 · 蓝色格：本课落点 · 绿色格：刚刚到达。同一行可左右滑动查看历史。</p><div id="tutorial-boards" class="tutorial-boards"></div>` : ''}
        ${lesson.plans ? `<div class="tutorial-practice-actions"><button id="tutorial-hint" class="ghost-btn" onclick="hintTutorial()" ${showQuiz || tutorialPhase === 'submit' ? 'disabled' : ''}>给我提示</button><button id="tutorial-undo" class="ghost-btn" onclick="undoTutorialMove()" ${!tutorialMoves.length || showQuiz ? 'disabled' : ''}>撤回练习一步</button><button id="tutorial-submit" class="submit-btn" onclick="submitTutorialAction()" ${tutorialPhase !== 'submit' ? 'disabled' : ''}>${showQuiz ? '已提交 · 轮到黑方' : '提交行动'}</button></div><p class="tutorial-scope">练习只开放本课走法；正式对局会显示全部合法落点。练习撤回仅用于教学。</p>` : ''}
        ${showQuiz ? `<section class="tutorial-quiz" aria-labelledby="tutorial-question"><h3 id="tutorial-question" tabindex="-1">理解检查：${escapeHtml(lesson.quiz.prompt)}</h3><div class="tutorial-answers">${lesson.quiz.answers.map((answer, i) => `<button class="ghost-btn" onclick="answerTutorial(${i})" ${tutorialPhase === 'done' ? 'disabled' : ''}>${escapeHtml(answer)}</button>`).join('')}</div></section>` : ''}
        <p id="tutorial-feedback" class="tutorial-feedback" role="status">${escapeHtml(tutorialFeedback)}</p>
        ${tutorialIndex === tutorialData.length - 1 && tutorialPhase === 'done' && tutorialCompleted.size === tutorialData.length ? '<div class="tutorial-graduation"><h3>已完成全部课程，可以开始实战了</h3><p>回到主页选择“人机对弈”，从简单难度开始。每回合按“红框 → 选子 → 落点 → 王安全 → 提交”检查。棋盘多时使用缩放与“当前时刻”定位；菜单或对局顶部都能重开教程。</p></div>' : ''}`;
    if (state) renderTutorialBoards(state);
    const next = document.getElementById('tutorial-next');
    next.disabled = tutorialPhase !== 'done';
    next.textContent = tutorialPhase !== 'done' ? '完成练习与问答后继续' : tutorialIndex < tutorialData.length - 1 ? '下一课 →'
        : tutorialCompleted.size === tutorialData.length ? '完成教程，回到游戏' : '继续未完成的课程';
    document.getElementById('tutorial-prev').disabled = tutorialIndex === 0;
    document.getElementById('tutorial-reset').disabled = false;
}
function renderTutorialBoards(state) {
    const lesson = tutorialData[tutorialIndex];
    const choices = ['select', 'target'].includes(tutorialPhase) ? tutorialChoices() : [];
    const recent = tutorialMoves.at(-1);
    const host = document.getElementById('tutorial-boards');
    // A row per timeline preserves the horizontal time / vertical timeline map.
    for (const lane of [...new Set(state.boards.map(board => board.coord.timeline))].sort((a, b) => a - b)) {
        const row = document.createElement('div');
        row.className = 'tutorial-lane';
        row.setAttribute('aria-label', `时间线 ${lane}`);
        const label = document.createElement('p');
        label.className = 'tutorial-lane-label';
        label.textContent = `L${lane > 0 ? '+' : ''}${lane} · 时间向右 →`;
        row.appendChild(label);
        const strip = document.createElement('div');
        strip.className = 'tutorial-lane-boards';
        let visibleCard = null;
        for (const board of state.boards.filter(item => item.coord.timeline === lane).sort((a, b) => a.coord.time_point - b.coord.time_point)) {
            const card = document.createElement('section');
            card.className = `tutorial-board ${board.is_required ? 'required' : ''} ${board.historical ? 'historical' : ''}`;
            const heading = document.createElement('h3');
            heading.textContent = `${coordLabel(board.coord)} · ${board.historical ? '历史' : '最新'}`;
            card.appendChild(heading);
            const badge = document.createElement('p');
            badge.className = `tutorial-board-status ${board.is_present ? 'at-present' : ''}`;
            badge.textContent = [board.is_present ? '当前时刻' : '', board.is_required ? '必须推进' : '', !board.timeline_active ? '非活动' : '', board.is_movable && !board.is_required ? '可选走子' : '', recent?.created_timeline === lane ? '新分支' : ''].filter(Boolean).join(' · ') || (board.historical ? '只可作为落点' : '等待对手阶段');
            card.appendChild(badge);
            const grid = document.createElement('div');
            grid.className = 'tutorial-grid';
            for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
                const square = {board: board.coord, x, y};
                const ch = board.board[y][x];
                const isSource = choices.some(move => tutorialSameSquare(move.source, square));
                const isTarget = tutorialSelection && choices.some(move => tutorialSameSquare(move.source, tutorialSelection) && tutorialSameSquare(move.destination, square));
                const arrival = recent && board.key === recent.result_destination_board.key && x === recent.destination.x && y === recent.destination.y;
                const cell = document.createElement('button');
                cell.type = 'button';
                cell.className = `tutorial-cell ${(x + y) % 2 ? 'dark' : 'light'} ${ch ? pieceColor(ch) + '-piece' : ''}`;
                if (isSource && (!lesson.independent || tutorialHint || tutorialSameSquare(square, tutorialSelection))) cell.classList.add('source');
                if (isTarget) cell.classList.add('target');
                if (arrival) cell.classList.add('arrival');
                cell.innerHTML = `${pieceSymbols[ch] || (isTarget ? '●' : '')}${x === 0 ? `<small class="tutorial-rank">${8-y}</small>` : ''}${y === 7 ? `<small class="tutorial-file">${'abcdefgh'[x]}</small>` : ''}`;
                cell.setAttribute('aria-label', `${tutorialSquareLabel(square)}${ch ? ' ' + colorLabel(pieceColor(ch)) + ({K:'王',Q:'后',R:'车',B:'象',N:'马',P:'兵'}[ch.toUpperCase()]) : ' 空格'}${isSource ? ' 可选择棋子' : isTarget ? ' 可移动到这里' : ''}`);
                cell.disabled = !['select', 'target'].includes(tutorialPhase);
                cell.tabIndex = isSource || isTarget ? 0 : -1;
                cell.onclick = () => tutorialCell(board.key, x, y);
                grid.appendChild(cell);
            }
            card.appendChild(grid);
            strip.appendChild(card);
            if (board.key === recent?.result_source_board?.key || board.key === recent?.result_destination_board.key ||
                choices.some(move => move.source.board.key === board.key)) visibleCard = card;
        }
        row.appendChild(strip);
        host.appendChild(row);
        // Keep the current source/result visible on narrow screens without
        // scrolling the entire dialog past the lesson explanation.
        if (visibleCard) strip.scrollLeft = visibleCard.offsetLeft;
    }
}
document.getElementById('tutorial-dialog').addEventListener('cancel', event => {
    event.preventDefault(); closeTutorial();
});
if (!tutorialSeen() && !window.location.search) openTutorial();
