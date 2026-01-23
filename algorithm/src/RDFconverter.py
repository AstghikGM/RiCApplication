import json 


class RDFconverter:
    """
    Simple converter from a JSON-LD structure (as produced by your RiC-O extraction)
    into a Turtle RDF string.

    - No external libraries used.
    - Assumes JSON-LD follows your structure: { "Record": [...], "Person": [...], ... }
    - Writes prefixes at top.
    - For each entity type, writes a comment before listing its instances.
    - Corrects minor inconsistencies: ensures IDs are formatted as <_ID>.
    - Attributes: any key that starts with "rico:" and has a literal value.
    - Relations: any key that starts with "rico:" and has object {"@id": ...} or list of such objects.
    """

    PREFIXES = """
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rico: <https://www.ica.org/standards/RiC/ontology#> .
    """

    def __init__(self, json_ld):
        self.raw_data = json_ld

    @staticmethod
    def clean_json(raw_data) -> dict:
        """Cleans and standardizes the input JSON-LD structure."""
        
        if not isinstance(raw_data, str):
            raise ValueError("Input JSON must be a string")

        start = raw_data.find('{')
        end = raw_data.rfind('}') 

        if start == -1 or end == -1 or start >= end:
            raise ValueError("Input string does not contain valid JSON object")
        
        cleaned_json = raw_data[start:end + 1]

        try: 
            ric_dict = json.loads(cleaned_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Error parsing JSON: {e}")
        
        if not isinstance(ric_dict, dict):
            raise TypeError("Parsed JSON is not a dictionary")
        
        return ric_dict


    @staticmethod
    def rdf_id(id_str: str):
        """Converts '001' → '<_001>'."""
        return f"<_{id_str}>"

    @staticmethod
    def rdf_value_name(value):
        """Formats a literal value for RDF."""
        return f"\"{value}\""
    
    @staticmethod
    def rdf_value(value):
        """Determines if value is a literal or reference and formats accordingly."""
        if isinstance(value, str) and value.isdigit():
            return RDFconverter.rdf_id(value)
        elif isinstance(value, str):
            return RDFconverter.rdf_value_name(value)
        else:
            raise ValueError("Unsupported value type for RDF conversion")

    @staticmethod
    def rdf_key_name(raw_key):
        """ Format the name of the attrubute to lowerCamelCase"""
        words = raw_key.split()

        if not words or (len(words) == 1 and words[0][0].islower()): 
            return raw_key 
        
        
        first_word = words[0].lower()
        other_words = [word.capitalize() for word in words[1:]]

        return first_word + ''.join(other_words)
    
    @staticmethod
    def rdf_entity_name(raw_name):
        """ Format the name of the entity to UpperCamelCase"""
        words = raw_name.split()
        if not words or len(words) == 1: 
            return raw_name
        
        capitalized_words = [word.capitalize() for word in words]

        return ''.join(capitalized_words)


    @staticmethod
    def map_entity(entity: dict) -> str:
        """Converts a single entity dictionary to its RDF representation."""
        e_id = RDFconverter.rdf_id(entity["@id"])
        e_type = RDFconverter.rdf_entity_name(entity["@type"])

        entity_def = [f"{e_id} a rico:{e_type} ;"]

        triples = []

        for key, value in entity.items():
            if key in ["@id", "@type"]:
                continue
            
            key = RDFconverter.rdf_key_name(key)

            if isinstance(value, list):
                for item in value: 
                    triples.append(f"     rico:{key} {RDFconverter.rdf_value(item)} ;")
            else: 
                triples.append(f"     rico:{key} {RDFconverter.rdf_value(value)} ;")                     

        # Replace last semicolon with a period
        if triples:
            triples[-1] = triples[-1].rstrip(" ;") + " ."
        
        return "\n".join(entity_def + triples)


    def json_to_ttl(obtained_json) -> str:

        json_dict = RDFconverter.clean_json(obtained_json)

        blocks = [RDFconverter.PREFIXES.strip()]
        blocks.append("\n")

        for main_enity, entity_list in json_dict.items():
            blocks.append(f"# ====== {main_enity}")
            for entity in entity_list:
                blocks.append(RDFconverter.map_entity(entity))
                blocks.append("")  # Blank line between entities

        return "\n".join(blocks)