import requests
from django.http import HttpResponse, Http404
from ..models import Template

def find_node_by_hash(node, image_hash):
    if not isinstance(node, dict):
        return None
    # Check fills
    fills = node.get('fills', [])
    for fill in fills:
        if isinstance(fill, dict) and fill.get('type') == 'IMAGE' and fill.get('imageHash') == image_hash:
            return node
    # Check children
    for child in node.get('children', node.get('elements', [])):
        found = find_node_by_hash(child, image_hash)
        if found:
            return found
    return None

def find_node_src_by_id(node, node_id):
    if not isinstance(node, dict):
        return None
    if node.get('id') == node_id and node.get('src'):
        return node.get('src')
    for child in node.get('children', node.get('elements', [])):
        found = find_node_src_by_id(child, node_id)
        if found:
            return found
    return None

def serve_image(request, image_hash):
    # Find node ID from templates that have imageHash
    node_id = None
    for template in Template.objects.all():
        found_node = find_node_by_hash(template.template_data, image_hash)
        if found_node:
            node_id = found_node.get('id')
            break
            
    if not node_id:
        raise Http404("Image hash not found in any template")
        
    # Find src URL from templates that have src for this node ID
    src_url = None
    for template in Template.objects.all():
        src_url = find_node_src_by_id(template.template_data, node_id)
        if src_url:
            break
            
    if not src_url:
        raise Http404("Image source URL not found for node ID")
        
    # Define local cache path
    import os
    from django.conf import settings
    cache_dir = os.path.join(settings.BASE_DIR, 'image_cache')
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"{image_hash}.png")
    
    # Serve from local cache if exists
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'rb') as f:
                content = f.read()
            django_response = HttpResponse(content, content_type='image/png')
            django_response["Access-Control-Allow-Origin"] = "*"
            return django_response
        except Exception:
            pass
            
    # Proxy and cache the image directly to avoid CORS and redirect issues
    try:
        response = requests.get(src_url, timeout=15)
        response.raise_for_status()
        content = response.content
        
        # Save to local cache
        try:
            with open(cache_path, 'wb') as f:
                f.write(content)
        except Exception:
            pass
            
        django_response = HttpResponse(content, content_type=response.headers.get('Content-Type', 'image/png'))
        django_response["Access-Control-Allow-Origin"] = "*"
        return django_response
    except Exception as e:
        raise Http404(f"Error fetching image: {e}")

def serve_icon(request, provider, name):
    color = request.GET.get('color', '#ffffff')
    url = f"https://api.iconify.design/{provider}/{name}.svg?color={color.replace('#', '%23')}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        django_response = HttpResponse(response.content, content_type='image/svg+xml')
        django_response["Access-Control-Allow-Origin"] = "*"
        return django_response
    except Exception as e:
        raise Http404(f"Error fetching icon: {e}")

from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import uuid
import os
from django.conf import settings

@csrf_exempt
def upload_image_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST method is allowed'}, status=405)
        
    uploaded_file = request.FILES.get('image')
    if not uploaded_file:
        return JsonResponse({'error': 'No image file provided'}, status=400)
        
    upload_dir = os.path.join(settings.MEDIA_ROOT, 'user_uploads')
    os.makedirs(upload_dir, exist_ok=True)
    
    ext = os.path.splitext(uploaded_file.name)[1] or '.png'
    filename = f"{uuid.uuid4()}{ext}"
    filepath = os.path.join(upload_dir, filename)
    
    try:
        with open(filepath, 'wb+') as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)
    except Exception as e:
        return JsonResponse({'error': f'Failed to write file: {str(e)}'}, status=500)
        
    file_url = f"{settings.MEDIA_URL}user_uploads/{filename}"
    return JsonResponse({'url': file_url})
