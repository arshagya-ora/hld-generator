#!/usr/bin/env python3
"""
Production Frontend Server with API Proxy
Serves built frontend (dist/) and proxies API requests to backend
"""
import argparse
import http.server
import socketserver
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
import sys


class ProxyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler that proxies /api requests to backend and serves static files"""

    backend_url = None  # Will be set via command line args

    def do_GET(self):
        """Handle GET requests"""
        if self.path.startswith('/api'):
            self._proxy_request('GET')
        else:
            self._serve_static_file()

    def do_POST(self):
        """Handle POST requests"""
        if self.path.startswith('/api'):
            self._proxy_request('POST')
        else:
            self.send_error(404)

    def do_PUT(self):
        """Handle PUT requests"""
        if self.path.startswith('/api'):
            self._proxy_request('PUT')
        else:
            self.send_error(404)

    def do_DELETE(self):
        """Handle DELETE requests"""
        if self.path.startswith('/api'):
            self._proxy_request('DELETE')
        else:
            self.send_error(404)

    def do_PATCH(self):
        """Handle PATCH requests"""
        if self.path.startswith('/api'):
            self._proxy_request('PATCH')
        else:
            self.send_error(404)

    def _proxy_request(self, method):
        """Proxy request to backend server"""
        try:
            # Build backend URL
            backend_path = f"{self.backend_url}{self.path}"

            # Read request body if present
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length) if content_length > 0 else None

            # Create request
            req = urllib.request.Request(
                backend_path,
                data=body,
                method=method
            )

            # Copy headers (except Host)
            for header, value in self.headers.items():
                if header.lower() not in ['host', 'connection']:
                    req.add_header(header, value)

            # Forward request to backend
            with urllib.request.urlopen(req, timeout=30) as response:
                # Send response status
                self.send_response(response.status)

                # Copy response headers
                for header, value in response.headers.items():
                    if header.lower() not in ['connection', 'transfer-encoding']:
                        self.send_header(header, value)
                self.end_headers()

                # Copy response body
                self.wfile.write(response.read())

        except urllib.error.HTTPError as e:
            # Backend returned an error
            self.send_response(e.code)
            for header, value in e.headers.items():
                if header.lower() not in ['connection', 'transfer-encoding']:
                    self.send_header(header, value)
            self.end_headers()
            self.wfile.write(e.read())

        except urllib.error.URLError as e:
            # Connection error
            self.send_error(502, f"Backend connection failed: {str(e.reason)}")

        except Exception as e:
            # Other errors
            self.send_error(500, f"Proxy error: {str(e)}")

    def _serve_static_file(self):
        """Serve static files from dist directory"""
        request_path = urllib.parse.urlsplit(getattr(self, 'path', '/')).path or '/'

        # Root should always resolve to the SPA entry point.
        if request_path == '/':
            self.path = '/index.html'
            return super().do_GET()

        # Serve files that physically exist.
        translated_path = Path(self.translate_path(request_path))
        if translated_path.is_file():
            self.path = request_path
            return super().do_GET()

        # SPA fallback only for browser navigations expecting HTML routes.
        accepts_html = 'text/html' in self.headers.get('Accept', '')
        is_spa_route = request_path != '/' and '.' not in Path(request_path).name
        if is_spa_route and accepts_html:
            self.path = '/index.html'
            return super().do_GET()

        self.send_error(404, "File not found")

    def log_message(self, format, *args):
        """Log with custom format"""
        path = getattr(self, 'path', '')

        if path.startswith('/api'):
            prefix = "PROXY"
        elif path:
            prefix = "STATIC"
        else:
            prefix = "HTTP"

        sys.stderr.write(f"[{prefix}] {format % args}\n")


class ReusableTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Threaded TCP server with address reuse enabled for quick restarts."""
    allow_reuse_address = True
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description='Production Frontend Server with API Proxy')
    parser.add_argument(
        '--port',
        type=int,
        default=6601,
        help='Port to serve frontend (default: 6601)'
    )
    parser.add_argument(
        '--host',
        default='127.0.0.1',
        help='Interface to bind (default: 127.0.0.1)'
    )
    parser.add_argument(
        '--backend-port',
        type=int,
        default=6602,
        help='Backend API port (default: 6602)'
    )
    parser.add_argument(
        '--backend-host',
        default='localhost',
        help='Backend API host (default: localhost)'
    )
    parser.add_argument(
        '--dist-dir',
        default='frontend/dist',
        help='Path to built frontend dist directory (default: frontend/dist)'
    )

    args = parser.parse_args()

    # Validate dist directory
    dist_path = Path(args.dist_dir)
    if not dist_path.exists():
        print(f"Error: Dist directory not found: {dist_path.absolute()}")
        print(f"Build the frontend first: cd frontend && npm run build")
        sys.exit(1)

    if not (dist_path / 'index.html').exists():
        print(f"Error: index.html not found in {dist_path.absolute()}")
        print(f"Make sure the dist directory is correctly built")
        sys.exit(1)

    # Set backend URL for proxy handler
    backend_url = f"http://{args.backend_host}:{args.backend_port}"
    ProxyHTTPRequestHandler.backend_url = backend_url

    # Change to dist directory
    import os
    os.chdir(dist_path)

    # Create server
    with ReusableTCPServer((args.host, args.port), ProxyHTTPRequestHandler) as httpd:
        print("=" * 70)
        print("ArchDraft Frontend Server")
        print("=" * 70)
        print(f"Serving from: {dist_path.absolute()}")
        print(f"Frontend URL: http://{args.host}:{args.port}")
        print(f"Backend API:  {backend_url}")
        print(f"Proxying /api/* => {backend_url}/api/*")
        print("=" * 70)
        print("\nPress Ctrl+C to stop\n")

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\nServer stopped")
            sys.exit(0)


if __name__ == "__main__":
    main()
