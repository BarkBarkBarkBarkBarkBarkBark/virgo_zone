"""Citations integration: VirgoZone drives the halloween-citations extension API.

VirgoZone never reads another installation's private extension data. It keeps its
own SQLite replica under DATA_DIR/citations and talks to the shared Supabase
workspace through the extension's own sync code, exactly like another device.
"""
