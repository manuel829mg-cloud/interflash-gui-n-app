"""Register Inter Flash TV inside the existing administration panel."""
def setup(flask_app):
    from inter_tv_native import setup as setup_native
    setup_native(flask_app)
