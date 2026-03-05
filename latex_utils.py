import os
import re
import uuid
import zipfile
import subprocess
import shutil
import pandas as pd
from typing import Tuple

def setup_latex_template() -> str:
    return r"""\documentclass[11pt, a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage{geometry}
\usepackage{graphicx}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{longtable}
\usepackage{xcolor}
\usepackage[colorlinks=true, urlcolor=blue]{hyperref}

\geometry{a4paper, margin=1.27cm}

\begin{document}
\renewcommand{\arraystretch}{1.5}
\begin{center}
    \textbf{\Large Test Paper} \\
\end{center}
\vspace{1cm}
"""

def parse_text(text: str, temp_dir: str) -> str:
    """
    Parses $ inline math $, $$ block math $$, and #url-ID# logic securely.
    """
    if pd.isna(text) or not str(text).strip():
        return ""
        
    text = str(text)
    
    # Standardize negative signs
    text = text.replace('−', '-')
    text = text.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    
    NL = '@@NL@@'
    text = text.replace('/n', NL).replace('\\n', NL).replace('\n', NL)
    
    # Handle Block Math
    text = re.sub(r'\$\$(.*?)\$\$', r'\\[ \1 \\]', text, flags=re.DOTALL)
    
    math_blocks = []
    def save_math(m):
        math_blocks.append(m.group(0))
        return f"@@MATH{len(math_blocks)-1}@@"

    text = re.sub(r'\\\[.*?\\\]', save_math, text, flags=re.DOTALL)
    text = re.sub(r'\\\(.*?\\\)', save_math, text)
    text = re.sub(r'\$([^\$]*?)\$', save_math, text)
    
    text = text.replace(NL, '\\newline ')
    text = text.lstrip()
    while text.startswith('\\newline'):
        text = text[len('\\newline'):].lstrip()
    
    import urllib.request
    
    def replace_image(match):
        img_url = match.group(1).strip()
        img_id = img_url
        if "id=" in img_url:
            img_id = img_url.split("id=")[1].split("&")[0].split("?")[0]
        elif "/d/" in img_url:
            img_id = img_url.split("/d/")[1].split("/")[0].split("?")[0].split("&")[0]
            
        assets_dir = os.path.join(os.path.dirname(__file__), "assets_cache")
        os.makedirs(assets_dir, exist_ok=True)
        cached_filepath = os.path.join(assets_dir, f"img_{img_id}.jpg")
        
        if not os.path.exists(cached_filepath):
            try:
                # Use thumbnail trick for Drive URLs
                thumb_url = f"https://drive.google.com/thumbnail?id={img_id}&sz=w1000"
                if not 'drive.google.com' in img_url:
                    thumb_url = img_url # direct link
                    
                req = urllib.request.Request(thumb_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as response, open(cached_filepath, 'wb') as out_file:
                    shutil.copyfileobj(response, out_file)
            except Exception as e:
                print(f"Failed to download image: {e}")
                return f"\\newline\\vspace{{0.2cm}}\\noindent\\textcolor{{blue}}{{\\href{{{img_url}}}{{\\textbf{{[Image Link]}}}}}}\\vspace{{0.2cm}}\\newline\n"
        
        local_filename = f"img_{img_id}.jpg"
        local_filepath = os.path.join(temp_dir, local_filename)
        try:
            shutil.copy2(cached_filepath, local_filepath)
            return f"\\newline\\vspace{{0.2cm}}\\noindent\\includegraphics[width=0.8\\linewidth, height=0.3\\textheight, keepaspectratio]{{{local_filename}}}\\vspace{{0.2cm}}\\newline\n"
        except Exception:
            return f"\\newline\\textbf{{[IMAGE MISSING: {img_url}]}}\\newline\n"

    # Images
    text = re.sub(r'#url-\s*(.*?)\s*#', replace_image, text)

    # Escape LaTeX special chars outside math blocks
    text = re.sub(r'(?<!\\)%', r'\%', text)
    text = re.sub(r'(?<!\\)&', r'\&', text)
    text = re.sub(r'(?<!\\)_', r'\_', text)
    text = re.sub(r'(?<!\\)\^', r'\\^{}', text)
    text = re.sub(r'(?<!\\)#', r'\#', text)
    
    # Restore math blocks
    for i, block in enumerate(math_blocks):
        text = text.replace(f"@@MATH{i}@@", block)
        
    return text

def build_latex_strings(df: pd.DataFrame, temp_dir: str) -> Tuple[str, str]:
    q_tex = setup_latex_template()
    a_tex = setup_latex_template()
    
    q_tex += "\\begin{longtable}{@{} p{0.10\\textwidth} p{0.75\\textwidth} p{0.15\\textwidth} @{}}\n"
    q_tex += "\\textbf{Q. No} & \\textbf{Question} & \\textbf{Marks} \\\\[2ex]\n\\hline\n"
    
    a_tex += "\\begin{longtable}{@{} p{0.10\\textwidth} p{0.90\\textwidth} @{}}\n"
    a_tex += "\\textbf{Q. No} & \\textbf{Answer} \\\\[2ex]\n\\hline\n"
    
    q_num = 1
    
    # Iterate through dataframe created from Google Sheets
    for idx, row in df.iterrows():
        q_text = parse_text(row.get('Question_Text', ''), temp_dir)
        
        # All questions are 1 mark default based on payload requirement logic
        q_tex += f"{q_num}. & {q_text} "
        
        opt_a = parse_text(row.get('Option_A', ''), temp_dir)
        opt_b = parse_text(row.get('Option_B', ''), temp_dir)
        opt_c = parse_text(row.get('Option_C', ''), temp_dir)
        opt_d = parse_text(row.get('Option_D', ''), temp_dir)
        
        has_options = any([opt_a, opt_b, opt_c, opt_d])
        if has_options:
            q_tex += "\\newline\\vspace{0.3cm}\n"
            if opt_a: q_tex += f"\\textbf{{(a)}} {opt_a} \\newline\\vspace{{0.2cm}}\n"
            if opt_b: q_tex += f"\\textbf{{(b)}} {opt_b} \\newline\\vspace{{0.2cm}}\n"
            if opt_c: q_tex += f"\\textbf{{(c)}} {opt_c} \\newline\\vspace{{0.2cm}}\n"
            if opt_d: q_tex += f"\\textbf{{(d)}} {opt_d}\n"
            
        q_tex += f"& \\textbf{{[1]}} \\\\\n\\hline\n"
        
        ans_text = parse_text(row.get('Correct_Answer', "Answer missing"), temp_dir)
        a_tex += f"{q_num}. & {ans_text} \\\\\n\\hline\n"
        
        q_num += 1
        
    q_tex += "\\end{longtable}\n\n\\end{document}"
    a_tex += "\\end{longtable}\n\n\\end{document}"
    
    return q_tex, a_tex

def generate_paper_package(selected_df: pd.DataFrame) -> Tuple[str, str]:
    """
    Main entry function to generate PDFs and DOCX files.
    Returns: (path_to_zip_file, path_to_temp_directory)
    """
    temp_dir = os.path.join(os.path.dirname(__file__), f"temp_{uuid.uuid4().hex}")
    os.makedirs(temp_dir, exist_ok=True)
    
    try:
        q_tex_str, a_tex_str = build_latex_strings(selected_df, temp_dir)
        
        q_tex_path = os.path.join(temp_dir, "question_paper.tex")
        a_tex_path = os.path.join(temp_dir, "answer_key.tex")
        
        with open(q_tex_path, "w", encoding="utf-8") as f:
            f.write(q_tex_str)
        with open(a_tex_path, "w", encoding="utf-8") as f:
            f.write(a_tex_str)
            
        q_pdf_path = os.path.join(temp_dir, "question_paper.pdf")
        q_docx_path = os.path.join(temp_dir, "Question_Paper.docx")
        a_pdf_path = os.path.join(temp_dir, "answer_key.pdf")
        a_docx_path = os.path.join(temp_dir, "Answer_Key.docx")
        
        # Compile PDFs
        subprocess.run(["xelatex", "-interaction=batchmode", "-halt-on-error", "question_paper.tex"], cwd=temp_dir, check=False, capture_output=True)
        subprocess.run(["xelatex", "-interaction=batchmode", "-halt-on-error", "question_paper.tex"], cwd=temp_dir, check=False, capture_output=True)
        
        subprocess.run(["xelatex", "-interaction=batchmode", "-halt-on-error", "answer_key.tex"], cwd=temp_dir, check=False, capture_output=True)
        subprocess.run(["xelatex", "-interaction=batchmode", "-halt-on-error", "answer_key.tex"], cwd=temp_dir, check=False, capture_output=True)
        
        # Pandoc DOCX Generation
        subprocess.run(["pandoc", q_tex_path, "-o", q_docx_path], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["pandoc", a_tex_path, "-o", a_docx_path], cwd=temp_dir, check=True, capture_output=True)
        
        # Python-docx Border Fix
        try:
            from docx import Document
            from docx.shared import Cm
            from docx.oxml import OxmlElement
            from docx.oxml.ns import qn
            
            for d_path in [q_docx_path, a_docx_path]:
                if os.path.exists(d_path):
                    doc = Document(d_path)
                    
                    # Set margins to Narrow (1.27 cm)
                    for section in doc.sections:
                        section.top_margin = Cm(1.27)
                        section.bottom_margin = Cm(1.27)
                        section.left_margin = Cm(1.27)
                        section.right_margin = Cm(1.27)
                        
                    for table in doc.tables:
                        tbl_pr = table._tbl.tblPr
                        
                        # Force table to occupy 100% of the page width
                        tbl_w = OxmlElement('w:tblW')
                        tbl_w.set(qn('w:w'), '5000')
                        tbl_w.set(qn('w:type'), 'pct')
                        tbl_pr.append(tbl_w)
                        
                        borders = OxmlElement('w:tblBorders')
                        for b_name in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
                            border = OxmlElement(f'w:{b_name}')
                            border.set(qn('w:val'), 'single')
                            border.set(qn('w:sz'), '4')
                            border.set(qn('w:space'), '0')
                            border.set(qn('w:color'), '000000')
                            borders.append(border)
                        tbl_pr.append(borders)
                        
                        for row in table.rows:
                            if row._tr.trPr is not None:
                                headers = row._tr.trPr.findall(qn("w:tblHeader"))
                                for h in headers:
                                    row._tr.trPr.remove(h)
                                    
                    doc.save(d_path)
        except Exception as e:
            print(f"Warning: Failed to apply explicit borders - {e}")
            
        zip_filename = os.path.join(temp_dir, "Test_Paper_Package.zip")
        with zipfile.ZipFile(zip_filename, 'w') as zipf:
            if os.path.exists(q_pdf_path): zipf.write(q_pdf_path, arcname="Question_Paper.pdf")
            if os.path.exists(q_docx_path): zipf.write(q_docx_path, arcname="Question_Paper.docx")
            if os.path.exists(a_pdf_path): zipf.write(a_pdf_path, arcname="Answer_Key.pdf")
            if os.path.exists(a_docx_path): zipf.write(a_docx_path, arcname="Answer_Key.docx")
            
        return zip_filename, temp_dir
            
    except Exception as e:
        # shutil.rmtree(temp_dir, ignore_errors=True)
        raise Exception(f"Failed to generate maths paper: {str(e)}")
