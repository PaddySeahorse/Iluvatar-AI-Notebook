"""Blueprint-based route registration for the notebook backend.

Blueprints live in sibling modules and read mutable runtime state
(``kernel_manager``, ``WORKSPACE_DIR`` …) from the entry-point module that is
stored on the Flask app as ``app.config['_STATE_MODULE']``.  Reading the state
at request time (rather than binding it at import time) keeps the state
monkeypatchable by the test-suite and avoids ``import app`` cycles.
"""

from flask import jsonify, current_app

from core.errors import AppError


def state():
    """Return the entry-point module holding mutable runtime state."""
    return current_app.config['_STATE_MODULE']


def register_error_handlers(app):
    """Register the structured JSON error handlers (ISSUE-009)."""

    @app.errorhandler(AppError)
    def handle_app_error(exc: AppError):
        """Convert any AppError subclass into a structured JSON response."""
        response = jsonify(exc.to_dict())
        response.status_code = exc.status_code
        return response

    @app.errorhandler(404)
    def handle_404(exc):
        return jsonify({'error': True, 'error_code': 'NOT_FOUND', 'message': 'Resource not found'}), 404

    @app.errorhandler(405)
    def handle_405(exc):
        return jsonify({'error': True, 'error_code': 'METHOD_NOT_ALLOWED', 'message': 'Method not allowed'}), 405

    @app.errorhandler(500)
    def handle_500(exc):
        return jsonify({'error': True, 'error_code': 'INTERNAL_ERROR', 'message': 'An unexpected server error occurred'}), 500


def register_routes(app):
    """Import and register every route Blueprint on *app*."""
    from .static_routes import bp as static_bp
    from .gpu_routes import bp as gpu_bp
    from .kernel_routes import bp as kernel_bp
    from .ai_routes import bp as ai_bp
    from .lint_routes import bp as lint_bp
    from .file_routes import bp as file_bp

    app.register_blueprint(static_bp)
    app.register_blueprint(gpu_bp)
    app.register_blueprint(kernel_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(lint_bp)
    app.register_blueprint(file_bp)
