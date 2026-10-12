/** Isolated practice: snapshots come from canonical engine moves, never live mutations. */
const TUTORIAL_STORAGE_KEY = '5dchess.tutorial.v1';
const tutorialLessons = [
    {
        title: '1 · 走子与提交',
        description: '一次“走子”只推进相关棋盘；一次“行动”可以包含多次走子。最后点击“提交行动”，才会换人。',
        select: '点击亮框中的白兵（e2）。', target: '点击蓝色落点 e4，让白兵前进两格。',
        moved: '白兵已在新棋盘上。白方仍在行动，但红框已清空，现在点击“提交行动”。',
        done: '提交成功，轮到黑方。旧棋盘保留历史，新棋盘显示走子结果。',
    },
    {
        title: '2 · 跨时间线移动',
        description: 'L0 和 L+1 是两条时间线。车沿时间线维度移动时，格子位置保持不变；这里两张最新棋盘都轮到白方。',
        select: '点击 L0 棋盘上的白车。两张红框棋盘都需要推进。',
        target: '点击 L+1 棋盘上相同位置的蓝色格子。',
        moved: '车离开 L0，进入 L+1；两张棋盘都产生后继棋盘，红框同时清空。点击“提交行动”。',
        done: '一次跨线走子推进了两张棋盘。移动前后的棋盘都被保留，轮到黑方。',
    },
    {
        title: '3 · 回到历史，生成分支',
        description: '横向是时间，纵向是时间线。只能从最新且轮到己方的棋盘选子；同色阶段的历史棋盘可以成为合法落点。',
        select: '点击 T1（较新棋盘）上的白车。左侧 T0 是历史，不能从那里选子。',
        target: '点击 T0 历史棋盘上的蓝色格子。车沿时间维度回到过去。',
        moved: 'L+1 分支已生成，白车出现在分支的新棋盘上；L0 的原历史没有被改写。现在提交行动。',
        done: '本课已完成！分支可能把“当前时刻”拉回过去；后续回合总是看最新红框，不能只看最右边的棋盘。',
    },
];
let tutorialData = null;
let tutorialIndex = 0;
let tutorialPhase = 'select';
let tutorialRequest = 0;
let tutorialOpener = null;
const tutorialCompleted = new Set();

function tutorialSeen() {
    try { return Boolean(localStorage.getItem(TUTORIAL_STORAGE_KEY)); } catch (_) { return false; }
}

function markTutorialSeen(value) {
    try { localStorage.setItem(TUTORIAL_STORAGE_KEY, value); } catch (_) { /* optional preference */ }
}

async function openTutorial() {
    const dialog = document.getElementById('tutorial-dialog');
    if (dialog.open) return;
    tutorialOpener = document.activeElement;
    dialog.showModal();
    if (tutorialData) {
        renderTutorial();
        return;
    }
    await loadTutorial();
}

async function loadTutorial() {
    const owner = ++tutorialRequest;
    const content = document.getElementById('tutorial-content');
    content.setAttribute('aria-busy', 'true');
    content.textContent = '正在准备练习棋盘…';
    document.getElementById('tutorial-next').disabled = true;
    document.getElementById('tutorial-reset').disabled = true;
    const result = await api('/api/tutorial');
    if (owner !== tutorialRequest || !document.getElementById('tutorial-dialog').open) return;
    content.setAttribute('aria-busy', 'false');
    if (isErrorResult(result) || !Array.isArray(result?.lessons) || result.lessons.length !== 3) {
        content.innerHTML = '<p role="alert">练习暂时无法加载。你的对局未受影响，可以重试或稍后再学。</p><button class="ghost-btn" onclick="loadTutorial()">重新加载</button>';
        return;
    }
    tutorialData = result.lessons;
    renderTutorial();
}

function closeTutorial(completed = false) {
    ++tutorialRequest;
    markTutorialSeen(completed ? 'completed' : 'dismissed');
    document.getElementById('tutorial-dialog').close();
    tutorialOpener?.focus();
}

function resetTutorialLesson() {
    if (!tutorialData) return;
    tutorialPhase = 'select';
    renderTutorial();
    document.getElementById('tutorial-dialog').scrollTop = 0;
    document.getElementById('tutorial-title').focus({preventScroll: true});
}

function nextTutorialLesson() {
    if (tutorialPhase !== 'done') return;
    if (tutorialIndex === 2) {
        closeTutorial(tutorialCompleted.size === 3);
        return;
    }
    tutorialIndex += 1;
    resetTutorialLesson();
}

function tutorialCell(key, x, y) {
    const move = tutorialData?.[tutorialIndex]?.move;
    if (!move) return;
    const expected = tutorialPhase === 'select' ? move.source : tutorialPhase === 'target' ? move.destination : null;
    if (!expected || expected.board.key !== key || expected.x !== x || expected.y !== y) return;
    tutorialPhase = tutorialPhase === 'select' ? 'target' : 'submit';
    renderTutorial();
}

function submitTutorialAction() {
    if (tutorialPhase !== 'submit' || !tutorialData?.[tutorialIndex]?.after_move.can_submit) return;
    tutorialPhase = 'done';
    tutorialCompleted.add(tutorialIndex);
    renderTutorial();
    document.getElementById('tutorial-next').focus();
}

function renderTutorial() {
    if (!tutorialData) return;
    const lesson = tutorialData[tutorialIndex];
    const copy = tutorialLessons[tutorialIndex];
    const moved = ['submit', 'done'].includes(tutorialPhase);
    const state = tutorialPhase === 'done' ? lesson.after_submit : moved ? lesson.after_move : lesson.before;
    document.getElementById('tutorial-title').textContent = copy.title;
    const nav = document.getElementById('tutorial-steps');
    nav.replaceChildren();
    tutorialLessons.forEach((item, index) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'tutorial-tab';
        button.textContent = `${tutorialCompleted.has(index) ? '✓ ' : ''}${item.title}`;
        button.setAttribute('aria-current', index === tutorialIndex ? 'step' : 'false');
        button.onclick = () => { tutorialIndex = index; resetTutorialLesson(); };
        nav.appendChild(button);
    });
    const instruction = tutorialPhase === 'select' ? copy.select : tutorialPhase === 'target' ? copy.target : tutorialPhase === 'submit' ? copy.moved : copy.done;
    const content = document.getElementById('tutorial-content');
    content.innerHTML = `<p class="tutorial-description">${escapeHtml(copy.description)}</p>
        <p class="tutorial-instruction" role="status">${escapeHtml(instruction)}</p>
        <div class="tutorial-state"><span>行动方：<strong>${colorLabel(state.turn)}</strong></span><span>当前需推进：<strong>${state.required_count} 张棋盘</strong></span></div>
        <div id="tutorial-boards" class="tutorial-boards"></div>
        <button id="tutorial-submit" class="submit-btn" onclick="submitTutorialAction()" ${tutorialPhase !== 'submit' ? 'disabled' : ''}>${tutorialPhase === 'done' ? '已提交 · 轮到黑方' : '提交行动'}</button>
        <details class="tutorial-rules"><summary>随时查阅：棋子与提交规则</summary>
            <p>棋子可沿棋盘横、纵、时间、时间线四个维度移动。车沿一维；象沿两维等距；后沿一至四维等距；王走同类方向一步；马在两维走 1+2。车、象、后的路径不能穿过棋子或缺失棋盘，马可以跳跃。</p>
            <p>兵直行、斜吃，不能倒退。跨线时白兵向更小的 L、黑兵向更大的 L 前进；跨时空吃子同时改变时间与时间线各一步。以选子后的合法落点为准。</p>
            <p>红框表示当前时刻需要推进的棋盘，移动后会重新计算。非活动时间线是可选走子，不决定当前时刻；新增分支也可能改变活动状态。</p>
            <p>提交时必须保护所有王，包括同一棋盘上的多个王和历史中的王。没有红框却仍不能提交时，请查看右侧的王安全提示。</p>
        </details>`;
    const keys = moved
        ? [lesson.move.result_source_board.key, lesson.move.result_destination_board.key,
            ...(tutorialIndex === 2 ? [lesson.move.destination.board.key] : [])]
        : [lesson.move.source.board.key, lesson.move.destination.board.key];
    const boards = document.getElementById('tutorial-boards');
    for (const key of [...new Set(keys)].sort((a, b) => Number(a.split(':')[0]) - Number(b.split(':')[0]) || Number(a.split(':')[1]) - Number(b.split(':')[1]))) {
        const board = state.boards.find(item => item.key === key);
        if (!board) continue;
        const card = document.createElement('section');
        card.className = `tutorial-board ${board.is_required ? 'required' : ''}`;
        const title = document.createElement('h3');
        title.textContent = `${coordLabel(board.coord)} · ${board.historical ? '历史' : '最新'}`;
        card.appendChild(title);
        const grid = document.createElement('div');
        grid.className = 'tutorial-grid';
        for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
            const cell = document.createElement('button');
            cell.type = 'button';
            const ch = board.board[y][x];
            const source = lesson.move.source, target = lesson.move.destination;
            const isSource = !moved && key === source.board.key && x === source.x && y === source.y;
            const isTarget = tutorialPhase === 'target' && key === target.board.key && x === target.x && y === target.y;
            const arrival = moved && key === lesson.move.result_destination_board.key && x === target.x && y === target.y;
            cell.className = `tutorial-cell ${(x + y) % 2 ? 'dark' : 'light'} ${ch ? pieceColor(ch) + '-piece' : ''}`;
            if (isSource) cell.classList.add('source');
            if (isTarget) cell.classList.add('target');
            if (arrival) cell.classList.add('arrival');
            cell.textContent = pieceSymbols[ch] || (isTarget ? '●' : '');
            cell.setAttribute('aria-label', `${coordLabel(board.coord)} ${'abcdefgh'[x]}${8-y}${isSource ? ' 选择棋子' : isTarget ? ' 移动到这里' : ''}`);
            cell.disabled = !(tutorialPhase === 'select' && isSource || isTarget);
            cell.onclick = () => tutorialCell(key, x, y);
            grid.appendChild(cell);
        }
        card.appendChild(grid);
        boards.appendChild(card);
    }
    const next = document.getElementById('tutorial-next');
    next.disabled = tutorialPhase !== 'done';
    next.textContent = tutorialPhase !== 'done' ? '完成本课后继续' : tutorialIndex === 2 ? '回到游戏' : '下一课 →';
    document.getElementById('tutorial-reset').disabled = false;
    document.getElementById('tutorial-close').textContent = tutorialPhase === 'done' && tutorialIndex === 2 ? '关闭教程' : '稍后再学';
    // Keep keyboard users on the next actionable square after rebuilding boards.
    if (tutorialPhase === 'target') content.querySelector('.tutorial-cell.target')?.focus();
    if (tutorialPhase === 'submit') document.getElementById('tutorial-submit').focus();
}

document.getElementById('tutorial-dialog').addEventListener('cancel', event => {
    event.preventDefault();
    closeTutorial();
});
if (!tutorialSeen() && !window.location.search) openTutorial();
