import os
import re
import time
import logging
import requests
from urllib.parse import urlparse, parse_qs
from requests.exceptions import HTTPError
from django.conf import settings
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

def retry_request(func, max_tries=3, initial_delay=1.0):
    """Dependency-free exponential backoff retry for HTTP requests."""
    delay = initial_delay
    for attempt in range(1, max_tries + 1):
        try:
            return func()
        except HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if attempt < max_tries and status in (429, 500, 502, 503, 504):
                retry_after = e.response.headers.get('Retry-After') if e.response is not None else None
                sleep_time = delay
                if retry_after:
                    try:
                        sleep_time = min(30, int(retry_after))
                    except ValueError:
                        pass
                logger.warning(f"Figma API request returned {status}. Retrying in {sleep_time}s (attempt {attempt}/{max_tries})...")
                time.sleep(sleep_time)
                delay *= 2
            else:
                raise
        except requests.RequestException as e:
            if attempt < max_tries:
                logger.warning(f"Figma API network error: {e}. Retrying in {delay}s (attempt {attempt}/{max_tries})...")
                time.sleep(delay)
                delay *= 2
            else:
                raise

class FigmaService:
    API_BASE_URL = "https://api.figma.com/v1"

    def __init__(self, api_token=None):
        env_path = os.path.join(settings.BASE_DIR, '.env')
        load_dotenv(env_path, override=True)
        
        token = api_token or os.getenv('FIGMA_API_TOKEN') or getattr(settings, 'FIGMA_API_TOKEN', None)
        if token:
            token = token.strip().strip('"\'')
        self.api_token = token
        
        if not self.api_token or self.api_token == "your_figma_api_token_here":
            raise ValueError(
                "Figma API token is not configured. Please set FIGMA_API_TOKEN in your backend/.env file "
                "or enter your active Figma Personal Access Token."
            )
        self.headers = {"X-Figma-Token": self.api_token}

    def _handle_error(self, response, e):
        """A helper to format HTTP errors with actionable feedback."""
        try:
            error_details = response.json()
            msg = error_details.get('err') or error_details.get('message') or "Unknown Figma API error"
        except ValueError:
            msg = response.text

        is_token_issue = (
            response.status_code == 401 or
            "token" in msg.lower() or
            "expired" in msg.lower()
        )
        if is_token_issue:
            msg = (
                f"Figma API Token error ({msg}). "
                "Please update your FIGMA_API_TOKEN in backend/.env or provide a new Personal Access Token in the admin form."
            )
        elif response.status_code == 403:
            msg = f"Access denied to Figma file ({msg}). Please ensure your Figma account has permissions to view this file."
        elif response.status_code == 404:
            msg = f"Figma file or node was not found ({msg}). Please verify your Figma URL."
        elif response.status_code == 429:
            msg = f"Figma API rate limit exceeded ({msg}). Please wait a minute and try again."

        e.args = (f"Figma API Error ({response.status_code}): {msg}",)
        raise e

    def get_file(self, file_key):
        """Fetches full Figma file document."""
        url = f"{self.API_BASE_URL}/files/{file_key}"
        logger.info(f"Making Figma API call: GET {url}")

        def _fetch():
            response = requests.get(url, headers=self.headers, timeout=35)
            response.raise_for_status()
            return response.json()

        try:
            return retry_request(_fetch)
        except HTTPError as e:
            self._handle_error(e.response, e)

    def get_file_node(self, file_key, node_id):
        """Fetches a specific node subtree from a Figma file."""
        url = f"{self.API_BASE_URL}/files/{file_key}/nodes"
        params = {"ids": node_id}
        logger.info(f"Making Figma API call: GET {url}?ids={node_id}")

        def _fetch():
            response = requests.get(url, headers=self.headers, params=params, timeout=35)
            response.raise_for_status()
            return response.json()

        try:
            return retry_request(_fetch)
        except HTTPError as e:
            self._handle_error(e.response, e)

    def get_file_images(self, file_key):
        """Fetches image fills mapping (imageHash -> S3 URL) for a file key."""
        url = f"{self.API_BASE_URL}/files/{file_key}/images"
        logger.info(f"Making Figma API call: GET {url}")

        def _fetch():
            response = requests.get(url, headers=self.headers, timeout=35)
            response.raise_for_status()
            data = response.json()
            return data.get("meta", {}).get("images", {})

        try:
            return retry_request(_fetch)
        except HTTPError as e:
            logger.warning(f"Failed to fetch image fills mapping: {e}")
            return {}

    def export_nodes_as_svg(self, file_key, node_ids, chunk_size=30):
        """Batch exports custom vector and shape nodes as SVG."""
        if not node_ids:
            return {}
        result = {}
        for i in range(0, len(node_ids), chunk_size):
            chunk = node_ids[i:i + chunk_size]
            url = f"{self.API_BASE_URL}/images/{file_key}"
            params = {
                "ids": ",".join(chunk),
                "format": "svg"
            }
            logger.info(f"Exporting batch of {len(chunk)} SVG nodes: GET {url}")

            def _fetch():
                response = requests.get(url, headers=self.headers, params=params, timeout=45)
                response.raise_for_status()
                data = response.json()
                return data.get("images", {})

            try:
                images = retry_request(_fetch)
                result.update(images)
            except HTTPError as e:
                self._handle_error(e.response, e)
            if i + chunk_size < len(node_ids):
                time.sleep(0.5)
        return result

    def export_nodes_as_png(self, file_key, node_ids, scale=1, chunk_size=30):
        """Batch exports nodes (frames, masked groups, images) as PNG."""
        if not node_ids:
            return {}
        result = {}
        for i in range(0, len(node_ids), chunk_size):
            chunk = node_ids[i:i + chunk_size]
            url = f"{self.API_BASE_URL}/images/{file_key}"
            params = {
                "ids": ",".join(chunk),
                "format": "png",
                "scale": str(scale),
                "use_absolute_bounds": "true"
            }
            logger.info(f"Exporting batch of {len(chunk)} PNG nodes: GET {url}")

            def _fetch():
                response = requests.get(url, headers=self.headers, params=params, timeout=45)
                response.raise_for_status()
                data = response.json()
                return data.get("images", {})

            try:
                images = retry_request(_fetch)
                result.update(images)
            except HTTPError as e:
                self._handle_error(e.response, e)
            if i + chunk_size < len(node_ids):
                time.sleep(0.5)
        return result

    def export_node_as_png(self, file_key, node_id, scale=1):
        """Exports a single node from a Figma file as a PNG image."""
        res = self.export_nodes_as_png(file_key, [node_id], scale=scale)
        return res.get(node_id)

    @staticmethod
    def extract_file_key_from_url(url):
        """Extracts the file key from any Figma URL."""
        if not isinstance(url, str):
            return None
        match = re.search(r"figma\.com/(?:file|design|buzz|board|proto)/([a-zA-Z0-9_-]+)", url)
        if match:
            return match.group(1)
        match_fallback = re.search(r"figma\.com/[a-zA-Z0-9_-]+/([a-zA-Z0-9]{20,24})", url)
        if match_fallback:
            return match_fallback.group(1)
        return None