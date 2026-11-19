"""
Vercel Serverless Function entrypoint for Groww Mutual Fund FAQ Assistant.
Provides REST API endpoints for /api/chat and /api/health.
Compatible with Vercel Python runtime using BaseHTTPRequestHandler.
"""

from http.server import BaseHTTPRequestHandler
import json
import os
import sys
import logging

# Ensure project root is in sys.path for relative imports
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.response import generate_rag_response
from src.config import config

logger = logging.getLogger("vercel_api")


class handler(BaseHTTPRequestHandler):
    """Vercel serverless request handler."""

    def _set_cors_headers(self, status_code: int = 200, content_type: str = "application/json"):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_OPTIONS(self):
        """Handle CORS pre-flight requests."""
        self._set_cors_headers(200)

    def do_GET(self):
        """Health check and metadata endpoint."""
        self._set_cors_headers(200)
        response = {
            "status": "healthy",
            "app": "Groww Mutual Fund FAQ Assistant",
            "backend": config.VECTOR_BACKEND,
            "database_configured": config.is_db_configured(),
            "schemes": [
                "HDFC Nifty 50 Index Fund",
                "HDFC Flexi Cap Fund",
                "HDFC ELSS Tax Saver Fund",
                "General Account Operations",
            ]
        }
        self.wfile.write(json.dumps(response, indent=2).encode("utf-8"))

    def do_POST(self):
        """Process FAQ queries through RAG pipeline."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self._set_cors_headers(400)
            self.wfile.write(json.dumps({"error": "Empty request body"}).encode("utf-8"))
            return

        try:
            body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(body)
            query = data.get("query", "").strip()
            scheme_filter = data.get("scheme_filter")

            if not query:
                self._set_cors_headers(400)
                self.wfile.write(json.dumps({"error": "Missing 'query' field"}).encode("utf-8"))
                return

            # Execute RAG query pipeline
            result = generate_rag_response(query, scheme_filter=scheme_filter)

            self._set_cors_headers(200)
            self.wfile.write(json.dumps(result, indent=2).encode("utf-8"))

        except Exception as e:
            logger.error(f"Error processing query: {e}", exc_info=True)
            self._set_cors_headers(500)
            error_response = {
                "error": "Internal Server Error",
                "message": str(e),
                "status": "error"
            }
            self.wfile.write(json.dumps(error_response).encode("utf-8"))
