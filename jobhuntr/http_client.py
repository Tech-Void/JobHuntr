"""Small retrying HTTP client with one requests.Session per thread."""
import threading
import time

import requests

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
SHORT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124"
RETRY_STATUS = {429, 500, 502, 503, 504}


class Http:
    def __init__(self, retries: int = 3, timeout: int = 30):
        self.retries = retries
        self.timeout = timeout
        self._local = threading.local()

    @property
    def session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            s = requests.Session()
            s.headers["User-Agent"] = USER_AGENT
            self._local.session = s
        return self._local.session

    def get(self, url, **kw) -> requests.Response:
        return self.request("GET", url, **kw)

    def post(self, url, **kw) -> requests.Response:
        return self.request("POST", url, **kw)

    def request(self, method, url, **kw) -> requests.Response:
        kw.setdefault("timeout", self.timeout)
        last_error = None
        for attempt in range(self.retries):
            try:
                resp = self.session.request(method, url, **kw)
                if resp.status_code in RETRY_STATUS:
                    raise requests.HTTPError(f"HTTP {resp.status_code} from {url}")
                resp.raise_for_status()
                return resp
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
                last_error = e
                if isinstance(e, requests.HTTPError) and e.response is not None \
                        and e.response.status_code not in RETRY_STATUS:
                    break  # 4xx other than 429 will not get better by retrying
                time.sleep(1.5 * (attempt + 1))
        raise last_error
