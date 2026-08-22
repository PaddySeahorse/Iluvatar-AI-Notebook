"""Unit tests for the structured context builder (core/context.py)."""

from core.context import build_context, context_to_text


class _FakeKM:
    def __init__(self, variables=None, outputs=None, errors=None):
        self._variables = variables or []
        self._outputs = outputs or {}
        self._errors = errors or []

    def get_variables(self):
        return list(self._variables)

    def fetch_recent_outputs(self, n=6):
        return dict(self._outputs)

    def get_recent_errors(self):
        return list(self._errors)


def test_build_context_shape():
    km = _FakeKM(
        variables=[{'name': 'df', 'type': 'DataFrame', 'repr': '<df>', 'shape': '[10, 3]'}],
        outputs={'3': '0'},
        errors=[{'title': 'KeyError: a', 'summary': 'line 4, in <module> a'}],
    )
    ctx = build_context(km, '/workspace')
    assert set(ctx.keys()) == {'variables', 'recent_outputs', 'recent_errors'}
    assert ctx['variables'][0]['name'] == 'df'
    assert ctx['recent_outputs'] == {'3': '0'}
    assert ctx['recent_errors'][0]['title'] == 'KeyError: a'


def test_build_context_degrades_gracefully():
    class _BrokenKM:
        def get_variables(self):
            raise RuntimeError('no kernel')

        def fetch_recent_outputs(self, n=6):
            raise RuntimeError('no channels')

        def get_recent_errors(self):
            raise RuntimeError('boom')

    ctx = build_context(_BrokenKM(), '/workspace')
    assert ctx == {'variables': [], 'recent_outputs': {}, 'recent_errors': []}


def test_variable_repr_is_truncated():
    km = _FakeKM(variables=[{'name': 'huge', 'type': 'str', 'repr': 'x' * 1000, 'shape': None}])
    ctx = build_context(km, '/workspace')
    assert len(ctx['variables'][0]['repr']) < 200
    assert ctx['variables'][0]['repr'].endswith('...')


def test_context_to_text_renders_sections():
    km = _FakeKM(
        variables=[{'name': 'x', 'type': 'int', 'repr': '1', 'shape': None}],
        outputs={'1': 'x = 1'},
        errors=[{'title': 'NameError: y', 'summary': ''}],
    )
    text = context_to_text(build_context(km, '/workspace'))
    assert 'x (int): 1' in text
    assert '[Out 1] x = 1' in text
    assert 'NameError: y' in text


def test_empty_context_text():
    km = _FakeKM()
    text = context_to_text(build_context(km, '/workspace'))
    assert '没有可用的变量' in text