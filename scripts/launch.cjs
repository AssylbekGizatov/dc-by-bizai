/* Cross-platform npm entry points; no shell interpolation or credentials in arguments. */
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
const python = path.join(root, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
if (!fs.existsSync(python)) { console.error('Create .venv and install backend/requirements-dev.txt first; see README.'); process.exit(2); }
function run(command, args, env = {}) {
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit', env: { ...process.env, PYTHONUTF8:'1', ...env } });
  if (result.error) { console.error(result.error.message); process.exit(2); }
  if (result.status !== 0) process.exit(result.status || 1);
}
function npm(args) {
  if (!process.env.npm_execpath) throw Error('Invoke through npm run, so its CLI path is known.');
  run(process.execPath, [process.env.npm_execpath, '--prefix', 'frontend', ...args]);
}
switch (process.argv[2]) {
  case 'dev': run(python,['scripts/with_env.py',python,'scripts/dev.py',...process.argv.slice(3)]);break;
  case 'serve': run(python,['scripts/with_env.py',python,'-m','uvicorn','app.main:app','--app-dir','backend','--host','127.0.0.1','--port',process.env.PORT||'8000','--no-access-log','--no-proxy-headers'], {FRONTEND_DIST:path.join(root,'frontend/dist')});break;
  case 'test':
    run(python,['-m','pytest','-q','backend/tests','scripts/tests'],{APP_MODE:'test',ENABLE_GROQ:'false',PYTHONPATH:'backend'});
    npm(['test']);npm(['run','build']);run(python,['scripts/check_release.py']);break;
  case 'e2e': run(python,['scripts/run_e2e.py',...process.argv.slice(3)]);break;
  default: console.error('Unknown task');process.exit(2);
}
