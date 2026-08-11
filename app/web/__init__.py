"""Server-rendered dashboard.

Jinja2 templates with hand-written CSS and a small vanilla-JS file. No build
step and no CDN, so the portal works on a Droplet with no outbound internet
access and deploys as part of the same service as the webhook.
"""

from app.web.routes import router
from app.web.templating import register, render, system_health

__all__ = ["router", "register", "render", "system_health"]
