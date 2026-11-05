// A plain to-do list for the demo-video test: a real server with real state. The last routes exist
// to make a take fail on purpose.
import http from 'node:http';

const port = Number(process.env.PORT || 4173);
const todos = [];
const slowScript = process.env.SLOW_SCRIPT_MS ? '<script src=/slow.js></script>' : '';
const page = `<!doctype html><meta charset=utf-8><title>To-do</title>${slowScript}
<style>
 body{font:20px/1.5 system-ui,sans-serif;background:#f6f4ef;color:#1f1d1a;margin:0;display:grid;place-items:center;min-height:100vh}
 main{width:640px;background:#fff;border-radius:16px;padding:40px;box-shadow:0 10px 40px #0002}
 h1{margin:0 0 20px;font-size:40px} form{display:flex;gap:12px}
 input[type=text]{flex:1;font:inherit;padding:12px;border:1px solid #bbb;border-radius:8px}
 button{font:inherit;padding:12px 20px;border:0;border-radius:8px;background:#1f6f54;color:#fff;cursor:pointer}
 ul{list-style:none;padding:0;margin:24px 0 0} li{padding:12px 0;border-top:1px solid #eee;display:flex;gap:12px;align-items:center}
 li.done span{text-decoration:line-through;color:#888} #count{margin-top:16px;color:#555}
</style>
<main><h1>To-do</h1><form id=add><input id=new-item type=text placeholder="Add an item"><button>Add</button></form><ul id=items></ul><div id=count></div></main>
<script>
const input = document.getElementById('new-item');
const items = document.getElementById('items');
async function load() {
  const todos = await (await fetch('/api')).json();
  items.innerHTML = '';
  for (const todo of todos) {
    const row = document.createElement('li');
    if (todo.done) row.className = 'done';
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = todo.done;
    box.onchange = async () => { await fetch('/api/' + todo.id, { method: 'POST' }); load(); };
    const text = document.createElement('span');
    text.textContent = todo.text;
    row.append(box, text);
    items.append(row);
  }
  document.getElementById('count').textContent = todos.filter(todo => !todo.done).length + ' left';
}
document.getElementById('add').onsubmit = async event => {
  event.preventDefault();
  if (!input.value) return;
  await fetch('/api', { method: 'POST', body: input.value });
  input.value = '';
  load();
};
load();
</script>`;

let rootHits = 0;
http.createServer((request, response) => {
  let body = '';
  request.on('data', chunk => { body += chunk; });
  request.on('end', () => {
    if (request.url === '/') {
      rootHits += 1;
      response.setHeader('content-type', 'text/html');
      return void setTimeout(() => response.end(page), Number(process.env.SLOW_ROOT_MS || 0));
    }
    if (request.url === '/hits') return response.end(String(rootHits));
    if (request.url === '/api' && request.method === 'GET') return response.end(JSON.stringify(todos));
    if (request.url === '/api') {
      todos.push({ id: todos.length, text: body, done: false });
      return response.end('ok');
    }
    const toggle = request.url.match(/^\/api\/(\d+)$/);
    if (toggle && todos[toggle[1]]) {
      todos[toggle[1]].done = !todos[toggle[1]].done;
      return response.end('ok');
    }
    if (request.url === '/slow.js') return void setTimeout(() => response.end(''), Number(process.env.SLOW_SCRIPT_MS));
    if (request.url === '/boom') { response.statusCode = 500; return response.end(); }
    if (request.url === '/drop') return request.socket.destroy();
    if (request.url === '/die') process.exit(3);
    if (request.url === '/hang') return undefined;
    response.statusCode = 404;
    return response.end();
  });
}).listen(port, '127.0.0.1', () => console.log('listening', port));
