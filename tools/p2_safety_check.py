from pathlib import Path

def main():
    text = (Path(__file__).resolve().parents[1] / 'docs/project/phase-02-acceptance.md').read_text(encoding='utf-8')
    for marker in ('部分完成', 'workspace-write', 'exit code: 1', '不切换日用 profile'):
        if marker not in text: raise SystemExit(f'missing safety marker: {marker}')
    print('P2 safety report: honest')

if __name__ == '__main__': main()
