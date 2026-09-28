import pytest

from clipscout import agents


@pytest.fixture(autouse=True)
def installed(monkeypatch):
    monkeypatch.setattr(agents.shutil, 'which', lambda name: f'/bin/{name}')


def test_commands_for_each_agent(library):
    p = 'Do Clip Scout task x.'
    claude = agents.command('claude', {'model': 'sonnet', 'effort': 'high'}, p)
    assert claude[:3] == ['/bin/claude', '-p', p] and '--strict-mcp-config' in claude
    assert claude[claude.index('--model') + 1] == 'sonnet' and claude[claude.index('--effort') + 1] == 'high'
    codex = agents.command('codex', {'model': 'gpt-5.5', 'effort': 'high'}, p)
    assert codex[-1] == p and '-m' in codex and 'model_reasoning_effort=high' in codex
    gemini = agents.command('gemini', {'model': 'gemini-3-pro'}, p)
    assert gemini[-2:] == ['-p', p] and '--approval-mode=yolo' in gemini and '--yolo' not in gemini
    opencode = agents.command('opencode', {'model': 'deepseek/deepseek-chat'}, p)
    assert opencode[:3] == ['/bin/opencode', 'run', '--auto'] and opencode[-1] == p
    custom = agents.command('custom', {'command': 'mytool --go {prompt}'}, p)
    assert custom == ['/bin/mytool', '--go', p]


def test_custom_needs_a_prompt_placeholder(library):
    with pytest.raises(ValueError):
        agents.command('custom', {'command': 'mytool --go'}, 'x')


def test_answer_from_stdout():
    fenced = 'Here you go:\n```json\n{"corrections": [], "picks": []}\n```\nDone.'
    assert agents.answer_from_stdout(fenced) == {'corrections': [], 'picks': []}
    bare = 'Thinking...\n[{"id": "t000100", "bin": "top"}]\n'
    assert agents.answer_from_stdout(bare) == [{'id': 't000100', 'bin': 'top'}]
    assert agents.answer_from_stdout('no json here {not json}') is None


def test_prompt_is_one_plain_line(library):
    text = agents.prompt_for('pick-tw1-p1', retry=True)
    assert '\n' not in text and '"' not in text and 'errors.txt' in text
