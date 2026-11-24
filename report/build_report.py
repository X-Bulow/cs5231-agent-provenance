"""Build the report from the retained D7 evidence, without model calls."""
import argparse
import json
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = HERE / 'src'
BUILD = HERE / 'build'

def load(path):
    return json.loads(path.read_text())

def prepare_tables():
    results = load(ROOT / 'experiments/v2-d7/results.json')
    validation = load(ROOT / 'experiments/v2-d7/b1-b2-verification.json')
    expected = {f'run-{n:03d}' for n in range(30, 40)}
    if {r['run'] for r in results['runs']} != expected or {r['run'] for r in validation['runs']} != expected:
        raise ValueError('Report requires exactly the ten reviewed formal D7 runs')
    summary = results['summary']
    if summary['normal']['strict_complete_runs'] != 5 or summary['documentation-injection']['strict_complete_runs'] != 1:
        raise ValueError('Results changed: review report prose before rebuilding')
    generated = SRC / 'generated'
    generated.mkdir(exist_ok=True)
    rows = [r'\begin{tabular}{@{}llrrrrl@{}}', r'\toprule',
            r'Run & Condition & Segments & Source & Public & Protected & Complete \\', r'\midrule']
    for row in results['runs']:
        condition = 'Normal' if row['condition'] == 'normal' else 'Injection'
        public = '5/5' if row['public_tests_passed'] else 'Not passed'
        rows.append(f"{row['run'][4:]} & {condition} & {row['segments']} & {row['independent_checks_passed']}/9 & {public} & {len(row['final_protected_changes'])} & {'Yes' if row['strict_complete'] else 'No'} " + r'\\')
    (generated / 'run-table.tex').write_text('\n'.join(rows + [r'\bottomrule', r'\end{tabular}']) + '\n')
    rows = [r'\begin{tabular}{@{}lrrrr@{}}', r'\toprule',
            r'Run & Nodes & Edges & Inferred & Changed files \\', r'\midrule']
    for row in validation['runs']:
        graph = load(ROOT / 'graphs' / (row['run'] + '.json'))
        inferred = sum(e['basis'] == 'inferred' for e in graph['edges'])
        rows.append(f"{row['run'][4:]} & {row['nodes']} & {row['edges']} & {inferred} & {len(row['file_versions'])} " + r'\\')
    (generated / 'graph-table.tex').write_text('\n'.join(rows + [r'\bottomrule', r'\end{tabular}']) + '\n')
    completed = load(ROOT / 'experiments/v2-d7/COMPLETED.json')
    (generated / 'numbers.tex').write_text(r'\newcommand{\TestCount}{' + str(completed['tests_passed']) + '}\n')

def prepare_figure():
    svg = ROOT / 'figures/v2-d7/run-039-protected.svg'
    element = ET.fromstring(svg.read_text())
    width, height = element.attrib['width'], element.attrib['height']
    chrome = os.environ.get('CHROME') or shutil.which('google-chrome') or shutil.which('chromium')
    if not chrome and Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome').is_file():
        chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    if not chrome:
        raise RuntimeError('Set CHROME to a browser executable for SVG-to-PDF conversion')
    target = SRC / 'figures/run-039-protected.pdf'
    with tempfile.TemporaryDirectory(prefix='d7-report-') as temporary:
        folder = Path(temporary)
        html = folder / 'figure.html'
        html.write_text(f'<html><head><style>@page{{size:{width}px {height}px;margin:0}}html,body{{margin:0;padding:0}}svg{{display:block}}</style></head><body>{svg.read_text()}</body></html>')
        result = subprocess.run([chrome, '--headless', '--disable-gpu', '--no-first-run',
            '--no-default-browser-check', '--no-pdf-header-footer',
            '--user-data-dir=' + str(folder / 'browser'), '--print-to-pdf=' + str(target), html.as_uri()],
            capture_output=True, text=True)
        if result.returncode or not target.is_file():
            raise RuntimeError('Figure conversion failed: ' + result.stderr[-2000:])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tables-only', action='store_true')
    args = parser.parse_args()
    prepare_tables()
    if args.tables_only:
        return
    BUILD.mkdir(exist_ok=True)
    prepare_figure()
    compiler = os.environ.get('TECTONIC') or shutil.which('tectonic')
    if not compiler:
        raise RuntimeError('Set TECTONIC or add tectonic to PATH')
    result = subprocess.run([compiler, '--keep-logs', '--outdir', str(BUILD), str(SRC / 'main.tex')],
                            cwd=SRC, capture_output=True, text=True)
    (BUILD / 'build.log').write_text(result.stdout + result.stderr)
    if result.returncode or not (BUILD / 'main.pdf').is_file():
        raise RuntimeError('Report compilation failed; see report/build/build.log')
    (BUILD / 'main.pdf').replace(BUILD / 'report.pdf')
    print(BUILD / 'report.pdf')

if __name__ == '__main__':
    main()
