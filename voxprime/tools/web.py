"""
Web tools — search, fetch pages, and get news.
"""

import httpx
import asyncio


def register(mcp):

    @mcp.tool()
    async def fetch_url(url: str) -> str:
        """
        Fetch a URL and return readable page text (HTML → markdown/plain).
        """
        from voxprime.core.media_ingest import fetch_webpage_markdown

        return fetch_webpage_markdown(url)

    @mcp.tool()
    async def search_web(query: str) -> str:
        """
        Search the web for a given query.
        Uses DuckDuckGo HTML interface for simple searches.
        Returns a summary of top results.
        """
        # Simple DuckDuckGo search via HTML scrape
        # For production, consider using Tavily API or similar
        search_url = f"https://html.duckduckgo.com/html/?q={httpx.URL(query)}"

        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            try:
                response = await client.get(search_url)
                response.raise_for_status()
                content = response.text

                # Extract result titles (simple parsing)
                results = []
                import re
                title_pattern = re.compile(r'<a class="result__a" href="[^"]*">([^<]+)</a>')
                for match in title_pattern.findall(content)[:5]:
                    results.append(match)

                if results:
                    return "Search results:\n" + "\n".join(f"- {r}" for r in results)
                return "No results found."
            except Exception as e:
                return f"Error performing search: {e}"

    @mcp.tool()
    async def get_weather(city: str) -> str:
        """
        Get current weather for a city.
        Uses wttr.in for weather data (no API key required).
        """
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                response = await client.get(f"https://wttr.in/{city}?format=%C+%t")
                response.raise_for_status()
                return f"Weather in {city}: {response.text.strip()}"
            except Exception as e:
                return f"Error fetching weather: {e}"
