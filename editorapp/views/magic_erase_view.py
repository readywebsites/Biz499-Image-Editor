import base64
import cv2
import numpy as np
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

@api_view(['POST'])
def magic_erase_view(request):
    """
    Intelligent Context-Aware AI Magic Eraser Endpoint.
    
    Intelligence:
    1. Analyzes the surrounding neighborhood (ring) of the user's brush mask selection.
    2. If the selected object (e.g., lanyard strap, clip, hanging thread) borders or extends into
       background / transparent space:
       -> Erases the object COMPLETELY and makes it 100% TRANSPARENT (zero background residual color).
    3. If the selected object (e.g., text line, logo, stain) is INSIDE a solid foreground subject (card/product):
       -> Inpaints the texture seamlessly using the surrounding card surface without altering transparency.
    """
    try:
        data = request.data
        image_data = data.get('image')
        mask_data = data.get('mask')
        method = data.get('inpaint_method', 'telea')

        if not image_data or not mask_data:
            return Response({'error': 'Both image and mask are required'}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Decode base64 image (preserving RGBA if present)
        if ',' in image_data:
            image_data = image_data.split(',')[1]
        img_bytes = base64.b64decode(image_data)
        img_np = np.frombuffer(img_bytes, np.uint8)
        img_rgba = cv2.imdecode(img_np, cv2.IMREAD_UNCHANGED)

        if img_rgba is None:
            return Response({'error': 'Invalid image payload'}, status=status.HTTP_400_BAD_REQUEST)

        has_alpha = False
        alpha_channel = None

        if len(img_rgba.shape) == 3 and img_rgba.shape[2] == 4:
            has_alpha = True
            img_bgr = img_rgba[:, :, :3].copy()
            alpha_channel = img_rgba[:, :, 3].copy()
        elif len(img_rgba.shape) == 3:
            img_bgr = img_rgba.copy()
            alpha_channel = np.full(img_rgba.shape[:2], 255, dtype=np.uint8)
        else:
            img_bgr = cv2.cvtColor(img_rgba, cv2.COLOR_GRAY2BGR)
            alpha_channel = np.full(img_rgba.shape[:2], 255, dtype=np.uint8)

        h, w = img_bgr.shape[:2]

        # 2. Decode base64 mask
        if ',' in mask_data:
            mask_data = mask_data.split(',')[1]
        mask_bytes = base64.b64decode(mask_data)
        mask_np = np.frombuffer(mask_bytes, np.uint8)
        mask_img = cv2.imdecode(mask_np, cv2.IMREAD_UNCHANGED)

        if mask_img is None:
            return Response({'error': 'Invalid mask payload'}, status=status.HTTP_400_BAD_REQUEST)

        if len(mask_img.shape) == 3 and mask_img.shape[2] == 4:
            mask_gray = mask_img[:, :, 3]
        elif len(mask_img.shape) == 3:
            mask_gray = cv2.cvtColor(mask_img, cv2.COLOR_BGR2GRAY)
        else:
            mask_gray = mask_img

        if mask_gray.shape[:2] != (h, w):
            mask_gray = cv2.resize(mask_gray, (w, h), interpolation=cv2.INTER_NEAREST)

        _, mask_binary = cv2.threshold(mask_gray, 10, 255, cv2.THRESH_BINARY)

        if cv2.countNonZero(mask_binary) == 0:
            return Response({'success': True, 'result_image': request.data.get('image')})

        # 3. Mask Dilation for smooth antialiased coverage
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        dilated_mask = cv2.dilate(mask_binary, kernel, iterations=1)

        # 4. Background Detection (Alpha transparency or Canvas Background Color)
        bg_mask = (alpha_channel < 50).astype(np.uint8) * 255

        # Check if background is solid uniform canvas color (for 3-channel images)
        corner_bg = img_bgr[5, 5]
        color_diff = np.linalg.norm(img_bgr.astype(np.float32) - corner_bg.astype(np.float32), axis=2)
        canvas_bg_mask = (color_diff < 15.0).astype(np.uint8) * 255
        
        is_bg_pixel = cv2.bitwise_or(bg_mask, canvas_bg_mask)

        # 5. Surrounding Ring Analysis around the user mask
        ring_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
        outer_ring = cv2.dilate(dilated_mask, ring_kernel, iterations=1)
        ring = cv2.subtract(outer_ring, dilated_mask)

        ring_bg_pixels = cv2.countNonZero(cv2.bitwise_and(ring, is_bg_pixel))
        ring_total_pixels = cv2.countNonZero(ring)
        transparent_ratio = ring_bg_pixels / float(ring_total_pixels) if ring_total_pixels > 0 else 0

        mask_touches_bg = cv2.countNonZero(cv2.bitwise_and(dilated_mask, is_bg_pixel)) > 0

        # 6. Intelligent Context-Aware Erase & Inpaint Engine
        result_bgr = img_bgr.copy()
        result_alpha = alpha_channel.copy()

        if transparent_ratio >= 0.12 or mask_touches_bg:
            # MODE A: External Projection / Strap / Border Object Erase
            # Make the erased region 100% TRANSPARENT!
            
            # Clean BGR from foreground neighbors to prevent background bleeding onto subject edges
            fg_ring_mask = cv2.subtract(ring, is_bg_pixel)
            bgr_clean = img_bgr.copy()
            if cv2.countNonZero(fg_ring_mask) > 0:
                bgr_clean = cv2.inpaint(bgr_clean, is_bg_pixel, 7, cv2.INPAINT_TELEA)

            # Inpaint BGR in user mask region using cleaned foreground
            if method == 'ns':
                result_bgr = cv2.inpaint(bgr_clean, dilated_mask, 5, cv2.INPAINT_NS)
            else:
                result_bgr = cv2.inpaint(bgr_clean, dilated_mask, 5, cv2.INPAINT_TELEA)

            # Update Alpha Channel: Erase to transparent inside dilated_mask with smooth feathering
            mask_float = dilated_mask.astype(np.float32) / 255.0
            mask_blurred = cv2.GaussianBlur(mask_float, (5, 5), 0)
            
            alpha_float = result_alpha.astype(np.float32)
            result_alpha = np.clip(alpha_float * (1.0 - mask_blurred), 0, 255).astype(np.uint8)

        else:
            # MODE B: Internal Foreground Feature Inpainting (preserving card/subject surface)
            if method == 'ns':
                result_bgr = cv2.inpaint(img_bgr, dilated_mask, 5, cv2.INPAINT_NS)
            else:
                result_bgr = cv2.inpaint(img_bgr, dilated_mask, 5, cv2.INPAINT_TELEA)

        # 7. Construct final RGBA output
        final_rgba = cv2.merge([result_bgr[:, :, 0], result_bgr[:, :, 1], result_bgr[:, :, 2], result_alpha])

        _, buffer = cv2.imencode('.png', final_rgba)
        res_base64 = base64.b64encode(buffer).decode('utf-8')
        result_data_url = f"data:image/png;base64,{res_base64}"

        return Response({
            'success': True,
            'result_image': result_data_url
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
