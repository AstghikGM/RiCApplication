from pathlib import Path
from typing import TypeVar
import fitz  # PyMuPDF
import json
import pymupdf4llm

from ocean_runner import Algorithm, Config

from .data import InputParameters
from .OpenWebUI import OpenWebUI
#from .FileReader import FileReader
import zipfile
from .RDFconverter import RDFconverter 
from .TextPrep import TextPrep

# OpenWebUi
OPENWEBUI_API_KEY = "sk-d2deb463434d4ff9abf0d024842f0284"
openwebui = OpenWebUI(api_key=OPENWEBUI_API_KEY)


# Change to real result type
ResultsT = TypeVar("ResultsT")
algorithm = Algorithm(config=Config(custom_input=InputParameters))

"""
@algorithm.validate
def validate() -> None:
    # Can remove this function to use the default behaviour. DEFAULT: Check DDOs and input files
    raise NotImplementedError()
"""

@algorithm.run
def run() -> ResultsT:
      # Provar amb tots els documents d'un mateix any (2025) en versio individual i versió "procesar tot junt"
      
      all_documents = []
      doc_context = []
      """ READ PDF FILES """
     # _, filename = next(algorithm.job_details.next_path()) 
      for _, filename in algorithm.job_details.next_path():
        
          algorithm.logger.info(f"Processing file: {filename.name}")
          #documents = TextPrep.read_file(filename, algorithm) 
          
          data = TextPrep.read_file(filename, algorithm)
 
          all_documents.extend(data)
          
      for doc in all_documents:
          doc_context.append({
                "record": doc['metadata']['source_zip'],
                "record_section": doc['metadata']['filename'],
                "content_fragment": doc['content']
          })

      doc_context_formatted = json.dumps(doc_context, indent=2, ensure_ascii=False)

      # First step: Extract entities, attributes and relationships in JSON
      prompt1 = f"""
You are a RiC-O (Records in Context Ontology) expert.
TASK: From the given archive's context, extract all Records in Context Ontology entities, their relevant attributes and the relationships between them to make a complete RiC-O model.
Treat the provided archive zip as a single record to analyze.

—-- STRICT GUIDELINES —--
- STRICT RiC-O entities (ONLY): Record Resource (with subentities Record Set, Record, Record Part), Agent (with subentities Person, Group, Family, Corporate Body, Position, Mechanism), Instantiation, Date, Place, Thing, Event (with subentity Activity) and Rule (with subentity Mandate).
- LET ONLY ENTITIES THAT DESCRIBE THE MAIN ARCHIVE. For example, if a Record mentions multiple Dates but only one is crucial for understanding its context, let only that ONE Date entity.
- For each entity, assign all FOUND attributes, remember that each entity has its specific attributes, for example:
    - Record Resource attributes: General Description, Identifier, Name, Authenticity Note, Classification, Conditions of Access, Conditions of Use, Content Type, History, Integrity Note, Language, Legal Status, Record Resource Extent, Scope and content, State, Structure
    - Agent attributes: General Description, Identifier, Name, History, Language, Legal Status
    - Date attributes: Description, Identifier, Name, Date Qualifier, Date Type, Expressed Date, Normalized Date
    - Place attributes: General Description, Identifier, Name, Coordinates, History, Location, Place Type
    - Thing attributes: General Description, Identifier, Name
    - Event attributes: General Description, Identifier, Name, Event Type, History
    - Rule attributes: General Description, Identifier, Name, History, Rule Type
    - Instantiation attributes: General Description, Identifier, Name, Authenticity Note, Carrier Extent, Carrier Type, Conditions of Access, Conditions of Use, History, Instantiation Extent, Physical Characteristics Note, Production Technique, Quality of Representation Note, Representation Type, Structure

- DO NOT output entities or attributes not found in the archive.
- Extract all significant relationships (e.g., hasCreator, isAssociatedWithDate) between entities and define them inline within the source entity object.


—-- OUTPUT FORMAT —--
- Return a single JSON-LD object. The top-level keys must be the MAIN RiC-O entity classes (e.g., "Agent": []).
- Each entity object must contain its attributes and relationships as key-value pairs, a numeric @id of three digits (001, 002...) and the  subentity type as @type.
- NO PRETEXT, NO POST-TEXT, NO MARKDOWN.


—-- SELECTED INFORMATION FROM THE ARCHIVE TO PROCESS —--
{doc_context_formatted}

"""
      result1 = openwebui.chat_with_model(OPENWEBUI_API_KEY, "gpt-oss:latest", prompt1)
      json_output = result1['choices'][0]['message']['content']
 
      # Second step: Convert JSON to Turtle RDF
      ttl_output = RDFconverter.json_to_ttl(json_output) 

      return {
          "doc_context": doc_context_formatted,
          "json_extraction": json_output,
          "ttl_output": ttl_output
      } 


@algorithm.save_results
def save(
    results: ResultsT,
    base_path: Path,
):
    # Markdown
    result_path = base_path / "docs_context.md"
    with result_path.open("w", encoding="utf-8") as f:
        f.write(results["doc_context"])

    """
    # Markdown
    result_path = base_path / "doc_context_result.md"
    with result_path.open("w", encoding="utf-8") as f:
       for doc in results["doc_context"]:
            f.write(f"# {doc['metadata']['filename']}\n\n")
            f.write(doc["content"])
            f.write("\n\n---\n\n")
    """
    

    # JSON 
    json_path = base_path / "entities_docs_context.json" 
    with json_path.open("w", encoding="utf-8") as first_step_file:
        first_step_file.write(results["json_extraction"])
   
    # TTL
    result_path = base_path / "rdf_docs_context.ttl"
    with result_path.open("w", encoding="utf-8") as result_file:
        result_file.write(f"{results["ttl_output"]}")

    

if __name__ == "__main__":
    algorithm()
