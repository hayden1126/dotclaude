// fig-2-walk: two walks from A, A-B-C and A-C-B. An example of CHASSIS.md's step-through form,
// written by hand for the skill's sample hub. A hub generates its own step-figs.js and steps.json
// from the checker's trace (06-site, step 2), with the frames as data like WALKS here.
// Baseline as of 2026-10-20; changes only via `12-retro`.
(function(){
  var WALKS = { abc: ['A', 'B', 'C'], acb: ['A', 'C', 'B'] };
  window.NotesFig = window.NotesFig || {};
  window.NotesFig['fig-2-walk'] = function(act, btn, fig){
    var mode = fig.dataset.mode || 'abc', k = +(fig.dataset.step || 0);
    if (WALKS[act]) { mode = act; k = 0; }
    var walk = WALKS[mode];
    if (act === 'next' && k < walk.length - 1) k++;
    else if (act === 'prev' && k > 0) k--;
    fig.dataset.mode = mode;
    fig.dataset.step = k;
    ['A', 'B', 'C'].forEach(function(n){
      fig.querySelector('#fig-2-walk-' + n).setAttribute('class', walk.indexOf(n) <= k ? 'accbx' : 'bx fill-surf');
    });
    fig.querySelectorAll('.fig-controls button[data-act]').forEach(function(b){
      if (WALKS[b.dataset.act]) b.setAttribute('aria-pressed', b.dataset.act === mode ? 'true' : 'false');
    });
    fig.querySelector('.fs-status').innerHTML = k === 0 ? '<strong>Step 0.</strong> Start at A. Press Next.'
      : '<strong>Step ' + k + ' of ' + (walk.length - 1) + '.</strong> Walk ' + walk.slice(0, k + 1).join('-') +
        ': ' + k + (k === 1 ? ' edge.' : ' edges.');
    fig.querySelector('button[data-act="next"]').disabled = k === walk.length - 1;
    fig.querySelector('button[data-act="prev"]').disabled = k === 0;
  };
})();
