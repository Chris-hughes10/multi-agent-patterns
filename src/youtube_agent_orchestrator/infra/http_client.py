"""HTTP client for fetching web content."""

import httpx

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


async def fetch_html(url: str, timeout: float = 10.0) -> str:
    """Fetch HTML content from a URL with browser-like headers.

    :param url: The URL to fetch
    :param timeout: Request timeout in seconds (default 10.0)
    :return: The HTML content as a string
    :raises httpx.HTTPStatusError: If the response status is an error
    :raises httpx.RequestError: If the request fails
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=_DEFAULT_HEADERS, timeout=timeout)
        response.raise_for_status()
        return response.text
