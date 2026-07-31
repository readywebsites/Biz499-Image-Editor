import requests
from django.conf import settings
import re
import backoff
import logging
import time
from requests.exceptions import HTTPError

logger = logging.getLogger(__name__)

def _is_rate_limit_error(e):
    """Check if the exception is a rate limit error (status code 429)."""
    is_http_error = isinstance(e, HTTPError)
    if is_http_error and e.response.status_code == 429:
        # Check if Retry-After is too large
        retry_after = e.response.headers.get('Retry-After')
        if retry_after:
            try:
                seconds = int(retry_after)
                if seconds > 30:
                    logger.warning(f"Figma API rate limit exceeded. Retry-After is too large ({seconds}s). Giving up.")
                    return False
            except ValueError:
                pass
        logger.warning("Figma API rate limit exceeded. Retrying with backoff...")
        return True
    return False

class FigmaService:
    API_BASE_URL = "https://api.figma.com/v1"

    def __init__(self, api_token=None):
        import os
        from dotenv import load_dotenv
        env_path = os.path.join(settings.BASE_DIR, '.env')
        load_dotenv(env_path, override=True)
        
        token = api_token or os.getenv('FIGMA_API_TOKEN') or settings.FIGMA_API_TOKEN
        if token:
            token = token.strip().strip('"\'')
        self.api_token = token
        
        if not self.api_token or self.api_token == "your_figma_api_token_here":
            raise ValueError("Figma API token is not configured. Please set it in your .env file.")
        self.headers = {"X-Figma-Token": self.api_token}

    def _handle_error(self, response, e):
        """A helper to format HTTP errors."""
        try:
            error_details = response.json()
            msg = error_details.get('err') or error_details.get('message') or "Unknown Figma API error"
        except ValueError:
            msg = response.text
        e.args = (f"Figma API Error: {msg}",)
        raise e

    @backoff.on_exception(backoff.expo, HTTPError, max_tries=15, giveup=lambda e: not _is_rate_limit_error(e))
    def get_file(self, file_key):
        """Fetches a Figma file document, with exponential backoff on rate limits."""
        url = f"{self.API_BASE_URL}/files/{file_key}"
        logger.info(f"Making Figma API call: GET {url}")
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except HTTPError as e:
            self._handle_error(e.response, e)

    @backoff.on_exception(backoff.expo, HTTPError, max_tries=15, giveup=lambda e: not _is_rate_limit_error(e))
    def get_file_images(self, file_key):
        """Fetches the image assets mapping (imageHash -> S3 URL) for a file key in a single request."""
        url = f"{self.API_BASE_URL}/files/{file_key}/images"
        logger.info(f"Making Figma API call: GET {url}")
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            return data.get("meta", {}).get("images", {})
        except HTTPError as e:
            self._handle_error(e.response, e)

    def get_image_urls(self, file_key, ids, chunk_size=50):
        """
        Fetches temporary URLs for image fills in batches.
        Uses exponential backoff for each batch request.
        """
        if not ids:
            return {}
        all_images = {}
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i:i + chunk_size]
            try:
                image_chunk = self._get_image_url_chunk(file_key, chunk)
                all_images.update(image_chunk)
                time.sleep(2)  # Add a 2-second delay between chunk requests
            except HTTPError as e:
                self._handle_error(e.response, e)
        return all_images

    @backoff.on_exception(backoff.expo, HTTPError, max_tries=15, giveup=lambda e: not _is_rate_limit_error(e))
    def _get_image_url_chunk(self, file_key, chunk):
        """Helper method to fetch a single chunk of image URLs."""
        url = f"{self.API_BASE_URL}/images/{file_key}"
        params = {"ids": ",".join(chunk)}
        logger.info(f"Making Figma API call: GET {url} (chunk of {len(chunk)} images)")
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        data = response.json()
        if data.get("err"):
            raise Exception(f"Figma API error while fetching images: {data['err']}")
        return data.get("images", {})

    @staticmethod
    def extract_file_key_from_url(url):
        """Extracts the file key from a Figma URL."""
        if not isinstance(url, str):
            return None
        # Match figma.com followed by any path segment (like file/design/buzz/board/proto) and then the key
        match = re.search(r"figma\.com/(?:file|design|buzz|board|proto)/([a-zA-Z0-9_-]+)", url)
        if match:
            return match.group(1)
        # Fallback: if there is a 20-24 character alpha-numeric key in the URL path, extract it
        match_fallback = re.search(r"figma\.com/[a-zA-Z0-9_-]+/([a-zA-Z0-9]{20,24})", url)
        if match_fallback:
            return match_fallback.group(1)
        return None

    @backoff.on_exception(backoff.expo, HTTPError, max_tries=5, giveup=lambda e: not _is_rate_limit_error(e))
    def export_node_as_png(self, file_key, node_id):
        """Exports a specific node from a Figma file as a PNG image."""
        url = f"{self.API_BASE_URL}/images/{file_key}"
        params = {
            "ids": node_id,
            "format": "png",
            "scale": "1",
            "use_absolute_bounds": "true"
        }
        logger.info(f"Making Figma API call: GET {url} for node {node_id}")
        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            if data.get("err"):
                raise Exception(f"Figma API error while exporting node: {data['err']}")
            return data.get("images", {}).get(node_id)
        except HTTPError as e:
            self._handle_error(e.response, e)