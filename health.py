"""Render HTTP listener: liveness is separate from Discord readiness."""
from aiohttp import web


def make_app(status):
    app = web.Application()

    async def health(request):
        return web.json_response(status(), headers={'Cache-Control': 'no-store'})

    async def ready(request):
        state = status()
        return web.json_response(state, status=200 if state['discord_ready'] and state['configured'] else 503,
                                 headers={'Cache-Control': 'no-store'})

    async def home(request):
        return web.Response(text='''<!doctype html><html><meta name="viewport" content="width=device-width">
<title>Clover Trading</title><style>body{font:18px system-ui;max-width:650px;margin:60px auto;padding:24px;background:#202225;color:#eee}a{color:#8fe2bc}</style>
<h1>Clover Trading</h1><p>This visit wakes the service if Render put it to sleep.</p>
<p><a href="/ready">Check Discord connection</a></p>
<p>Once discord_ready and configured are true, return to Discord and use /search.
The first search loads the last 24 hours of trading posts. If loading is still in progress, try /search again shortly.</p>
<p>A sleeping service cannot receive Discord Gateway commands. This page does not guarantee 24/7 uptime.</p></html>''', content_type='text/html', headers={'Cache-Control': 'no-store'})

    app.router.add_get('/', home)
    app.router.add_get('/health', health)
    app.router.add_get('/ready', ready)
    return app
