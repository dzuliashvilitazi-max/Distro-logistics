import os

# server.py refuses to import without an explicit APP_ENV.
os.environ.setdefault("APP_ENV", "test")
