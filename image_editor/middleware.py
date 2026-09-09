import os
import traceback
import logging
from django.conf import settings
from django.http import HttpResponse

logger = logging.getLogger(__name__)

class ExceptionLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        tb = traceback.format_exc()
        log_file = os.path.join(settings.BASE_DIR, 'django_error.log')
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write("\n" + "="*55 + "\n")
                f.write(f"Exception on {request.method} {request.get_full_path()}\n")
                f.write(f"Exception: {type(exception).__name__}: {exception}\n")
                f.write(tb)
                f.write("="*55 + "\n")
        except Exception:
            pass

        logger.error(f"500 on {request.method} {request.get_full_path()}: {exception}\n{tb}")

        # If it is an admin request, return the formatted traceback directly
        if request.path.startswith('/admin/'):
            html = f"""<!DOCTYPE html>
<html>
<head><title>Admin Error: {type(exception).__name__}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8fafc; padding: 30px; }}
.card {{ max-width: 900px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); padding: 30px; border-left: 6px solid #ef4444; }}
h1 {{ color: #dc2626; font-size: 22px; margin-top: 0; }}
h2 {{ color: #1e293b; font-size: 16px; margin: 15px 0 5px 0; }}
pre {{ background: #1e293b; color: #f8fafc; padding: 20px; border-radius: 8px; overflow-x: auto; font-size: 13px; line-height: 1.5; }}
.back-btn {{ display: inline-block; margin-top: 20px; padding: 10px 20px; background: #3b82f6; color: white; text-decoration: none; border-radius: 6px; font-weight: 500; }}
</style>
</head>
<body>
<div class="card">
    <h1>Admin Server Error: {type(exception).__name__}</h1>
    <p><strong>Path:</strong> {request.method} {request.get_full_path()}</p>
    <p><strong>Message:</strong> {exception}</p>
    <h2>Traceback Details:</h2>
    <pre>{tb}</pre>
    <a href="/admin/" class="back-btn">&larr; Return to Admin Dashboard</a>
</div>
</body>
</html>"""
            return HttpResponse(html, status=500)
        return None
