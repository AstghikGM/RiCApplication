import os
import json
import difflib
import re
from rdflib import Graph, Literal, Namespace, RDF, URIRef
from pyshacl import validate
from graphviz import Digraph
import hashlib
import textwrap

class RDFLibConverter:
    """
    Class to convert LLM-generated JSON-LD into a structured RDFLib Graph
    and validate it according to RiC-O Ontology and SHACL shapes.
    """
    # Official Namespaces
    RICO = Namespace("https://www.ica.org/standards/RiC/ontology#")
    BASE = Namespace("http://udl.cat/archive/")
    #BASE = Namespace("http://example.org/archive/")

    def __init__(self, ontology_data_path="/algorithm/src/RiC_Ontology/RiC-O_1-1_schema.json"):
        self.ontology_data_path = ontology_data_path
        self.valid_classes = set()
        self.valid_properties = set()

        if os.path.exists(self.ontology_data_path):
            with open(self.ontology_data_path, 'r', encoding='utf-8') as f:
                ontology_data = json.load(f)
                self.valid_classes = set(ontology_data.get('classes', []))
                self.valid_properties = set(ontology_data.get('properties', []))
        else:
            raise FileNotFoundError(f"Ontology data not found: {self.ontology_data_path}")
       
       
    def clean_json(self, raw_data):
        if not isinstance(raw_data, str):
            raise ValueError("Input JSON must be a string")

        start = raw_data.find('{')
        end = raw_data.rfind('}') 

        if start == -1 or end == -1 or start >= end:
            raise ValueError("No valid JSON object found in LLM output")
        
        cleaned_json = raw_data[start:end+1]

        try: 
            return json.loads(cleaned_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Error parsing JSON: {e}")
    

    def to_camel_case(self, text, upper=False):
        """
        Converts a string to UpperCamelCase (classes) or lowerCamelCase (properties).
        """
        words = re.findall(r'[a-zA-Z0-9]+', text)
        if not words: return text 
 
        if upper: # UpperCamelCase - entities
            if len(words) == 1: return text
            else:
               return "".join(word.capitalize() for word in words)
        else: # lowerCamelCase - attributes and relationships 
            if len(words) == 1 and words[0][0].islower(): return text
            else: 
               first_word = words[0].lower()
               return first_word + "".join(word.capitalize() for word in words[1:])


    def json_to_rdflib_graph(self, raw_llm_output):
        """
        Converts LLM-generated JSON-LD output into an RDFLib Graph.
        """
        # Get cleaned json
        data = self.clean_json(raw_llm_output)

        g = Graph()
        g.bind("rico", self.RICO)
        g.bind("udl", self.BASE)
        #g.bind("ex", self.BASE)


        for entity_class, entities in data.items():
            if not isinstance(entities, list): continue
            for entity in entities:
                eid = str(entity.get("@id", ""))
                        
                # Create Subject (URI based on @id)
                subject = self.BASE[eid]
                
                # Assign Class (@type)
                class_name = self.to_camel_case(entity.get("@type", entity_class), upper=True)
                g.add((subject, RDF.type, self.RICO[class_name]))

                # Process Attributes and Relationships
                for key, value in entity.items():
                    if key in ["@id", "@type"]:
                        continue
                    
                    # Clean prefix if the LLM included it in the key name
                    prop_name = self.to_camel_case(key.replace("rico:", ""), upper=False)
                    predicate = self.RICO[prop_name]
                    
                    # Helper function to process values, treating 3-digit IDs as URIs and others as Literals
                    def process_value(v):
                        v_str = str(v)
                        if v_str.isdigit() and len(v_str) == 3:
                            return self.BASE[v_str]
                        return Literal(v_str)
                    
                    if isinstance(value, list):
                        # If it's a list, we assume it's a multi-valued property or relationship
                        for item in value:
                            obj = process_value(item)
                            g.add((subject, predicate, obj))
                    else:
                        g.add((subject, predicate, process_value(value)))
        return g


    def validate_and_report(self, data_graph):
        """
        Validates the graph against SHACL and flags properties 
        that do not exist in the official RiC-O ontology.
        """
        
        # Basic integrity rules for RiC-O rdf
        shapes_graph = f"""
        @prefix sh: <http://www.w3.org/ns/shacl#> .
        @prefix rico: <{self.RICO}> .
        @prefix udl: <{self.BASE}> .

        udl:RecordResourceShape
            a sh:NodeShape ;
            sh:targetClass rico:Record, rico:RecordSet ;
            sh:or (
                [
                   sh:path rico:identifier ;
                   sh:minCount 1 ;
                ]
                [
                   sh:path rico:name ;
                   sh:minCount 1 ;
                ]
            );
            sh:message "Missing mandatory identification: Every Record or RecordSet must have at least an identifier or a name." .
        """

        conforms, _, results_text = validate(
            data_graph,
            shacl_graph=shapes_graph,
            abort_on_first=False
        )

        
        suggestions = [] # To generate suggestions for nomenclature errors
        
        # Entities validation
        for s, p, o in data_graph.triples((None, RDF.type, None)):
            class_name = str(o).split("#")[-1]
            if str(o).startswith(str(self.RICO)) and class_name not in self.valid_classes:
                match = difflib.get_close_matches(class_name, list(self.valid_classes), n=1)
                msg = f"Entity Class 'rico:{class_name}' invalid."
                if match:
                    msg += f"Try 'rico:{match[0]}'"
                suggestions.append(msg)

        # Attributes and relationships validation 
        for p in data_graph.predicates():
            p_name = str(p).split("#")[-1]
            if str(p).startswith(str(self.RICO)) and p_name not in self.valid_properties:
                match = difflib.get_close_matches(p_name, self.valid_properties, n=1)
                msg = f"Property 'rico:{p_name}' invalid."
                if match:
                    msg += f"Try 'rico:{match[0]}'"
                suggestions.append(msg)
        
        # We return the output even if it's not perfect
        is_valid = conforms and not suggestions
        
        final_report = "--- SHACL REPORT ---\n" + results_text
        if suggestions:
            final_report += "\n\n--- ONTOLOGY SUGGESTIONS (RiC-O 1.1) ---\n" + "\n".join(suggestions)
        
        return is_valid, final_report
    

    def visualize_graph(self, g, output_path):
        """
        From RDF to Graphviz visualization
        """

        # Helper function to create a mapping for safe node IDs in Graphviz
        safe_ids = {}
        def sid(uri):
            if uri not in safe_ids:
                safe_ids[uri] = "n_" + hashlib.md5(uri.encode()).hexdigest()
            return safe_ids[uri]

        # Helper function to wrap long text for Graphviz labels
        def wrap_text(text, width=45):
            wrapped_lines = textwrap.wrap(str(text), width=width)
            return "<BR/>".join(wrapped_lines)

        dot = Digraph(format="svg", engine="dot")
        dot.attr(rankdir="LR", overlap="false", splines="true")

        nodes = {}

        # Structure
        for s, p, o in g:
            s = str(s)

            if s not in nodes:
                nodes[s] = {"type": "Unknown Resource", "attrs": [], "rels": []}

            p_name = str(p).split("#")[-1]
            if p == RDF.type:
                nodes[s]["type"] = str(o).split("#")[-1]
            elif isinstance(o, Literal):
                val = str(o)
                wrapped_val = wrap_text(val)
                nodes[s]["attrs"].append(f"{p_name}: {wrapped_val}")
            else:
                nodes[s]["rels"].append((p_name, str(o)))

        # Nodes
        for uri, data in nodes.items():
            label = uri.split("/")[-1]

            attrs_html = "".join(
                f"<TR><TD ALIGN='LEFT'>{a}</TD></TR>"
                for a in data["attrs"]
            )

            html = f"""<
            <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="4">
                <TR>
                    <TD BGCOLOR="#2C3E50">
                        <FONT COLOR="white">
                            <B>{label}</B><BR/>({data['type']})
                        </FONT>
                    </TD>
                </TR>
                {attrs_html if data["attrs"] else "<TR><TD><I>No attributes</I></TD></TR>"}
            </TABLE>
            >"""

            dot.node(sid(uri), label=html, shape="none")

        # Edges
        for uri, data in nodes.items():
            for rel, target in data["rels"]:
                if target in nodes:
                    dot.edge(sid(uri), sid(target), label=rel)

        dot.render(str(output_path).replace(".svg", ""), cleanup=True)
