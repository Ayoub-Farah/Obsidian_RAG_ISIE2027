"""Render the consolidated Markdown scientific report with native LaTeX maths.

Requires XeLaTeX and its fontspec, unicode-math and standard table packages.
Intermediates stay in build/final_report; the deliverable is reports/final_report.pdf.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def text(value):
    escapes = {'\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$',
               '#': r'\#', '_': r'\_', '{': r'\{', '}': r'\}',
               '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}
    value = value.replace('\u2011', '-').replace('\u2013', '-').replace('\u2014', '-')
    return ''.join(escapes.get(char, char) for char in value)


def inline(value):
    tokens = re.compile(r'(\*\*.*?\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))')
    result = []
    for token in tokens.split(value):
        if token.startswith('**') and token.endswith('**'):
            result.append(r'\textbf{' + inline(token[2:-2]) + '}')
        elif token.startswith('`') and token.endswith('`'):
            code = token[1:-1]
            if '/' in code or len(code) > 28:
                result.append(r'{\ttfamily\footnotesize\nolinkurl{' + code + '}}')
            elif '_' in code or '=' in code:
                result.append(r'{\ttfamily\nolinkurl{' + code + '}}')
            else:
                result.append(r'\texttt{' + text(code) + '}')
        elif token.startswith('[') and '](' in token:
            label, target = token[1:-1].split('](', 1)
            result.append(r'\href{\detokenize{' + target + '}}{' + inline(label) + '}')
        else:
            result.append(text(token))
    return ''.join(result)


def table(lines):
    rows = [[cell.strip() for cell in line.strip().strip('|').split('|')] for line in lines]
    rows = [rows[0], *rows[2:]]
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError('Markdown table has inconsistent column counts')
    if width == 8:
        weights = [.9, .5, .5, 1.5, 1, 1.7, 1.2, 1.7]
    elif width == 4:
        weights = [1, 1.1, 1.2, 1.2]
    elif width == 3:
        weights = [1.15, 1.45, 2.8] if 'Paramètre' in rows[0][0] else [1.3, 2.15, 2.55]
    elif width == 2:
        weights = [1.7, 4.3]
    else:
        weights = [1] * width
    total = sum(weights)
    # p-column widths plus intercolumn padding sum to the text width.
    available_mm = 170 - (2 * width - 2) * 3.5 * 25.4 / 72.27
    columns = []
    for index, weight in enumerate(weights):
        numeric = width in (4, 8) and index > 0
        alignment = r'\raggedleft' if numeric else r'\raggedright'
        columns.append('>{' + alignment + r'\arraybackslash}p{' + f'{available_mm * weight / total:.3f}' + 'mm}')
    header = r'\rowcolor{tablebg} ' + ' & '.join(r'{\sffamily\bfseries ' + inline(cell) + '}' for cell in rows[0]) + r' \\'
    result = [r'\begingroup\small\setlength{\tabcolsep}{3.5pt}\renewcommand{\arraystretch}{1.23}',
              r'\begin{longtable}{@{}' + ''.join(columns) + '@{}}', r'\toprule', header,
              r'\midrule\endfirsthead', r'\toprule', header, r'\midrule\endhead',
              r'\bottomrule\endfoot']
    result += [' & '.join(inline(cell) for cell in row) + r' \\' for row in rows[1:]]
    result += [r'\end{longtable}\endgroup', '']
    return '\n'.join(result)


def render_markdown(source, work):
    lines = source.read_text(encoding='utf-8').splitlines()
    body, assets = [], []
    index = 0
    contents = False
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith('# '):
            body.append(r'\reporttitle{' + inline(line[2:]) + '}')
            index += 1
        elif line.startswith('> '):
            quote = []
            while index < len(lines) and lines[index].strip().startswith('>'):
                quote.append(lines[index].strip().lstrip('>').strip())
                index += 1
            body.append(r'\begin{tcolorbox}[colback=calloutbg,colframe=accent,boxrule=.4pt,arc=1mm,left=3mm,right=3mm,top=2mm,bottom=2mm]\small ' + inline(' '.join(quote)) + r'\end{tcolorbox}')
            if not contents:
                body.append(r'\vspace{3mm}\tableofcontents\clearpage')
                contents = True
        elif line.startswith('## '):
            title = re.sub(r'^\d+(?:\.\d+)*\.?\s+', '', line[3:])
            if title.startswith('Sources, archives'):
                body.append(r'\clearpage')
            elif title.startswith('Place du modèle historique'):
                body.append(r'\Needspace{11cm}')
            else:
                body.append(r'\Needspace{6\baselineskip}')
            body.append(r'\section{' + inline(title) + '}')
            index += 1
        elif line.startswith('### '):
            title = re.sub(r'^\d+(?:\.\d+)*\.?\s+', '', line[4:])
            body.append(r'\Needspace{9cm}' if title.startswith('Résultats selon') else r'\Needspace{10\baselineskip}')
            body.append(r'\subsection{' + inline(title) + '}')
            index += 1
        elif line == '$$':
            formula = []
            index += 1
            while index < len(lines) and lines[index].strip() != '$$':
                formula.append(lines[index])
                index += 1
            if index == len(lines):
                raise ValueError('Unclosed display equation')
            # French words in a superscript require text mode, preserving meaning.
            equation = '\n'.join(formula).replace('^{après}', r'^{\text{après}}')
            body.append('\\begin{equation}\n' + equation + '\n\\end{equation}')
            index += 1
        elif line.startswith('```'):
            code = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith('```'):
                code.append(lines[index])
                index += 1
            if index == len(lines):
                raise ValueError('Unclosed code fence')
            body.append('\\begin{Verbatim}[fontsize=\\scriptsize,breaklines,breakanywhere,frame=single,framesep=2mm]\n' + '\n'.join(code) + '\n\\end{Verbatim}')
            index += 1
        elif line.startswith('|'):
            rows = []
            while index < len(lines) and lines[index].strip().startswith('|'):
                rows.append(lines[index])
                index += 1
            body.append(table(rows))
        elif line.startswith('!['):
            match = re.fullmatch(r'!\[([^\]]*)\]\(([^)]+)\)', line)
            if not match:
                raise ValueError('Unsupported image syntax')
            caption, relative = match.groups()
            asset = (source.parent / relative).resolve(strict=True)
            if not asset.is_relative_to(ROOT):
                raise ValueError('Report figures must be local repository files')
            filename = f'{len(assets) + 1:02d}_{asset.name}'
            (work / 'assets').mkdir(exist_ok=True)
            shutil.copyfile(asset, work / 'assets' / filename)
            assets.append(dict(path=asset.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(asset.read_bytes()).hexdigest()))
            body.append(r'\begin{figure}[H]\centering\includegraphics[width=\linewidth,height=.34\textheight,keepaspectratio]{assets/' + filename + r'}\caption{' + inline(caption) + r'}\end{figure}')
            index += 1
        else:
            paragraph = []
            while index < len(lines) and lines[index].strip() and not re.match(r'^(#|>|\||```|\$\$|!\[)', lines[index].strip()):
                paragraph.append(lines[index].strip())
                index += 1
            if not paragraph:
                raise ValueError(f'Unsupported Markdown block: {lines[index]}')
            lookahead = index
            while lookahead < len(lines) and not lines[lookahead].strip():
                lookahead += 1
            if paragraph[-1].endswith(':') and lookahead < len(lines) and lines[lookahead].strip() == '$$':
                body.append(r'\Needspace{6\baselineskip}')
            body.append(inline(' '.join(paragraph)) + '\n\n')
    return '\n'.join(body), assets


PREAMBLE = r'''\documentclass[10pt,a4paper]{article}
\usepackage[margin=20mm,headheight=16pt,headsep=6mm,footskip=11mm]{geometry}
\usepackage{fontspec}
\setmainfont{Libertinus Serif}
\setsansfont{Libertinus Sans}
\setmonofont{Latin Modern Mono}[Scale=MatchLowercase]
\usepackage{amsmath,amssymb}
\usepackage{unicode-math}
\setmathfont{Libertinus Math}
\usepackage[french]{babel}
\usepackage[table]{xcolor}
\definecolor{ink}{HTML}{18364A}
\definecolor{accent}{HTML}{226B8C}
\definecolor{tablebg}{HTML}{EAF1F5}
\definecolor{calloutbg}{HTML}{F3F7FA}
\usepackage{array,longtable,booktabs,graphicx,float,needspace}
\usepackage{caption}
\captionsetup{font=small,labelfont=bf,labelsep=colon}
\usepackage{fvextra,tcolorbox}
\usepackage{xurl}
\usepackage{microtype}
\usepackage{titlesec}
\usepackage{fancyhdr,lastpage}
\usepackage[colorlinks=true,linkcolor=accent,urlcolor=accent,bookmarksnumbered=true,pdfusetitle]{hyperref}
\hypersetup{pdftitle={Temps de transmission et dégradation de synchronisation},pdfauthor={Obsidian\_RAG},pdfsubject={Synthèse des équations, mesures et limites de validité}}
\pagestyle{fancy}\fancyhf{}
\fancyhead[L]{\small\sffamily\color{ink}Obsidian\_RAG}
\fancyhead[R]{\small\sffamily\color{ink}Transmission et synchronisation}
\fancyfoot[L]{\footnotesize\sffamily Rapport final - 30 octobre 2026}
\fancyfoot[R]{\footnotesize\sffamily\thepage\ / \pageref{LastPage}}
\renewcommand{\headrulewidth}{.3pt}
\renewcommand{\footrulewidth}{0pt}
\titleformat{\section}{\Large\sffamily\bfseries\color{ink}}{\thesection.}{.55em}{}
\titleformat{\subsection}{\large\sffamily\bfseries\color{ink}}{\thesubsection}{.55em}{}
\titlespacing*{\section}{0pt}{3ex plus .8ex minus .3ex}{1.1ex}
\titlespacing*{\subsection}{0pt}{2.2ex plus .5ex minus .2ex}{.8ex}
\newcommand{\reporttitle}[1]{\noindent{\sffamily\small\bfseries\color{accent}RAPPORT FINAL}\par\vspace{4mm}{\sffamily\bfseries\color{ink}\fontsize{25}{29}\selectfont #1}\par\vspace{4mm}}
\setlength{\parindent}{0pt}
\setlength{\parskip}{.65em plus .15em minus .1em}
\setlength{\emergencystretch}{2em}
\setlength{\LTpre}{.65em}\setlength{\LTpost}{.7em}
\renewcommand{\arraystretch}{1.15}
\setcounter{tocdepth}{1}
\numberwithin{equation}{section}
\widowpenalty=10000\clubpenalty=10000\displaywidowpenalty=10000
\allowdisplaybreaks[1]
\begin{document}
'''


def build(source, output, work, engine=None):
    source, output, work = Path(source).resolve(), Path(output).resolve(), Path(work).resolve()
    if not work.is_relative_to(ROOT / 'build' / 'final_report'):
        raise ValueError('Intermediates must remain inside build/final_report')
    if not output.is_relative_to(ROOT / 'reports') or output.suffix.lower() != '.pdf':
        raise ValueError('Final PDFs must remain inside reports')
    executable = engine or shutil.which('xelatex')
    if not executable:
        candidate = Path('C:/texlive/2025/bin/windows/xelatex.exe')
        executable = str(candidate) if candidate.is_file() else None
    if not executable:
        raise RuntimeError('XeLaTeX is required; install a TeX distribution or use --xelatex')
    work.mkdir(parents=True, exist_ok=True)
    body, assets = render_markdown(source, work)
    tex = work / 'report.tex'
    tex.write_text(PREAMBLE + body + '\n\\end{document}\n', encoding='utf-8')
    for number in range(1, 3):
        result = subprocess.run([executable, '-no-shell-escape', '-interaction=nonstopmode', '-halt-on-error',
                                 '-file-line-error', 'report.tex'], cwd=work,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        transcript = result.stdout.decode('utf-8', errors='replace')
        (work / f'xelatex_pass_{number}.txt').write_text(transcript, encoding='utf-8')
        if result.returncode:
            raise RuntimeError(f'XeLaTeX failed; see {work / f"xelatex_pass_{number}.txt"}\n' + transcript[-5000:])
    log = (work / 'report.log').read_text(encoding='utf-8', errors='replace')
    missing = [line for line in log.splitlines() if 'Missing character:' in line]
    if missing:
        raise RuntimeError('Missing font glyphs:\n' + '\n'.join(missing))
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(work / 'report.pdf', output)
    provenance = dict(source=source.relative_to(ROOT).as_posix(), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                      output=output.relative_to(ROOT).as_posix(), output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                      engine=str(executable), figures=assets,
                      overfull_boxes=[line for line in log.splitlines() if 'Overfull' in line])
    (work / 'render_provenance.json').write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
    return provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'reports' / 'final_report.md')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports' / 'final_report.pdf')
    parser.add_argument('--work', type=Path, default=ROOT / 'build' / 'final_report')
    parser.add_argument('--xelatex')
    args = parser.parse_args()
    result = build(args.source, args.output, args.work, args.xelatex)
    print(json.dumps(dict(output=result['output'], sha256=result['output_sha256'], overfull_boxes=result['overfull_boxes'])))


if __name__ == '__main__':
    main()
