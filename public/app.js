'use strict';
const form = document.querySelector('#chat-form');
const input = document.querySelector('#message');
const access = document.querySelector('#access-code');
const messages = document.querySelector('#messages');
const welcome = document.querySelector('#welcome');
const notice = document.querySelector('#notice');
const send = document.querySelector('#send');
let history = [];
let busy = false;

function bubble(role, text) {
  const el = document.createElement('div');
  el.className = `bubble ${role}`;
  const speaker = document.createElement('span');
  speaker.className = 'speaker';
  speaker.textContent = role === 'user' ? 'You' : 'Finance assistant';
  el.append(speaker);
  // No generated HTML is inserted. Links are constructed from validated http(s) URLs.
  const pattern = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|\*\*([^*\n]+)\*\*/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    el.append(document.createTextNode(text.slice(last, match.index)));
    const node = document.createElement(match[3] ? 'strong' : 'a');
    node.textContent = match[3] || match[1];
    if (!match[3]) { node.href = match[2]; node.target = '_blank'; node.rel = 'noopener noreferrer'; }
    el.append(node); last = match.index + match[0].length;
  }
  el.append(document.createTextNode(text.slice(last)));
  messages.append(el); messages.scrollTop = messages.scrollHeight;
  return el;
}

async function submit(question) {
  if (busy) return;
  if (!access.value.trim()) {
    notice.textContent = 'Enter your private access code to start chatting.';
    access.focus(); return;
  }
  if (!question.trim()) return;
  busy = true; send.disabled = true; notice.textContent = '';
  welcome.hidden = true;
  const userBubble = bubble('user', question);
  const pending = document.createElement('div'); pending.className = 'pending';
  pending.textContent = 'Thinking through your question…'; messages.append(pending);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 115000);
  try {
    const response = await fetch('/api/chat', {method:'POST',
      headers:{'Content-Type':'application/json', 'Authorization':`Bearer ${access.value.trim()}`},
      body:JSON.stringify({message:question,history}), signal:controller.signal});
    const result = await response.json();
    if (!response.ok) {
      const detail = typeof result.detail === 'string' ? result.detail : 'Please shorten your question or start a new chat.';
      throw new Error(detail);
    }
    pending.remove(); bubble('assistant', result.answer);
    if (result.tools_called.length) {
      const tool = document.createElement('div'); tool.className = 'tool-note';
      tool.textContent = `Tools used: ${result.tools_called.map(n => n.replaceAll('_',' ')).join(' · ')}`;
      messages.append(tool);
    }
    history.push({role:'user',content:question},{role:'assistant',content:result.answer.slice(0,6000)});
    history = history.slice(-12);
    while (history.reduce((n,m)=>n+m.content.length,0)>18000) history.splice(0,2);
    input.value = '';
  } catch (error) {
    pending.remove(); userBubble.remove();
    notice.textContent = error.name === 'AbortError' ? 'This request took too long. Please retry.' : error.message;
    if (!history.length) welcome.hidden = false;
  } finally {
    clearTimeout(timer); busy = false; send.disabled = false;
    messages.scrollTop = messages.scrollHeight;
  }
}
form.addEventListener('submit', event => {event.preventDefault(); submit(input.value);});
input.addEventListener('keydown', event => {if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();submit(input.value);}});
document.querySelectorAll('[data-prompt]').forEach(button => button.addEventListener('click',()=>{input.value=button.dataset.prompt;input.focus();}));
document.querySelector('#lock-toggle').addEventListener('click',()=>{access.value='';notice.textContent='Access code cleared from this tab.';access.focus();});
document.querySelector('#new-chat').addEventListener('click',()=>{
  if(busy)return;history=[];messages.querySelectorAll('.bubble,.tool-note,.pending').forEach(el=>el.remove());
  welcome.hidden=false;input.value='';notice.textContent='New chat started. Previous messages were cleared from this tab.';
});
