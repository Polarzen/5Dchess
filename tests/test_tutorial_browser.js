'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function client(saved = null) {
    const nodes = new Map();
    const node = () => ({open: false, disabled: false, textContent: '', innerHTML: '', children: [],
        setAttribute() {}, addEventListener() {}, focus() {}, classList: {add() {}},
        replaceChildren() { this.children = []; }, appendChild(child) { this.children.push(child); },
        showModal() { this.open = true; }, close() { this.open = false; }});
    const context = {Set, window: {location: {search: '?test=1'}},
        localStorage: {getItem() { return saved; }, setItem(k, v) { saved = v; context.saved = JSON.parse(v); }},
        document: {activeElement: node(), createElement: node, querySelector() { return null; }, getElementById(id) {
            if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id);
        }}, api: async () => ({version: 2, lessons: []}), isErrorResult: r => Boolean(r.error),
        escapeHtml: String, colorLabel: value => value, coordLabel: coord => coord.key,
        pieceColor: () => 'white', pieceSymbols: {P: '♙'}};
    vm.createContext(context);
    vm.runInContext(fs.readFileSync('src/web/static/js/tutorial.js', 'utf8'), context);
    return context;
}
const run = (c, code) => vm.runInContext(code, c);
const square = (lane, y) => ({board: {key: `${lane}:0`}, x: 4, y});
const move = (lane, rank) => ({source: square(lane, 6), destination: square(lane, rank),
    result_destination_board: {key: `${lane}:1`}, display_notation: `move ${lane} to ${rank}`});
const state = (remaining, turn = 'white') => ({boards: [], required_count: remaining, can_submit: remaining === 0 && turn === 'white', turn});
const quiz = {prompt: '选择正确答案', answers: ['错误', '正确'], correct: 1, explanation: '规则说明'};
function lessons() {
    const plans = [];
    for (const order of [[0, 1], [1, 0]]) for (const a of [4, 5]) for (const b of [4, 5]) {
        plans.push({steps: [a, b].map((rank, i) => ({move: move(order[i], rank), before: state(2-i), after_move: state(1-i)})), after_submit: state(2, 'black')});
    }
    return [{id: 'intro', title: '入门', description: '简介', points: ['一点'], quiz},
        {id: 'practice', title: '练习', description: '实践', points: ['两步'], quiz, plans, independent: true, success: '成功'}];
}
async function load(c, data = lessons()) {
    c.api = async path => {
        assert.equal(path, '/api/tutorial', 'practice must never call a live-game mutation');
        return {version: 2, lessons: data};
    };
    await run(c, 'openTutorial()');
}
(async () => {
    const c = client();
    let resolve;
    c.api = () => new Promise(done => { resolve = done; });
    const pending = run(c, 'openTutorial()');
    run(c, 'closeTutorial()');
    resolve({version: 2, lessons: lessons()});
    await pending;
    assert.equal(run(c, 'tutorialData'), null, 'late response cannot resurrect closed tutorial');
    assert.equal(c.saved.status, 'dismissed');

    await load(c);
    run(c, 'nextTutorialLesson(); answerTutorial(0)');
    assert.equal(run(c, 'tutorialIndex'), 0);
    assert.equal(run(c, 'tutorialPhase'), 'quiz');
    assert.equal(c.document.getElementById('tutorial-next').disabled, true);
    assert.match(c.document.getElementById('tutorial-content').innerHTML, /再想一想/);
    run(c, 'answerTutorial(1); nextTutorialLesson()');
    assert.equal(run(c, 'tutorialIndex'), 1);
    assert.equal(run(c, 'tutorialCompleted.size'), 1);
    run(c, "submitTutorialAction(); tutorialCell('0:0', 1, 1)");
    assert.equal(run(c, 'tutorialPhase'), 'select');
    // Choosing the second board first, and changing selection before moving.
    run(c, "tutorialCell('0:0', 4, 6); tutorialCell('1:0', 4, 6)");
    assert.equal(run(c, 'tutorialChoices().filter(m => tutorialSameSquare(m.source, tutorialSelection)).length'), 4);
    run(c, "tutorialCell('1:0', 4, 5); submitTutorialAction()");
    assert.equal(run(c, 'tutorialState().required_count'), 1);
    assert.equal(run(c, 'tutorialPhase'), 'select', 'submission must wait for all boards');
    run(c, 'undoTutorialMove()');
    assert.equal(run(c, 'tutorialState().required_count'), 2);
    run(c, "tutorialCell('1:0', 4, 6); tutorialCell('1:0', 4, 4); tutorialCell('0:0', 4, 6); tutorialCell('0:0', 4, 5)");
    assert.equal(run(c, 'tutorialPhase'), 'submit');
    assert.equal(run(c, 'tutorialState().turn'), 'white');
    run(c, 'answerTutorial(1)');
    assert.equal(run(c, 'tutorialPhase'), 'submit', 'quiz cannot bypass explicit submission');
    run(c, 'submitTutorialAction()');
    assert.equal(run(c, 'tutorialState().turn'), 'black');
    run(c, 'answerTutorial(1); nextTutorialLesson()');
    assert.equal(c.saved.status, 'completed');
    assert.equal(c.document.getElementById('tutorial-dialog').open, false);

    // Resume only known course IDs; a forged/stale entry is not completion.
    const resume = client(JSON.stringify({lesson: 'practice', completed: ['intro', 'obsolete']}));
    await load(resume);
    assert.equal(run(resume, 'tutorialIndex'), 1);
    assert.equal(run(resume, 'tutorialCompleted.size'), 1);
    assert.equal(run(resume, 'tutorialMoves.length'), 0);
    resume.localStorage.setItem = () => { throw new Error('storage disabled'); };
    run(resume, 'closeTutorial()');
    assert.equal(resume.document.getElementById('tutorial-dialog').open, false);

    const skipped = client();
    await load(skipped);
    run(skipped, "goTutorialLesson(1); tutorialCell('0:0',4,6); tutorialCell('0:0',4,4); tutorialCell('1:0',4,6); tutorialCell('1:0',4,4); submitTutorialAction(); answerTutorial(1); nextTutorialLesson()");
    assert.equal(run(skipped, 'tutorialIndex'), 0, 'finish sends learner to missing lessons');
    assert.notEqual(skipped.saved.status, 'completed');

    const failed = client();
    failed.api = async () => ({lessons: [{}, {}, {}]});
    await run(failed, 'openTutorial()');
    assert.match(failed.document.getElementById('tutorial-content').innerHTML, /重新加载/);
    assert.equal(run(failed, 'tutorialData'), null);
    console.log('Tutorial browser tests passed: gates, choices, undo, feedback, resume, isolation, races');
})().catch(error => { console.error(error); process.exitCode = 1; });
