import os
import json
from dotenv import get_key
from pathlib import Path

import requests
import time
from typing import Any

from pydantic import BaseModel, Field
from ocean_runner import Algorithm, Config

from .TextPrep import TextPrep
from .RDFLibConverter import RDFLibConverter



# OpenWebUi Configuration
OPENWEBUI_URL = "https://chat.agrospai.udl.cat"
CHAT_COMPLETIONS_URL = f"{OPENWEBUI_URL}/api/chat/completions"
MAX_RETRIES = 3
MAX_JSON_RETRIES = 3
PAUSE_BETWEEN_RETRIES = 60 #seconds



# Inputs definition
class InputParameters(BaseModel):
    model_id: str = Field(
        default="gpt-oss:latest",
        title="AI Model ID",
        description="The AI model to be used for the RiC-O extraction task."
    )

# Output Type Definition
type ResultsT = dict[str, Any]

# Algorithm Instance
algorithm = Algorithm[InputParameters, ResultsT].create(
    Config(custom_input=InputParameters)
)


# Helper functions
def get_api_key() -> str:
    if algorithm.job_details.paths.algorithm.exists():
        api_key = get_key(str(algorithm.job_details.paths.algorithm), "OPENWEBUI_API_KEY")
    else:
        api_key = os.environ.get("OPENWEBUI_API_KEY")
 
    assert api_key is not None, (
        f"API key not populated from environment file {algorithm.job_details.paths.algorithm} nor environment"
    )
 
    return api_key

def _check_server_health(session: requests.Session, model_id: str) -> None:
    """Quick check on the OpenWebUI server."""
    algorithm.logger.info("Performing server health check...")
    data = {
        "model": model_id,
        "messages": [{"role": "user", "content": "test"}],
        "max_tokens": 5
    }
    
    try:
        health_res = session.post(
            CHAT_COMPLETIONS_URL, 
            json = data, 
            timeout=50
        )
        if health_res.status_code != 200:
            raise algorithm.Error("AI server is unreachable or returned an error.")
    except Exception as e:
        raise algorithm.Error(f"Health check failed: {str(e)}")


def call_llm_api(session: requests.Session, prompt: str, model_id: str) -> str:
    """HTTP requests, retries, and error handling."""

    data = {
        "model": model_id,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }

    # Main call with retries
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.post(CHAT_COMPLETIONS_URL, json=data, timeout=300)
            response.raise_for_status()
                
            result_json = response.json()
            if not result_json or "choices" not in result_json:
                raise algorithm.Error("API response missing 'choices'.")
                
            content = result_json['choices'][0]['message']['content']
            if not content or content.lower() == "none":
                raise algorithm.Error("API returned empty content.")
                
            return content
            
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code
            if status_code in [429, 502, 503, 504]:
                error_msg = f"Server temporarily busy (HTTP {status_code})"
            else:
                algorithm.logger.error(f" [!] Fatal HTTP Error {status_code}: {e.response.reason}")
                raise algorithm.Error(f"LLM API failed with HTTP error {status_code}: {e.response.reason}")
        except (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout) as e:
            error_msg = f"Connection Error: {str(e)}"
        except requests.exceptions.ReadTimeout:
            error_msg = "Timeout: Server took too long to respond"
        except Exception as e:
            error_msg = f"Unexpected {type(e).__name__}: {str(e)}"

        if attempt == MAX_RETRIES:
            raise algorithm.Error(f"Critical failure after {MAX_RETRIES} attempts. Reason: {error_msg}")

        wait_time = PAUSE_BETWEEN_RETRIES * attempt
        algorithm.logger.warning(f"Attempt {attempt} failed: {error_msg}. Retrying in {wait_time}s...")
        time.sleep(wait_time)


# Preconditions validation
@algorithm.validate
def validate(_) -> None:
    """Validation of preconditions."""
    algorithm.logger.info("Validating preconditions...")
    jd = algorithm.job_details
    assert jd.files, "The dataset does not contain any files to process."
    get_api_key() # Check credentials exist


# Main function
@algorithm.run
def run(_) -> ResultsT:
    """Main execution pipeline."""
    params = algorithm.job_details.input_parameters
    
    # Credentials
    api_key = get_api_key()

    # Documents Processing
    all_documents = []
    doc_context = []
    
    for _, filename in algorithm.job_details.inputs():
        algorithm.logger.info(f"Processing file: {filename.name}")
        doc_data = TextPrep.read_file(filename, algorithm)
        if doc_data:
            all_documents.extend(doc_data)
            
    if not all_documents:
        raise algorithm.Error("No documents were processed. Check input files.")
        
    for doc in all_documents:
        doc_context.append({
            "source_zip": doc['metadata'].get('source_zip', 'PDF Archive'),
            "filename": doc['metadata'].get('filename', 'N/A'),
            "content_fragment": doc['content']
        })
    doc_context_json = json.dumps(doc_context, indent=2, ensure_ascii=False)

    # Prompt definition
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

### CONTENT 
{doc_context_json}
"""
    
    # Initializing converter
    converter = RDFLibConverter(Path(".")/"src"/"RiC_Ontology"/"RiC-O_1-1_schema.json")

    # Call Model API with JSON Validation Retry
    ttl_output = None
    validation_report = None
    graph = None

    with requests.Session() as session:
        session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        })
        
        _check_server_health(session, params.model_id)

        for attempt in range(1, MAX_JSON_RETRIES + 1):
            try:
                algorithm.logger.info(f"Calling model {params.model_id}... (Attempt {attempt}/{MAX_JSON_RETRIES})")
                content = call_llm_api(session,prompt, params.model_id)
                # print("LLM Output (truncated):", content, "...\n") 
     
                # RDF Conversion
                algorithm.logger.info("Converting result to RDF and running SHACL validation...")
                graph = converter.json_to_rdflib_graph(content)

                # Validation report
                validation_report = converter.validate_and_report(graph)
                ttl_output = graph.serialize(format="turtle")
            
                break
            
            except (ValueError, TypeError, AttributeError, KeyError) as format_error:
                # Errors in the model output
                algorithm.logger.warning(f"JSON format error on attempt {attempt}: {format_error}")
                if attempt == MAX_JSON_RETRIES:
                    raise algorithm.Error(f"Failed to generate valid JSON from LLM after {MAX_JSON_RETRIES} attempts. Last error: {format_error}")
            
                algorithm.logger.info("Retrying LLM call to get a valid JSON format...")
                time.sleep(2)
            
            except Exception as e:
                # Captures any other exceptions during RDFLib conversion or SHACL validation and raises an error.
                raise algorithm.Error(f"Error during RDFLib conversion or SHACL validation: {e}")

    return {
        "ttl_output": ttl_output,
        "validation_report": validation_report,
        "graph_obj": graph,
        "converter_obj": converter
    } 


# Save results
@algorithm.save_results
def save(_, result: ResultsT, base: Path):
    """Saving output files."""

    # TTL Output
    result_path = base / "rdf_docs_context.ttl"
    with result_path.open("w", encoding="utf-8") as f:
        f.write(result["ttl_output"])

    # Validation Report
    validation_path = base / "validation_report.txt"
    with validation_path.open("w", encoding="utf-8") as f:
        f.write(result["validation_report"])

    # Graph Image
    try:
        image_dest = base / "graph_image"
        result["converter_obj"].visualize_graph(
            result["graph_obj"], 
            output_path=image_dest
        )
        algorithm.logger.info(f"Graph image saved in: {image_dest}.png")
    except Exception as e:
        algorithm.logger.error(f"Error generating graph image: {e}")

if __name__ == "__main__":
    algorithm()