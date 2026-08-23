"""Raw X11 helpers (python-xlib) for what GTK4 no longer exposes.

Everything Xlib-flavoured is quarantined here: XTEST paste injection,
WM window dressing (dialog type, centering) and the XEmbed tray icon.
python-xlib ships no type stubs, so pyright checks this package at
reduced strength (see pyproject.toml).
"""
