'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function client() {
    const nodes = new Map();
    const node = () => ({open: false, disabled: false, textContent: '', innerHTML: '',
        setAttribute() {}, addEventListener() {}, focus() {},
        showModal() { this.open = true; }, close() { this.open = false; }});
    const context = {Set, window: {location: {search: ''}},
        localStorage: {getItem() { return 'dismissed'; }, setItem(k, v) { context.saved = v; }},
        document: {activeElement: node(), getElementById(id) {
            if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id);
        }},
        api: async () => ({lessons: []}), isErrorResult: r => Boolean(r.error)};
    vm.createContext(context);
    vm.runInContext(fs.readFileSync('src/web/static/js/tutorial.js', 'utf8'), context);
    vm.runInContext('renderTutorial = () => { renders = (typeof renders === "undefined" ? 0 : renders) + 1; }', context);
    return context;
}

(async () => {
    const context = client();
    let resolve;
    context.api = () => new Promise(done => { resolve = done; });
    const pending = vm.runInContext('openTutorial()', context);
    assert(context.document.getElementById('tutorial-dialog').open);
    vm.runInContext('closeTutorial()', context);
    resolve({lessons: [{}, {}, {}]});
    await pending;
    assert.equal(context.saved, 'dismissed');
    assert.equal(vm.runInContext('tutorialData', context), null, 'late response must not resurrect a closed tutorial');
    assert.equal(context.document.getElementById('tutorial-dialog').open, false);

    context.api = async path => {
        assert.equal(path, '/api/tutorial', 'practice must never send a live-game mutation');
        return {lessons: [0, 1, 2].map(() => ({move: {
            source: {board: {key: '0:0'}, x: 3, y: 4},
            destination: {board: {key: '1:0'}, x: 3, y: 4}}, after_move: {can_submit: true}}))};
    };
    await vm.runInContext('openTutorial()', context);
    vm.runInContext('submitTutorialAction(); nextTutorialLesson()', context);
    assert.equal(vm.runInContext('tutorialIndex', context), 0, 'cannot advance before doing the lesson');
    vm.runInContext("tutorialCell('0:0', 2, 4)", context);
    assert.equal(vm.runInContext('tutorialPhase', context), 'select');
    vm.runInContext("tutorialCell('0:0', 3, 4); tutorialCell('1:0', 3, 4)", context);
    assert.equal(vm.runInContext('tutorialPhase', context), 'submit');
    vm.runInContext('submitTutorialAction(); nextTutorialLesson()', context);
    assert.equal(vm.runInContext('tutorialIndex', context), 1);
    assert.equal(vm.runInContext('tutorialCompleted.size', context), 1);
    context.localStorage.setItem = () => { throw new Error('storage disabled'); };
    vm.runInContext('closeTutorial()', context);
    assert.equal(context.document.getElementById('tutorial-dialog').open, false);
    console.log('Tutorial browser tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
