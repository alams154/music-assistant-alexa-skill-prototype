from flask import Response, request, jsonify, render_template_string
from typing import Dict, Any


OPENAPI_SPEC: Dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Music Assistant Alexa API", "version": "1.0.0"},
    "paths": {
        "/ma/push-url": {
            "post": {
                "summary": "Accept stream metadata push",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "streamUrl": {"type": "string"},
                                    "title": {"type": "string"},
                                    "artist": {"type": "string"},
                                    "album": {"type": "string"},
                                    "imageUrl": {"type": "string"},
                                },
                                "required": ["streamUrl"],
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "ok"},
                    "400": {"description": "Missing required fields"},
                },
            }
        },
        "/ma/latest-url": {
            "get": {
                "summary": "Get last pushed stream metadata",
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {"type": "object"},
                                "example": {
                                    "streamUrl": "https://example.com/stream.mp3",
                                    "title": "Example Song",
                                    "artist": "Example Artist",
                                    "album": "Example Album",
                                    "imageUrl": "https://example.com/cover.jpg",
                                },
                            }
                        },
                    },
                    "404": {"description": "No URL available"},
                },
            }
        },
    },
}


def openapi_spec() -> Response:
    """Return the OpenAPI 3 spec describing the API for Swagger UI.

    Keeping the spec together with the UI code makes it easy to update and
    prevents duplication elsewhere in the project.
    """
    return jsonify(OPENAPI_SPEC)


_HTML_TEMPLATE = """<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Music Assistant Alexa API Docs</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/4.15.5/swagger-ui.min.css" />
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/4.15.5/swagger-ui-bundle.min.js"></script>
  <script>
    window.onload = function() {
      const ui = SwaggerUIBundle({
        url: "{{ openapi_url }}",
        dom_id: "#swagger-ui",
        deepLinking: true
      });
    }
  </script>
</body>
</html>
"""


def render() -> Response:
    """Return the Swagger UI HTML page pointing to `/openapi.json`.

    Uses a small template so the HTML remains easy to read and modify.
    """
    openapi_url = request.url_root.rstrip('/') + '/openapi.json'
    rendered = render_template_string(_HTML_TEMPLATE, openapi_url=openapi_url)
    return Response(rendered, mimetype='text/html')
