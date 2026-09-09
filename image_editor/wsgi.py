"""
WSGI config for image_editor project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os
import sys
import traceback
from pathlib import Path
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'image_editor.settings')

django_app = get_wsgi_application()

def application(environ, start_response):
    try:
        return django_app(environ, start_response)
    except Exception as e:
        tb = traceback.format_exc()
        base_dir = Path(__file__).resolve().parent.parent
        log_file = base_dir / 'django_error.log'
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*55}\nWSGI CRASH: {environ.get('REQUEST_METHOD')} {environ.get('PATH_INFO')}\n{tb}{'='*55}\n")
        except Exception:
            pass

        status = '500 Internal Server Error'
        body = f"""<!DOCTYPE html>
<html>
<head><title>500 Internal Server Error</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 40px; margin: 0; }}
.card {{ max-width: 960px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 32px; border-left: 6px solid #ef4444; }}
h1 {{ color: #ef4444; font-size: 24px; margin-top: 0; }}
p {{ font-size: 15px; color: #94a3b8; }}
strong {{ color: #f8fafc; }}
pre {{ background: #0f172a; padding: 20px; border-radius: 8px; overflow-x: auto; font-family: monospace; font-size: 13px; line-height: 1.5; color: #e2e8f0; }}
</style>
</head>
<body>
<div class="card">
    <h1>Internal Server Error: {type(e).__name__}</h1>
    <p><strong>Path:</strong> {environ.get('REQUEST_METHOD')} {environ.get('PATH_INFO')}</p>
    <p><strong>Message:</strong> {e}</p>
    <h2>Traceback Details:</h2>
    <pre>{tb}</pre>
</div>
</body>
</html>""".encode('utf-8')

        response_headers = [
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Content-Length', str(len(body))),
        ]
        start_response(status, response_headers)
        return [body]
