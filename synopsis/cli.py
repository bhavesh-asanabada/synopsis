"""Console entry point: running `synopsis` starts the server and opens it in the browser."""
import os
import threading
import webbrowser

from waitress import serve

from . import create_app


def main(app=None):
    app = app or create_app()
    port = int(os.environ.get('PORT', '5001'))
    url = f'http://127.0.0.1:{port}'
    print(f'Synopsis is running at {url} (press Ctrl+C to stop)')
    if not os.environ.get('SYNOPSIS_NO_BROWSER'):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    serve(app, host='127.0.0.1', port=port, threads=8)


if __name__ == '__main__':
    main()
