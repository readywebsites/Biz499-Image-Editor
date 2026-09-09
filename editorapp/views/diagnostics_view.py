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
    if token:
        token_preview = f'{token[:6]}...{token[-4:]} (length {len(token)})'
    else:
        token_preview = 'NOT CONFIGURED'

    return JsonResponse({
        'status': 'online',
        'git_commit': git_info,
        'python_version': sys.version,
        'db_status': db_status,
        'figma_token': token_preview,
        'recent_errors': [l.strip() for l in error_log_lines if l.strip()],
    }, json_dumps_params={'indent': 2})
