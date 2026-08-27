"""Static analysis (lint) route for code cells (方案三：FastAPI 版)."""

import ast
import builtins

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from core.routes import json_body, state

router = APIRouter()


def _lint_cell(code: str, kernel_manager):
    """Pure lint logic, extracted so it can run inside an executor thread."""
    errors = []
    warnings = []

    # 1. Check syntax errors via AST parse
    try:
        root = ast.parse(code)
    except SyntaxError as e:
        errors.append({
            'line': e.lineno or 1,
            'col': e.offset or 1,
            'message': str(e),
        })
        return {'errors': errors, 'warnings': warnings}
    except Exception as e:  # noqa: BLE001
        errors.append({
            'line': 1,
            'col': 1,
            'message': f"AST 解析未知错误: {str(e)}",
        })
        return {'errors': errors, 'warnings': warnings}

    # 2. Check for undefined variables
    defined_names = set(dir(builtins))
    loaded_names = set()

    class NameFinder(ast.NodeVisitor):
        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Store):
                defined_names.add(node.id)
            elif isinstance(node.ctx, ast.Load):
                loaded_names.add(node.id)
            self.generic_visit(node)

        def visit_Import(self, node):
            for alias in node.names:
                defined_names.add(alias.asname or alias.name)
            self.generic_visit(node)

        def visit_ImportFrom(self, node):
            for alias in node.names:
                defined_names.add(alias.asname or alias.name)
            self.generic_visit(node)

        def _add_func_args(self, args_node):
            for arg in args_node.args:
                defined_names.add(arg.arg)
            if args_node.vararg:
                defined_names.add(args_node.vararg.arg)
            if args_node.kwarg:
                defined_names.add(args_node.kwarg.arg)
            for arg in getattr(args_node, 'kwonlyargs', []):
                defined_names.add(arg.arg)

        def visit_FunctionDef(self, node):
            defined_names.add(node.name)
            self._add_func_args(node.args)
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            defined_names.add(node.name)
            self._add_func_args(node.args)
            self.generic_visit(node)

        def visit_Lambda(self, node):
            self._add_func_args(node.args)
            self.generic_visit(node)

        def visit_ClassDef(self, node):
            defined_names.add(node.name)
            self.generic_visit(node)

    NameFinder().visit(root)

    # Check loaded names against local definition and kernel namespace
    cached_var_names = set(v['name'] for v in kernel_manager.get_variables())
    for name in loaded_names:
        if name not in defined_names and name not in cached_var_names:
            class NameLocator(ast.NodeVisitor):
                def visit_Name(self, node):
                    if node.id == name and isinstance(node.ctx, ast.Load):
                        warnings.append({
                            'line': node.lineno,
                            'col': node.col_offset,
                            'message': f"未定义的变量: '{name}'",
                        })

            NameLocator().visit(root)

    return {'errors': errors, 'warnings': warnings}


@router.post('/api/lint_cell')
async def lint_cell(request: Request):
    s = state(request)
    data = await json_body(request)
    code = data.get('code', '') or ''

    return await run_in_threadpool(_lint_cell, code, s.kernel_manager)