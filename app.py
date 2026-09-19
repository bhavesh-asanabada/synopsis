"""Run Synopsis locally with `python app.py`."""
from synopsis import create_app
from synopsis.cli import main

app = create_app()

if __name__ == '__main__':
    main(app)
