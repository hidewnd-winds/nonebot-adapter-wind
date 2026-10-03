"""检查交付文档和示例能被独立工程用户使用。"""
import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_documentation_local_links_resolve():
    errors = []
    files = [ROOT / 'README.md', *sorted((ROOT / 'docs').rglob('*.md'))]
    for path in files:
        content = re.sub(r'```.*?```', '', path.read_text(encoding='utf-8'), flags=re.S)
        content = re.sub(r'(`+).*?\1', '', content, flags=re.S)
        for link in re.findall(r'\[[^\]]*\]\(([^)]+)\)', content):
            link = link.split('#', 1)[0].strip('<>')
            if not link or '://' in link or link.startswith('mailto:'):
                continue
            if not (path.parent / link).exists():
                errors.append(f'{path.relative_to(ROOT)} -> {link}')
    assert not errors, '\n'.join(errors)


def test_documented_examples_are_standalone_python():
    examples = list((ROOT / 'examples').rglob('*.py'))
    assert examples, '必须交付可运行示例'
    for path in examples:
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith('src.'), path
            elif isinstance(node, ast.Import):
                assert all(not alias.name.startswith('src.') for alias in node.names), path


def test_runtime_has_no_host_imports():
    for path in (ROOT / 'nonebot/adapters/wind').rglob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith('src.'), path
            elif isinstance(node, ast.Import):
                assert all(not alias.name.startswith('src.') for alias in node.names), path


def test_documented_qq_bot_config_matches_pinned_sdk():
    import json
    from nonebot.adapters.qq.config import Config

    text = (ROOT / 'docs/integration.md').read_text(encoding='utf-8')
    values = re.findall(r"^QQ_BOTS='([^']+)'", text, flags=re.M)
    assert values, '接入说明必须提供真实可校验的 QQ_BOTS 配置'
    for value in values:
        config = Config(qq_bots=json.loads(value))
        assert all(not bot.use_websocket for bot in config.qq_bots)
