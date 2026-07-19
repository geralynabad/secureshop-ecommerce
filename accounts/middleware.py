class SecurityHeadersMiddleware:
    """
    Adds a Content-Security-Policy and a few extra hardening headers that
    Django doesn't set out of the box. CSP is the strongest defense-in-depth
    layer against XSS: even if a script tag slipped past output-escaping,
    the browser refuses to execute it unless it matches this policy.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        response["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            # Both payment providers use a full hosted-page redirect (no
            # embedded iframe/JS SDK), so only form-action needs their
            # domains — script-src/frame-src stay locked to 'self'.
            "form-action 'self' https://checkout.paymongo.com "
            "https://www.paypal.com https://www.sandbox.paypal.com; "
            "frame-ancestors 'none';"
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Permitted-Cross-Domain-Policies"] = "none"
        response["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response
