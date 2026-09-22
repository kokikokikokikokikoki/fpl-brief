import json
import time
import urllib.error
import urllib.request


BASE = "https://fantasy.premierleague.com/api"
HEADERS = {"User-Agent": "Mozilla/5.0 (fpl-brief fetcher)"}


class FetchError(RuntimeError):
    pass


class Client:
    def __init__(self, opener=urllib.request.urlopen, sleep=time.sleep):
        self.opener, self.sleep, self.cache = opener, sleep, {}

    def get(self, path):
        if path in self.cache:
            return self.cache[path]
        url = f"{BASE}/{path}"
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers=HEADERS)
                with self.opener(request, timeout=30) as response:
                    value = json.load(response)
                self.cache[path] = value
                return value
            except urllib.error.HTTPError as error:
                if error.code not in (429,) and error.code < 500:
                    raise FetchError(f"could not fetch {path}: HTTP {error.code}") from error
                retry_after = error.headers.get("Retry-After") if error.headers else None
                delay = min(int(retry_after), 10) if retry_after and retry_after.isdigit() else attempt + 1
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                delay = attempt + 1
            if attempt == 2:
                raise FetchError(f"could not fetch {path}: {error}") from error
            self.sleep(delay)

    def standings(self, league_id):
        results, seen_pages, page = [], set(), 1
        while True:
            if page in seen_pages:
                raise FetchError("league standings pagination repeated a page")
            seen_pages.add(page)
            payload = self.get(f"leagues-classic/{league_id}/standings/?page_standings={page}")
            page_results = payload.get("standings", {}).get("results", [])
            results.extend(page_results)
            if not payload.get("standings", {}).get("has_next"):
                break
            page += 1
        return list({row["entry"]: row for row in results}.values())
