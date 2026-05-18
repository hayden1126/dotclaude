#!/usr/bin/env bash
input=$(cat)

python3 -c "
import sys, json, os
from datetime import date, timedelta

data = json.loads(sys.stdin.read())
model = data.get('model', {}).get('display_name', 'Claude')
used = data.get('context_window', {}).get('used_percentage')
session_id = data.get('session_id', '')
session_cost = float(data.get('cost', {}).get('total_cost_usd') or 0)
cwd = data.get('workspace', {}).get('current_dir') or data.get('cwd', os.getcwd())

import socket, getpass
user = getpass.getuser()
host = socket.gethostname().split('.')[0]

# agnoster-style identity: bold magenta user@host, bold blue cwd
identity = f'\033[1;35m{user}@{host}\033[0m:\033[1;34m{cwd}\033[0m'

cost_file = os.path.expanduser('~/.claude/daily-costs.json')
today = date.today().isoformat()

if os.path.exists(cost_file):
    with open(cost_file) as f:
        cost_data = json.load(f)
else:
    cost_data = {}

cutoff = (date.today() - timedelta(days=30)).isoformat()
cost_data = {k: v for k, v in cost_data.items() if k >= cutoff}

if today not in cost_data:
    cost_data[today] = {}
if session_id:
    cost_data[today][session_id] = session_cost

with open(cost_file, 'w') as f:
    json.dump(cost_data, f)

daily_total = sum(cost_data[today].values())

if daily_total < 0.005:
    cost_str = '\$0.00'
else:
    cost_str = f'~\${daily_total:.2f}'

if used is not None:
    filled = round(used * 20 / 100)
    empty = 20 - filled
    bar = '#' * filled + '-' * empty
    print(f'{identity}  \033[36m{model}\033[0m  [{bar}] \033[33m{used:.0f}%\033[0m used  \033[32m{cost_str}/day\033[0m')
else:
    print(f'{identity}  \033[36m{model}\033[0m  [--------------------] --% used  \033[32m{cost_str}/day\033[0m')
" <<< "$input" 2>/dev/null || printf "\033[1;35m$(whoami)@$(hostname -s)\033[0m:\033[1;34m$(pwd)\033[0m  \033[36mClaude\033[0m  [--------------------] --%% used  \033[32m\$0.00/day\033[0m"
