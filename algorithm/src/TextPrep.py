import pymupdf4llm
import zipfile
import fitz
from pathlib import Path
import re


class TextPrep: 
    """
    Class to read and save the selected content of PDF files, either directly or from within ZIP archives.
    """
   
    def __init__(self, filename=None):
        self.filename = filename


    @staticmethod
    def read_file(path: Path, algorithm):
        ext = path.suffix.lower()
        try:
            if ext == '.zip':
                return TextPrep.read_zip(path, algorithm)
            if ext == '.pdf':
                return TextPrep.read_pdf(path)
        except Exception as e:
            algorithm.logger.error(f"Fatal error processing file: {path.name}: {e}")
        return []
        


    @staticmethod
    def remove_tables(markdown_text):
        lines = markdown_text.split('\n')

        cleaned_lines = [
            line for line in lines 
            if not line.strip().startswith('|') and line.count('|') < 2
        ]
        return '\n'.join(cleaned_lines)

    @staticmethod
    def truncate_text(text, limit=2000):
        if len(text) > limit: 
            half = limit // 2
            header = text[:half]
            footer = text[-half:]
            return f"{header}\n\n[... CONTENT OMITTED FOR EFFICIENCY ...]\n\n{footer}"
        
        return text

    @staticmethod
    def get_sort_key(filename):
        match = re.search(r"(\d+)", Path(filename).stem)
        return int(match.group(1)) if match else float('inf')


    @staticmethod
    def read_pdf(path: Path):
        with fitz.open(path) as doc:
            raw_content = pymupdf4llm.to_markdown(doc, write_images=False)
        
        clean_content = TextPrep.remove_tables(raw_content)
        final_content = TextPrep.truncate_text(clean_content)

        return [{
            "metadata": {
                "filename": path.name, 
                "source": "pdf"},
            "content": final_content
        }]
    
    @staticmethod
    def read_zip(path: Path, algorithm):
        documents = []
        with zipfile.ZipFile(path, "r") as zip_ref:
            names = [n for n in zip_ref.namelist() 
                     if n.lower().endswith(".pdf") 
                     and not n.startswith("__")
                     #and not name.startswith("__MACOSX/")
                     #and not Path(name).name.startswith("._")
                ]
            
            names.sort(key=TextPrep.get_sort_key)

            for i, name in enumerate(names):
                algorithm.logger.info(f"Processing: {name}")
                
                if i == 0:
                    with zip_ref.open(name) as f:
                        with fitz.open(stream=f.read(), filetype="pdf") as doc:
                            content = pymupdf4llm.to_markdown(doc)
                            content = TextPrep.remove_tables(content)
                            content = TextPrep.truncate_text(content)
                else:
                    content = f"[Content of file {name}]"

                documents.append({
                    "metadata": {"filename": name, "source_zip": path.name, "order": i},
                    "content": content
                })

        return documents
 