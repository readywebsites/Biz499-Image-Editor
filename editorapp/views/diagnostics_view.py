import os
import sys
import subprocess
from pathlib import Path
from django.conf import settings
from django.http import JsonResponse

def system_diagnostics_view(request):
    base_dir = Path(settings.BASE_DIR)
    
    git_info = 'unavailable'
    try:
        git_commit = subprocess.check_output(
            ['git', 'log', '-1', '--format=%h - %s (%ci)'],
            cwd=str(base_dir),
            text=True,
            timeout=3
        ).strip()
        git_info = git_commit
    except Exception as e:
        git_info = f'Error reading git: {e}'

    error_log_lines = []
    log_file = base_dir / 'django_error.log'
    if log_file.exists():
        try:
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                error_log_lines = f.readlines()[-40:]
        except Exception as e:
            error_log_lines = [f'Error reading log file: {e}']

    db_status = 'ok'
    try:
        from editorapp.models import Template
        count = Template.objects.count()
        db_status = f'Connected. Templates count: {count}'
    except Exception as e:
        db_status = f'DB Error: {e}'

    token = os.getenv('FIGMA_API_TOKEN') or getattr(settings, 'FIGMA_API_TOKEN', None)
    token_status = 'NOT CONFIGURED'
    if token and token != "your_figma_api_token_here":
        clean_tok = token.strip().strip('"\'')
        token_preview = f'Configured (length {len(clean_tok)})'
        try:
            import requests
            r = requests.get('https://api.figma.com/v1/me', headers={'X-Figma-Token': clean_tok}, timeout=3)
            if r.status_code == 200:
                user_info = r.json()
                token_status = f"VALID - Account: {user_info.get('email') or user_info.get('handle')}"
            else:
                err_text = r.json().get('err') or r.text
                token_status = f"INVALID/EXPIRED ({r.status_code}): {err_text}"
        except Exception as te:
            token_status = f"CHECK ERROR: {te}"
        tier1_status = 'not checked'
        try:
            r1 = requests.get(
                'https://api.figma.com/v1/files/BnSvyoOglXYZcUIu1eQCPy/nodes?ids=3:4',
                headers={'X-Figma-Token': clean_tok},
                timeout=5
            )
            retry_after = r1.headers.get('Retry-After')
            plan_tier = r1.headers.get('X-Figma-Plan-Tier')
            limit_type = r1.headers.get('X-Figma-Rate-Limit-Type')
            if r1.status_code == 200:
                tier1_status = f"OK (200) - Plan: {plan_tier or 'standard'}, Limit: {limit_type or 'standard'}"
            elif r1.status_code == 429:
                try:
                    sec = int(float(retry_after))
                    cooldown_str = f"{round(sec / 3600, 1)} hours" if sec >= 3600 else f"{sec}s"
                except Exception:
                    cooldown_str = f"{retry_after}s"
                tier1_status = f"RATE LIMITED (429) - Cooldown remaining: {cooldown_str}, Plan: {plan_tier}, Limit: {limit_type}"
            else:
                tier1_status = f"STATUS {r1.status_code}: {r1.text[:120]}"
        except Exception as e1:
            tier1_status = f"Error testing Tier 1: {e1}"
    else:
        token_preview = 'NOT CONFIGURED'
        tier1_status = 'Token not configured'

    return JsonResponse({
        'status': 'online',
        'git_commit': git_info,
        'python_version': sys.version,
        'db_status': db_status,
        'figma_token': token_preview,
        'figma_token_health': token_status,
        'figma_tier1_health': tier1_status,
        'recent_errors': [l.strip() for l in error_log_lines if l.strip()],
    }, json_dumps_params={'indent': 2})

