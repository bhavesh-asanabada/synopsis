"""Run Synopsis locally with `python app.py`."""
import os
from synopsis import create_app

app = create_app()

if __name__ == '__main__':
    from waitress import serve
    serve(app, host='127.0.0.1', port=int(os.environ.get('PORT', '5001')), threads=8)
