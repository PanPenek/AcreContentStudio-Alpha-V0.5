/**
 * overseer.js — the chat manager that produces videos end to end by calling tools.
 *
 * Protocol (works with any text model, incl. subscription CLIs without native tool calling):
 * the model answers JSON {say, actions:[{tool,args}], done}; we run the tools and feed the results back
 * as the next user message, up to MAX_STEPS per turn.
 */
const fs = require('fs');
const path = require('path');
const store = require('./store');
const llm = require('./llm');
const episodes = require('./episodes');
const pipeline = require('./pipeline');
const prompts = require('./prompts');
const characters = require('./characters');

const MAX_STEPS = 6;
let emit = () => {};
let busy = false;
function setEmitter(fn) { emit = fn; }

function history() { return store.read('overseer').messages; }
function push(msg) {
  const messages = [...history(), { ...msg, at: Date.now() }].slice(-200);
  store.write('overseer', { messages });
  emit('overseer', msg);
}

function stateSummary() {
  const eps = episodes.list().slice(0, 12).map((e) => `- ${e.id} "${e.title}" beats=${e.beats} audio=${e.hasAudio} stills=${e.hasStills} frames=${e.frames}/${e.framesNeeded ?? '?'} final=${e.hasFinal}${e.status?.state ? ` last=${e.status.stage}:${e.status.state}` : ''}`);
  const ideas = pipeline.ideas();
  const st = pipeline.status();
  return `EPISODES (${eps.length}):\n${eps.join('\n') || '(none)'}
IDEAS: ${ideas.length} total, ${ideas.filter((i) => i.status === 'new').length} new, ${ideas.filter((i) => i.status === 'approved').length} approved
QUEUE: running=${st.running ? st.running.label : 'none'}; queued=${st.queued.length}
CHARACTERS (current; trust this over older chat messages): ${characters.list().map((c) => `${c.id} (${c.built ? 'ready to host' : 'not built'})`).join(', ')}
SETS: ${Object.keys(episodes.VOCAB.sets).join(', ')}`;
}

const TOOLS = {
  list_episodes: () => episodes.list().map(({ id, title, beats, duration, hasFinal, status }) => ({ id, title, beats, duration, hasFinal, last: status?.stage && `${status.stage}:${status.state}` })),
  get_episode: ({ id }) => ({ episode: episodes.get(id), summary: episodes.summary(id) }),
  new_ideas: async ({ count = 5, theme = '' }) => (await pipeline.generateIdeas(count, theme)).map((i) => ({ id: i.id, title: i.title, hook: i.hook, score: i.score })),
  list_ideas: () => pipeline.ideas().slice(0, 40).map((i) => ({ id: i.id, title: i.title, status: i.status, score: i.score })),
  set_idea_status: ({ idea_id: id, status }) => pipeline.setIdeaStatus(id, status),
  write_script: async ({ idea_id: ideaId, topic }) => pipeline.writeScript({ ideaId, topic }),
  update_episode: ({ id, patch = {} }) => {
    const ep = episodes.get(id);
    if (!ep) throw new Error('unknown episode');
    const { beat_edits: edits, ...rest } = patch;
    Object.assign(ep, rest);
    for (const e of edits || []) ep.beats[e.index] = { ...ep.beats[e.index], ...e.set };
    const { episode, fixes } = episodes.validate(ep);
    episodes.save(id, episode);
    return { saved: true, fixes, note: 'text/timing changes need the audio stage again; staging-only changes just need stills/render' };
  },
  run_stage: ({ id, stage }) => pipeline.enqueue('stage', { episodeId: id, stage }, `${stage}: ${id}`),
  produce_episode: ({ idea_id: ideaId, topic }) => {
    if (ideaId) pipeline.setIdeaStatus(ideaId, 'queued');
    return pipeline.enqueue('produce', { ideaId, topic }, `produce: ${topic || ideaId}`);
  },
  review_stills: async ({ id }) => pipeline.reviewStills(id),
  fix_staging: ({ id, rounds }) => pipeline.enqueue('autofix', { episodeId: id, rounds: rounds || 1 }, `fix staging: ${id}`),
  job_status: () => {
    const s = pipeline.status();
    const slim = (j) => j && { id: j.id, label: j.label, state: j.state, progress: j.progress, message: j.message };
    return { running: slim(s.running), queued: s.queued.map(slim), recent: s.recent.map(slim) };
  },
  cancel_job: ({ job_id: id }) => pipeline.cancel(id),
  list_characters: () => characters.list(),
  rebuild_character: ({ id }) => characters.rebuild(id),
};

function trim(v, n = 3500) {
  const s = typeof v === 'string' ? v : JSON.stringify(v);
  return s.length > n ? s.slice(0, n) + '…(truncated)' : s;
}

async function turn(userText) {
  if (busy) throw new Error('Overseer is still working on the previous message');
  busy = true;
  emit('overseer-busy', true);
  push({ role: 'user', content: userText });
  try {
    // context: the last ~16 chat messages (tool results included, compact)
    const ctx = history().slice(-16).map((m) => ({ role: m.role === 'tool' ? 'user' : m.role, content: m.role === 'tool' ? `TOOL RESULTS:\n${m.content}` : m.content }));
    for (let step = 0; step < MAX_STEPS; step++) {
      const sys = prompts.overseerSystem(stateSummary());
      const r = await llm.chat('overseer', sys, ctx);
      let j;
      try { j = llm.extractJson(r.text); } catch { j = { say: r.text.trim(), actions: [], done: true }; }
      const say = j.say || '';
      const actions = Array.isArray(j.actions) ? j.actions : [];
      push({ role: 'assistant', content: say || '(working…)', provider: r.provider, actions: actions.map((a) => a.tool) });
      ctx.push({ role: 'assistant', content: JSON.stringify(j) });
      if (!actions.length || j.done === true && !actions.length) break;
      const results = [];
      for (const a of actions.slice(0, 6)) {
        const fn = TOOLS[a.tool];
        if (!fn) { results.push({ tool: a.tool, error: 'unknown tool' }); continue; }
        try { results.push({ tool: a.tool, ok: true, result: await fn(a.args || {}) }); } catch (e) { results.push({ tool: a.tool, ok: false, error: e.message }); }
      }
      // get_episode needs room for a whole script; everything else stays compact
      const txt = trim(results.map((x) => ({ ...x, result: x.result && trim(x.result, x.tool === 'get_episode' ? 9000 : 1500) })), 14000);
      push({ role: 'tool', content: txt });
      ctx.push({ role: 'user', content: `TOOL RESULTS:\n${txt}` });
      if (j.done === true) break;
    }
  } catch (e) {
    push({ role: 'assistant', content: `I hit an error: ${e.message}`, error: true });
  } finally {
    busy = false;
    emit('overseer-busy', false);
  }
}

function clear() { store.write('overseer', { messages: [] }); }

module.exports = { setEmitter, turn, history, clear, TOOLS, stateSummary };
