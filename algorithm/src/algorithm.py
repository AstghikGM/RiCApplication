from pathlib import Path
import os
import json
import requests

from ocean_runner import Algorithm, Config

from .TextPrep import TextPrep
from .RDFLibConverter import RDFLibConverter

from src.data import Results
import time

# OpenWebUi Configuration
OPENWEBUI_API_KEY = os.getenv("OPENWEBUI_API_KEY")
OPENWEBUI_URL = "https://chat.agrospai.udl.cat"
CHAT_COMPLETIONS_URL = f"{OPENWEBUI_URL}/api/chat/completions"
MODEL_ID = "gpt-oss:latest"

MAX_RETRIES = 3
PAUSE_BETWEEN_RETRIES = 60 #seconds

algorithm = Algorithm()


def check_server_health(session):
    """Quick check on the Openwebui server by sending a test request."""
    algorithm.logger.info("Performing server health check...")
    data = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": "test"}],
        "max_tokens": 5
    }

    try:
        response = session.post(CHAT_COMPLETIONS_URL, json=data, timeout=50)
        return response.status_code == 200
    except Exception as e:
        algorithm.logger.error(f"Health check failed: {e}")
        return False
    
@algorithm.run
def run() -> Results:
      
      if not OPENWEBUI_API_KEY:
        algorithm.logger.error("Missing API Key")
        raise ValueError("Execution aborted: OPENWEBUI_API_KEY environment variable is missing.")
      
      headers = {
              "Authorization": f"Bearer {OPENWEBUI_API_KEY}",
              "Content-Type": "application/json"
                }
      # Server health check
      with requests.Session() as session:
        session.headers.update(headers)
        if not check_server_health(session):
            algorithm.logger.error("Aborting: Server health check failed.")
            raise RuntimeError("AI Server (OpenWebUI) is downstream or unreachable. Cannot proceed.")
        
      all_documents = []
      doc_context = []

      # 1. Read all files and prepare the unified document context for the LLM
      for _, filename in algorithm.job_details.next_path():
          algorithm.logger.info(f"Processing file: {filename.name}")
          
          doc_data = TextPrep.read_file(filename, algorithm)
        
          if doc_data:
               all_documents.extend(doc_data)

      if not all_documents:
          algorithm.logger.error("No documents were processed. Check input files")   
          raise ValueError("No documents were processed. Check input files")
    
      for doc in all_documents:
          doc_context.append({
                "source_zip": doc['metadata'].get('source_zip', 'PDF Archive'),
                "filename": doc['metadata'].get('filename', 'N/A'),
                "content_fragment": doc['content']
          })

      doc_context_json = json.dumps(doc_context, indent=2, ensure_ascii=False)

      # 2. LLM prompt and API call - Extract entities, attributes and relationships in JSON
      prompt = f"""
### ROLE: Act as an expert in Records in Context Ontology (RiC-O). 
### TASK: Use all given records to make a complete RECORDS IN CONTEXT ONTOLOGY model json through mapping Records in Context Ontology entities, attributes, and relationships.

### GUIDELINES:
- **STRICT RiC-O entities (ONLY):** Record Resource (with subentities Record Set, Record, Record Part), Agent (with subentities Person, Group, Family, Corporate Body, Position, Mechanism), Instantiation, Date, Place, Thing, Event (with subentity Activity) and Rule (with subentity Mandate).
- **GET ONLY ENTITIES THAT DESCRIBE THE MAIN ARCHIVE:** For example, if a Record mentions multiple Dates but only one is crucial for understanding its context, let only that ONE Date entity.
- **Attributes:** For each entity, assign all SIGNIFICANT attributes, remember that each entity has its specific attributes, for example:
    - Record Resource attributes: 'identifier', 'name', 'generalDescription', 'authenticityNote', 'classification', 'conditionsOfAccess', 'conditionsOfUse', 'hasContentOfType', 'history', 'integrityNote', 'hasOrHadLanguage', 'hasOrHadLegalStatus', 'recordResourceExtent', 'scopeAndContent', 'structure'
    - Agent attributes: 'identifier', 'name', 'generalDescription', 'history', 'hasOrHadLanguage', 'hasOrHadLegalStatus'
    - Date attributes: 'name', 'identifier', 'generalDescription', 'dateQualifier', 'hasDateType', 'expressedDate', 'normalizedDateValue'
    - Place attributes: 'identifier', 'name', 'generalDescription', 'hasOrHadCoordinates', 'history', 'location', 'hasOrHadPlaceType'
    - Instantiation attributes: 'identifier', 'name', 'generalDescription', 'hasCarrierType', 'physicalCharacteristicsNote', 'productionTechnique'...

- **Filtering:** DO NOT output entities or attributes not found in the source OR TRIVIAL ONES.
- **Relationships:** Extract all significant relationships between entities and define them inline within the source entity object. Relationship examples: 'hasCreator', 'isAssociatedWithDate', 'includesOrIncluded', 'isAssociatedWithPlace'...

### OUTPUT FORMAT:
- Return a single JSON-LD object. The top-level keys must be the MAIN RiC-O entity classes (e.g., "Agent": []).
- Each entity object must contain its attributes and relationships as key-value pairs, a unique numeric @id of three digits (001, 002...) and individually the subentity type as @type.
- NO PRETEXT, NO POST-TEXT, NO MARKDOWN.

### REPRESENTATIVE EXAMPLE: 
INPUT: 
[
  {{
    "source_zip": "Budget_2021.zip",
    "filename": "Budget_presentation.pdf",
    "content_fragment": "Budget Presentation ... Signed in 19/11/2021"
   }},
   {{
    "source_zip": "Budget_2021.zip",
    "filename": "Budget_execution.pdf",
    "content_fragment": "None"
   }},
]

OUTPUT:
{{
  "RecordResource": [
    {{
      "@id": "001",
      "@type": "Record Set",
      "name": "Budget_2021",
      "includesOrIncluded": ["002", "003"],
      "isAssociatedWithDate": "004",
      "generalDescription": ...
    }},
    {{
      "@id": "002",
      "@type": "Record Part",
      "name": "Budget Presentation",
      "generalDescription": ...
    }},
    {{
      "@id": "003",
      "@type": "Record Part",
      "name": "Budget Execution",
      "generalDescription": ...
    }}
  ],
  "Date": [
    {{
      "@id": "004",
      "@type": "Date",
      "normalizedDateValue": "2021-11-19",
      "generalDescription": ...
    }}
  ]
}}

### CONTENT 
{doc_context_json}
"""
      
      data = {
             "model": MODEL_ID,
             "stream": False,
             "messages": [
               {
                 "role": "user",
                 "content": prompt
               }
             ],
             "temperature": 0.7
           }
      

      with requests.Session() as session:
          session.headers.update(headers)
    
          for attempt in range(1, MAX_RETRIES + 1):
               try: 
                    response = session.post(CHAT_COMPLETIONS_URL, json=data, timeout=300)
                    response.raise_for_status()

                    result_json = response.json()
                    if not result_json or "choices" not in result_json or not result_json["choices"]:
                      raise ValueError("API response missing 'choices'")
                    
                    content = result_json['choices'][0]['message']['content']
                    if not content or content.lower() == "none":
                            algorithm.logger.warning("API returned empty content or 'None'. Check the input data and prompt.")
                            raise ValueError("API returned empty content")
                    
                    break  # Exit loop if successful
               except requests.exceptions.HTTPError as e:
                    status_code = e.response.status_code
                    if status_code in [429, 502, 503, 504]:
                        error_msg = f"Server temporarily busy (HTTP {status_code})"
                    else:
                        algorithm.logger.error(f" [!] Fatal HTTP Error {status_code}: {e.response.reason}")
                        raise RuntimeError(f"LLM API failed with HTTP error {status_code}: {e.response.reason}")
               except (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout) as e:
                    error_msg = f"Connection Error: {str(e)}"
               except requests.exceptions.ReadTimeout:
                    error_msg = "Timeout: Server took too long to respond"
               except Exception as e:
                    error_msg = f"Unexpected {type(e).__name__}: {str(e)}"


               # Exponential backoff
               if attempt == MAX_RETRIES:
                  algorithm.logger.error(f"CRITICAL: Final failure calling LLM API after {MAX_RETRIES} attempts. Reason: {error_msg}")
                  raise RuntimeError(f"LLM API completely failed: {error_msg}")
               else:
                  wait_time = PAUSE_BETWEEN_RETRIES * attempt
                  algorithm.logger.warning(f" [!] Attempt {attempt} failed: {error_msg}. Retrying in {wait_time}s...")
                  time.sleep(wait_time) 
      
      # 3. RDFLib conversion and SHACL validation
      converter = RDFLibConverter()

      try: 
          graph = converter.json_to_rdflib_graph(content)
          is_valid, validation_report= converter.validate_and_report(graph)
          ttl_output = graph.serialize(format="turtle")
      except Exception as e:
          algorithm.logger.error(f"Error during RDFLib conversion or SHACL validation: {e}")
          raise

      return {
          "doc_context": doc_context_json,
          "json_extraction": content,
          "ttl_output": ttl_output,
          "validation_report": validation_report,
          "graph_obj": graph,  
          "converter_obj": converter
      } 


@algorithm.save_results
def save(
    results: Results,
    base_path: Path,
):
    # Markdown
    result_path = base_path / "docs_context.md"
    with result_path.open("w", encoding="utf-8") as f:
        f.write(results["doc_context"])

    """
    # Markdown for separated files 
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

    # SHACL
    validation_path = base_path / "validation_report.txt"
    with validation_path.open("w", encoding="utf-8") as val_file:
        val_file.write(f"{results["validation_report"]}")

    # IMAGE
    try:
        image_dest = base_path / "graph_image"
        
        results["converter_obj"].visualize_graph(
            results["graph_obj"], 
            output_path=image_dest
        )
        algorithm.logger.info(f"Graph image saved in: {image_dest}.png")
    except Exception as e:
        algorithm.logger.error(f"Error generating graph image: {e}")


if __name__ == "__main__":
    algorithm()
