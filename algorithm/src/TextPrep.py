import pymupdf4llm
import zipfile
import tempfile
import os
import fitz
from pathlib import Path
import re


class TextPrep: 
 
    def __init__(self, filename):
        self.filename = filename

    @staticmethod
    def extract_ric_context(filename, algorithm):
        all_documents = TextPrep.read_file(filename, algorithm)

        if not all_documents:
            algorithm.logger.warning("No documents to process for RiC-O extraction.")
            return {
                    "pdf_markdown": [],
                    "json_extraction": "{}"
            }
            
        titles = [doc["metadata"]["filename"] for doc in all_documents]
        titles_string = "\n".join([f"- {t}" for t in titles])

        first_doc_content = all_documents[0]["content"]

        ric_context = []
        if len(first_doc_content) > 5000:
            header = first_doc_content[:2500]
            footer = first_doc_content[-2500:]
            ric_context = f"{header}\n\n[... CONTENT OMITTED FOR EFFICIENCY ...]\n\n{footer}"
        else: 
            ric_context = first_doc_content
            
        extracted_data = {
            "set_titles": titles_string,
            "main_document_sample": ric_context
        }
            
        return all_documents, extracted_data


    @staticmethod
    def read_file(filename, algorithm):
        name = filename.name.lower()

        if name.endswith('.zip'):
            return TextPrep.read_zip_context_2(filename, algorithm)
        
        if name.endswith('.pdf'):
            return TextPrep.read_pdf(filename)
        
        algorithm.logger.warning(f"Skipping unsupported file: {filename.name}")
        return []
        
    @staticmethod
    def read_pdf(path: Path):
        doc = fitz.open(path)
        try:
            content = pymupdf4llm.to_markdown(doc)
        finally:
            doc.close()

        return [{
            "metadata": {
                "filename": path.name,
                "source": "pdf"
            },
            "content": content
        }] 


    @staticmethod
    def read_zip(path: Path, algorithm):
        documents = []

        with zipfile.ZipFile(path, "r") as zip_ref: 
            pdf_docs = [
                name for name in zip_ref.namelist()
                if name.lower().endswith(".pdf")
            ] 

            """
            pdf_docs = [
                name for name in zip_ref.namelist()
                if name.lower().endswith(".pdf")
                and not name.startswith("__MACOSX/")
                and not Path(name).name.startswith("._")
            ] 
            """
            if not pdf_docs:
                algorithm.logger.warning("No PDF documents found in the zip file.")
                return documents
            

            for pdf_name in pdf_docs:
                algorithm.logger.info(f"Processing document: {pdf_name}")

                try:
                    with zip_ref.open(pdf_name) as f:
                        pdf_bytes = f.read()

                    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                    try:
                        content = pymupdf4llm.to_markdown(pdf_doc)
                    finally:
                        pdf_doc.close()

                    documents.append({
                        "metadata": {
                            "filename": pdf_name,
                            "source_zip": path.name
                        },
                        "content": content
                    })

                except Exception as e:
                    algorithm.logger.error(
                        f"Error processing document {pdf_name}: {e}"
                    )

        return documents
    



    @staticmethod
    def read_zip_ordered(path: Path, algorithm):
        documents = []

        with zipfile.ZipFile(path, "r") as zip_ref:
            """
            pdf_docs = [
                name for name in zip_ref.namelist()
                if name.lower().endswith(".pdf")
            ] 
            
            """
            pdf_docs = [
                name for name in zip_ref.namelist()
                if name.lower().endswith(".pdf")
                and not name.startswith("__MACOSX/")
                and not Path(name).name.startswith("._")
            ] 
           

            def extract_index(name: str):
                """
                Extract leading integer from filename.
                Examples:
                  '01-Intro.pdf' -> 1
                  '2 Results.pdf' -> 2
                  '10_Final.pdf' -> 10
                """
                m = re.match(r"\s*(\d+)", Path(name).stem)
                return int(m.group(1)) if m else float("inf")

            pdf_docs.sort(key=extract_index)

            for info in pdf_docs:
                pdf_name = info.encode('cp437').decode('utf-8')
                algorithm.logger.info(f"Processing document: {pdf_name}")
                
                try:
                    with zip_ref.open(info) as f:
                        pdf_bytes = f.read()

                    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                    try:
                        content = pymupdf4llm.to_markdown(pdf_doc)
                    finally:
                        pdf_doc.close()

                    documents.append({
                        "metadata": {
                            "filename": pdf_name,
                            "order": extract_index(pdf_name),
                            "source_zip": path.name
                        },
                        "content": content
                    })

                except Exception as e:
                    algorithm.logger.error(
                        f"Error processing document {pdf_name}: {e}"
                    )

                return documents



    @staticmethod
    def remove_tables(markdown_text):
        lines = markdown_text.split('\n')

        cleaned_lines = [
            line for line in lines 
            if not line.strip().startswith('|') and line.count('|') < 2
        ]
        return '\n'.join(cleaned_lines)

    @staticmethod
    def read_zip_context(path: Path, algorithm):
        documents = []

        with zipfile.ZipFile(path, "r") as zip_ref:
    
            pdf_docs = [
                name for name in zip_ref.namelist()
                if name.lower().endswith(".pdf")
                and not name.startswith("__MACOSX/")
                and not Path(name).name.startswith("._")
            ] 
           

            def extract_index(name: str):
                m = re.match(r"\s*(\d+)", Path(name).stem)
                return int(m.group(1)) if m else None

            if pdf_docs and extract_index(pdf_docs[0]) is not None:
                pdf_docs.sort(key=lambda x: extract_index(x) if extract_index(x) is not None else float("inf"))

            for info in pdf_docs:
                pdf_name = info.encode('cp437').decode('utf-8') #to handle special characters
                algorithm.logger.info(f"Processing document: {pdf_name}")
                
                try:
                    with zip_ref.open(info) as f:
                        pdf_bytes = f.read()

                    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                    try:
                        content = pymupdf4llm.to_markdown(pdf_doc)
                        # Clean tables from content
                        content = TextPrep.remove_tables(content)

                        ric_context = []
                        if len(content) > 2000:
                             header = content[:1000]
                             footer = content[-1000:]
                             ric_context = f"{header}\n\n[... CONTENT OMITTED FOR EFFICIENCY ...]\n\n{footer}"
                        else: 
                             ric_context = content
            
                    finally:
                        pdf_doc.close()


                    documents.append({
                        "metadata": {
                            "filename": pdf_name,
                            "order": extract_index(pdf_name),
                            "source_zip": path.name
                        },
                        "content": ric_context
                    })

                except Exception as e:
                    algorithm.logger.error(
                        f"Error processing document {pdf_name}: {e}"
                    )

        return documents


    @staticmethod
    def read_zip_context_2(path: Path, algorithm):
        documents = []

        with zipfile.ZipFile(path, "r") as zip_ref:
    
            pdf_docs = [
                name for name in zip_ref.namelist()
                if name.lower().endswith(".pdf")
                and not name.startswith("__MACOSX/")
                and not Path(name).name.startswith("._")
            ] 
           

            def extract_index(name: str):
                m = re.match(r"\s*(\d+)", Path(name).stem)
                return int(m.group(1)) if m else None

            if pdf_docs and extract_index(pdf_docs[0]) is not None:
                pdf_docs.sort(key=lambda x: extract_index(x) if extract_index(x) is not None else float("inf"))

            for i, info in enumerate(pdf_docs):
                try:
                    pdf_name = info.encode('cp437').decode('utf-8')
                except:
                    pdf_name = info

                algorithm.logger.info(f"Processing document: {pdf_name}")
                
                
                ric_context = []
                

                if i == 0:
                    try:
                        with zip_ref.open(info) as f:
                            pdf_bytes = f.read()

                        pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                        try:
                            content = pymupdf4llm.to_markdown(pdf_doc)
                            # Clean tables from content
                            content = TextPrep.remove_tables(content)
                            
                            if len(content) > 2000:
                                 header = content[:1000]
                                 footer = content[-1000:]
                                 ric_context = f"{header}\n\n[... CONTENT OMITTED FOR EFFICIENCY ...]\n\n{footer}"
                            else: 
                                 ric_context = content
                        finally:
                            pdf_doc.close()
                    except Exception as e:
                        algorithm.logger.error(f"Error extracting content from first PDF {pdf_name}: {e}")
                        ric_context = "Error extracting content."
                else:
                    
                    ric_context = f"[Only title stored for this section of record {path.name}]"
                    #ric_context = "[Only title stored for this record]"

               
                documents.append({
                    "metadata": {
                        "filename": pdf_name,
                        "order": extract_index(info),
                        "source_zip": path.name
                    },
                    "content": ric_context
                })

        return documents
