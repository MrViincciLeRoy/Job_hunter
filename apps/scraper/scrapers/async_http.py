try:
    import aiohttp
except ImportError:
    aiohttp = None

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-ZA,en;q=0.9",
}


async def fetch_many(urls, timeout=15, max_concurrent=12):
    if aiohttp is None:
        return {}
    sem = asyncio.Semaphore(max_concurrent)
    connector = aiohttp.TCPConnector(limit=max_concurrent, ssl=False)
    results = {}

    async def _fetch(session, url):
        async with sem:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                    results[url] = await r.text(errors="replace")
            except Exception:
                results[url] = ""

    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        await asyncio.gather(*[_fetch(session, u) for u in urls])

    return results


def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(1) as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def parallel_fetch(urls, fn, max_workers=10):
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fn, url): url for url in urls}
        for future in as_completed(futures):
            try:
                r = future.result()
                if r:
                    results.append(r)
            except Exception:
                pass
    return results


def parallel_run(fns_args, max_workers=6):
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fn, *args): (fn, args) for fn, *args in fns_args}
        for future in as_completed(futures):
            try:
                r = future.result()
                if r is not None:
                    results.append(r)
            except Exception:
                pass
    return results